"""Night-return calendar block (2026-10-15).

Operator rule: the car wash closes at 8 PM, so a car returned at night can't be
washed before an early pickup. Every booked or in-progress trip whose return
falls in the night window (from 7:00 PM up to 8:00 AM) gets a host calendar
block on that car from the return time until the next 8:00 AM. Fleet-wide,
co-hosted cars included (probed 2026-10-15: a co-host session may add/remove
blocks on the owners' listings).

Turo fleet-calendar API (cookie-auth, same-origin, probed live 2026-10-15):
  POST /api/fleet/unavailabilities/add     add_body()    -> {requestId, vehicleDates}
  POST /api/fleet/unavailabilities/remove  remove_body() -> {requestId, vehicleDates}
  GET  /api/fleet/unavailabilities/status?requestId&updateType=ADD|REMOVE&vehicleId
       -> {vehicleStatus: SUCCESS, dailyData:[{date, unavailabilities:[{id, start{time},
           end{time}, unavailabilityReason: CUSTOM|RESERVATION}]}]}
  A block overlapping a booked trip is DROPPED SILENTLY (SUCCESS, no CUSTOM
  entry) — confirm_block() turns that into "not placed". A block that crosses
  midnight is one id listed on both days.

Pure functions here; the daemon (turo_agent.night_block_sweep) owns the driver
calls, state["night_blocks"] and the Telegram lines.
"""
import datetime, time

DEFAULTS = {"enabled": True, "from": "19:00", "until": "08:00", "interval_sec": 900,
            "gap_hours": 3,      # Turo's minimum gap between trips: a return within
                                 # gap_hours of `until` needs no block (operator 2026-10-15)
            "notes": ""}         # notes are visible on Turo; keep empty (operator 2026-10-15)
RETRY_FAILED_SEC = 86400     # a dropped add is retried once a day (the clash may clear)


def _hm(hhmm):
    h, m = (hhmm or "0:0").split(":")[:2]
    return int(h) * 60 + int(m)


def night_return(end_time, start="19:00", until="08:00", gap_hours=3):
    """True when a return at end_time (24h HH:MM) lands in [start, 24:00) ∪
    [00:00, until - gap_hours): Turo will not let the next trip start within
    gap_hours of a return, so a 5–8 AM return already cannot be picked up
    before 8 AM and needs no block."""
    t = _hm(end_time)
    return t >= _hm(start) or t < _hm(until) - int(round(float(gap_hours or 0) * 60))


def window(end_date, end_time, start="19:00", until="08:00", gap_hours=3):
    """Block span for a trip ending end_date end_time, or None when it needs none:
    an evening return blocks until `until` NEXT day, an after-midnight return
    until `until` the same morning."""
    if not end_date or not end_time or not night_return(end_time, start, until, gap_hours):
        return None
    d = datetime.date.fromisoformat(end_date)
    if _hm(end_time) >= _hm(start):
        d += datetime.timedelta(days=1)
    return {"start_date": end_date, "start_time": end_time,
            "end_date": d.isoformat(), "end_time": until}


def local_ms(date, hhmm):
    """Local-time epoch ms (the daemon Mac runs in the fleet's LA timezone)."""
    dt = datetime.datetime.strptime("%s %s" % (date, hhmm), "%Y-%m-%d %H:%M")
    return int(time.mktime(dt.timetuple()) * 1000)


def plan(upcoming, blocks, cfg, now_ms):
    """Diff the feed against the blocks we hold -> ordered actions.

    upcoming: turo_api.map_upcoming rows (one trip may appear several times —
              the feed emits an item per event type).
    blocks:   state["night_blocks"] {res_id: {vehicle_id, block_id, window,
              failed_ts?, vehicle_name?, plate?}}.
    Actions: {"op": add|remove|forget, "res_id", "vehicle_id", "window",
              "block_id", "reason", "row"}.
    """
    start, until = cfg.get("from", DEFAULTS["from"]), cfg.get("until", DEFAULTS["until"])
    gap = cfg.get("gap_hours", DEFAULTS["gap_hours"])
    seen, want = set(), {}
    for u in upcoming or []:
        rid = str(u.get("reservation_id") or "")
        if not rid or not u.get("vehicle_id") or rid in seen:
            continue
        seen.add(rid)
        w = window(u.get("end_date"), u.get("end_time"), start, until, gap)
        if w:
            want[rid] = (u["vehicle_id"], w, u)
    actions = []
    for rid, (vid, w, u) in want.items():
        cur = blocks.get(rid) or {}
        if cur.get("window") == w:
            if cur.get("block_id"):
                continue                                   # in place
            if cur.get("failed_ts") and now_ms / 1000 - cur["failed_ts"] < RETRY_FAILED_SEC:
                continue                                   # alerted; retry tomorrow
        elif cur.get("block_id"):
            actions.append({"op": "remove", "res_id": rid, "vehicle_id": cur.get("vehicle_id", vid),
                            "window": cur["window"], "block_id": cur["block_id"],
                            "reason": "trip end changed", "row": u})
        if u.get("end_ms") and u["end_ms"] <= now_ms:
            continue                                       # trip already over
        actions.append({"op": "add", "res_id": rid, "vehicle_id": vid, "window": w,
                        "block_id": None, "reason": "night return", "row": u})
    for rid, cur in blocks.items():
        if rid in want:
            continue
        base = {"res_id": rid, "vehicle_id": cur.get("vehicle_id"), "window": cur.get("window"),
                "block_id": cur.get("block_id"), "row": cur}
        if not cur.get("block_id"):
            actions.append(dict(base, op="forget", reason="no block held"))
            continue
        w = cur.get("window") or {}
        try:
            starts = local_ms(w["start_date"], w["start_time"])
        except (KeyError, ValueError):
            starts = 0
        if starts <= now_ms:
            actions.append(dict(base, op="forget", reason="block already served"))
        elif rid in seen:
            actions.append(dict(base, op="remove", reason="trip end moved to daytime"))
        else:
            actions.append(dict(base, op="remove", reason="trip cancelled"))
    return actions


def confirm_block(status, start_date, start_time):
    """The id of OUR block in an ADD status payload (CUSTOM entry starting at
    start_date start_time), else None. Lags behind the add — the driver confirms
    through the list endpoint first and uses this only as a fallback."""
    for d in ((status or {}).get("dailyData") or []):
        if d.get("date") != start_date:
            continue
        for u in d.get("unavailabilities") or []:
            if (u.get("unavailabilityReason") == "CUSTOM" and u.get("id")
                    and ((u.get("start") or {}).get("time") == start_time)):
                return u["id"]
    return None


def list_body(vehicle_id, w):
    """POST /api/fleet/unavailabilities body: every block of the vehicle touching
    the window's days (this list shows ALL blocks, with notes and tripOverlapped;
    the calendar read collapses overlapping blocks into one)."""
    dates = [w["start_date"]] + ([w["end_date"]] if w["end_date"] != w["start_date"] else [])
    return {"vehicleId": vehicle_id, "dates": dates}


def find_blocks(listing, w):
    """Ids of the blocks in a list payload that span exactly window w (oldest
    first). Used to adopt an existing block before adding (no duplicates) and
    to confirm an add — the status endpoint lags and under-reports."""
    out = []
    for u in ((listing or {}).get("unavailabilities") or []):
        st, en = u.get("start") or {}, u.get("end") or {}
        if (u.get("id") and st.get("localDate") == w["start_date"] and st.get("localTime") == w["start_time"]
                and en.get("localDate") == w["end_date"] and en.get("localTime") == w["end_time"]):
            out.append(u["id"])
    return sorted(out)


def add_body(vehicle_id, w, notes=""):
    return {"type": "TIMESPAN_DISCRETE", "startTime": w["start_time"], "endTime": w["end_time"],
            "notes": notes or "",
            "timespanDiscreteVehicleDates": {"startDate": w["start_date"], "endDate": w["end_date"],
                                             "vehicleIds": [vehicle_id]}}


def remove_body(block_id):
    return {"type": "DISTINCT", "distinctUnavailability": {"unavailabilityId": block_id},
            "repeatType": "INDIVIDUAL"}


def fmt(date, hhmm):
    """'Mon 10/19 10:30 PM' for Telegram lines."""
    dt = datetime.datetime.strptime("%s %s" % (date, hhmm), "%Y-%m-%d %H:%M")
    return "%s %d/%d %d:%02d %s" % (dt.strftime("%a"), dt.month, dt.day,
                                    dt.hour % 12 or 12, dt.minute, "AM" if dt.hour < 12 else "PM")


def car_label(row):
    name = (row or {}).get("vehicle_name") or (row or {}).get("name") or "car"
    plate = (row or {}).get("plate") or ""
    return ("%s %s" % (name, plate)).strip()
