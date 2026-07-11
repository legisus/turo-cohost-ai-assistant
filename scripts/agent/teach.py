"""🎓 Teach: turn an operator lesson into a persistent rule for future drafts.

The distilled rule is appended to `rules/07-learned.md`, which draft._load_rules()
picks up automatically (it globs rules/*.md) — no other wiring needed. The
operator's original words are always preserved so a bad distillation can be
corrected by hand. Pure prompt/parse/persist functions are separated from the
subprocess call, same pattern as draft.py.
"""
import os, re, subprocess, time

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "rules")
LEARNED_FILE = "07-learned.md"
_FILE_HEADER = ("# Learned rules — taught by the operator via 🎓 Teach\n\n"
                "<!-- Appended automatically by the agent. Edit or delete freely;\n"
                "     every draft is grounded in this file like any other rules file. -->\n")


def build_distill_prompt(lesson, thread_text, header=""):
    return (
        "You maintain the reply rules for a Turo co-host bot. The operator just "
        "taught a lesson while reviewing a guest conversation. Distill it into ONE "
        "short, generalized, reusable rule for SIMILAR FUTURE situations.\n"
        "- Generalize: describe the situation pattern, never this specific guest "
        "(no names, dates, or trip numbers).\n"
        "- Keep the operator's intent exactly — do not soften, extend, or invent.\n"
        "- 1-3 plain-text lines, imperative voice (e.g. 'When a guest asks X, do Y.').\n\n"
        "Card: %s\n\nGuest conversation (context only):\n%s\n\n"
        "OPERATOR'S LESSON:\n%s\n\n"
        "Output ONLY the rule, wrapped EXACTLY between <RULE> and </RULE>."
        % (header or "n/a", (thread_text or "n/a").strip()[:3000], lesson.strip())
    )


def extract_rule(out):
    m = re.search(r"<RULE>(.*?)</RULE>", out or "", re.S)
    rule = m.group(1).strip() if m else (out or "").strip()
    return re.split(r"</?RULE>", rule)[0].strip()


def distill(lesson, thread_text, header=""):
    p = subprocess.run(["claude", "--model", "claude-sonnet-5", "-p",
                        build_distill_prompt(lesson, thread_text, header)],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError("claude distill failed: " + p.stderr.strip()[:200])
    rule = extract_rule(p.stdout)
    if not rule:
        raise RuntimeError("distill returned an empty rule")
    return rule


def save_lesson(rule, lesson, header=""):
    """Append the rule (rule == lesson when distillation failed → saved verbatim,
    no duplicate sub-note). Returns the exact block written, for the confirmation."""
    path = os.path.join(RULES_DIR, LEARNED_FILE)
    block = "\n## %s — %s\n- %s\n" % (time.strftime("%Y-%m-%d"),
                                      header or "general", rule.strip())
    if lesson.strip() != rule.strip():
        block += "  - (operator's words: \"%s\")\n" % lesson.strip().replace('"', "'")
    fresh = not os.path.exists(path)
    with open(path, "a") as f:
        if fresh:
            f.write(_FILE_HEADER)
        f.write(block)
    return block
