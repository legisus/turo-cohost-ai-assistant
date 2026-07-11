# CLAUDE.md — Turo Co-Host Assistant

Unattended Turo co-host daemon: reads the inbox via the user's real logged-in
Chrome (AppleScript + JS), drafts replies with `claude -p`, and asks the
operator to approve every send over a Telegram bot. See README.md for setup.

## Hard invariants — never regress these

- **NEVER use Selenium or headless browsing against Turo** — Cloudflare blocks
  it on sight. Only the AppleScript `execute javascript` path into the user's
  real Chrome works.
- **Nothing is sent to a guest without an explicit operator tap.** Do not add
  auto-send paths.
- **Navigate tabs via JS (`location.href`), never AppleScript `set URL`** — the
  latter steals window focus from the user. `_focus_tab` must not `activate`.
- **Before set/send, the driver navigates to the target thread AND verifies
  `location.href` contains the thread id** — this is the wrong-customer guard.
- **Typed-text routing uses the compose pointer** (`state["compose"]`, set by
  `begin_compose` on an Edit/Regen/Teach tap). Never route the operator's text
  by scanning threads in dict order — that once sent a hint verbatim to the
  wrong guest. New await stages must go through `begin_compose`/`route_text`
  and be added to `_COMPOSING` in BOTH `turo_agent.py` and `agent/detect.py`.
- A backgrounded Chrome without the anti-throttle flags silently drops
  keystrokes and renders stale content — reads/sends are only trusted with the
  flags + the dedicated window (`scripts/launch_agent_chrome.sh`).

## Architecture

```
scripts/turo_agent.py      daemon: poll loop, Telegram events, approval flow
scripts/turo_chrome.py     Chrome driver (AppleScript+JS): list/read/set/send
scripts/agent/
  detect.py    which threads need a draft (pure, tested)
  meta.py      preview parsing, sender classification (KNOWN_HOSTS), headers
  draft.py     claude -p drafting, grounded in rules/*.md   (<REPLY> markers)
  teach.py     🎓 lessons → distilled rules in rules/07-learned.md (<RULE>)
  chat.py      operator free-chat + photo analysis
  persona.py   operator identity from config.json (signature, host_names)
  telegram.py  minimal Bot API client (stdlib only)
  store.py     config/state JSON persistence
rules/         PRIVATE operational rules — injected into every draft
rules-examples/  sanitized templates for new installs
```

State machine per thread: `pending.stage` ∈ `await_approval` → (`await_edit` |
`await_regen` | `await_teach`) → resolved. Stages in `_COMPOSING` block
re-carding and receive the operator's next text via the compose pointer.

## Working on this repo

- Tests: `.venv/bin/python -m pytest tests/ -q` — keep them green; bug fixes
  start with a failing test that reproduces the bug.
- All `claude -p` calls pin `--model claude-sonnet-5`; keep model choice in one
  place per call site.
- Message classification is evidence-based: outbound geometry → (Host)/(Guest)
  tag → signature → avatar vs. roster. When unsure return "unknown" and let the
  drafting prompt SKIP — never infer "host" from the absence of a tag (that
  drops real guest messages).
- Restart after code changes: `launchctl kickstart -k gui/$(id -u)/com.turo.cohost`
  (modules are loaded in memory). Logs: `tail -f logs/agent.log`.
- The daemon and any ad-hoc script share ONE Chrome — stop the daemon
  (`launchctl bootout gui/$(id -u)/com.turo.cohost`) before driving threads
  manually, restart with `launchctl bootstrap gui/$(id -u)
  ~/Library/LaunchAgents/com.turo.cohost.plist`.

## Privacy

`config.json`, `state.json`, `logs/`, `chrome-profile/`, and `rules/` contain
secrets and guest PII. They are gitignored: never commit, print, or paste their
contents into issues/PRs. When adding a host account, update config.json
`host_names` AND `rules/02-hosts-and-vehicles.md`.
