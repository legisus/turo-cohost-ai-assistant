import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import turo_agent as ta


# Regression: the real SANEL message that went unanswered must be detected as a
# lock request, so the auto-reply gate fires (thread 55875801, 2026-06-21).
def test_remote_intent_catches_sanel_lock_request():
    assert ta.remote_intent("Is it possible you can lock it?") == "lock"


def test_remote_intent_lock_phrasings():
    assert ta.remote_intent("can you lock the car?") == "lock"
    assert ta.remote_intent("the car won't lock") == "lock"


def test_remote_intent_unlock_unchanged():
    assert ta.remote_intent("I'm at the car and can't get in") == "unlock"


def test_remote_intent_none_for_plain_message():
    assert ta.remote_intent("thanks, the car was great") is None


# The guest-facing confirmation text (#2). Sent only AFTER a confirmed action, so
# it may state the fact; must be signed and match the action.
def test_vehicle_reply_text_lock():
    txt = ta.vehicle_reply_text("lock")
    assert txt and "- %s" % ta.persona.SIGNATURE in txt and "lock" in txt.lower()


def test_vehicle_reply_text_unlock():
    txt = ta.vehicle_reply_text("unlock")
    assert txt and "- %s" % ta.persona.SIGNATURE in txt and "unlock" in txt.lower()


def test_vehicle_reply_text_status_is_none():
    # No guest reply for a status check.
    assert ta.vehicle_reply_text("vstatus") is None
