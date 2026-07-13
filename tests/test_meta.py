import os, sys
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from agent import meta

HOST, GUEST = "Acme LLC.", "Christie"


def msg(text="", tag="", avatar="", outbound=False, photo=False):
    return {"text": text, "tag": tag, "avatar": avatar, "outbound": outbound, "photo": photo}


# --- the bug: the operator's own sent message must be recognized as host ------
def test_operator_own_unsigned_message_is_host():
    # Right-aligned bubble, no (Host)/(Guest) tag, no avatar, not signed "- Alex".
    # Before the fix this returned "unknown" and got drafted as if a guest sent it.
    m = msg(text="You can make check out pictures and then upload it 10:44 PM",
            outbound=True)
    assert meta.classify_sender(m, HOST, GUEST) == "host"


def test_operator_own_signed_message_is_host():
    m = msg(text="Give it a few seconds and try again - Alex", outbound=True)
    assert meta.classify_sender(m, HOST, GUEST) == "host"


# --- regression: outbound must NOT swallow received messages ------------------
def test_guest_notag_message_is_not_skipped():
    # A real guest message that lacks the (Guest) tag (Turo only tags the last of a
    # consecutive group). It is left-aligned (outbound=False) and MUST NOT be host.
    m = msg(text="Hi I just landed. Where in the car park is the car?",
            outbound=False, avatar="")
    assert meta.classify_sender(m, HOST, GUEST) != "host"


def test_guest_tagged_message_is_guest():
    m = msg(text="And which car park? 2:06 PM - Christie (Guest)", tag="guest",
            avatar="Christie")
    assert meta.classify_sender(m, HOST, GUEST) == "guest"


def test_owner_tagged_message_is_host():
    m = msg(text="Friendly Reminder: ... 5:00 PM - Acme LLC. (Host)", tag="host",
            avatar="Acme LLC.")
    assert meta.classify_sender(m, HOST, GUEST) == "host"


# --- the bug (2026-07-10): Viktor P's automatic messages carded as guest ------
def test_known_host_avatar_recognized_without_preview():
    # Preview parse often fails (host=""), so the avatar must be checked against
    # the KNOWN host roster, not only the name parsed from the preview.
    m = msg(text="Check-in instructions: the car is parked at ...",
            avatar="Viktor P")
    with mock.patch.object(meta, "KNOWN_HOSTS", ("viktor",)):
        assert meta.classify_sender(m, "", "") == "host"


def test_evgenii_avatar_with_parsed_preview_is_host():
    m = msg(text="Your pickup steps ...", avatar="Viktor")
    assert meta.classify_sender(m, "Viktor P", "MEI") == "host"


def test_unknown_avatar_still_guest_when_matches_guest():
    m = msg(text="what time can I pick up?", avatar="MEI")
    with mock.patch.object(meta, "KNOWN_HOSTS", ("viktor",)):
        assert meta.classify_sender(m, "", "MEI") == "guest"


# --- the bug (2026-07-10): own-account vehicles have NO "(X's vehicle)" suffix ---
# Turo only appends the suffix for co-hosted vehicles from other owners' accounts;
# the operator's own cars parsed to None -> cards showed a bare thread id.

def test_parse_own_vehicle_preview_without_suffix():
    p = meta.parse_preview("Booked trip with 2017 Ford Escape 8:07 PM David Yes, same level please")
    assert p is not None
    assert p["year"] == "2017" and p["vehicle"] == "Ford Escape"
    assert p["guest"] == "David"
    assert p["host"] == meta.OWN_HOST   # own account (persona.SIGNATURE)


def test_parse_own_vehicle_preview_with_trip_date():
    p = meta.parse_preview("Booked trip with 2017 Ford Escape 06/17/2026 6:14 PM Kimberly Hello Kimberly, Thank you")
    assert p is not None
    assert p["vehicle"] == "Ford Escape"   # date must not pollute the vehicle name
    assert p["guest"] == "Kimberly"


def test_parse_cohosted_preview_with_trip_date_keeps_vehicle_clean():
    p = meta.parse_preview(
        "Booked trip with 2025 Tesla Model 3 07/09/2026 4:12 PM MEI (Viktor P's vehicle) hi")
    assert p is not None
    assert p["vehicle"] == "Tesla Model 3" and p["host"] == "Viktor P"
    assert p["guest"] == "MEI"


# --- the bug (2026-07-12): partial thread render carded the host's own message ---
# The inbox preview always carries the beginning of the TRUE latest message. If the
# thread read returns a different last message (partial/out-of-order SPA render),
# the stale message was classified 'unknown' and drafted as if a guest sent it.

_FAREWELL_PREVIEW = ("Booked trip with 2025 Tesla Model Y 6:30 AM Dana "
                     "(Acme LLC.’s vehicle) Hi Dana . I am glad you were my guest. "
                     "When the trip is over, leave the car where you picked it up. Don't forget to leave")


def test_stale_read_detected_when_last_msg_differs_from_preview():
    stale = "How much should I charge the car before drop off? 9:12 PM - Dana (Guest)"
    assert meta.preview_matches_last(_FAREWELL_PREVIEW, stale) is False


def test_fresh_read_matches_preview_despite_newlines_and_suffix():
    fresh = ("Hi Dana .\nI am glad you were my guest. When the trip is over, "
             "leave the car where you picked it up. Don't forget to leave the keys inside "
             "the car and don't forget to fill up the gas tank—full—or charge it. "
             "Please text me when you leave the car.\n\n6:30 AM - Acme LLC. (Host)")
    assert meta.preview_matches_last(_FAREWELL_PREVIEW, fresh) is True


def test_guest_message_matches_its_preview():
    pv = ("Booked trip with 2025 Tesla Model 3 5:21 AM KAYLA (Acme LLC.’s vehicle) "
          "Hi there, I have a early flight. The app will not let me check out yet. But I’ve added")
    txt = ("Hi there, I have a early flight. The app will not let me check out yet. "
           "But I’ve added new photos and left the car in B7 @ garage\n5:21 AM - KAYLA (Guest)")
    assert meta.preview_matches_last(pv, txt) is True


def test_own_account_preview_matches_message():
    pv = "Booked trip with 2017 Ford Escape 8:07 PM David Yes, same level please. I will be there"
    assert meta.preview_matches_last(pv, "Yes, same level please. I will be there in 5\n8:07 PM") is True


def test_unparseable_or_empty_preview_fails_open():
    assert meta.preview_matches_last("", "anything at all in the message body") is True
    assert meta.preview_matches_last("Some odd system banner", "anything at all here") is True


def test_short_low_signal_message_fails_open():
    # 'Ok' carries too little signal to declare the read stale — never block on it.
    pv = "Booked trip with 2017 Ford Escape 8:07 PM David Ok"
    assert meta.preview_matches_last(pv, "Ok 8:07 PM - David (Guest)") is True
    assert meta.preview_matches_last(pv, "Thanks! 7:00 PM - David (Guest)") is True


# --- reservation page: distill pending guest request lines -------------------
def test_pending_request_distills_change_request():
    lines = ["Trip change request", "Dana wants to change the trip dates",
             "Jul 15, 4:00 PM → Jul 17, 10:00 AM", "Approve by Jul 14, 9:00 AM"]
    out = meta.pending_request(lines)
    assert "wants to change" in out and "Approve by" in out


def test_pending_request_ignores_boilerplate_and_dedupes():
    lines = ["CANCELLATION POLICY", "Request a change", "Special requests?",
             "Dana wants to add a child seat", "Dana wants to add a child seat"]
    out = meta.pending_request(lines)
    assert out.count("child seat") == 1
    assert "CANCELLATION" not in out and "Request a change" not in out


def test_pending_request_empty_when_nothing_pending():
    assert meta.pending_request([]) == ""
    assert meta.pending_request(None) == ""
    assert meta.pending_request(["Booked trip", "Pickup & return"]) == ""


def test_parse_cohosted_preview_unchanged():
    p = meta.parse_preview(
        "Booked trip with 2024 Subaru Crosstrek 9:17 AM Kayla (Acme LLC.'s vehicle) hello")
    assert p == {"year": "2024", "vehicle": "Subaru Crosstrek",
                 "guest": "Kayla", "host": "Acme LLC."}
