"""Regression (2026-07-12): a partial thread render returned an older, untagged
message as the "last" one; it classified 'unknown' and the host's own farewell was
carded as a guest message. make_draft_and_card must re-read when the thread read
disagrees with the inbox preview, and skip once the true (host) message appears."""
import os, sys
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import turo_agent as ta

PREVIEW = ("Booked trip with 2025 Tesla Model Y 6:30 AM Dana "
           "(Acme LLC.’s vehicle) Hi Dana . I am glad you were my guest. "
           "When the trip is over, leave the car where you picked it up. Don't forget to leave")

STALE = {"text": "How much should I charge before drop off?", "tag": "",
         "avatar": "", "outbound": False, "photo": False}
FRESH = {"text": ("Hi Dana .\nI am glad you were my guest. When the trip is over, "
                  "leave the car where you picked it up. Don't forget to leave the keys "
                  "inside the car.\n\n6:30 AM - Acme LLC. (Host)"),
         "tag": "host", "avatar": "Acme LLC.", "outbound": False, "photo": False}


class FakeTG:
    def __init__(self): self.msgs = []
    def send(self, t): self.msgs.append(t)
    def send_card(self, *a, **k): self.msgs.append(("card", a))


def run(reads):
    reads = list(reads)
    tg, logged = FakeTG(), []
    drafted = []
    with mock.patch.object(ta.chrome, "last_message", lambda tid: reads.pop(0)), \
         mock.patch.object(ta.chrome, "read_thread", lambda tid: "thread text"), \
         mock.patch.object(ta.chrome, "trip", lambda tid: {}), \
         mock.patch.object(ta.draft, "draft_reply",
                           lambda *a, **k: drafted.append(1) or "SKIP"), \
         mock.patch.object(ta, "log", lambda m: logged.append(m)):
        ta.make_draft_and_card(tg, {"threads": {}}, "12345678", PREVIEW)
    return tg, logged, drafted


def test_stale_first_read_is_reread_and_host_message_skipped():
    tg, logged, drafted = run([STALE, FRESH])
    assert any("stale render" in m for m in logged)
    assert any("from host" in m for m in logged)      # classified host after re-read
    assert drafted == [] and tg.msgs == []            # no draft, no card


def test_fresh_first_read_needs_no_reread():
    tg, logged, drafted = run([FRESH])                # a second read would IndexError
    assert not any("stale render" in m for m in logged)
    assert any("from host" in m for m in logged)


def test_persistently_stale_read_still_proceeds_to_draft():
    # The guard must never silently drop a message: after two re-reads it proceeds
    # and lets classification/Claude decide (STALE is untagged -> 'unknown' -> draft).
    tg, logged, drafted = run([STALE, STALE, STALE])
    assert any("still disagrees" in m for m in logged)
    assert drafted == [1]                             # drafted (Claude said SKIP)
