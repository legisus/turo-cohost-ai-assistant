# Setting up and operating with Claude Code

This project is built to be installed, operated, and modified with
[Claude Code](https://claude.com/claude-code) — the same CLI the bot itself
uses for drafting. The repo ships a `CLAUDE.md` that teaches Claude Code the
architecture and the safety invariants, so you can drive everything
conversationally.

## Prerequisites

- A Mac that can stay on and unlocked (see README hardware table)
- Google Chrome logged into your Turo account
- Claude Code installed and authenticated: `npm install -g @anthropic-ai/claude-code`
  (or the desktop app), then run `claude` once to log in — a Claude
  subscription covers both your setup session and the bot's drafting calls

## Guided install (recommended)

```bash
git clone https://github.com/<owner>/turo-cohost-assistant.git
cd turo-cohost-assistant
claude
```

Then ask, in your own words:

> Set this Turo co-host assistant up for me. I co-host for the Turo accounts
> "<owner name(s) as the inbox shows them>", my replies should be signed
> "<your first name>", and here is my Telegram bot token: <token>.

Claude Code will read `CLAUDE.md` and `README.md`, then walk through:

1. `config.json` from `config.example.json` — your token, chat id, signature,
   host names. (Get a token from [@BotFather](https://t.me/BotFather); message
   your bot once so it can discover your chat id.)
2. Your `rules/` from `rules-examples/` — it will interview you for your
   voice, vehicles, key locations, and pickup flows, and write the files.
3. `bash scripts/launch_agent_chrome.sh` — the dedicated Chrome window.
4. `bash scripts/install_agent.sh` — venv, launchd plist, daemon start.
5. A verification pass: `/check` from Telegram, `tail logs/agent.log`.

macOS will prompt once to allow Automation control of Chrome — click Allow,
and enable *View → Developer → Allow JavaScript from Apple Events* in Chrome.

## Day-2 operations, conversationally

Useful things to ask Claude Code in the repo directory:

- "Why didn't the bot reply to <guest>'s message this morning? Check the logs."
- "Add my new host account 'Jane D' everywhere it needs to go."
  (config `host_names` + `rules/02` — CLAUDE.md tells it both.)
- "The bot keeps suggesting airport instructions for home pickups — fix my
  rules." (Or use the 🎓 Teach button right from Telegram.)
- "Restart the daemon" / "check whether the daemon is healthy."
- "Run the test suite."

## Things Claude Code is told never to do (see CLAUDE.md)

- Use Selenium/headless browsing against Turo (Cloudflare blocks it — the
  AppleScript-into-real-Chrome path is the only one that works)
- Add any path that sends a guest a message without your explicit approval tap
- Commit `config.json`, `rules/`, `state.json`, logs, or the Chrome profile
