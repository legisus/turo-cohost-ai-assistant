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


def test_parse_cohosted_preview_unchanged():
    p = meta.parse_preview(
        "Booked trip with 2024 Subaru Crosstrek 9:17 AM Kayla (Acme LLC.'s vehicle) hello")
    assert p == {"year": "2024", "vehicle": "Subaru Crosstrek",
                 "guest": "Kayla", "host": "Acme LLC."}
