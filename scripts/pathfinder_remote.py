#!/usr/bin/env python3
"""Verified remote lock/unlock for Turo trips on a NissanConnect vehicle.

Before touching the doors it VERIFIES, from the Turo reservation page, that:
  1. the thread/reservation is for a configured vehicle (the Pathfinder), and
  2. the trip is in an allowed window:
       - UNLOCK: only from 1 hour before pickup, while the trip is active
                 (not ended/cancelled).
       - LOCK:   any time during/around the trip (guest may be unable to lock
                 from inside). Blocked only if the trip is cancelled.

Then it calls ~/nissan-remote (nissan_api) to act, confirms via the
service-request SUCCESS + a lockStatus re-read, and prints a JSON result.

Usage:
  python3 scripts/pathfinder_remote.py check  <thread_id>          # verify only, no action
  python3 scripts/pathfinder_remote.py status <thread_id>          # verify car, read-only telemetry
  python3 scripts/pathfinder_remote.py unlock <thread_id>
  python3 scripts/pathfinder_remote.py lock   <thread_id>

Exit 0 only on an allowed+confirmed action (or a passing 'check'/'status').
"""

import datetime
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NISSAN_DIR = os.path.expanduser("~/nissan-remote")

# vehicle-name substring (lowercase) -> nissan-remote alias (in its config.json)
VEHICLES = {"nissan pathfinder": "pathfinder"}

EARLY_UNLOCK_MIN = 60     # unlock allowed starting 60 min before pickup
LATE_UNLOCK_GRACE_MIN = 120  # ... through 2h past dropoff (late-checkout grace)


def _trip(thread_id):
    out = subprocess.run(
        [sys.executable, os.path.join(HERE, "turo_chrome.py"), "trip", thread_id],
        capture_output=True, text=True,
    )
    line = (out.stdout or "").strip().splitlines()
    for ln in reversed(line):  # last JSON line (driver may print a cwd notice)
        try:
            return json.loads(ln)
        except ValueError:
            continue
    raise SystemExit("could not read trip info for %s: %s" % (thread_id, out.stderr.strip()))


def _parse_dt(pair):
    if not pair:
        return None
    now = datetime.datetime.now()
    try:
        dt = datetime.datetime.strptime(
            "%s %d %s" % (pair["date"], now.year, pair["time"].upper().replace(" ", "")),
            "%a, %b %d %Y %I:%M%p",
        )
    except ValueError:
        return None
    # year inference around the boundary
    if (now - dt).days > 60:
        dt = dt.replace(year=now.year + 1)
    elif (dt - now).days > 300:
        dt = dt.replace(year=now.year - 1)
    return dt


def evaluate(action, trip):
    """Return (allowed: bool, alias: str|None, reason: str)."""
    veh = (trip.get("vehicle") or "").lower()
    alias = next((a for sub, a in VEHICLES.items() if sub in veh), None)
    if not alias:
        return False, None, "vehicle not configured for remote control: %r" % trip.get("vehicle")

    trip_type = (trip.get("tripType") or "").lower()  # booked/past/cancelled trip
    if "cancel" in trip_type:
        return False, alias, "trip is cancelled"

    if action == "lock":
        return True, alias, "lock allowed (guest request); vehicle verified: %s" % trip.get("vehicle")

    # ---- unlock gating ----
    if "past" in trip_type:
        return False, alias, "trip has ended (Past trip)"
    now = datetime.datetime.now()
    pickup = _parse_dt(trip.get("pickup"))
    dropoff = _parse_dt(trip.get("dropoff"))
    if pickup is None:
        return False, alias, "could not read pickup time; blocking unlock (verify manually)"
    earliest = pickup - datetime.timedelta(minutes=EARLY_UNLOCK_MIN)
    if now < earliest:
        return False, alias, ("too early: unlock allowed from 1h before pickup "
                              "(pickup %s, earliest %s)" % (pickup, earliest))
    if dropoff and now > dropoff + datetime.timedelta(minutes=LATE_UNLOCK_GRACE_MIN):
        return False, alias, "trip window ended (dropoff %s + grace)" % dropoff
    return True, alias, "within unlock window (pickup %s, dropoff %s)" % (pickup, dropoff)


def _nissan(args):
    out = subprocess.run(
        [sys.executable, "-m", "nissan_api", "--json"] + args,
        cwd=NISSAN_DIR, capture_output=True, text=True,
    )
    try:
        return out.returncode, json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return out.returncode, {"ok": False, "error": (out.stderr or out.stdout).strip()}


def _lock_status(alias):
    rc, data = _nissan(["status", alias])
    if rc == 0 and isinstance(data, dict):
        return (((data.get("status") or {}).get("lockStatus") or {}).get("lockStatus"))
    return None


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("check", "status", "lock", "unlock"):
        print(__doc__)
        return 2
    action, thread_id = sys.argv[1], sys.argv[2]

    trip = _trip(thread_id)

    if action == "status":
        veh = (trip.get("vehicle") or "").lower()
        alias = next((a for sub, a in VEHICLES.items() if sub in veh), None)
        res = {"action": "status", "thread": thread_id, "vehicle": trip.get("vehicle")}
        if not alias:
            res.update(ok=False, reason="vehicle not configured: %r" % trip.get("vehicle"))
            print(json.dumps(res))
            return 1
        rc, data = _nissan(["status", alias])
        ok = rc == 0 and isinstance(data, dict) and data.get("ok") is not False
        res["ok"] = ok
        res["status"] = data.get("status") if isinstance(data, dict) else data
        if not ok:
            res["reason"] = data.get("error") if isinstance(data, dict) else "status failed"
        print(json.dumps(res))
        return 0 if ok else 1

    verify_action = "lock" if action == "lock" else "unlock"
    allowed, alias, reason = evaluate(verify_action, trip)

    result = {"action": action, "thread": thread_id, "vehicle": trip.get("vehicle"),
              "allowed": allowed, "reason": reason, "trip": trip}

    if action == "check" or not allowed:
        result["ok"] = allowed
        print(json.dumps(result))
        return 0 if allowed else 1

    rc, door = _nissan([action, alias])
    result["door"] = door
    result["lockStatus_after"] = _lock_status(alias)
    confirmed = rc == 0 and isinstance(door, dict) and door.get("confirmed")
    expected = "unlocked" if action == "unlock" else "locked"
    result["ok"] = bool(confirmed and result["lockStatus_after"] == expected)
    print(json.dumps(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
