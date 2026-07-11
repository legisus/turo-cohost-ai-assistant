"""Operator/host identity, loaded from config.json so any Turo host can adapt the
tool without touching code. Generic defaults apply when the keys are absent —
set `signature`, `host_names`, and `remote_vehicle_names` in config.json.

- SIGNATURE: signs every guest reply ("- <name>") and marks our own messages.
- HOST_NAMES: every host-team account whose messages must never be answered as a
  guest's (owners you co-host for; Turo scheduled messages come from them too).
- REMOTE_VEHICLE_NAMES: vehicle names wired for remote lock/unlock (lowercase
  substring match against the card header / inbox preview).
"""
import json, os

_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "config.json")


def _load():
    try:
        with open(_CONFIG) as f:
            return json.load(f)
    except Exception:
        return {}


_c = _load()
SIGNATURE = _c.get("signature", "Alex")
HOST_NAMES = list(_c.get("host_names", ["Sample Owner LLC."]))
REMOTE_VEHICLE_NAMES = tuple(n.lower() for n in _c.get("remote_vehicle_names", []))

# Lowercased first tokens for avatar matching (operator included).
KNOWN_HOST_TOKENS = tuple(sorted(
    {n.split()[0].lower().rstrip(".") for n in HOST_NAMES if n.strip()}
    | {SIGNATURE.split()[0].lower()}))

# Host-team names as shown in prompts (operator included).
TEAM_NAMES = HOST_NAMES + [SIGNATURE]
