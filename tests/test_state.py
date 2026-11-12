"""In-memory state tests: dedupe, channel and the correction cap.

They replace the persistent-store tests. The contract that matters is the same
(idempotency + per-conversation cap); what changes is where the data lives,
and that is documented as a decision in app/core/state.py.
"""

from __future__ import annotations

import threading

import pytest

from app.core.state import DEDUPE_MAX, HubState


# --- Idempotencia ----------------------------------------------------------

def test_first_delivery_is_not_duplicate():
    st = HubState()
    assert st.seen_before("message.created:m1") is False


def test_second_delivery_of_same_key_is_duplicate():
    st = HubState()
    st.seen_before("message.created:m1")
    assert st.seen_before("message.created:m1") is True


def test_different_keys_are_independent():
    st = HubState()
    assert st.seen_before("a") is False
    assert st.seen_before("b") is False
    assert st.seen_before("a") is True


def test_dedupe_cache_is_bounded():
    """Un servicio dias levantado no puede crecer sin tope."""
    st = HubState()
    for i in range(DEDUPE_MAX + 500):
        st.seen_before(f"k{i}")
    assert len(st._seen) == DEDUPE_MAX
    # The oldest entry was evicted; re-delivering it would now look new.
    # That is the trade accepted by staying in RAM.
    assert "k0" not in st._seen
    assert st.seen_before(f"k{DEDUPE_MAX + 499}") is True


def test_concurrent_deliveries_only_one_wins():
    """Atomic check-and-mark: N threads with the same key -> exactly 1 new."""
    st = HubState()
    results: list[bool] = []
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        results.append(st.seen_before("same-key"))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(False) == 1
    assert results.count(True) == 7


# --- Channel per conversation ------------------------------------------------

def test_channel_roundtrip():
    st = HubState()
    st.remember_channel("conv-1", "whatsapp")
    assert st.channel_for("conv-1") == "whatsapp"


def test_unknown_conversation_has_no_channel():
    st = HubState()
    assert st.channel_for("no-existe") is None
    assert st.channel_for(None) is None


def test_empty_values_are_not_stored():
    st = HubState()
    st.remember_channel("", "email")
    st.remember_channel("conv-2", "")
    assert st.channel_for("") is None
    assert st.channel_for("conv-2") is None


def test_channel_cache_is_bounded():
    st = HubState()
    for i in range(2500):
        st.remember_channel(f"c{i}", "email")
    assert len(st._channels) <= 2000


# --- Tope de correcciones --------------------------------------------------

def test_correction_slots_up_to_the_limit():
    st = HubState()
    assert [st.take_correction_slot("c1", 3) for _ in range(3)] == [True, True, True]
    assert st.take_correction_slot("c1", 3) is False
    assert st.corrections_count("c1") == 3


def test_limit_is_per_conversation():
    st = HubState()
    for _ in range(3):
        st.take_correction_slot("c1", 3)
    assert st.take_correction_slot("c2", 3) is True


def test_concurrent_reservations_respect_the_limit():
    """Two concurrent pipelines must not exceed the cap by reading one count."""
    st = HubState()
    granted: list[bool] = []
    lock = threading.Lock()
    barrier = threading.Barrier(10)

    def worker():
        barrier.wait()
        ok = st.take_correction_slot("c1", 3)
        with lock:
            granted.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert granted.count(True) == 3
    assert st.corrections_count("c1") == 3


# --- Introspeccion ---------------------------------------------------------

def test_snapshot_reports_volumes_not_content():
    st = HubState()
    st.seen_before("k1")
    st.remember_channel("c1", "email")
    st.take_correction_slot("c1", 5)
    snap = st.snapshot()
    assert snap["deduped_events"] == 1
    assert snap["conversations_with_channel"] == 1
    assert snap["conversations_corrected"] == 1
    assert snap["corrections_total"] == 1
    assert all(isinstance(v, int) for v in snap.values())


def test_shared_state_instance_exists():
    from app.core.state import STATE

    assert isinstance(STATE, HubState)
