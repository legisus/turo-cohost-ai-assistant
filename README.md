# Turo Co-Host Assistant

An unattended daemon that watches your Turo inbox 24/7 through your **real,
logged-in Chrome**, drafts a reply to every new guest message with Claude, and
asks you to **Approve / Edit / Regenerate / Skip / 🎓 Teach** over a private
Telegram bot. **Nothing is ever sent to a guest without your explicit tap.**

```
Turo inbox ──(AppleScript+JS reads real Chrome)──▶ daemon ──▶ Claude drafts reply
     ▲                                                              │
     └────────── send after your ✅ Approve ◀── Telegram card ◀─────┘
```

Why drive a real browser? Turo sits behind Cloudflare, which blocks
Selenium/headless automation on sight. Reading and writing through the Chrome
you actually use — via AppleScript's `execute javascript` — looks like you,
because it is you.

## Features

- **Approval cards in Telegram** — guest message + proposed reply + buttons.
- **🎓 Teach** — explain once how to handle a situation; the lesson is distilled
  into a permanent rule (`rules/07-learned.md`) that grounds every future draft.
- **Regenerate with a hint** ("say we'll check tomorrow"), **Edit** (your exact
  text), **Skip**.
- **Free-text chat** with the assistant about pending guests, plus photo
  analysis (send it a screenshot).
- **Host-team aware** — never replies to your own or your owners' messages,
  including Turo's scheduled/automatic host messages.
- **Optional remote lock/unlock** for supported vehicles (NissanConnect/BMW
  orchestrators included; needs separate per-vehicle setup).
- Safety guards: wrong-thread send guard, read-back before send, post-send
  verification, self-healing Chrome relaunch, "blind" alerts when the inbox is
  unreadable.

## Hardware / software requirements

| Requirement | Why |
|---|---|
| A Mac that stays on, awake, and **unlocked** | launchd daemon + AppleScript into Chrome; a locked screen suspends the tab (the bot alerts you when blind). The daemon runs `caffeinate` itself. Any Apple-silicon or Intel Mac works — this runs comfortably on a base MacBook Air. |
| Google Chrome, logged into your Turo account | The bot drives a dedicated Chrome window with anti-throttle flags so it keeps rendering in the background while you use the machine. |
| Python 3.11+ (`brew install python`) | Daemon runtime (stdlib only — no packages beyond pytest for tests). |
| [Claude Code CLI](https://claude.com/claude-code) installed and authenticated | Drafting, chat, photo analysis, and Teach distillation all shell out to `claude -p`. A Claude subscription is your only per-message cost. |
| A Telegram account + bot token from [@BotFather](https://t.me/BotFather) | Your private approval channel. |

## Setup

> **Prefer a guided install?** Open the repo in
> [Claude Code](https://claude.com/claude-code) and ask it to set the assistant
> up for you — see [docs-public/RUNNING-WITH-CLAUDE-CODE.md](docs-public/RUNNING-WITH-CLAUDE-CODE.md).

```bash
git clone https://github.com/legisus/turo-cohost-ai-assistant.git
cd turo-cohost-ai-assistant

# 1. Configure
cp config.example.json config.json     # fill in: bot token, chat id, signature, host_names
cp rules-examples/*.md rules/          # fill in your voice, hosts, vehicles, locations
$EDITOR vehicles.json                  # optional: plate lookup for card headers

# 2. Telegram: message your new bot once, then get your chat id:
#    curl https://api.telegram.org/bot<TOKEN>/getUpdates   → result[0].message.chat.id

# 3. Chrome: launch the dedicated inbox window (re-run after any reboot/Chrome restart)
bash scripts/launch_agent_chrome.sh

# 4. Install + start the daemon (creates .venv, generates the launchd plist)
bash scripts/install_agent.sh

# 5. Watch it
tail -f logs/agent.log
```

First run seeds the current inbox state and messages you "Agent started". Send
`/check` to force a scan, `/status` for pending cards, `/pause` `/resume`
`/stop` as expected.

### macOS permissions (one-time)

The first AppleScript call will prompt: allow your terminal (and `Python` under
launchd) to control **Google Chrome** (System Settings → Privacy & Security →
Automation). In Chrome, enable *View → Developer → Allow JavaScript from Apple
Events*.

### Keep the rules files rich

Draft quality is your rules quality. Everything in `rules/*.md` is injected
into every draft: voice, host accounts, per-vehicle facts, location-gated
pickup instructions, templates. Start from `rules-examples/`, then let the
🎓 Teach button grow `rules/07-learned.md` as real situations come in.

## Security & privacy

- `config.json` (bot token), `chrome-profile/` (Turo session cookies),
  `state.json` + `logs/` (guest conversations) are **gitignored — keep it that
  way**. Anyone with your bot token can approve sends: treat it like a password.
- The bot never auto-sends to guests; the only unattended outbound messages are
  the optional post-confirmation remote lock/unlock notes, and those fire only
  after a verified action the guest explicitly requested.
- Your `rules/` contain addresses and phone numbers — they stay local and
  gitignored.

## Running the tests

```bash
.venv/bin/python -m pytest tests/ -q
```

## Troubleshooting

- **"can't read inbox" alerts** — Mac locked, Chrome closed, or the flags got
  lost after a Chrome update: `bash scripts/launch_agent_chrome.sh`.
- **Cards show a bare thread id** — the inbox preview format changed; open an
  issue with the (redacted) preview text.
- **Daemon won't start** — `tail logs/agent.log`; `launchctl list | grep turo`.
  Reinstall with `bash scripts/install_agent.sh`.

## Contributing

PRs welcome — read [CONTRIBUTING.md](CONTRIBUTING.md) (failing-test-first, no
personal data in commits, and the CLAUDE.md safety invariants are
non-negotiable).

## License

MIT — see LICENSE.
