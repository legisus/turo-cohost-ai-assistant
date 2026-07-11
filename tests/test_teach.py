"""🎓 Teach: operator lessons become persistent rules that ground future drafts.
Spec: docs/superpowers/specs/2026-07-10-teach-button-design.md
"""
import os, sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from agent import teach, telegram, detect
import turo_agent as ta


# --- distill prompt / rule extraction ----------------------------------------

def test_distill_prompt_contains_lesson_and_conversation():
    p = teach.build_distill_prompt("never promise a refund", "Guest: refund?", "🚗 hdr")
    assert "never promise a refund" in p
    assert "Guest: refund?" in p
    assert "<RULE>" in p  # output contract


def test_extract_rule_from_markers():
    assert teach.extract_rule("blah\n<RULE>Do X when Y.</RULE>\nblah") == "Do X when Y."


def test_extract_rule_without_markers_falls_back_to_text():
    assert teach.extract_rule("Do X when Y.") == "Do X when Y."


# --- persistence ---------------------------------------------------------------

def test_save_lesson_creates_and_appends(tmp_path):
    with mock.patch.object(teach, "RULES_DIR", str(tmp_path)):
        teach.save_lesson("Rule one.", "my words one", "🚗 hdrA")
        teach.save_lesson("Rule two.", "Rule two.", "🚗 hdrB")  # verbatim (distill failed)
        text = (tmp_path / "07-learned.md").read_text()
    assert "Rule one." in text and "Rule two." in text
    assert "my words one" in text          # original words preserved
    assert "hdrA" in text and "hdrB" in text
    assert text.count("Rule two.") == 1    # verbatim saves aren't duplicated as a sub-note


def test_saved_rules_reach_the_draft_prompt(tmp_path):
    from agent import draft
    with mock.patch.object(teach, "RULES_DIR", str(tmp_path)), \
         mock.patch.object(draft, "RULES_DIR", str(tmp_path)):
        teach.save_lesson("Always mention the toll pass.", "words", "hdr")
        p = draft.build_prompt("? : hello")
    assert "Always mention the toll pass." in p


# --- card button / routing / supersede guard ----------------------------------

def test_card_has_teach_button():
    rows = telegram.card_rows("42")
    flat = [b["callback_data"] for row in rows for b in row]
    assert "teach:42" in flat


def test_teach_stage_routes_typed_text():
    state = {"threads": {"T": {"pending": {"stage": "await_approval"}}}}
    ta.begin_compose(state, "T", "await_teach")
    assert ta.route_text(state) == ("T", "await_teach")


def test_new_guest_message_does_not_clobber_mid_teach():
    listing = [{"id": "T", "text": "new message"}]
    state = {"threads": {"T": {"last_seen": "old", "last_sent": "",
                               "pending": {"stage": "await_teach"}}}}
    assert detect.candidates(listing, state) == []


# --- do_teach orchestration ------------------------------------------------------

def _teach_state():
    return {"threads": {"T": {"last_seen": "", "last_sent": "",
                              "pending": {"stage": "await_teach", "draft": "d",
                                          "header": "🚗 hdr", "host": "Jane",
                                          "guest": "Sam"}}}}


def test_do_teach_saves_then_redrafts():
    tg = mock.Mock(); state = _teach_state()
    with mock.patch.object(ta.chrome, "read_thread", return_value="convo"), \
         mock.patch.object(ta.teach, "distill", return_value="The rule.") as dis, \
         mock.patch.object(ta.teach, "save_lesson", return_value="- The rule.") as save, \
         mock.patch.object(ta, "regenerate") as regen:
        ta.do_teach(tg, state, "T", "always do X")
    dis.assert_called_once()
    save.assert_called_once_with("The rule.", "always do X", "🚗 hdr")
    regen.assert_called_once_with(tg, state, "T", "always do X")


def test_do_teach_distill_failure_saves_verbatim():
    tg = mock.Mock(); state = _teach_state()
    with mock.patch.object(ta.chrome, "read_thread", return_value="convo"), \
         mock.patch.object(ta.teach, "distill", side_effect=RuntimeError("api down")), \
         mock.patch.object(ta.teach, "save_lesson", return_value="- verbatim") as save, \
         mock.patch.object(ta, "regenerate"):
        ta.do_teach(tg, state, "T", "always do X")
    save.assert_called_once_with("always do X", "always do X", "🚗 hdr")


def test_do_teach_empty_text_reprompts_and_keeps_stage():
    tg = mock.Mock(); state = _teach_state()
    with mock.patch.object(ta, "regenerate") as regen:
        ta.do_teach(tg, state, "T", "   ")
    regen.assert_not_called()
    assert ta.route_text(state) == ("T", "await_teach")
