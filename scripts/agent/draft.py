"""Draft a reply with `claude -p`, grounded in the project's reply rules/docs.

Rules live INSIDE the project (`rules/*.md`), not in ~/Documents — the latter is
TCC-protected and unreadable by the unattended daemon under launchd.
"""
import glob, os, re, subprocess

from agent import persona

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "rules")


def _load_rules():
    parts = []
    for p in sorted(glob.glob(os.path.join(RULES_DIR, "*.md"))):
        with open(p) as f:
            parts.append(f.read())
    return "\n\n".join(parts)


# Location-specific instructions (LAX airport handoff vs home-base parking) must be
# chosen by the trip's REAL pickup/drop-off location, which turo_chrome prepends to
# the thread as "📍 Trip pickup/drop-off location: <address>". Sending LAX/Budget
# Parking steps to a non-LAX trip is a real failure we guard against here.
_LOCATION_RULE = (
    "- LOCATION GATING (critical): the conversation begins with the trip's real "
    "pickup/drop-off location ('📍 Trip pickup/drop-off location: ...'). Rules and "
    "templates that are gated to a specific place (an airport lot, a shuttle flow, a "
    "particular street) may be used ONLY when that location line matches the place "
    "they are gated to; for any other location use the rules for THAT location and "
    "never mix in another site's instructions. If the location line is missing, do "
    "NOT give location-specific pickup instructions (airport/shuttle especially).\n"
)


_FACTS_RULE = (
    "- TRIP FACTS GROUNDING: if the conversation begins with '📋 Trip facts: ...', "
    "treat that line as ground truth for the reservation (trip state, pickup/drop-off "
    "window, pending guest requests). If it shows a pending guest request, confirm the "
    "request is possible and that we're approving it in the app. If the guest asks for "
    "a change or extra (dates, child seat, etc.) and NO pending request is shown, tell "
    "them to submit it in the Turo app so we can approve it. Never invent dates, "
    "extras, or approval status that the facts line doesn't show.\n"
    "- NEVER REPEAT: do not restate information a host message earlier in this "
    "conversation already gave (instructions, addresses, codes, times). If the guest "
    "re-asks, briefly note it was sent above and give only the direct answer.\n"
)


def facts_line(trip):
    """One-line 📋 summary of reservation facts for the drafting prompt; '' if none.
    Prepended to the thread text like the 📍 location line (see turo_agent)."""
    if not trip:
        return ""
    bits = []
    if trip.get("tripType"):
        bits.append(trip["tripType"])
    pu, do = trip.get("pickup") or {}, trip.get("dropoff") or {}
    if pu.get("date"):
        bits.append("%s %s → %s %s" % (pu.get("date", ""), pu.get("time", ""),
                                       do.get("date", ""), do.get("time", "")))
    if trip.get("status"):
        bits.append(trip["status"])
    if trip.get("pending_request"):
        bits.append("⚠️ pending guest request: " + trip["pending_request"])
    return ("📋 Trip facts: " + " · ".join(bits)) if bits else ""


def build_prompt(thread_text, guidance="", guest="", host=""):
    """Assemble the claude prompt (separated from the subprocess call so it's testable)."""
    rules = _load_rules()
    who = ""
    if host or guest:
        bits = []
        if host:
            bits.append("This thread is for a %s vehicle — apply any %s-specific rules."
                        % (host, host))
        if guest:
            bits.append("The guest is %s." % guest)
        bits.append("We are the HOST; our messages sign '- %s' and address the guest "
                    "by first name; the guest's messages ask questions or make requests."
                    % persona.SIGNATURE)
        who = "\n" + " ".join(bits) + "\n"
    steer = ""
    if guidance.strip():
        steer = (
            "\n\nHOST GUIDANCE for THIS reply — weave it in naturally and produce a "
            "polished message; do NOT send the guidance verbatim:\n  " + guidance.strip() + "\n")
    sig = persona.SIGNATURE
    team = ", ".join("'%s'" % n for n in persona.TEAM_NAMES)
    return (
        "You are drafting a Turo host reply. Follow these rules EXACTLY:\n"
        "- Sign every reply '- " + sig + "'. Use 'we'/'our vehicle' (co-host, not owner).\n"
        "- Plain text only (no markdown). Keep it warm, concise, specific.\n"
        "- Never promise availability or a specific pickup time; for those, say we'll "
        "check and point them to the app/Turo support.\n"
        + _LOCATION_RULE + _FACTS_RULE + "\n"
        "REFERENCE (rules, vehicles, templates):\n" + rules + who + "\n\n"
        "CONVERSATION below (most recent message last). Each line is prefixed with the "
        "sender (the guest's name, a host-team name — " + team + " — or '?' when "
        "unknown); '[PHOTO ATTACHED]' marks an image the sender sent.\n\n"
        + thread_text + steer + "\n\n"
        "STEP 1 — Look at ONLY the single most recent message. Output EXACTLY "
        "<REPLY>SKIP</REPLY> and nothing else if EITHER: (a) WE the host team wrote it — "
        "any message from " + team + ", INCLUDING Turo's "
        "automated/scheduled host messages (check-in/check-out instructions, reminders); "
        "a host message addresses the guest by name, gives info/instructions/timing, or "
        "is signed '- " + sig + "'; OR (b) the guest's message raises no question, request, or "
        "problem — small talk, pleasantries, acknowledgments ('sounds good', 'ok', "
        "'thanks', 'great', 'perfect', 'see you', 'will do', an emoji), or a mid-trip "
        "status update that needs nothing from us. Do NOT reply just to be polite; an "
        "unnecessary message disturbs the guest. EXCEPTIONS that DO deserve a brief "
        "reply: the guest reports the car returned or checkout complete (thank them, "
        "confirm anything pending), or reports damage or an incident (acknowledge, say "
        "we'll follow up). "
        "STEP 2 — Only if the most recent message is from the guest AND genuinely needs a "
        "response (a question, request, problem, or one of the EXCEPTIONS above), "
        "output ONLY the message to send, wrapped EXACTLY between <REPLY> and </REPLY>, "
        "nothing else. Example: <REPLY>Hi Sam, ...\n- " + sig + "</REPLY>"
    )


def draft_reply(thread_text, guidance="", guest="", host="", allow_skip=True):
    prompt = build_prompt(thread_text, guidance=guidance, guest=guest, host=host)
    p = subprocess.run(["claude", "--model", "claude-sonnet-5", "-p", prompt], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError("claude draft failed: " + p.stderr.strip())
    out = p.stdout.strip()
    # Extract only the marked reply; strips any reasoning/preamble the model adds.
    m = re.search(r"<REPLY>(.*?)</REPLY>", out, re.S)
    reply = m.group(1).strip() if m else out
    # Defensive: if a stray marker remains (no closing tag), cut at it.
    reply = re.split(r"</?REPLY>", reply)[0].strip()
    return reply
