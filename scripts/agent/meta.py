"""Build a human-readable card header from an inbox preview.

Header pattern (user-requested): host / vehicle / plate / guest.
Host, vehicle, and guest come straight from the inbox preview text. The plate is a
local lookup in vehicles.json (make+model+year -> plate); for fleet duplicates the
message can't say which physical car, so we show 'N in fleet'.
"""
import json, os, re

from agent import persona

_VJSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "vehicles.json")

# Co-hosted: "Booked trip with 2024 Subaru Crosstrek 9:17 AM Kayla (Acme LLC.'s vehicle) ..."
# Own account: same but WITHOUT the "(X's vehicle)" suffix — Turo only appends it for
# other owners' cars. Either variant may carry a trip date after the vehicle name
# ("... Ford Escape 06/17/2026 6:14 PM ..."), which must not pollute the vehicle.
_STEM = (r"(?:Booked|Past|Cancelled) trip with (\d{4}) (.+?)"
         r"(?:\s+\d{1,2}/\d{1,2}/\d{4})?"
         r" \d{1,2}:\d{2}\s*[AP]M ")
_PREVIEW = re.compile(_STEM + r"(.+?) \((.+?)['’]s vehicle\)")
_PREVIEW_OWN = re.compile(_STEM + r"(\S+)")  # guest first name only — no suffix delimiter
OWN_HOST = persona.SIGNATURE  # host label for vehicles in the operator's own account


def _plate_map():
    try:
        with open(_VJSON) as f:
            return json.load(f).get("by_make_model_year", {})
    except Exception:
        return {}


def parse_preview(text):
    m = _PREVIEW.search(text or "")
    if m:
        return {"year": m.group(1), "vehicle": m.group(2).strip(),
                "guest": m.group(3).strip(), "host": m.group(4).strip()}
    m = _PREVIEW_OWN.search(text or "")
    if m:
        return {"year": m.group(1), "vehicle": m.group(2).strip(),
                "guest": m.group(3).strip(), "host": OWN_HOST}
    return None


def plate_for(vehicle, year):
    plates = _plate_map().get(("%s %s" % (vehicle, year)).lower(), [])
    if len(plates) == 1:
        return plates[0]
    if len(plates) > 1:
        return "%d in fleet" % len(plates)
    return "?"


# Every host-team account whose messages must never be answered as a guest's.
# The inbox preview often fails to parse (host=""), so avatar matching cannot
# rely on the preview name alone — check this roster too. Configured via
# config.json `host_names`/`signature` (see agent/persona.py); keep the rules
# file host list in sync when a host account is added.
KNOWN_HOSTS = persona.KNOWN_HOST_TOKENS


def classify_sender(last, host, guest):
    """Who sent the latest message: 'host', 'guest', or 'unknown'.
    Uses the reliable per-message signals when present (in priority order):
      1. 'outbound' — our own sent messages render as right-aligned bubbles; these
         carry NO (Host)/(Guest) tag and NO avatar, so without this they fell through
         to 'unknown' and got drafted as if a guest sent them (the self-reply bug).
      2. the (Host)/(Guest) text tag (reliable for received messages, but Turo only
         appends it to the LAST message of a consecutive same-sender group).
      3. the "- <signature>" signature or the avatar name.
    Returns 'unknown' for an unmarked grouped received message so the caller can let
    Claude arbitrate (drafting an extra reply is recoverable; dropping a real guest
    message is not — so we never infer 'host' from the mere ABSENCE of a tag)."""
    if last.get("outbound"):
        return "host"
    tag = (last.get("tag") or "")
    if tag in ("host", "guest"):
        return tag
    text = (last.get("text") or "").lower()
    if persona.SIGNATURE.lower() in text:
        return "host"
    av = (last.get("avatar") or "").lower()
    if av:
        h = (host or "").lower().rstrip(".")
        g = (guest or "").lower()
        if (h and (h.split()[0] in av or av in h)) or "llc" in av:
            return "host"
        if g and (g.split()[0] in av or av.split()[0] in g):
            return "guest"
        # Roster fallback AFTER the guest check: a guest sharing a host's first
        # name must not be skipped; this only catches host accounts the preview
        # failed to name (e.g. a co-hosted owner's scheduled messages, host="" parse).
        if any(k in av for k in KNOWN_HOSTS):
            return "host"
    return "unknown"


def header(preview_text, tid):
    p = parse_preview(preview_text)
    if not p:
        return "\U0001F697 thread %s" % tid
    return "\U0001F697 %s / %s %s / %s / %s" % (
        p["host"], p["year"], p["vehicle"], plate_for(p["vehicle"], p["year"]), p["guest"])
