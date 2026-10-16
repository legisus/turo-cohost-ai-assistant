"""Night-return calendar block (2026-10-15).

Operator ask: "check all new reservations and if a reservation ends after 7 pm,
set the car unavailable till 8 am next day — the car wash closes at 8 pm, so a
night return can't be washed before an early pickup."

The upcoming-trips feed gives every booked/in-progress trip with its end time;
agent/nightblock.py decides which trips need a block (end in [from, until) of the
night window), what the block's span is (trip end → next 8:00 AM), and which
existing blocks must go (trip cancelled or its end moved). The daemon applies
the plan through the fleet-calendar API (turo_chrome unavail_add/unavail_remove)
and tells the operator on Telegram. Turo's status endpoint lags behind an add,
so the driver adopts an identical existing block and confirms an add through
the unavailabilities list; a block that is really missing becomes an alert.
"""
import os, sys, time, datetime
from unittest import mock
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from agent import nightblock, turo_api
import turo_agent as ta
ta.NIGHT_BLOCK_SETTLE_SEC = 0        # no real pause in tests

CFG = {"from": "19:00", "until": "08:00"}


def _ms(date, hhmm):
    dt = datetime.datetime.strptime("%s %s" % (date, hhmm), "%Y-%m-%d %H:%M")
    return int(time.mktime(dt.timetuple()) * 1000)


def row(rid, vid, end_date, end_time, start_date="2026-10-10", start_time="10:00", name="Avery's Mazda", plate="7ABC123"):
    return {"vehicle_id": vid, "reservation_id": rid, "vehicle_name": name, "plate": plate,
            "start_ms": _ms(start_date, start_time), "start": {"date": start_date, "time": start_time},
            "end_ms": _ms(end_date, end_time), "end_date": end_date, "end_time": end_time}


# ---- qualifying + window --------------------------------------------------------

def test_night_return_window_edges():
    assert nightblock.night_return("19:00") is True        # at the threshold: no time to wash
    assert nightblock.night_return("23:30") is True
    assert nightblock.night_return("00:30") is True        # after midnight is still a night return
    assert nightblock.night_return("04:59") is True
    assert nightblock.night_return("05:00") is False       # Turo's 3 h gap already pushes pickup past 8 AM
    assert nightblock.night_return("07:00") is False
    assert nightblock.night_return("07:59") is False
    assert nightblock.night_return("08:00") is False
    assert nightblock.night_return("07:00", gap_hours=0) is True
    assert nightblock.night_return("06:30", gap_hours=1.5) is False
    assert nightblock.night_return("06:29", gap_hours=1.5) is True
    assert nightblock.night_return("18:30") is False
    assert nightblock.night_return("14:00") is False


def test_window_evening_return_blocks_until_next_morning():
    assert nightblock.window("2026-10-19", "23:30") == {
        "start_date": "2026-10-19", "start_time": "23:30", "end_date": "2026-10-20", "end_time": "08:00"}


def test_window_after_midnight_return_blocks_until_same_morning():
    assert nightblock.window("2026-10-20", "01:00") == {
        "start_date": "2026-10-20", "start_time": "01:00", "end_date": "2026-10-20", "end_time": "08:00"}


def test_window_daytime_return_is_none():
    assert nightblock.window("2026-10-19", "15:00") is None
    assert nightblock.window("2026-10-19", "07:00") is None     # 3 h gap covers it
    assert nightblock.window("2026-10-19", "07:00", gap_hours=0)["end_time"] == "08:00"


def test_plan_removes_block_when_gap_rule_makes_it_redundant():
    old = nightblock.window("2026-10-19", "07:00", gap_hours=0)
    blocks = {"1": {"vehicle_id": 11, "block_id": 55, "window": old}}
    up = [row("1", 11, "2026-10-19", "07:00")]
    acts = nightblock.plan(up, blocks, {}, _ms("2026-10-15", "12:00"))
    assert [a["op"] for a in acts] == ["remove"] and acts[0]["block_id"] == 55


def test_window_honours_config_thresholds():
    assert nightblock.window("2026-10-19", "19:00", start="19:30", until="09:00") is None
    assert nightblock.window("2026-10-19", "20:00", start="19:30", until="09:00")["end_time"] == "09:00"


# ---- plan -------------------------------------------------------------------------

def test_plan_adds_block_for_new_night_return():
    now = _ms("2026-10-15", "12:00")
    acts = nightblock.plan([row("1", 10, "2026-10-19", "22:30")], {}, CFG, now)
    assert [a["op"] for a in acts] == ["add"]
    assert acts[0]["res_id"] == "1" and acts[0]["vehicle_id"] == 10
    assert acts[0]["window"] == nightblock.window("2026-10-19", "22:30")


def test_plan_skips_daytime_returns_and_duplicate_feed_rows():
    now = _ms("2026-10-15", "12:00")
    rows = [row("1", 10, "2026-10-19", "22:30"), row("1", 10, "2026-10-19", "22:30"),   # feed lists a trip per item type
            row("2", 11, "2026-10-19", "14:00")]
    acts = nightblock.plan(rows, {}, CFG, now)
    assert len(acts) == 1 and acts[0]["res_id"] == "1"


def test_plan_is_idempotent_once_block_recorded():
    now = _ms("2026-10-15", "12:00")
    w = nightblock.window("2026-10-19", "22:30")
    blocks = {"1": {"vehicle_id": 10, "block_id": 555, "window": w}}
    assert nightblock.plan([row("1", 10, "2026-10-19", "22:30")], blocks, CFG, now) == []


def test_plan_replaces_block_when_trip_end_moves_later():
    now = _ms("2026-10-15", "12:00")
    old = nightblock.window("2026-10-19", "22:30")
    blocks = {"1": {"vehicle_id": 10, "block_id": 555, "window": old}}
    acts = nightblock.plan([row("1", 10, "2026-10-21", "21:00")], blocks, CFG, now)
    assert [a["op"] for a in acts] == ["remove", "add"]
    assert acts[0]["block_id"] == 555 and acts[1]["window"]["start_date"] == "2026-10-21"


def test_plan_removes_block_when_trip_end_moves_to_daytime():
    now = _ms("2026-10-15", "12:00")
    blocks = {"1": {"vehicle_id": 10, "block_id": 555, "window": nightblock.window("2026-10-19", "22:30")}}
    acts = nightblock.plan([row("1", 10, "2026-10-19", "15:00")], blocks, CFG, now)
    assert [a["op"] for a in acts] == ["remove"] and "daytime" in acts[0]["reason"]


def test_plan_removes_block_when_trip_vanishes_before_it_ends():
    now = _ms("2026-10-15", "12:00")
    blocks = {"1": {"vehicle_id": 10, "block_id": 555, "window": nightblock.window("2026-10-19", "22:30")}}
    acts = nightblock.plan([row("2", 11, "2026-10-19", "22:30")], blocks, CFG, now)
    assert [(a["op"], a["res_id"]) for a in acts] == [("add", "2"), ("remove", "1")]
    assert "cancel" in acts[1]["reason"]


def test_plan_forgets_served_block_after_trip_ended():
    now = _ms("2026-10-21", "12:00")
    blocks = {"1": {"vehicle_id": 10, "block_id": 555, "window": nightblock.window("2026-10-19", "22:30")}}
    acts = nightblock.plan([], blocks, CFG, now)
    assert [a["op"] for a in acts] == ["forget"]


def test_plan_does_not_add_for_trips_already_over():
    now = _ms("2026-10-20", "12:00")
    assert nightblock.plan([row("1", 10, "2026-10-19", "22:30")], {}, CFG, now) == []


def test_plan_retries_failed_add_only_after_a_day():
    now = _ms("2026-10-15", "12:00")
    w = nightblock.window("2026-10-19", "22:30")
    fresh = {"1": {"vehicle_id": 10, "block_id": None, "window": w, "failed_ts": now / 1000 - 3600}}
    assert nightblock.plan([row("1", 10, "2026-10-19", "22:30")], fresh, CFG, now) == []
    stale = {"1": {"vehicle_id": 10, "block_id": None, "window": w, "failed_ts": now / 1000 - 90000}}
    assert [a["op"] for a in nightblock.plan([row("1", 10, "2026-10-19", "22:30")], stale, CFG, now)] == ["add"]


# ---- status confirmation ----------------------------------------------------------

STATUS_OK = {"dailyData": [{"date": "2026-12-26", "unavailabilities": [
    {"end": {"terminal": True, "time": "23:00"}, "id": 50000001, "reservationStatus": "APPROVED",
     "start": {"terminal": False, "time": "00:00"}, "unavailabilityReason": "RESERVATION"},
    {"end": {"terminal": False, "time": "23:59"}, "id": 30000001, "reservationStatus": None,
     "start": {"terminal": True, "time": "23:00"}, "unavailabilityReason": "CUSTOM"}]},
    {"date": "2026-12-27", "unavailabilities": [
        {"end": {"terminal": True, "time": "08:00"}, "id": 30000001, "reservationStatus": None,
         "start": {"terminal": False, "time": "00:00"}, "unavailabilityReason": "CUSTOM"}]}],
    "updateType": "ADD", "vehicleId": 1000001, "vehicleStatus": "SUCCESS"}

STATUS_DROPPED = {"dailyData": [{"date": "2026-12-26", "unavailabilities": [
    {"end": {"terminal": True, "time": "23:00"}, "id": 50000001, "reservationStatus": "APPROVED",
     "start": {"terminal": False, "time": "00:00"}, "unavailabilityReason": "RESERVATION"}]}],
    "updateType": "ADD", "vehicleId": 1000001, "vehicleStatus": "SUCCESS"}


LISTING = {"unavailabilities": [
    {"id": 30000003, "notes": "", "start": {"localDate": "2026-12-20", "localTime": "19:00"},
     "end": {"localDate": "2026-12-21", "localTime": "08:00"}, "tripOverlapped": False, "vehicleId": 1000002},
    {"id": 30000004, "notes": "", "start": {"localDate": "2026-12-20", "localTime": "19:00"},
     "end": {"localDate": "2026-12-21", "localTime": "08:00"}, "tripOverlapped": False, "vehicleId": 1000002},
    {"id": 30000002, "notes": "bot probe", "start": {"localDate": "2026-12-20", "localTime": "20:00"},
     "end": {"localDate": "2026-12-20", "localTime": "21:00"}, "tripOverlapped": False, "vehicleId": 1000002}]}


def test_list_body_covers_both_days_of_the_window():
    assert nightblock.list_body(7, nightblock.window("2026-12-20", "19:00")) == {"vehicleId": 7, "dates": ["2026-12-20", "2026-12-21"]}
    assert nightblock.list_body(7, nightblock.window("2026-12-21", "01:00")) == {"vehicleId": 7, "dates": ["2026-12-21"]}


def test_find_blocks_matches_exact_span_only_oldest_first():
    assert nightblock.find_blocks(LISTING, nightblock.window("2026-12-20", "19:00")) == [30000003, 30000004]
    assert nightblock.find_blocks(LISTING, nightblock.window("2026-12-20", "20:00")) == []
    assert nightblock.find_blocks(None, nightblock.window("2026-12-20", "19:00")) == []


def test_sweep_adopting_an_existing_block_is_silent():
    tg, state = FakeTG(), {"threads": {}}
    p1, p2 = _patches()
    with p1, p2, mock.patch.object(ta.chrome, "upcoming", lambda: [row("1", 10, "2026-10-19", "22:30")]), \
         mock.patch.object(ta.chrome, "unavail_add", lambda vid, w, notes: {"block_id": 99, "adopted": True}):
        ta.night_block_sweep(tg, state, {"night_block": CFG}, now_ms=_ms("2026-10-15", "12:00"))
    assert state["night_blocks"]["1"]["block_id"] == 99 and tg.notes == []


def test_confirm_block_finds_custom_entry_by_start():
    assert nightblock.confirm_block(STATUS_OK, "2026-12-26", "23:00") == 30000001


def test_confirm_block_none_when_turo_dropped_it():
    assert nightblock.confirm_block(STATUS_DROPPED, "2026-12-26", "23:00") is None
    assert nightblock.confirm_block(None, "2026-12-26", "23:00") is None


# ---- feed mapping ------------------------------------------------------------------

FEED = {"upcomingTripItems": [
    {"reservationId": 50000001, "upcomingTripFeedItemType": "CO_HOST_TRIP_START", "inProgress": False,
     "timeZone": "America/Los_Angeles",
     "interval": {"end": {"epochMillis": 1798354800000, "localDate": "2026-12-26", "localTime": "23:00"},
                  "start": {"epochMillis": 1795197600000, "localDate": "2026-11-20", "localTime": "10:00"}},
     "vehicle": {"id": 1000001, "name": "Avery's Volkswagen", "registration": {"licensePlate": "8XYZ987"}}}]}


def test_map_upcoming_carries_end_and_vehicle_name():
    rows = turo_api.map_upcoming(FEED)
    assert len(rows) == 1
    r = rows[0]
    assert r["vehicle_id"] == 1000001 and r["reservation_id"] == 50000001
    assert r["end_ms"] == 1798354800000 and r["end_date"] == "2026-12-26" and r["end_time"] == "23:00"
    assert r["vehicle_name"] == "Avery's Volkswagen" and r["plate"] == "8XYZ987"
    assert r["start"] == {"date": "2026-11-20", "time": "10:00 AM"}     # unchanged for extension.py


def test_add_body_and_remove_body_match_the_probed_api():
    w = {"start_date": "2026-12-26", "start_time": "23:00", "end_date": "2026-12-27", "end_time": "08:00"}
    assert nightblock.add_body(1000001, w, "wash") == {
        "type": "TIMESPAN_DISCRETE", "startTime": "23:00", "endTime": "08:00", "notes": "wash",
        "timespanDiscreteVehicleDates": {"startDate": "2026-12-26", "endDate": "2026-12-27",
                                         "vehicleIds": [1000001]}}
    assert nightblock.remove_body(30000001) == {
        "type": "DISTINCT", "distinctUnavailability": {"unavailabilityId": 30000001},
        "repeatType": "INDIVIDUAL"}


# ---- daemon sweep -------------------------------------------------------------------

class FakeTG:
    def __init__(self): self.notes = []
    def send(self, t): self.notes.append(t)


def _patches():
    return (mock.patch.object(ta, "log", lambda m: None),
            mock.patch.object(ta.store, "save_state", lambda p, s: None))


def test_sweep_adds_block_records_it_and_tells_operator():
    tg, state = FakeTG(), {"threads": {}}
    calls = []
    def add(vid, w, notes):
        calls.append(("add", vid, w)); return {"block_id": 777, "status": {"vehicleStatus": "SUCCESS"}}
    p1, p2 = _patches()
    with p1, p2, mock.patch.object(ta.chrome, "upcoming", lambda: [row("1", 10, "2026-10-19", "22:30")]), \
         mock.patch.object(ta.chrome, "unavail_add", add), \
         mock.patch.object(ta.chrome, "unavail_remove", lambda *a: (_ for _ in ()).throw(AssertionError("no remove"))):
        ta.night_block_sweep(tg, state, {"night_block": CFG}, now_ms=_ms("2026-10-15", "12:00"))
    assert calls == [("add", 10, nightblock.window("2026-10-19", "22:30"))]
    nb = state["night_blocks"]["1"]
    assert nb["block_id"] == 777 and nb["vehicle_id"] == 10 and nb["window"]["end_date"] == "2026-10-20"
    assert len(tg.notes) == 1 and "🌙" in tg.notes[0] and "Avery's Mazda" in tg.notes[0] \
        and "10:30 PM" in tg.notes[0] and "8:00 AM" in tg.notes[0]


def test_sweep_alerts_when_turo_drops_the_block_and_does_not_retry_at_once():
    tg, state = FakeTG(), {"threads": {}}
    calls = []
    def add(vid, w, notes):
        calls.append(vid); return {"block_id": None, "status": {"vehicleStatus": "SUCCESS"}}
    p1, p2 = _patches()
    rows = [row("1", 10, "2026-10-19", "22:30")]
    with p1, p2, mock.patch.object(ta.chrome, "upcoming", lambda: rows), \
         mock.patch.object(ta.chrome, "unavail_add", add):
        ta.night_block_sweep(tg, state, {"night_block": CFG}, now_ms=_ms("2026-10-15", "12:00"))
        ta.night_block_sweep(tg, state, {"night_block": CFG}, now_ms=_ms("2026-10-15", "12:15"))
    assert calls == [10]
    assert state["night_blocks"]["1"]["block_id"] is None and state["night_blocks"]["1"]["failed_ts"]
    assert len(tg.notes) == 1 and "⚠️" in tg.notes[0] and "another trip" in tg.notes[0]


def test_sweep_removes_block_of_cancelled_trip():
    tg, state = FakeTG(), {"threads": {}, "night_blocks": {
        "1": {"vehicle_id": 10, "block_id": 555, "window": nightblock.window("2026-10-19", "22:30"),
              "vehicle_name": "Avery's Mazda", "plate": "7ABC123"}}}
    removed = []
    p1, p2 = _patches()
    with p1, p2, mock.patch.object(ta.chrome, "upcoming", lambda: [row("2", 11, "2026-10-19", "14:00")]), \
         mock.patch.object(ta.chrome, "unavail_remove", lambda vid, bid: removed.append((vid, bid)) or {"ok": True}):
        ta.night_block_sweep(tg, state, {"night_block": CFG}, now_ms=_ms("2026-10-15", "12:00"))
    assert removed == [(10, 555)]
    assert "1" not in state["night_blocks"]
    assert len(tg.notes) == 1 and "removed" in tg.notes[0] and "cancel" in tg.notes[0]


def test_sweep_does_nothing_on_empty_feed():
    """An empty feed means the read failed — it must never look like every trip was cancelled."""
    tg, state = FakeTG(), {"threads": {}, "night_blocks": {
        "1": {"vehicle_id": 10, "block_id": 555, "window": nightblock.window("2026-10-19", "22:30")}}}
    p1, p2 = _patches()
    with p1, p2, mock.patch.object(ta.chrome, "upcoming", lambda: []), \
         mock.patch.object(ta.chrome, "unavail_remove", lambda *a: (_ for _ in ()).throw(AssertionError("no remove"))):
        ta.night_block_sweep(tg, state, {"night_block": CFG}, now_ms=_ms("2026-10-15", "12:00"))
    assert state["night_blocks"]["1"]["block_id"] == 555 and tg.notes == []


def test_sweep_disabled_by_config():
    tg, state = FakeTG(), {"threads": {}}
    p1, p2 = _patches()
    with p1, p2, mock.patch.object(ta.chrome, "upcoming", lambda: (_ for _ in ()).throw(AssertionError("no read"))):
        ta.night_block_sweep(tg, state, {"night_block": {"enabled": False}}, now_ms=_ms("2026-10-15", "12:00"))
    assert tg.notes == []


def test_night_block_command_lists_held_blocks():
    tg, state = FakeTG(), {"threads": {}, "night_blocks": {
        "1": {"vehicle_id": 10, "block_id": 555, "window": nightblock.window("2026-10-19", "22:30"),
              "vehicle_name": "Avery's Mazda", "plate": "7ABC123"}}}
    with mock.patch.object(ta.store, "load_config", lambda p: {"night_block": CFG}), \
         mock.patch.object(ta, "night_block_sweep", lambda *a, **k: {"add": 0, "remove": 0, "failed": 0}), \
         mock.patch.object(ta, "log", lambda m: None):
        ta.handle_command(tg, state, "night_block")
    assert any("Avery's Mazda" in n and "10/19" in n for n in tg.notes)


def test_sweep_pauses_after_a_remove_before_the_next_add():
    old = nightblock.window("2026-10-19", "22:30")
    tg = FakeTG()
    state = {"threads": {}, "night_blocks": {"1": {"vehicle_id": 10, "block_id": 55, "window": old, "plate": "7ABC123"}}}
    slept = []
    p1, p2 = _patches()
    with p1, p2, mock.patch.object(ta.chrome, "upcoming", lambda: [row("1", 10, "2026-10-19", "23:00")]), \
         mock.patch.object(ta.chrome, "unavail_remove", lambda vid, bid: {"ok": True}), \
         mock.patch.object(ta.chrome, "unavail_add", lambda vid, w, notes: {"block_id": 56}), \
         mock.patch.object(ta.time, "sleep", lambda s: slept.append(s)), \
         mock.patch.object(ta, "NIGHT_BLOCK_SETTLE_SEC", 8):
        ta.night_block_sweep(tg, state, {"night_block": CFG}, now_ms=_ms("2026-10-15", "12:00"))
    assert slept == [8] and state["night_blocks"]["1"]["block_id"] == 56
