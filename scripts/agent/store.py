"""Load/save config.json and state.json. State writes are atomic.

Secrets (Telegram bot token + chat id) may be supplied via the environment
(TURO_BOT_TOKEN / TURO_CHAT_ID), which overrides config.json — so credentials
need never live in the repo. config.json (git-ignored) is the local fallback.
"""
import json, os

_ENV = {"bot_token": "TURO_BOT_TOKEN", "chat_id": "TURO_CHAT_ID"}


def load_config(path="config.json"):
    cfg = {}
    if os.path.exists(path):
        with open(path) as f:
            cfg = json.load(f)
    for key, env in _ENV.items():
        val = os.environ.get(env)
        if val:
            cfg[key] = int(val) if key == "chat_id" and val.lstrip("-").isdigit() else val
    return cfg


def save_config(cfg, path="config.json"):
    _atomic_write(path, json.dumps(cfg, indent=2))
    os.chmod(path, 0o600)


def load_state(path="state.json"):
    if not os.path.exists(path):
        return {"threads": {}}
    with open(path) as f:
        return json.load(f)


def save_state(path, state):
    _atomic_write(path, json.dumps(state, indent=2))


def _atomic_write(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
