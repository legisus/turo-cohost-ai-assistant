"""Map Turo's internal JSON API responses to the bot's internal shapes.

Turo has no public API; these are the endpoints turo.com's own frontend calls,
fetched from INSIDE the logged-in tab (same cookies, real browser — see
turo_chrome.api_get). Shapes were probed live on 2026-07-13. A shape change
must degrade gracefully: mappers raise ValueError only when a payload is
structurally unusable, which the driver turns into a DOM-scraping fallback.
"""
import re

API_FEED = "/api/v2/feeds/conversation?appMode=HOST&itemsPerPage=%d&page=1"
API_CONV = "/api/v2/reservation/conversation?reservationId=%s"
API_DETAIL = "/api/reservation/detail?oppTermsAware=true&reservationId=%s"


def _ampm(hhmm):
    h, m = (hhmm or "0:0").split(":")[:2]
    h = int(h)
    return "%d:%s %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def _trip_word(status_code):
    s = (status_code or "").upper()
    if "CANCEL" in s:
        return "Cancelled trip"
    return "Booked trip" if s == "BOOKED" else "Past trip"


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def synth_preview(item):
    """Synthesize the DOM inbox-preview format from a feed item so downstream
    parsing (meta.parse_preview / header / preview_matches_last) is unchanged.
    The format is now under OUR control — stable across Turo redesigns."""
    r = item.get("reservation") or {}
    m = item.get("mostRecentMessage") or {}
    v = r.get("vehicle") or {}
    bits = ["%s with %s %s %s" % (_trip_word(r.get("statusCode")), v.get("year", ""),
                                  v.get("make", ""), v.get("model", "")),
            _ampm((m.get("sentTime") or {}).get("localTime")),
            (r.get("renter") or {}).get("firstName", "")]
    if r.get("vehicleOwnerTitle"):
        bits.append(r["vehicleOwnerTitle"])   # e.g. "(Jane’s vehicle)"
    bits.append(_clean(m.get("text")))
    return _clean(" ".join(b for b in bits if b))[:200]


def map_feed(data):
    """Feed → inbox listing items; adds structured keys the DOM can't provide."""
    items = []
    for it in (data or {}).get("list") or []:
        r = it.get("reservation") or {}
        m = it.get("mostRecentMessage") or {}
        if not r.get("id"):
            continue
        items.append({"id": str(r["id"]), "text": synth_preview(it),
                      "last_msg_id": str(m.get("id") or ""),
                      "last_role": (m.get("authorDriverRole") or "").upper(),
                      "pending": bool(r.get("hasPendingChangeRequest"))})
    if not items:
        raise ValueError("feed had no usable conversations")
    return items


def map_messages(data):
    """Conversation payload → message dicts (legacy keys kept for classify)."""
    if not isinstance(data, list) or not data:
        raise ValueError("conversation payload unusable")
    # The live API returns NEWEST-first; the bot's contract is oldest-first
    # (msgs[-1] == latest everywhere). Sort by epoch — never trust the order.
    data = sorted(data, key=lambda m: (m.get("sentTime") or {}).get("epochMillis") or 0)
    out = []
    for m in data:
        a = m.get("author") or {}
        out.append({"text": (m.get("text") or "").strip(),
                    "id": str(m.get("id") or ""),
                    "role": (m.get("authorDriverRole") or "").upper(),
                    "avatar": a.get("name") or a.get("firstName") or "",
                    "photo": bool((m.get("media") or {}).get("images")),
                    "tag": "", "outbound": False})
    return out


def thread_lines(msgs):
    """Render messages exactly like the DOM `read` output for the draft prompt."""
    return ["%s: %s%s" % (m["avatar"] or m["role"] or "?", _clean(m["text"]),
                          " [PHOTO ATTACHED]" if m["photo"] else "")
            for m in msgs if m["text"] or m["photo"]]


def map_trip(reservation, detail):
    """Reservation (feed) + detail → the trip dict draft.facts_line consumes."""
    r = reservation or {}
    iv = r.get("interval") or (detail or {}).get("interval") or {}

    def _end(k):
        p = iv.get(k) or {}
        if not p.get("localDate"):
            return None
        return {"date": p.get("localDate", ""), "time": _ampm(p.get("localTime"))}

    v = r.get("vehicle") or (detail or {}).get("vehicle") or {}
    name = _clean(" ".join(str(v.get(k) or "") for k in ("year", "make", "model")))
    plate = ((((detail or {}).get("vehicle") or {}).get("registration") or {})
             .get("licensePlate") or "")
    end_pair = iv.get("end") or {}
    trip = {"tripType": _trip_word(r.get("statusCode") or (detail or {}).get("statusCode")),
            "pickup": _end("start"), "dropoff": _end("end"),
            "vehicle": name or None,
            "status": "", "pending_request": "",
            "plate": plate,
            "location": _place(detail),
            "extras": _extras(detail),
            "vehicle_id": ((detail or {}).get("vehicle") or {}).get("id"),
            "res_id": str(r.get("id") or (detail or {}).get("id") or "") or None,
            "pickup_ms": _pair_ms(iv.get("start") or {}),
            "dropoff_ms": _pair_ms(end_pair)}
    if r.get("hasPendingChangeRequest"):
        trip["pending_request"] = ("Guest has a pending trip change request — "
                                   "review it on the reservation page")
    return trip


def _pair_ms(pair):
    """epochMillis of an interval endpoint; falls back to parsing the local
    date/time (detail payloads carried epochMillis when probed 2026-08-07, but
    the fixture-era shape without it still occurs)."""
    if not pair:
        return None
    if pair.get("epochMillis"):
        return int(pair["epochMillis"])
    try:
        import datetime, time as _t
        dt = datetime.datetime.strptime(
            "%s %s" % (pair.get("localDate"), pair.get("localTime")), "%Y-%m-%d %H:%M")
        return int(_t.mktime(dt.timetuple()) * 1000)
    except (TypeError, ValueError):
        return None


def map_upcoming(feed):
    """upcoming-trips feed -> [{vehicle_id, reservation_id, start_ms, start, plate,
    end_ms, end_date, end_time, vehicle_name, in_progress}]. Rows without a
    vehicle or start are dropped (junk-safe). The feed emits one item per event
    type, so a trip can appear more than once — consumers dedupe by reservation_id."""
    out = []
    for it in (feed or {}).get("upcomingTripItems") or []:
        v = it.get("vehicle") or {}
        start = ((it.get("interval") or {}).get("start")) or {}
        ms = _pair_ms(start)
        if not v.get("id") or not ms:
            continue
        end = ((it.get("interval") or {}).get("end")) or {}
        out.append({"vehicle_id": v["id"],
                    "reservation_id": it.get("reservationId"),
                    "start_ms": ms,
                    "start": {"date": start.get("localDate", ""),
                              "time": _ampm(start.get("localTime"))},
                    # end in 24h local form for the night-return block (nightblock.py)
                    "end_ms": _pair_ms(end),
                    "end_date": end.get("localDate", ""),
                    "end_time": end.get("localTime", ""),
                    "vehicle_name": v.get("name") or "",
                    "in_progress": bool(it.get("inProgress")),
                    "plate": (v.get("registration") or {}).get("licensePlate") or ""})
    return out


def map_vehicles(feed):
    """upcoming-trips feed hostedAndCoHostedVehicles -> the whole co-hosted
    fleet as [{vehicle_id, name '2026 BMW 3 Series', url, plate}]."""
    out = []
    for v in (feed or {}).get("hostedAndCoHostedVehicles") or []:
        if not v.get("id"):
            continue
        name = _clean(" ".join(str(v.get(k) or "")
                               for k in ("year", "make", "model")))
        out.append({"vehicle_id": v["id"], "name": name,
                    "url": v.get("url") or "",
                    "plate": (v.get("registration") or {}).get("licensePlate") or ""})
    return out


def _extras(detail):
    """Booked extras from detail booking.extras[] as ['<label> ×<qty>', ...].
    (Shape probed live 2026-08-05: extraType.label + quantity.)"""
    out = []
    for e in ((detail or {}).get("booking") or {}).get("extras") or []:
        label = _clean(((e.get("extraType") or {}).get("label")) or "")
        if label:
            out.append("%s ×%d" % (label, int(e.get("quantity") or 1)))
    return out


def _place(detail):
    loc = (detail or {}).get("location") or {}
    code = _clean(loc.get("airportCode") or "")
    if code:
        # Airport deliveries carry only a city-level address; the airport
        # identity (code + name) is what the LAX-rules gate keys on.
        name = _clean(loc.get("airportName") or loc.get("name") or "")
        return _clean(", ".join(p for p in ("%s %s" % (code, name) if name else code,
                                            loc.get("address")) if p))
    return _clean(", ".join(p for p in (loc.get("address"), loc.get("city")) if p)) \
        or _clean(loc.get("name") or "")


def location_line(detail):
    place = _place(detail)
    return "📍 Trip pickup/drop-off location: %s" % place if place else ""
