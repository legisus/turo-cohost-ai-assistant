import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from agent import detect

def mk_state(threads): return {"threads": threads}

def test_new_thread_is_candidate():
    listing = [{"id": "1", "text": "Booked trip 9:00 PM Steve hello there"}]
    state = mk_state({})  # unseen id treated as candidate
    assert detect.candidates(listing, state) == ["1"]

def test_unchanged_preview_not_candidate():
    listing = [{"id": "1", "text": "same"}]
    state = mk_state({"1": {"last_seen": "same", "last_sent": "", "pending": None}})
    assert detect.candidates(listing, state) == []

def test_own_echo_not_candidate():
    listing = [{"id": "1", "text": "Thanks, see you then! - Jane"}]
    state = mk_state({"1": {"last_seen": "older", "last_sent": "Thanks, see you then! - Jane", "pending": None}})
    assert detect.candidates(listing, state) == []

def test_cancelled_trip_skipped():
    listing = [{"id": "1", "text": "Cancelled trip 7:00 PM Kelley need pickup"}]
    state = mk_state({})
    assert detect.candidates(listing, state) == []

def test_awaiting_approval_new_message_supersedes():
    # A NEW guest message on a thread merely awaiting approval MUST re-card —
    # otherwise messages are silently dropped while a stale card sits unresolved
    # (the bug: guest's later messages never surfaced).
    listing = [{"id": "1", "text": "new message"}]
    state = mk_state({"1": {"last_seen": "old", "last_sent": "", "pending": {"stage": "await_approval"}}})
    assert detect.candidates(listing, state) == ["1"]


def test_awaiting_approval_unchanged_not_recandidated():
    # No new message (preview unchanged) -> still not a candidate (last_seen guard).
    listing = [{"id": "1", "text": "same"}]
    state = mk_state({"1": {"last_seen": "same", "last_sent": "", "pending": {"stage": "await_approval"}}})
    assert detect.candidates(listing, state) == []


def test_mid_compose_not_interrupted():
    # While the operator is actively editing/regenerating, a new message does NOT
    # interrupt (their in-progress input would be lost).
    for stage in ("await_edit", "await_regen"):
        listing = [{"id": "1", "text": "new message"}]
        state = mk_state({"1": {"last_seen": "old", "last_sent": "", "pending": {"stage": stage}}})
        assert detect.candidates(listing, state) == [], stage

def test_seed_marks_all_seen_without_candidates():
    listing = [{"id": "1", "text": "a"}, {"id": "2", "text": "b"}]
    state = detect.seed(listing)
    assert state["threads"]["1"]["last_seen"] == "a"
    assert state["threads"]["2"]["last_seen"] == "b"
    assert detect.candidates(listing, state) == []
