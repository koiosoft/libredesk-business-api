"""JEV (TypeSafe) classifier client, served through OpenRouter.

Request verified against the real API:

    POST https://openrouter.ai/api/alpha/decisions
    { "model": "typesafe/jev-1.14",
      "state": "<text to evaluate>",
      "questions": { "<id>": {"type":"choice","instructions":"...","criteria":{...}} } }

Response verified:

    { "answers": { "<id>": {"type":"choice","choice":"returns",
                            "probabilities":{"returns":1,"shipping":0},
                            "confidence":1} },
      "usage": {"input_tokens":357,"output_tokens":38,"cost":0.000014994} }

Three measured facts that define this module:

  - JEV is a DECISIONS model. The standard chat/completions endpoint REJECTS it
    with "is a decisions model and cannot be used with the chat/completions
    endpoint". That is why CLASSIFIER_URL is configurable and never derived from
    the nemotron base URL.
  - `supported_parameters: []` in the model card. temperature, reasoning_effort and
    max_tokens are not sent: OpenRouter ignores them silently, so configuring them
    would only create invisible debt.
  - `confidence` and `probabilities` are DISTINCT axes. Measured against Koiosoft
    criteria: choice close-forward-human at probability 0.37 returned confidence
    0.16. Both are evaluated; neither decides alone.

Errors NEVER publish. Misclassifying is recoverable; publishing garbage into a
customer channel is not.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger("hub-api.jev.classifier")

# Identifier of the single MVP question. Plan O3 chose top-1: JEV picks
# ONE option, and mixing "ask the stack" + "close and hand to human" in one
# prompt puede contradecirse.
ACTION_QUESTION = "action"

# Hard cap on options. TypeSafe allows up to 255, but each option costs input
# input tokens (~$0.000000042/token measured) and muddies the decision.
MAX_OPTIONS = 255


@dataclass(frozen=True)
class Decision:
    """Result of classifying one message."""

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
    """Builds the body per the verified contract. Pure: testable without network."""
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
                # {name -> description}, same shape as the YAML (V21).
                "criteria": criteria,
            }
        },
    }


def parse_response(data: dict[str, Any], min_confidence: float,
                   min_probability: float) -> Decision:
    """Reads `answers.action` and applies BOTH thresholds.

    Without a valid decision nothing runs: an unexpected response (different model,
    missing field, missing question) yields should_act=False with an explicit reason.
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

    # `none` wins by business rule, not threshold: if JEV says do not intervene,
    # do not intervene even when extremely confident.
    if choice == "none":
        return Decision(**{**decision.__dict__, "reason": "jev_said_none"})

    if confidence < min_confidence:
        return Decision(**{**decision.__dict__, "reason": "low_confidence"})

    if probability < min_probability:
        return Decision(**{**decision.__dict__, "reason": "low_probability"})

    return Decision(**{**decision.__dict__, "should_act": True, "reason": "accepted"})


class Classifier:
    """Wraps the outbound HTTP. One shared client (Phase D)."""

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
        """Classifies. Any failure returns should_act=False; never raises to the caller."""
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
            # Network, timeout, DNS. Not publishing is the only correct outcome:
            # LibreDesk never retries, so retrying here costs nobody anything.
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
