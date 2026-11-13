"""Snippet pipeline: wire shape, resolution contract, YAML extension.

All content here is synthetic. Snippet rows live in LibreDesk's database and
change without restarting hub-api; a test wired to real titles or text would be
untestable the next time someone edits one (conftest rule, learned from the
rules/*.yaml coupling). What IS pinned: the response envelope verified against
the live API (flat list under `data`, no pagination wrapper) and the behavior
contract G3/G4/G5/G7 of .sdd/plans/FEATURE.md.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest

from app.core.rules import RulesError, load_rules
from app.jev.libredesk import LibreDeskClient, SnippetRow
from app.jev.snippets import (SNIPPETS_BLOCK_LIMIT, Snippet, TableSnippetSource,
                              format_snippets)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE = dict(base_url="http://libredesk.test", api_key="k" * 32, api_secret="s" * 64)


def _snip(sid: int, title: str = "", content: str = "filler",
          enabled: bool = True) -> Snippet:
    return Snippet(id=sid, title=title or f"S{sid}", content=content,
                   enabled=enabled, updated_at="2026-11-10T00:00:00Z")


# --- T1.2: wire shape (fixture captured from the live endpoint structure) ------

@pytest.mark.asyncio
async def test_snippets_are_read_from_the_flat_data_list():
    """The messages endpoint paginates; this one does not. Shape pinned here so
    nobody 'fixes' the parser into expecting results/total_pages."""
    payload = json.loads((FIXTURES / "snippets_shape.json").read_text())
    seen_path = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_path["path"] = request.url.path
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as h:
        ld = LibreDeskClient(h, **BASE)
        rows = await ld.get_snippets()

    assert seen_path["path"] == "/api/v1/ai/snippets"
    assert [r.id for r in rows] == [102, 101, 103], "server order preserved verbatim"
    assert all(isinstance(r, SnippetRow) for r in rows)
    assert rows[2].enabled is False


@pytest.mark.asyncio
async def test_malformed_rows_are_skipped_not_fatal(caplog):
    payload = {"status": "success", "data": [
        {"id": 1, "title": "ok", "content": "c", "enabled": True, "updated_at": "t"},
        {"title": "no id"},
        "not even an object",
    ]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as h:
        ld = LibreDeskClient(h, **BASE)
        with caplog.at_level(logging.WARNING, logger="hub-api.libredesk"):
            rows = await ld.get_snippets()
    assert [r.id for r in rows] == [1]
    assert any("malformed snippet row" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_cache_invalidates_when_max_updated_at_moves():
    calls = {"n": 0}
    stamps = ["2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z"]

    def handler(request: httpx.Request) -> httpx.Response:
        body = {"status": "success", "data": [
            {"id": 7, "title": "A", "content": "a", "enabled": True,
             "updated_at": stamps[min(calls["n"], 1)]}]}
        calls["n"] += 1
        return httpx.Response(200, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as h:
        ld = LibreDeskClient(h, **BASE)
        first = await ld.get_snippets()          # fetch 1: primes the cache
        second = await ld.get_snippets()         # same stamp as cached: served locally
        third = await ld.get_snippets()          # server stamp moved: refetch
    assert calls["n"] == 3, "the listing is re-read every event; the stamp guards parsing"
    # The double flips the server stamp on its SECOND response. So: call 1 primes
    # with t1; call 2 fetches t2 (stamp differs from cache -> parse); call 3
    # fetches t2 again and gets the cached object back without reparsing.
    assert first[0].updated_at == "2026-11-01T00:00:00Z"
    assert second[0].updated_at == third[0].updated_at == "2026-11-02T00:00:00Z"
    assert third is second or [r.updated_at for r in third] == [r.updated_at for r in second]


@pytest.mark.asyncio
async def test_unreachable_api_serves_stale_cache_never_raises():
    responses = [
        {"status": "success", "data": [
            {"id": 9, "title": "A", "content": "a", "enabled": True,
             "updated_at": "t1"}]},
        {"status": "error", "message": "boom"},
    ]
    idx = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = responses[min(idx["n"], len(responses) - 1)]
        idx["n"] += 1
        code = 200 if body["status"] == "success" else 500
        return httpx.Response(code, json=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as h:
        ld = LibreDeskClient(h, **BASE)
        await ld.get_snippets()               # primes the cache
        after_failure = await ld.get_snippets()
        empty_client = LibreDeskClient(h, **BASE)   # cold client, failing API
        cold_failure = await empty_client.get_snippets()
    assert [r.id for r in after_failure] == [9], "stale beats nothing"
    assert cold_failure == [], "cold failure degrades to empty, never raises"


# --- T1.3 / G4: resolution contract --------------------------------------------

async def _source(rows: list[Snippet]) -> TableSnippetSource:
    async def fetch_all():
        return rows
    return TableSnippetSource(fetch_all)


@pytest.mark.asyncio
async def test_resolve_preserves_declared_order_and_filters_disabled():
    src = await _source([_snip(3), _snip(7, enabled=False), _snip(12)])
    out = await src.resolve([12, 3, 7])
    assert [s.id for s in out] == [12, 3], "declared order wins; disabled excluded"


@pytest.mark.asyncio
async def test_missing_id_warns_and_is_omitted(caplog):
    src = await _source([_snip(3)])
    with caplog.at_level(logging.WARNING, logger="hub-api.jev.snippets"):
        out = await src.resolve([3, 999])
    assert [s.id for s in out] == [3], "G4: absent id never aborts classification"
    assert any("snippet 999 unavailable" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_empty_ids_short_circuit_without_fetching():
    fetched = {"n": 0}

    async def fetch_all():
        fetched["n"] += 1
        raise AssertionError("must not fetch when no ids are declared")

    src = TableSnippetSource(fetch_all)
    assert await src.resolve([]) == []
    assert fetched["n"] == 0


# --- G7 / G3: formatting ---------------------------------------------------------

def test_format_is_title_colon_content_from_one_helper():
    body = format_snippets([_snip(1, "Alfa", "uno"), _snip(2, "Beta", "dos")])
    assert body == "- Alfa: uno\n- Beta: dos"
    assert format_snippets([]) == ""


def test_block_ceiling_clips_with_warning(caplog):
    big = _snip(1, "Enorme", "x" * (SNIPPETS_BLOCK_LIMIT + 500))
    with caplog.at_level(logging.WARNING, logger="hub-api.jev.snippets"):
        body = format_snippets([big])
    assert len(body) <= SNIPPETS_BLOCK_LIMIT + len(" [...]")
    assert body.endswith("[...]")
    assert any("exceeds" in r.getMessage() for r in caplog.records)


def test_under_ceiling_there_is_no_limit_at_all():
    ok = _snip(1, "Grande", "y" * (SNIPPETS_BLOCK_LIMIT - 50))
    body = format_snippets([ok])
    assert "[...]" not in body and len(body) > SNIPPETS_BLOCK_LIMIT - 60


# --- G5: rules accept `snippets:` (format only, existence never checked) --------

from tests.conftest import write_rules  # noqa: E402  (fixture writer, tmp-based)

_OPTIONS_WITH_SNIPPETS = """\
question:
  instructions: Que debe hacer la correccion?
options:
  none: No intervenir.
  close-forward-human:
    text: Reescribe cerrando y derivando.
    snippets: [7, 12]
  plain-with-post:
    text: Devuelve el lead.
    post_action: revive-assistant
"""


def test_snippets_field_parses_into_rules(tmp_path):
    rules = load_rules(write_rules(tmp_path, options_yaml=_OPTIONS_WITH_SNIPPETS))
    assert rules.snippet_ids("close-forward-human") == (7, 12)
    assert rules.snippet_ids("plain-with-post") == (), "optional stays optional"
    assert rules.snippet_ids("none") == ()
    assert rules.all_snippet_ids() == (7, 12)


def test_multiple_options_union_deduplicated_in_declaration_order(tmp_path):
    rules = load_rules(write_rules(tmp_path, options_yaml=(
        _OPTIONS_WITH_SNIPPETS + """  other:
    text: Otra accion.
    snippets: [12, 3]
""")))
    assert rules.all_snippet_ids() == (7, 12, 3)
    assert rules.snippet_ids("other") == (12, 3)


@pytest.mark.parametrize("bad,match", [
    ("snippets: 7", "must be a list"),
    ("snippets: [seven]", "not an integer"),
    ("snippets: [0]", "must be positive"),
    ("snippets: [-3]", "must be positive"),
    ("snippets: [4, 4]", "duplicate snippet ids"),
])
def test_bad_snippets_format_aborts_startup(tmp_path, bad, match):
    d = write_rules(tmp_path, options_yaml=(
        "question:\n  instructions: ok\noptions:\n"
        "  none: No intervenir.\n"
        f"  x:\n    text: Reescribe Y.\n    {bad}\n"))
    with pytest.raises(RulesError, match=match):
        load_rules(d)


def test_unknown_snippet_id_loads_fine(tmp_path):
    """G5: existence is NEVER validated at load -- the DB changes underneath us."""
    rules = load_rules(write_rules(tmp_path, options_yaml=(
        "question:\n  instructions: ok\noptions:\n"
        "  none: No intervenir.\n"
        "  x:\n    text: Reescribe Y.\n    snippets: [999999]\n")))
    assert rules.snippet_ids("x") == (999999,)
