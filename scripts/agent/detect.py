"""Pure detection: which threads need a draft this cycle.

A thread is a candidate when its current inbox preview differs from what we last
saw AND differs from what we last sent (not our own echo), and it is not a
cancelled trip. `seed` initializes state on cold start so only post-startup
messages are acted on.

A NEW message supersedes a card that is merely awaiting approval (else the
guest's later messages are silently dropped while a stale card sits unresolved).
We only hold back when the operator is mid-compose (editing/regenerating), so
their in-progress input isn't clobbered.
"""

# pending stages during which a new message must NOT interrupt the operator.
_COMPOSING = ("await_edit", "await_regen", "await_teach")


def _thread(state, tid):
    return state.get("threads", {}).get(tid, {})


def candidates(listing, state):
    out = []
    for item in listing:
        tid, text = item["id"], item["text"]
        if "Cancelled trip" in text:
            continue
        t = _thread(state, tid)
        if (t.get("pending") or {}).get("stage") in _COMPOSING:
            continue
        if text == t.get("last_seen"):
            continue
        if text == t.get("last_sent"):
            continue
        out.append(tid)
    return out


def seed(listing):
    threads = {}
    for item in listing:
        threads[item["id"]] = {"last_seen": item["text"], "last_sent": "", "pending": None}
    return {"threads": threads}
