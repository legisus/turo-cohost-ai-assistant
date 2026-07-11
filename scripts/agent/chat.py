"""Conversational chat with the operator over Telegram, via `claude -p`.

Any free-text the operator sends (when not mid Edit/Regenerate) is routed here. We give
Claude the house rules + current pending cards + recent chat history so replies are
grounded in the actual co-hosting context.
"""
import subprocess
from agent import persona
from agent.draft import _load_rules

SYSTEM = (
    "You are the operator's (" + persona.SIGNATURE + "'s) assistant for his Turo co-hosting business. You "
    "watch the Turo inbox and draft guest replies that he approves over Telegram. Right "
    "now he is chatting with YOU directly (not a guest). Be concise and practical — this "
    "is a phone chat, so keep replies short and PLAIN TEXT only (no markdown/asterisks — "
    "Telegram shows them literally). You can answer questions, think through guest "
    "situations, explain the Turo/LAX rules you know, and help compose message text. "
    "To actually send a guest a reply he should use the approval card buttons "
    "(Approve / Edit / Regenerate) or you can give him text to paste. To scan the inbox "
    "now, he can send /check. Do not invent facts about specific guests you haven't been "
    "given; ask or say you'd need to open the thread."
)


def analyze_image(image_path, caption="", history=None, context=""):
    """Vision: look at a photo the operator forwarded (e.g. a guest's photo) and say what
    it shows + how to respond. Runs `claude -p` referencing the local image file."""
    parts = [SYSTEM,
             "The operator just sent you a PHOTO" +
             (" with the note: '%s'" % caption if caption else "") + ". Look at the image "
             "at %s and reply SHORT and PLAIN TEXT: (1) what it shows, (2) anything relevant "
             "to a Turo trip (vehicle damage, a dashboard light, a document, a parking spot, "
             "the car/keys, etc.), and (3) if it looks like something a guest sent, suggest "
             "how to respond (or offer to draft a reply)." % image_path]
    if context:
        parts.append("CONTEXT: " + context)
    if history:
        parts.append("RECENT CHAT:\n" + "\n".join(
            "%s: %s" % (h["role"], h["text"]) for h in history[-6:]))
    parts.append("YOUR HOUSE RULES:\n" + _load_rules())
    p = subprocess.run(["claude", "--model", "claude-sonnet-5", "-p", "\n\n".join(parts)],
                       capture_output=True, text=True, timeout=150)
    if p.returncode != 0:
        raise RuntimeError("claude vision failed: " + p.stderr.strip())
    return p.stdout.strip()


def chat_reply(message, history=None, context=""):
    parts = [SYSTEM]
    if context:
        parts.append("CURRENT STATUS:\n" + context)
    parts.append("YOUR HOUSE RULES / VEHICLES / TEMPLATES:\n" + _load_rules())
    if history:
        convo = "\n".join("%s: %s" % (h["role"], h["text"]) for h in history[-8:])
        parts.append("RECENT CHAT:\n" + convo)
    parts.append("Operator: " + message + "\nAssistant:")
    p = subprocess.run(["claude", "--model", "claude-sonnet-5", "-p", "\n\n".join(parts)],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise RuntimeError("claude chat failed: " + p.stderr.strip())
    return p.stdout.strip()
