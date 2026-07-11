"""Typed-text routing: the operator's next message must go to the thread whose
button they just tapped — never to some other thread with a stale compose stage.

The bug (2026-07-10): Edit was tapped on thread A on Jun 27 and never completed;
13 days later the operator tapped Regenerate on thread B and typed a hint — the
router picked A (first awaiting thread in dict order) and sent the hint VERBATIM
to A's guest. Root cause: no link between the tapped card and the next text, and
compose stages never expire.
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import turo_agent as ta


def mk_state():
    return {"threads": {
        # stale: operator tapped Edit long ago and never sent the text
        "A": {"last_seen": "", "last_sent": "",
              "pending": {"stage": "await_edit", "draft": "dA", "header": "hA"}},
        "B": {"last_seen": "", "last_sent": "",
              "pending": {"stage": "await_approval", "draft": "dB", "header": "hB"}},
    }}


def test_text_routes_to_last_tapped_thread_not_dict_order():
    state = mk_state()
    ta.begin_compose(state, "B", "await_regen")   # operator taps Regenerate on B
    tid, stage = ta.route_text(state)
    assert (tid, stage) == ("B", "await_regen")   # bug: returned ("A", "await_edit")


def test_tap_supersedes_stale_compose_elsewhere():
    state = mk_state()
    ta.begin_compose(state, "B", "await_regen")
    # A's stale compose must be reverted so its card is still approvable,
    # but it can no longer swallow typed text.
    assert state["threads"]["A"]["pending"]["stage"] == "await_approval"


def test_route_is_consumed_once():
    state = mk_state()
    ta.begin_compose(state, "B", "await_regen")
    ta.consume_compose(state)
    assert ta.route_text(state) == (None, None)   # next text falls through to chat


def test_no_compose_means_chat():
    state = mk_state()
    assert ta.route_text(state) == (None, None)


def test_route_ignores_pointer_to_resolved_thread():
    # Pointer set, but the thread got resolved meanwhile (e.g. superseded card).
    state = mk_state()
    ta.begin_compose(state, "B", "await_regen")
    state["threads"]["B"]["pending"] = None
    assert ta.route_text(state) == (None, None)


def test_startup_clears_stale_compose():
    # After a daemon restart the operator's mid-compose context is gone: every
    # composing stage must revert to a plain approvable card and the pointer clear.
    state = mk_state()
    ta.begin_compose(state, "B", "await_regen")
    ta.clear_stale_compose(state)
    assert state["threads"]["A"]["pending"]["stage"] == "await_approval"
    assert state["threads"]["B"]["pending"]["stage"] == "await_approval"
    assert ta.route_text(state) == (None, None)
