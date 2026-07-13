"""Subprocess wrappers over scripts/turo_chrome.py with hard timeouts.

Running the driver as a subprocess (rather than importing it) isolates the daemon
from a hung Chrome/AppleScript call: the timeout raises instead of freezing.
"""
import json, os, subprocess, base64

_HERE = os.path.dirname(os.path.abspath(__file__))
_PY = os.path.join(_HERE, "..", "..", ".venv", "bin", "python")
_DRIVER = os.path.join(_HERE, "..", "turo_chrome.py")


def _run(args, timeout=45):
    p = subprocess.run([_PY, _DRIVER] + args, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("driver %s failed: %s" % (args, p.stderr.strip() or p.stdout.strip()))
    return p.stdout.strip()


def healthy():
    """True if a logged-in Turo tab is present."""
    return _run(["find"]).startswith("WIN")


def list_threads():
    out = _run(["list"])
    return json.loads(out) if out.startswith("[") else []


def last_message(tid):
    return json.loads(_run(["last", str(tid)], timeout=60))


def read_thread(tid):
    return _run(["read", str(tid)], timeout=60)


def trip(tid):
    """Reservation-page facts: vehicle, pickup/dropoff, status, raw request lines."""
    out = _run(["trip", str(tid)], timeout=60)
    return json.loads(out) if out.startswith("{") else {}


def set_message(tid, text):
    b64 = base64.b64encode(text.encode()).decode()
    return _run(["setmsg", str(tid), b64])


def send(tid):
    return _run(["send", str(tid)])
