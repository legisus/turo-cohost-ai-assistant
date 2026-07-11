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
