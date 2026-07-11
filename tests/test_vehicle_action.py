import os, sys
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import turo_agent as ta


class FakeTG:
    def __init__(self): self.msgs = []
    def send(self, t): self.msgs.append(t)


def run_action(action, remote_result, last_text):
    """Patch the I/O boundaries of do_vehicle_action; capture do_send + log."""
    sent, logged = [], []
    tg = FakeTG()
    with mock.patch.object(ta, "_run_remote", lambda cmd, tid: remote_result), \
         mock.patch.object(ta.chrome, "last_message", lambda tid: {"text": last_text}), \
         mock.patch.object(ta, "do_send", lambda tg, st, tid, text: sent.append((tid, text))), \
         mock.patch.object(ta, "log", lambda m: logged.append(m)):
        ta.do_vehicle_action(tg, {"threads": {}}, action, "55875801")
    return tg, sent, logged


def test_confirmed_lock_when_guest_asked_replies_to_guest():
    tg, sent, logged = run_action("lock", {"ok": True}, "Is it possible you can lock it?")
    assert len(sent) == 1 and sent[0][0] == "55875801"
    assert "locked" in sent[0][1].lower()
    assert any("CONFIRMED" in m for m in logged)


def test_confirmed_lock_proactive_does_not_message_guest():
    # Guest's last message is unrelated -> no auto-reply (proactive /pathfinder lock).
    tg, sent, logged = run_action("lock", {"ok": True}, "thanks, great car!")
    assert sent == []
    assert any("no guest auto-reply" in m for m in logged)


def test_unlock_when_guest_asked_replies():
    tg, sent, logged = run_action("unlock", {"ok": True}, "I'm at the car and can't get in")
    assert len(sent) == 1 and "unlock" in sent[0][1].lower()


def test_blocked_action_logs_and_no_guest_reply():
    tg, sent, logged = run_action("lock", {"ok": False, "allowed": False, "reason": "trip is cancelled"}, "can you lock it?")
    assert sent == []
    assert any("BLOCKED" in m for m in logged)


def test_not_confirmed_logs_and_no_guest_reply():
    tg, sent, logged = run_action("lock", {"ok": False, "allowed": True, "door": {"status": "INITIATED"}}, "can you lock it?")
    assert sent == []
    assert any("NOT CONFIRMED" in m for m in logged)


def test_status_never_messages_guest():
    tg, sent, logged = run_action("vstatus", {"ok": True, "status": {}}, "can you lock it?")
    assert sent == []
