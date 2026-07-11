# Contributing

Improvements are welcome — this tool runs against real guests' messages, so
the bar is: **every change is tested, and no change may weaken a safety
guard.**

## Ground rules

1. **Read `CLAUDE.md` first.** It lists the hard invariants (never Selenium
   against Turo, nothing auto-sent to guests, compose-pointer text routing,
   wrong-thread send guards). PRs that violate them will be declined.
2. **Bug fixes start with a failing test** that reproduces the bug, then the
   fix, then the passing suite. Look at `tests/test_routing.py` for the style —
   each regression test says what broke and why.
3. **No personal data in commits.** Never commit `config.json`, `rules/`,
   `vehicles.json`, `state.json`, logs, or Chrome profiles; scrub real guest
   names, addresses, phone numbers, and license plates from test data, code
   comments, and issue reports. Use obviously fictional stand-ins.
4. Keep the runtime **stdlib-only** (the daemon deliberately has zero runtime
   dependencies; `pytest` is the only dev dependency).
5. Match the existing code style: small pure functions separated from
   subprocess/AppleScript calls so they're testable, and comments that explain
   *why* (especially anything guarding against a Turo UI quirk — those
   comments encode hard-won bugs).

## Workflow

```bash
# fork on GitHub, then:
git clone git@github.com:<you>/turo-cohost-assistant.git
cd turo-cohost-assistant
python3 -m venv .venv && .venv/bin/pip install pytest

git checkout -b fix/describe-the-thing
# ... failing test → fix → green suite ...
.venv/bin/python -m pytest tests/ -q

git commit    # small, focused commits; message says WHY
git push -u origin fix/describe-the-thing
# open a Pull Request against main
```

In the PR description, include:

- What breaks / what improves, and how you verified it against a real inbox
  (redact everything guest-identifying)
- Test output (`pytest -q` tail is enough)
- For anything touching send paths or message classification: which of the
  CLAUDE.md invariants you checked and how

## Contributing with Claude Code

Claude Code makes good PRs here because `CLAUDE.md` teaches it the invariants:
open the repo, describe the bug or feature, and ask it to follow the
failing-test-first convention. Review its diff yourself before pushing — you
are the author of what you submit.

## Turo UI breakage reports

Turo's frontend changes without notice. If the bot goes blind or misparses,
open an issue titled "Turo UI change: <what broke>" with the redacted DOM
snippet or preview text — selectors live in `scripts/turo_chrome.py` and
parsing in `scripts/agent/meta.py`.
