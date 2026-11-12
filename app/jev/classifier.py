"""Cliente del clasificador JEV (TypeSafe servido por OpenRouter).

Request verificado contra la API real:

    POST https://openrouter.ai/api/alpha/decisions
    { "model": "typesafe/jev-1.14",
      "state": "<texto a evaluar>",
      "questions": { "<id>": {"type":"choice","instructions":"...","criteria":{...}} } }

Response verificada:

    { "answers": { "<id>": {"type":"choice","choice":"returns",
                            "probabilities":{"returns":1,"shipping":0},
                            "confidence":1} },
      "usage": {"input_tokens":357,"output_tokens":38,"cost":0.000014994} }

Tres hechos medidos que definen este modulo:

  - JEIV es modelo de DECISIONES. El endpoint estandar chat/completions lo RECHAZA
    con "is a decisions model and cannot be used with the chat/completions
    endpoint". Por eso CLASSIFIER_URL es configurable y no se deriva del base URL
    de nemotron.
  - `supported_parameters: []` en la ficha del modelo. No se envia temperature,
    reasoning ni max_tokens: OpenRouter los ignora en silencio, configurarlos
    seria deuda invisible.
  - `confidence` y `probabilities` son ejes DISTINTOS. Medido sobre criterios de
    Koiosoft: eleccion close-forward-human con probabilidad 0.37 devolvio
    confidence 0.16. Se evaluan los dos; ninguno solo decide.

El error NUNCA publica. Clasificar mal es recuperable; publicar basura en un canal
de cliente no.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("hub-api.jev.classifier")

# Identificador de la pregunta unica del MVP. O3 del plan decidio top-1: JEV elige
# UNA opcion, y mezclar "pregunta el stack" + "cierra y pasa a humano" en un mismo
# prompt puede contradecirse.
ACTION_QUESTION = "action"

# Tope duro de opciones. TypeSafe admite hasta 255, pero cada opcion cuesta tokens
# de entrada (~$0.000000042/token medidos) y ensucia la decision.
MAX_OPTIONS = 255


@dataclass(frozen=True)
class Decision:
    """Resultado de clasificar un mensaje."""

    should_act: bool
    reason: str
    choice: str | None = None
    confidence: float = 0.0
    probability: float = 0.0
    probabilities: dict[str, float] | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None

    def as_log(self) -> dict[str, Any]:
        return {
            "should_act": self.should_act,
            "reason": self.reason,
            "choice": self.choice,
            "confidence": round(self.confidence, 4),
            "probability": round(self.probability, 4),
            "cost_usd": self.cost_usd,
        }


def build_request(state: str, instructions: str, criteria: dict[str, str],
                  model: str) -> dict[str, Any]:
    """Arma el body segun el contrato verificado. Puro: testeable sin red."""
    if not criteria:
        raise ValueError("criteria empty: nothing to classify against")
    if len(criteria) > MAX_OPTIONS:
        raise ValueError(f"too many options: {len(criteria)} > {MAX_OPTIONS}")
    return {
        "model": model,
        "state": state,
        "questions": {
            ACTION_QUESTION: {
                "type": "choice",
                "instructions": instructions,
                # Las claves de prompts.yaml van tal cual: JEV acepta mapa
                # {nombre -> descripcion}, misma forma que el YAML (V21).
                "criteria": criteria,
            }
        },
    }


def parse_response(data: dict[str, Any], min_confidence: float,
                   min_probability: float) -> Decision:
    """Lee `answers.action` y aplica los DOS umbrales.

    Sin `decision` valida no se actua: una respuesta inesperada (modelo distinto,
    campo ausente, pregunta ausente) produce should_act=False con motivo explicito.
    """
    answers = data.get("answers")
    if not isinstance(answers, dict):
        return Decision(False, "no_answers")

    answer = answers.get(ACTION_QUESTION)
    if not isinstance(answer, dict):
        return Decision(False, "no_action_answer")

    if answer.get("type") != "choice":
        return Decision(False, f"unexpected_type:{answer.get('type')}")

    choice = answer.get("choice")
    if not isinstance(choice, str) or not choice:
        return Decision(False, "empty_choice")

    try:
        confidence = float(answer.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return Decision(False, "bad_confidence")

    probs_raw = answer.get("probabilities")
    probs: dict[str, float] = {}
    if isinstance(probs_raw, dict):
        for k, v in probs_raw.items():
            try:
                probs[str(k)] = float(v)
            except (TypeError, ValueError):
                continue

    probability = probs.get(choice, 0.0)

    usage = data.get("usage") or {}
    cost = usage.get("cost")
    model_id = data.get("model")

    decision = Decision(
        should_act=False,
        reason="pending_thresholds",
        choice=choice,
        confidence=confidence,
        probability=probability,
        probabilities=probs,
        cost_usd=float(cost) if isinstance(cost, (int, float)) else None,
        input_tokens=usage.get("input_tokens")
        if isinstance(usage.get("input_tokens"), int) else None,
    )

    # `none` gana por regla de negocio, no por umbral: si JEV dice no intervenir,
    # no se interviene aunque estuviera segurisimo.
    if choice == "none":
        return Decision(**{**decision.__dict__, "reason": "jev_said_none"})

    if confidence < min_confidence:
        return Decision(**{**decision.__dict__, "reason": "low_confidence"})

    if probability < min_probability:
        return Decision(**{**decision.__dict__, "reason": "low_probability"})

    return Decision(**{**decision.__dict__, "should_act": True, "reason": "accepted"})


class Classifier:
    """Envuelve el HTTP saliente. Un solo cliente compartido (Fase D)."""

    def __init__(self, client: httpx.AsyncClient, *, url: str, api_key: str,
                 model: str, timeout_s: float = 10.0,
                 log_request: bool = False) -> None:
        self._client = client
        self._url = url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_s
        self._log_request = log_request

    async def classify(self, state: str, instructions: str,
                       criteria: dict[str, str], *, min_confidence: float,
                       min_probability: float) -> Decision:
        """Clasifica. Cualquier fallo devuelve should_act=False; nunca lanza al caller."""
        try:
            body = build_request(state, instructions, criteria, self._model)
        except ValueError as exc:
            log.error("classifier request invalid: %s", exc)
            return Decision(False, f"bad_request:{exc}")

        if not self._api_key:
            return Decision(False, "no_api_key")

        if self._log_request:
            # The body exactly as it will be serialized and sent. `state` holds the
            # customer conversation, so this is opt-in via CLASSIFIER_LOG_REQUEST.
            log.info(
                "jev request payload %s",
                json.dumps(body, ensure_ascii=False, sort_keys=True),
            )

        try:
            resp = await self._client.post(
                self._url,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            # Red, timeout, DNS. No publicar es la unica salida correcta: LibreDesk
            # no reintenta, asi que reintentar aqui no tiene coste para nadie.
            log.warning("classifier network error: %s", exc)
            return Decision(False, "network_error")

        if resp.status_code != 200:
            log.warning("classifier HTTP %s body=%s",
                        resp.status_code, resp.text[:200])
            return Decision(False, f"http_{resp.status_code}")

        try:
            data = resp.json()
        except ValueError:
            return Decision(False, "not_json")

        if not isinstance(data, dict):
            return Decision(False, "not_object")

        decision = parse_response(data, min_confidence, min_probability)
        log.info(
            "jev decision choice=%s confidence=%.3f probability=%.3f act=%s reason=%s "
            "cost=%s model=%s",
            decision.choice, decision.confidence, decision.probability,
            decision.should_act, decision.reason, decision.cost_usd, data.get("model"),
        )
        return decision
