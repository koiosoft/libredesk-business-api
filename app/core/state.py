"""In-memory state for the enforcement loop.

Deliberate decision (2026-11-11): hub-api has NO table of its own. The plan
proposed persisting every event (D10/T4.1) for auditing, durable idempotency and
reprocessing. It was dropped because:

  - deduplication already worked in RAM and still works for a single process;
  - the per-conversation correction cap is a counter, not a record;
  - the only thing that truly needs disk is "reprocess what was left half-done",
    and in the MVP there is barely anything to reprocess (JEV answers `none` or
    the message was already fine), so the cost of introducing our own schema --
    and its migration -- does not pay off yet.

Accepted consequences, so they are not surprises later:

  1. History is lost on restart: an agent message evaluated before a restart can
     be evaluated again if LibreDesk re-delivers it (it does not: it never
     retries). In practice the effect is that the correction CAP resets, not that
     publications get duplicated.
  2. It does not work with more than one replica. With --workers > 1 or several
     container copies, each process keeps its own counter. The Dockerfile pins a
     single worker precisely for this reason. If this ever scales, it moves to
     Redis or to a table with a UNIQUE constraint.
  3. There is no queryable audit trail for "why was this message not corrected".
     There are structured logs with the exact reason, but they are ephemeral.

All three are recorded in CHANGELOG as known debt, not as bugs.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

log = logging.getLogger("hub-api.state")

# Cache ceilings: a dedupe without a cap grows forever on a service that has been
# up for days, so these two constants bound memory.
DEDUPE_MAX = 5000
CHANNELS_MAX = 2000


class HubState:
    """State shared across handlers. Thread-safe and I/O-free.

    Methods are synchronous and cheap (microseconds): they are called straight from
    the event loop, without asyncio.to_thread, because there is no database.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Dedupe key -> True. OrderedDict so the oldest entry can be evicted.
        self._seen: OrderedDict[str, bool] = OrderedDict()
        # conversation_uuid -> inbox_channel (source: conversation.created).
        self._channels: OrderedDict[str, str] = OrderedDict()
        # conversation_uuid -> True while the assistant has the conversation
        # open. Set on conversation.created and by live status reads; cleared
        # when a resolved/closed status is observed (webhook or GET). Absent =
        # unknown, which costs one header read at most once per conversation.
        self._open: OrderedDict[str, bool] = OrderedDict()
        # conversation_uuid -> True once a resolved/closed status was observed.
        self._closed: OrderedDict[str, bool] = OrderedDict()
        # conversation_uuid -> True once the assistant handed the conversation to a
        # human. Observed from webhooks only; cleared by a successful revive.
        self._handoffs: OrderedDict[str, bool] = OrderedDict()
        # conversation_uuid -> published corrections.
        self._corrections: dict[str, int] = {}

    # --- Idempotency --------------------------------------------------------

    def seen_before(self, key: str) -> bool:
        """Record `key` and report whether it had been seen before.

        Check-and-mark happens in one step: done separately, two concurrent
        deliveries of the same event could both slip through.
        """
        with self._lock:
            if key in self._seen:
                return True
            self._seen[key] = True
            while len(self._seen) > DEDUPE_MAX:
                self._seen.popitem(last=False)
            return False

    # --- Channel per conversation -------------------------------------------

    def remember_channel(self, conversation_uuid: str, channel: str) -> None:
        if not conversation_uuid or not channel:
            return
        with self._lock:
            self._channels[conversation_uuid] = channel
            self._channels.move_to_end(conversation_uuid)
            while len(self._channels) > CHANNELS_MAX:
                self._channels.popitem(last=False)

    def channel_for(self, conversation_uuid: str | None) -> str | None:
        if not conversation_uuid:
            return None
        with self._lock:
            return self._channels.get(conversation_uuid)

    # --- Open-conversation tracking (closed-conversation guard) --------------

    def remember_open(self, conversation_uuid: str) -> None:
        """(Re-)register as open. A reopened conversation leaves the closed set."""
        if not conversation_uuid:
            return
        with self._lock:
            self._closed.pop(conversation_uuid, None)
            self._open[conversation_uuid] = True
            self._open.move_to_end(conversation_uuid)
            while len(self._open) > CHANNELS_MAX:
                self._open.popitem(last=False)

    def mark_closed(self, conversation_uuid: str) -> None:
        """Observed resolved/closed: drop from _open and remember as closed.

        Both maps are LRU-bounded (CHANNELS_MAX). Eviction from _open means
        "unknown", which costs at most one header read on the next event --
        never a false "closed". Eviction from _closed likewise degrades to
        unknown, not to open.
        """
        if not conversation_uuid:
            return
        with self._lock:
            self._open.pop(conversation_uuid, None)
            self._closed[conversation_uuid] = True
            self._closed.move_to_end(conversation_uuid)
            while len(self._closed) > CHANNELS_MAX:
                self._closed.popitem(last=False)

    def conversation_state(self, conversation_uuid: str | None) -> bool | None:
        """True=open, False=closed (observed), None=never seen."""
        if not conversation_uuid:
            return None
        with self._lock:
            if conversation_uuid in self._open:
                return True
            return False if conversation_uuid in self._closed else None



    def remember_handoff(self, conversation_uuid: str) -> None:
        """Mark that the AI agent gave this conversation up to a human."""
        if not conversation_uuid:
            return
        with self._lock:
            self._handoffs[conversation_uuid] = True
            while len(self._handoffs) > CHANNELS_MAX:
                self._handoffs.popitem(last=False)

    def had_handoff(self, conversation_uuid: str | None) -> bool:
        if not conversation_uuid:
            return False
        with self._lock:
            return bool(self._handoffs.get(conversation_uuid))

    def clear_handoff(self, conversation_uuid: str) -> None:
        """The bot is back in the conversation: forget the abandonment flag."""
        with self._lock:
            self._handoffs.pop(conversation_uuid, None)

    # --- Correction cap -----------------------------------------------------

    def corrections_count(self, conversation_uuid: str) -> int:
        with self._lock:
            return self._corrections.get(conversation_uuid, 0)

    def take_correction_slot(self, conversation_uuid: str, max_corrections: int) -> bool:
        """Reserve a slot. False if the conversation already hit the cap.

        It reserves instead of read-then-write: two concurrent pipelines for the
        same conversation must not both publish while seeing the same stale count.
        """
        with self._lock:
            current = self._corrections.get(conversation_uuid, 0)
            if current >= max_corrections:
                return False
            self._corrections[conversation_uuid] = current + 1
            return True

    # --- Introspection ------------------------------------------------------

    def snapshot(self) -> dict[str, int]:
        """Counters for /meta/config. No content, only volumes."""
        with self._lock:
            return {
                "deduped_events": len(self._seen),
                "conversations_with_channel": len(self._channels),
                "conversations_handed_off": len(self._handoffs),
                "conversations_corrected": len(self._corrections),
                "corrections_total": sum(self._corrections.values()),
            }


STATE = HubState()
