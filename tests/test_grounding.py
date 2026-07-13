"""Drafts are grounded in reservation facts; pending requests banner the card."""
import os, sys
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import turo_agent as ta

PREVIEW = ("Booked trip with 2025 Tesla Model Y 6:30 AM Dana "
           "(Acme LLC.’s vehicle) can I add a child seat for my trip?")
GUEST_MSG = {"text": "can I add a child seat for my trip? 6:30 AM - Dana (Guest)",
             "tag": "guest", "avatar": "Dana", "outbound": False, "photo": False}
TRIP = {"tripType": "Booked trip",
        "pickup": {"date": "Sat, Jul 12", "time": "4:00 PM"},
        "dropoff": {"date": "Tue, Jul 15", "time": "4:00 PM"},
        "status": "", "req": ["Dana wants to add a child seat", "Approve by Jul 14, 9:00 AM"]}


class FakeTG:
    def __init__(self): self.cards = []
    def send(self, t): pass
    def send_card(self, text, tid, extra_rows=None): self.cards.append(text)


def run(trip_result):
    tg, drafted = FakeTG(), []
    def fake_trip(tid):
        if isinstance(trip_result, Exception):
            raise trip_result
        return trip_result
    with mock.patch.object(ta.chrome, "last_message", lambda tid: GUEST_MSG), \
         mock.patch.object(ta.chrome, "read_thread", lambda tid: "Dana: can I add a child seat?"), \
         mock.patch.object(ta.chrome, "trip", fake_trip), \
         mock.patch.object(ta.draft, "draft_reply",
                           lambda text, **k: drafted.append(text) or "Hi Dana, yes!\n- Alex"), \
         mock.patch.object(ta, "log", lambda m: None):
        ta.make_draft_and_card(tg, {"threads": {}}, "1234", PREVIEW)
    return tg, drafted


def test_facts_block_prepended_and_banner_on_card():
    tg, drafted = run(TRIP)
    assert drafted and drafted[0].startswith("📋 Trip facts: Booked trip")
    assert "child seat" in drafted[0]              # pending request reaches the model
    assert len(tg.cards) == 1
    assert tg.cards[0].startswith("⚠️ Pending guest request:")
    assert "approve/decline in the Turo app" in tg.cards[0]


def test_no_banner_without_pending_request():
    tg, drafted = run({"tripType": "Booked trip", "req": []})
    assert "Pending guest request" not in tg.cards[0]
    assert drafted[0].startswith("📋 Trip facts: Booked trip")


def test_trip_read_failure_still_drafts():
    tg, drafted = run(RuntimeError("reservation page timed out"))
    assert len(tg.cards) == 1                      # card still sent
    assert "📋" not in drafted[0]                  # just no facts block
