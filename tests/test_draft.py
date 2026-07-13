import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from agent import draft


def test_prompt_includes_location_gating():
    p = draft.build_prompt("📍 Trip pickup/drop-off location: 500 Main St, Springfield\nStephen: where do I park?")
    assert "LOCATION GATING" in p
    # the gate ties location-specific instructions to a matching trip location
    assert "ONLY when that location line matches" in p
    assert "do NOT give location-specific pickup instructions" in p


def test_prompt_carries_the_location_line_and_thread():
    thread = "📍 Trip pickup/drop-off location: 500 Main Street, Springfield\nStephen: hi"
    p = draft.build_prompt(thread, guest="Stephen", host="Jane")
    assert "500 Main Street" in p
    assert "Stephen" in p


def test_lax_rule_is_gated_in_rules_file():
    import os, pytest
    if not os.path.exists(os.path.join(draft.RULES_DIR, "04-lax-airport-rules.md")):
        pytest.skip("operator-specific rules file not present")
    rules = draft._load_rules()
    assert "APPLIES ONLY TO LAX TRIPS" in rules
    assert "05-home-parking.md" in rules  # points non-LAX trips to home parking


def test_prompt_names_all_host_accounts():
    # Claude arbitrates unmarked messages; it must know EVERY host account name
    # (Viktor P was missing -> his scheduled messages were answered as guest).
    from agent import persona
    p = draft.build_prompt("? : hello")
    for name in persona.TEAM_NAMES:
        assert name in p, name


def test_facts_line_formats_trip_and_pending_request():
    line = draft.facts_line({
        "tripType": "Booked trip",
        "pickup": {"date": "Sat, Jul 12", "time": "4:00 PM"},
        "dropoff": {"date": "Tue, Jul 15", "time": "4:00 PM"},
        "status": "Trip starts in 2 hours",
        "pending_request": "Dana wants to add a child seat; Approve by Jul 14"})
    assert line.startswith("📋 Trip facts: Booked trip")
    assert "Sat, Jul 12 4:00 PM → Tue, Jul 15 4:00 PM" in line
    assert "⚠️ pending guest request: Dana wants to add a child seat" in line


def test_facts_line_empty_for_missing_trip():
    assert draft.facts_line({}) == ""
    assert draft.facts_line(None) == ""


def test_facts_line_without_request_has_no_warning():
    line = draft.facts_line({"tripType": "Booked trip", "pending_request": ""})
    assert line == "📋 Trip facts: Booked trip"


def test_prompt_grounds_in_trip_facts_and_never_repeats():
    p = draft.build_prompt("📋 Trip facts: Booked trip\nDana: can I add a child seat?")
    assert "TRIP FACTS GROUNDING" in p
    assert "submit it in the Turo app" in p
    assert "NEVER REPEAT" in p
    assert "it was sent above" in p


def test_prompt_skip_policy_is_strict_with_key_moments():
    p = draft.build_prompt("Dana: the car is great, thanks!")
    assert "disturbs the guest" in p          # do not reply just to be polite
    assert "EXCEPTIONS" in p
    assert "returned" in p and "damage" in p  # key moments still get a brief reply
