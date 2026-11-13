"""Context-coverage contract for the classifier state and the correction prompt.

Origin of these cases: .sdd/plans/FEATURE.md (D1/D2, phases T1.1/T4.4). The bug
class they prevent is losing normative clauses on the way to the model: measured
on a real payload, the old 2400-character policy clip cut mid-sentence twice
("NUNCA mencione ..." / "Despues del punto 3 ...") and the corrector received
neither history nor the rules it was supposed to enforce.

Everything here runs on synthetic fixtures. Snippet content lives in LibreDesk's
database and changes without restarting hub-api, so no test may depend on real
titles or text -- only on the wire shape captured in tests/fixtures/.
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from app.jev import composer

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN_STATE = FIXTURES / "golden_state.txt"
GOLDEN_CORRECTION_PROMPT = FIXTURES / "golden_correction_prompt.txt"
UPDATE_ENV = "UPDATE_GOLDEN"


# --- Synthetic material -------------------------------------------------------
# Long enough that any future character limit would visibly truncate it: the
# golden files are what detect a re-introduced clip (FEATURE.md G2).

INSTRUCTIONS = (
    "Instruccion normativa A que debe llegar completa al clasificador sin recorte.\n"
    + "x" * 1500
    + "\nInstruccion normativa Z, ultima linea de la politica: NUNCA mencione el origen interno."
)
GUARDRAILS = (
    "A. ESTRUCTURA OBLIGATORIA DEL TURNO: exactamente una pregunta por respuesta.\n"
    + "y" * 1500
    + "\nDespues del punto 3 no se agrega nada mas: ni enlaces ni promesas de plazo."
)
TURN_STRUCTURE = (
    "MANDATORY TURN STRUCTURE (check the reply against this):\n"
    "ESTRUCTURA OBLIGATORIA DEL TURNO: exactamente una pregunta por respuesta."
)
SNIPPETS_TEXT = (
    "- Snippet Alfa: contenido alfa de prueba.\n"
    "- Snippet Beta: contenido beta de prueba."
)
HISTORY = [
    ("contact", "Cliente historico uno: mi sistema esta caido"),
    ("agent", "Asistente historico uno: le agendo una sesion"),
]
CUSTOMER = "URGENTE: nuestro sistema esta caido desde esta manana"
AGENT_REPLY = "Claro, con gusto. Que stack prefieres? Y tambien, cual es tu presupuesto?"


def _state_kwargs() -> dict:
    return dict(
        customer_message=CUSTOMER,
        agent_message=AGENT_REPLY,
        history=HISTORY,
        policy=composer.build_policy_header(INSTRUCTIONS, GUARDRAILS),
        turn_structure=TURN_STRUCTURE,
        snippets=SNIPPETS_TEXT,
    )


def _prompt_kwargs() -> dict:
    return dict(
        action_text="Reescribe la respuesta y deja exactamente una pregunta.",
        assistant_name="Agente Koiosoft Fixture",
        instructions=INSTRUCTIONS,
        guardrails=GUARDRAILS,
        history=HISTORY,
        customer_message=CUSTOMER,
        agent_message=AGENT_REPLY,
        snippets=SNIPPETS_TEXT,
    )


def check_golden(path: Path, actual: str) -> None:
    """Exact snapshot comparison; UPDATE_GOLDEN=1 rewrites instead.

    Deliberately byte-exact: a silent rewrite on every run would stop being a
    regression detector the first time someone refreshes it casually.
    """
    if os.environ.get(UPDATE_ENV):
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"missing golden file {path.name}: run with {UPDATE_ENV}=1 once"
    assert actual == path.read_text(encoding="utf-8"), (
        f"{path.name} drifted: the composed context changed. Review the diff; "
        f"only regenerate with {UPDATE_ENV}=1 when the change is intended."
    )


# --- Golden payloads (T1.1 / T4.4) ---------------------------------------------

def test_golden_classifier_state_is_byte_exact():
    check_golden(GOLDEN_STATE, composer.build_state_for_jev(**_state_kwargs()))


def test_golden_correction_prompt_is_byte_exact():
    check_golden(GOLDEN_CORRECTION_PROMPT, composer.compose_prompt(**_prompt_kwargs()))


# --- D1: the policy travels whole ------------------------------------------------

def test_policy_header_has_no_character_limit():
    """G2: instructions/guardrails must never be clipped again.

    The signature itself is part of the contract: reintroducing a `limit`
    keyword would fail here before any clause silently disappears.
    """
    import inspect

    params = inspect.signature(composer.build_policy_header).parameters
    assert "limit" not in params, "policy clipping must not come back (FEATURE.md G2)"

    header = composer.build_policy_header(INSTRUCTIONS, GUARDRAILS)
    assert "[...]" not in header
    assert INSTRUCTIONS in header and GUARDRAILS in header
    # The tail of each field is exactly where the old 2400 clip used to cut.
    assert header.rstrip().endswith(GUARDRAILS.strip())


def test_history_and_messages_keep_their_clips():
    """Only the policy lost its limit; conversation turns stay bounded."""
    long_turn = "z" * 5000
    st = composer.build_state_for_jev(customer_message=long_turn,
                                      agent_message="respuesta corta",
                                      history=[("contact", long_turn)])
    assert "[...]" in st, "turn clipping still applies (D1 kept _clip for turns)"


# --- §9 block order (contractual) --------------------------------------------------

def test_state_block_order_matches_agreed_layout():
    st = composer.build_state_for_jev(**_state_kwargs())
    positions = [st.find(marker) for marker in (
        "MANDATORY TURN STRUCTURE",   # 1
        "POLITICA DEL ASISTENTE",     # 2-3 (instructions then LIMITES)
        "LIMITES:",                   # 3
        "SNIPPETS OBLIGATORIOS",      # 4
        "historico uno",              # 5
        CUSTOMER[:20],                # 6
        AGENT_REPLY[:20],             # 7
    )]
    assert all(p >= 0 for p in positions), f"a block vanished: {positions}"
    assert positions == sorted(positions), "block order changed: §9 is contractual"
    assert st.rstrip().endswith("Asistente: " + AGENT_REPLY), \
        "the reply under evaluation stays last (V18 precedence)"


def test_snippets_block_sits_between_policy_and_history():
    st = composer.build_state_for_jev(**_state_kwargs())
    snip = st.find("SNIPPETS OBLIGATORIOS")
    assert st.find("LIMITES:") < snip < st.find("historico uno")


def test_state_without_snippets_keeps_previous_shape():
    """Options with no declared snippets must not grow an empty block."""
    kwargs = _state_kwargs() | {"snippets": ""}
    st = composer.build_state_for_jev(**kwargs)
    assert "SNIPPETS OBLIGATORIOS" not in st
    assert "LIMITES:" in st


# --- D2: the corrector sees what the generator saw ---------------------------------

def test_compose_prompt_action_block_is_last():
    """G6: JEV precedence is positional -- ACCION closes the prompt."""
    p = composer.compose_prompt(**_prompt_kwargs())
    assert p.rfind("ACCION APLICAR:") > p.rfind("RESPUESTA DEL ASISTENTE A MEJORAR:")
    assert p.count("ACCION APLICAR:") == 1


def test_compose_prompt_carries_guardrails_history_and_snippets():
    p = composer.compose_prompt(**_prompt_kwargs())
    assert "Limites que NUNCA puede cruzar:" in p          # V15 fix at compose level
    assert GUARDRAILS in p and "[...]" not in p            # unclipped there too
    assert "Asistente historico uno" in p                  # V19/V20 fix: history arrives
    assert SNIPPETS_TEXT in p                              # same snippets the judge saw


def test_compose_prompt_without_optional_context_still_valid():
    kwargs = {k: v for k, v in _prompt_kwargs().items() if k not in ("history", "snippets")}
    p = composer.compose_prompt(**kwargs)
    assert "ACCION APLICAR:" in p and p.startswith("Eres un revisor")
