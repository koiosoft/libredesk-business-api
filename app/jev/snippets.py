"""Snippet resolution for the JEV decision and the correction.

The problem this module solves: the assistant policy references snippets by id
("aplique el snippet S10", "matriz de snippets autorizada") but neither the
classifier nor the corrector could resolve the reference -- the judge received
the pointer without the material (FEATURE.md V10).

Design (D4): one narrow interface, ``SnippetSource.resolve(ids)``, is the single
substitution point. Today it is backed by the LibreDesk admin API
(``GET /api/v1/ai/snippets``); a semantic backend stays out of reach until
LibreDesk exposes filtered retrieval over HTTP (no route on Manager.Search(),
in-memory brute-force index, encrypted embedding key -- V28-V30). That makes it
unreachable, not pending.

Rules bind options to snippet ids; ids are numeric because ai_knowledge_base has
no code column (V32) and its SERIAL primary key survives the planned move to
dedicated persistence (D5). Content changes in the database between events on
purpose, so nothing here may assume specific titles or text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, Sequence

log = logging.getLogger("hub-api.jev.snippets")

# G3: ceiling for the whole formatted block, not per snippet. Under it there is
# no limit at all; over it the block is clipped and the log says so, because a
# silently truncated compliance list is exactly the bug this feature removes.
SNIPPETS_BLOCK_LIMIT = 8000


@dataclass(frozen=True)
class Snippet:
    """One knowledge-base entry as the admin API returns it."""

    id: int
    title: str
    content: str
    enabled: bool
    updated_at: str


class SnippetSource(Protocol):
    """Resolution strategy behind D4. Implementations must never raise on a
    missing id: classification must not depend on knowledge-base hygiene (G4).
    """

    def resolve(self, ids: Sequence[int]) -> list[Snippet]: ...


class TableSnippetSource:
    """Backend reading every snippet through the cached admin-API listing.

    ``fetch_all`` is injected (typically ``LibreDeskClient.get_snippets``) so
    this class stays free of transport concerns and tests can feed it doubles.
    The client owns the cache invalidation (max(updated_at)); here we only
    filter, order and warn.
    """

    def __init__(self, fetch_all) -> None:  # noqa: ANN001 - callable protocol
        self._fetch_all = fetch_all

    async def resolve(self, ids: Sequence[int]) -> list[Snippet]:
        wanted = list(dict.fromkeys(int(i) for i in ids))
        if not wanted:
            return []
        rows = await self._fetch_all()
        by_id = {s.id: s for s in rows if s.enabled}
        out: list[Snippet] = []
        for sid in wanted:
            snip = by_id.get(sid)
            if snip is None:
                # G4/G5: absent or disabled is a warning, never an abort. The
                # database changes without restarting hub-api; a deletion made
                # by someone else must not stop every classification.
                log.warning("snippet %s unavailable (deleted or disabled); skipped", sid)
                continue
            out.append(snip)
        # Declared order is preserved: rules read top-to-bottom as priorities.
        return out


def format_snippets(items: Sequence[Snippet]) -> str:
    """Single formatter for both prompts (G7): ``- {title}: {content}`` per line.

    Deliberately NOT replicating LibreDesk's chunk prefix (title + section
    heading, V36): that formula belongs to their embedding pipeline, and
    reimplementing someone else's formula here is the recorded lesson about the
    hash separator.
    """
    if not items:
        return ""
    body = "\n".join(f"- {s.title}: {s.content}" for s in items)
    if len(body) > SNIPPETS_BLOCK_LIMIT:
        log.warning(
            "snippets block exceeds %s chars (%s); clipped -- declare fewer ids "
            "or shorten the snippets", SNIPPETS_BLOCK_LIMIT, len(body),
        )
        body = body[:SNIPPETS_BLOCK_LIMIT].rstrip() + " [...]"
    return body
