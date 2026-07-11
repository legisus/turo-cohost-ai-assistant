"""Minimal Telegram Bot API client (stdlib only)."""
import json, socket, urllib.request, urllib.parse, urllib.error


def card_rows(thread_id, extra_rows=None):
    """Inline keyboard for an approval card (module-level so tests can inspect it)."""
    rows = [
        [{"text": "✅ Approve", "callback_data": "ok:%s" % thread_id},
         {"text": "🔄 Regenerate", "callback_data": "regen:%s" % thread_id}],
        [{"text": "✏️ Edit", "callback_data": "edit:%s" % thread_id},
         {"text": "⏭️ Skip", "callback_data": "skip:%s" % thread_id}],
        [{"text": "🎓 Teach", "callback_data": "teach:%s" % thread_id}],
    ]
    if extra_rows:
        rows += extra_rows
    return rows


class Telegram:
    def __init__(self, token, chat_id):
        self.token = token
        self.base = "https://api.telegram.org/bot%s/" % token
        self.chat_id = chat_id
        self.offset = 0

    def download_photo(self, file_id, dest):
        """Download a photo the user sent to a local file (dest). Returns dest."""
        path = self._call("getFile", file_id=file_id)["result"]["file_path"]
        urllib.request.urlretrieve(
            "https://api.telegram.org/file/bot%s/%s" % (self.token, path), dest)
        return dest

    def _call(self, method, **params):
        url = self.base + method
        data = urllib.parse.urlencode(
            {k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
             for k, v in params.items()}).encode()
        with urllib.request.urlopen(url, data=data, timeout=40) as r:
            return json.load(r)

    def send(self, text):
        return self._call("sendMessage", chat_id=self.chat_id, text=text)

    def set_commands(self, commands):
        """commands: list of (command, description) → the tappable '/' menu in Telegram."""
        try:
            return self._call("setMyCommands",
                              commands=[{"command": c, "description": d} for c, d in commands])
        except Exception:
            return None

    def send_card(self, text, thread_id, extra_rows=None):
        return self._call("sendMessage", chat_id=self.chat_id, text=text,
                          reply_markup={"inline_keyboard": card_rows(thread_id, extra_rows)})

    def send_inline(self, text, rows):
        """Send a message with an arbitrary inline keyboard (list of button rows)."""
        return self._call("sendMessage", chat_id=self.chat_id, text=text,
                          reply_markup={"inline_keyboard": rows})

    def answer_callback(self, callback_id, text=""):
        # Best-effort: only clears the button's loading spinner. Telegram returns
        # 400 for expired/old callback queries — ignore so the action still runs.
        try:
            return self._call("answerCallbackQuery", callback_query_id=callback_id, text=text)
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout,
                TimeoutError, ConnectionError):
            return None

    def poll(self, timeout=30):
        """Return a list of normalized events:
        {kind: 'button', action, thread_id, callback_id} or
        {kind: 'text', text} or {kind: 'command', cmd}.
        Network hiccups return [] (offset is only advanced on a parsed update,
        so nothing is lost — Telegram redelivers unconfirmed updates)."""
        try:
            r = self._call("getUpdates", offset=self.offset, timeout=timeout)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError):
            return []
        events = []
        for u in r.get("result", []):
            self.offset = u["update_id"] + 1
            if "callback_query" in u:
                cq = u["callback_query"]
                action, tid = cq["data"].split(":", 1)
                events.append({"kind": "button", "action": action,
                               "thread_id": tid, "callback_id": cq["id"]})
            elif "message" in u and "photo" in u["message"]:
                m = u["message"]
                events.append({"kind": "photo", "file_id": m["photo"][-1]["file_id"],
                               "caption": m.get("caption", "")})
            elif "message" in u and "text" in u["message"]:
                t = u["message"]["text"]
                if t.startswith("/"):
                    events.append({"kind": "command", "cmd": t.split()[0][1:].lower()})
                else:
                    events.append({"kind": "text", "text": t})
        return events
