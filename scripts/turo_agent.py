#!/usr/bin/env python3
"""Unattended Turo co-host daemon.

Watches the Turo inbox 24/7 via the real logged-in Chrome. For every new guest
message it drafts a reply and asks the user to Approve / Edit / Skip over Telegram
before anything is sent. Nothing reaches a guest without an explicit tap.

Spec: docs/superpowers/specs/2026-06-13-telegram-autonomous-agent-design.md
"""
import os, sys, time, json, re, subprocess, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import store, detect, chrome, draft, meta, chat, teach, persona
from agent.telegram import Telegram

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config.json")
STATE = os.path.join(ROOT, "state.json")


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def safe_send(tg, text):
    """Best-effort Telegram reply. Never raises — if the user has blocked the bot
    Telegram returns 403, which must NOT prevent a command (e.g. /stop) from acting."""
    try:
        tg.send(text)
    except Exception as e:
        log("send failed (bot blocked / network?): %s" % e)


# --- Remote lock/unlock (NissanConnect-equipped vehicles) --------------------
PATHFINDER_REMOTE = os.path.join(ROOT, "scripts", "pathfinder_remote.py")


def is_remote_vehicle(text):
    return any(n in (text or "").lower() for n in persona.REMOTE_VEHICLE_NAMES)


_UNLOCK_INTENT = re.compile(
    r"\b(unlock|can'?t get in|won'?t open|still locked|is locked|locked out|"
    r"how (do|to)\s.*\bget in|let me in|at the car|i'?m here|open the (car|door))\b", re.I)
_LOCK_INTENT = re.compile(
    r"\b(lock it|can you lock|won'?t lock|can'?t lock|doesn'?t lock|how (do|to)\s.*\block)\b", re.I)


def remote_intent(text):
    """Return 'unlock' | 'lock' | None for a guest message on a remote-capable car."""
    t = text or ""
    if _UNLOCK_INTENT.search(t):
        return "unlock"
    if _LOCK_INTENT.search(t):
        return "lock"
    return None


# Guest-facing confirmation sent automatically AFTER a confirmed remote action
# (only when the guest's latest message actually asked for it — see do_vehicle_action).
# Because it fires post-confirmation, it may state the fact (cf. rules/06-remote-unlock.md,
# which forbids claiming it at the unconfirmed DRAFT stage).
GUEST_LOCK_REPLY = ("Done — I've locked it for you remotely. You're all set! "
                    "Safe travels, and thanks again. - %s" % persona.SIGNATURE)
GUEST_UNLOCK_REPLY = ("I've unlocked it for you remotely — give it a few seconds and try the "
                      "door again. The key is in the middle console. Let me know once you're in! "
                      "- %s" % persona.SIGNATURE)


def vehicle_reply_text(action):
    """Guest confirmation text for a remote action, or None (e.g. status checks)."""
    return {"lock": GUEST_LOCK_REPLY, "unlock": GUEST_UNLOCK_REPLY}.get(action)


def vehicle_button_rows(tid):
    return [
        [{"text": "🔓 Unlock", "callback_data": "unlock:%s" % tid},
         {"text": "🔒 Lock", "callback_data": "lock:%s" % tid}],
        [{"text": "📊 Vehicle status", "callback_data": "vstatus:%s" % tid}],
    ]


def _run_remote(cmd, tid):
    """Run the verified orchestrator and return its parsed JSON result."""
    out = subprocess.run([sys.executable, PATHFINDER_REMOTE, cmd, tid],
                         capture_output=True, text=True, timeout=150)
    for ln in reversed((out.stdout or "").strip().splitlines()):
        try:
            return json.loads(ln)
        except ValueError:
            continue
    return {"ok": False, "allowed": True, "reason": (out.stderr or "no output").strip()[:200]}


def _fmt_status(d):
    s = d.get("status") or {}
    lock = (s.get("lockStatus") or {}).get("lockStatus") or "?"
    ck = s.get("cockpit") or {}
    fa, mi = ck.get("fuelAutonomy") or {}, ck.get("totalMileage") or {}
    parts = ["🚗 Pathfinder — %s" % lock]
    if fa:
        parts.append("range ~%s %s" % (fa.get("value"), fa.get("unit")))
    if mi:
        parts.append("odo %s %s" % (mi.get("value"), mi.get("unit")))
    return " · ".join(parts)


def _guest_asked_for(action, tid):
    """True if the guest's latest message on `tid` actually requested this remote
    action — so a proactive lock (e.g. via /pathfinder between trips) does NOT
    auto-message the guest. Read failure => False (we don't message on a guess)."""
    try:
        return remote_intent(chrome.last_message(tid).get("text", "")) == action
    except Exception:
        return False


def do_vehicle_action(tg, state, action, tid):
    """Handle a 🔓/🔒/📊 button via the verified pathfinder_remote orchestrator.

    Outcomes are logged (#1) so 'did the bot lock it?' is answerable from the log,
    not only from a transient Telegram message. On a CONFIRMED lock/unlock that the
    guest actually requested, the guest gets an automatic confirmation reply (#2)."""
    cmd = {"unlock": "unlock", "lock": "lock", "vstatus": "status"}[action]
    log("vehicle %s requested for thread %s" % (cmd, tid))
    tg.send({"unlock": "🔓 Unlocking…", "lock": "🔒 Locking…",
             "vstatus": "📊 Checking the car…"}[action])
    try:
        d = _run_remote(cmd, tid)
    except Exception as e:
        tg.send("⚠️ Remote %s failed: %s" % (cmd, e))
        log("vehicle %s ERROR for thread %s: %s" % (cmd, tid, e))
        return
    if action == "vstatus":
        if d.get("ok"):
            tg.send(_fmt_status(d)); log("vehicle status for thread %s: %s" % (tid, _fmt_status(d)))
        else:
            tg.send("⚠️ Couldn't read status: %s" % d.get("reason", "unknown"))
            log("vehicle status FAILED for thread %s: %s" % (tid, d.get("reason", "unknown")))
        return
    if d.get("ok"):
        tg.send("🔓 Unlocked — confirmed." if action == "unlock" else "🔒 Locked — confirmed.")
        log("vehicle %s CONFIRMED for thread %s" % (cmd, tid))
        reply = vehicle_reply_text(action)
        if reply and _guest_asked_for(action, tid):
            do_send(tg, state, tid, reply)  # confirm to the guest, with echo bookkeeping
        else:
            log("vehicle %s: no guest auto-reply for thread %s (not a guest request)" % (cmd, tid))
    elif not d.get("allowed", True):
        tg.send("🚫 Can't %s: %s" % (action, d.get("reason", "blocked")))
        log("vehicle %s BLOCKED for thread %s: %s" % (cmd, tid, d.get("reason", "blocked")))
    else:
        door = d.get("door") or {}
        why = door.get("status") or d.get("reason", "unknown")
        tg.send("⚠️ %s not confirmed (status=%s). Check the car or try again."
                % (action.title(), why))
        log("vehicle %s NOT CONFIRMED for thread %s: %s" % (cmd, tid, why))


def ensure_caffeinate():
    """Keep a `caffeinate` child alive so the Mac doesn't sleep."""
    proc = getattr(ensure_caffeinate, "proc", None)
    if proc is None or proc.poll() is not None:
        ensure_caffeinate.proc = subprocess.Popen(["caffeinate", "-dimsu"])
        log("started caffeinate")


def ensure_chrome():
    """Make sure Chrome is running with the anti-throttle flags AND a Turo inbox window,
    so the system fully auto-resumes after a reboot with no manual steps. Only relaunches
    Chrome when the flags are missing (e.g. after a reboot) — otherwise just opens a Turo
    window if one isn't present, without disturbing the user's other tabs."""
    flagged = subprocess.run(["pgrep", "-f", "disable-backgrounding-occluded-windows"],
                             capture_output=True).returncode == 0
    if not flagged:
        log("Chrome missing anti-throttle flags — relaunching via launch_agent_chrome.sh")
        subprocess.run(["bash", os.path.join(ROOT, "scripts", "launch_agent_chrome.sh")],
                       capture_output=True, timeout=90)
        time.sleep(3)
        return
    try:
        healthy = chrome.healthy()
    except Exception:
        healthy = False
    if not healthy:
        log("Chrome has flags but no Turo tab — opening one")
        subprocess.run(["osascript", "-e",
                        'tell application "Google Chrome"\n make new window\n'
                        ' set URL of active tab of front window to '
                        '"https://turo.com/us/en/inbox/messages"\nend tell'],
                       capture_output=True)
        time.sleep(3)


def card_text(header, last_in, draft_text):
    return ("%s\n\nGuest said:\n  %s\n\nProposed reply:\n  %s\n\n"
            "Approve = send · Regenerate = redraft from your hint · "
            "Edit = send your exact text · Skip = ignore · "
            "Teach = save a rule for cases like this."
            % (header, last_in.strip()[:600], draft_text.strip()[:1200]))


def make_draft_and_card(tg, state, tid, preview=""):
    """Confirm the latest message is inbound, draft a reply, send the approval card
    with a human-readable header (host / vehicle / plate / guest). Sets pending so
    the thread is not re-carded until resolved; caller updates last_seen regardless."""
    # Our OWN sent messages render as right-aligned bubbles (no (Host)/(Guest) tag,
    # no avatar); classify_sender reads that 'outbound' geometry to skip them — this is
    # what stops the daemon drafting a reply to our own message. The (Host)/(Guest) text
    # tag is only on the LAST message of a consecutive group, so its absence is NOT taken
    # as "ours" (that would drop real guest messages); such 'unknown' cases still draft
    # and let Claude SKIP if needed. ask-before-send makes a stray card cheap.
    last = chrome.last_message(tid)
    # Stale-render guard: the inbox preview carries the start of the TRUE latest
    # message. A partial/out-of-order thread render can return an OLDER message as
    # the last one (untagged → 'unknown' → drafted as if a guest wrote it — that's
    # how the host's own farewell got carded as a guest message). Re-read until the
    # thread agrees with the preview; if it never does, proceed with the final read
    # (this guard may only trigger re-reads — it must never drop a guest message).
    for attempt in (1, 2):
        if meta.preview_matches_last(preview, last.get("text", "")):
            break
        log("thread %s read disagrees with inbox preview (stale render?) — re-read %d"
            % (tid, attempt))
        last = chrome.last_message(tid)
    else:
        if not meta.preview_matches_last(preview, last.get("text", "")):
            log("thread %s still disagrees with preview after re-reads — proceeding" % tid)
    info = meta.parse_preview(preview) or {}
    # Skip host/own messages; for a confirmed guest, draft; for an unmarked grouped
    # received message ('unknown'), draft and let Claude decide (SKIP if it's really ours).
    sender = meta.classify_sender(last, info.get("host", ""), info.get("guest", ""))
    if sender == "host":
        log("latest msg is from host for %s — skip" % tid)
        return
    hdr = meta.header(preview, tid)
    thread_text = chrome.read_thread(tid)
    # Ground the draft in reservation facts (trip window, status, pending guest
    # requests like date changes or child seats). Grounding must never block a
    # reply: on any failure we draft without the facts block and just log it.
    trip = {}
    try:
        trip = chrome.trip(tid) or {}
    except Exception as e:
        log("trip facts unavailable for %s: %s" % (tid, e))
    trip["pending_request"] = meta.pending_request(trip.get("req", []))
    facts = draft.facts_line(trip)
    if facts:
        thread_text = facts + "\n" + thread_text
    try:
        body = draft.draft_reply(thread_text, guest=info.get("guest", ""),
                                 host=info.get("host", ""))
    except Exception as e:
        tg.send("⚠️ Couldn't draft for %s (%s). Reply manually:\n%s"
                % (hdr, e, last.get("text", "")[:600]))
        return
    if body.strip().upper() in ("SKIP", "<REPLY>SKIP</REPLY>", ""):
        log("draft says no reply needed for %s" % tid)
        return  # caller marks it seen
    photo = ("\n\n📷 The guest attached a photo — open the thread in Turo to view it."
             if last.get("photo") else "")
    remote = is_remote_vehicle(preview or hdr)
    extra = vehicle_button_rows(tid) if remote else None
    notice = ""
    if remote:
        intent = remote_intent(last.get("text", ""))
        if intent == "unlock":
            notice = "👉 Guest seems to need the car UNLOCKED — tap 🔓 Unlock below (verified).\n\n"
        elif intent == "lock":
            notice = "👉 Guest seems to need the car LOCKED — tap 🔒 Lock below.\n\n"
    if trip.get("pending_request"):
        notice = ("⚠️ Pending guest request: %s — approve/decline in the Turo app.\n\n"
                  % trip["pending_request"]) + notice
    tg.send_card(notice + card_text(hdr, last.get("text", ""), body) + photo, tid, extra_rows=extra)
    t = state["threads"].setdefault(tid, {"last_seen": "", "last_sent": "", "pending": None})
    t["pending"] = {"stage": "await_approval", "draft": body, "header": hdr,
                    "host": info.get("host", ""), "guest": info.get("guest", "")}
    log("sent approval card for thread %s (%s)%s" % (tid, hdr, " [photo]" if last.get("photo") else ""))


def do_send(tg, state, tid, text):
    """Read-back-before-send and verify-after-send. Marks the thread to reconcile
    its own echo on the next scan so we never reply to our own message."""
    readback = chrome.set_message(tid, text)
    if readback.strip() != text.strip():
        tg.send("⚠️ Couldn't stage the reply for thread %s (got: %r) — NOT sent."
                % (tid, readback[:40]))
        return
    result = chrome.send(tid)
    if result in ("WRONG_THREAD", "NO_TEXTAREA"):
        tg.send("⚠️ Send guard tripped for thread %s (%s) — NOT sent." % (tid, result))
        return
    time.sleep(4)  # let Turo's send round-trip render before verifying
    try:
        posted = (chrome.last_message(tid).get("text", "") or "").lower()
        if text.strip()[:25].lower() not in posted and persona.SIGNATURE.lower() not in posted:
            tg.send("⚠️ Sent to %s but couldn't verify it posted — please check the "
                    "thread (is the Chrome tab foreground / screen unlocked?)." % tid)
    except Exception:
        pass
    t = state["threads"].setdefault(tid, {"last_seen": "", "last_sent": "", "pending": None})
    hdr = (t.get("pending") or {}).get("header") or ("thread %s" % tid)
    t["pending"] = None
    t["awaiting_echo"] = True
    tg.send("✅ Sent — %s" % hdr)
    log("sent reply to thread %s" % tid)


def reconcile_echoes(state, listing_map):
    """After we send, the thread's inbox preview becomes our own message. Fold that
    into last_seen/last_sent so it is not mistaken for a new guest message."""
    for tid, t in state["threads"].items():
        if t.get("awaiting_echo"):
            preview = listing_map.get(tid, t.get("last_seen", ""))
            t["last_seen"] = preview
            t["last_sent"] = preview
            t["awaiting_echo"] = False


# Typed-text routing. The operator's next message goes ONLY to the thread whose
# Edit/Regenerate button was tapped LAST (state["compose"]) — never picked by
# dict-order scan. That scan caused the 2026-07-10 wrong-guest send: a 13-day-old
# stale await_edit on another thread swallowed the operator's regen hint verbatim.
_COMPOSING = ("await_edit", "await_regen", "await_teach")


def begin_compose(state, tid, stage):
    """Point typed-text routing at `tid` and revert any OTHER thread left in a
    composing stage back to a plain approvable card (stale compose must never
    swallow text meant for a different guest)."""
    for otid, t in state["threads"].items():
        p = t.get("pending")
        if otid != tid and p and p.get("stage") in _COMPOSING:
            p["stage"] = "await_approval"
    t = state["threads"].setdefault(tid, {"last_seen": "", "last_sent": "", "pending": None})
    if t.get("pending"):
        t["pending"]["stage"] = stage
    state["compose"] = tid


def route_text(state):
    """(tid, stage) the next typed message belongs to, else (None, None) → chat."""
    tid = state.get("compose")
    p = state["threads"].get(tid, {}).get("pending") if tid else None
    if p and p.get("stage") in _COMPOSING:
        return tid, p["stage"]
    return None, None


def consume_compose(state):
    state["compose"] = None


def clear_stale_compose(state):
    """On startup, mid-compose context from a previous run is meaningless: revert
    every composing stage to an approvable card and drop the pointer."""
    for t in state["threads"].values():
        p = t.get("pending")
        if p and p.get("stage") in _COMPOSING:
            p["stage"] = "await_approval"
    state["compose"] = None


def regenerate(tg, state, tid, guidance):
    """Re-draft a reply, weaving in the host's hint, and send a fresh approval card."""
    last = chrome.last_message(tid)
    thread_text = chrome.read_thread(tid)
    hint = "" if guidance.strip().lower() in ("go", "regen", "regenerate", "again") else guidance
    pend = state["threads"].get(tid, {}).get("pending", {}) or {}
    try:
        body = draft.draft_reply(thread_text, guidance=hint,
                                 guest=pend.get("guest", ""), host=pend.get("host", ""))
    except Exception as e:
        tg.send("⚠️ Regenerate failed for thread %s (%s). Try again or Edit." % (tid, e))
        return
    hdr = pend.get("header") or ("\U0001F697 thread %s" % tid)
    extra = vehicle_button_rows(tid) if is_remote_vehicle(hdr) else None
    tg.send_card(card_text(hdr, last.get("text", ""), body), tid, extra_rows=extra)
    state["threads"].setdefault(tid, {})["pending"] = {
        "stage": "await_approval", "draft": body, "header": hdr,
        "host": pend.get("host", ""), "guest": pend.get("guest", "")}
    log("regenerated draft for thread %s" % tid)


def do_teach(tg, state, tid, lesson):
    """Persist an operator lesson as a permanent rule (rules/07-learned.md), show
    what was saved, then redraft the pending card with the lesson as guidance.
    A failed distillation saves the lesson verbatim — a teaching is never lost."""
    pend = state["threads"].get(tid, {}).get("pending") or {}
    hdr = pend.get("header") or ("thread %s" % tid)
    if not lesson.strip():
        begin_compose(state, tid, "await_teach")
        tg.send("🎓 Tell me in a sentence or two what to do in situations like this.")
        return
    try:
        thread_text = chrome.read_thread(tid)
    except Exception:
        thread_text = ""
    try:
        rule = teach.distill(lesson, thread_text, hdr)
        saved = teach.save_lesson(rule, lesson, hdr)
        tg.send("🎓 Learned — saved for all future replies:\n%s" % saved.strip())
        log("taught rule for thread %s" % tid)
    except Exception as e:
        saved = teach.save_lesson(lesson, lesson, hdr)
        tg.send("🎓 Saved your words verbatim (couldn't distill a rule: %s):\n%s"
                % (e, saved.strip()))
        log("taught verbatim for thread %s (distill failed: %s)" % (tid, e))
    regenerate(tg, state, tid, lesson)


def _log_chat(you, me):
    """Append a chat exchange to logs/chat.log (persistent record of our conversation)."""
    try:
        with open(os.path.join(ROOT, "logs", "chat.log"), "a") as f:
            f.write("%s  You: %s\n%s  Me:  %s\n\n"
                    % (time.strftime("%Y-%m-%d %H:%M"), you, " " * 16, me))
    except Exception:
        pass


def chat_with_operator(tg, state, message):
    """Free-text from the operator → a context-aware chat reply from Claude."""
    history = state.setdefault("chat", [])
    pend = [(v.get("pending") or {}).get("header") or k
            for k, v in state["threads"].items() if v.get("pending")]
    ctx = "Pending guest cards awaiting his decision: %s" % ("; ".join(pend) or "none")
    try:
        reply = chat.chat_reply(message, history, ctx)
    except Exception as e:
        tg.send("⚠️ Chat error: %s" % e)
        return
    history.append({"role": "Operator", "text": message})
    history.append({"role": "Assistant", "text": reply})
    state["chat"] = history[-16:]
    tg.send(reply)
    _log_chat(message, reply)


def handle_command(tg, state, cmd):
    cfg = store.load_config(CONFIG)
    if cmd == "pause":
        # Persist the flag BEFORE replying so a blocked-bot 403 can't undo the pause.
        cfg["paused"] = True; store.save_config(cfg, CONFIG)
        safe_send(tg, "⏸️ Paused — I won't send anything until /resume.")
    elif cmd == "resume":
        cfg["paused"] = False; store.save_config(cfg, CONFIG)
        safe_send(tg, "▶️ Resumed.")
    elif cmd == "status":
        pend = [(v.get("pending") or {}).get("header") or k
                for k, v in state["threads"].items() if v.get("pending")]
        tg.send("Status: %s%s.\nPending:\n%s"
                % ("paused" if cfg.get("paused") else "active",
                   " (BLIND — can't read inbox)" if main.blind else "",
                   "\n".join("• " + h for h in pend) or "none"))
    elif cmd == "check":
        tg.send("🔍 Checking the inbox now…")
        try:
            before = sum(1 for v in state["threads"].values() if v.get("pending"))
            scan_inbox(tg, state, dict(cfg, paused=False))  # force-card on manual check
            main.scan_fail = 0; main.blind = False
            new = sum(1 for v in state["threads"].values() if v.get("pending")) - before
            tg.send("Done — %d new message(s) need your reply." % new if new > 0
                    else "Done — no new guest messages.")
        except Exception as e:
            tg.send("⚠️ Couldn't read the inbox (%s). Is the Mac screen locked or "
                    "Chrome closed?" % e)
    elif cmd in ("pathfinder", "car"):
        tid = next((k for k, v in state["threads"].items()
                    if is_remote_vehicle(v.get("last_seen", ""))), None)
        if not tid:
            tg.send("No active Pathfinder thread is being tracked right now."); return
        d = _run_remote("status", tid)
        txt = _fmt_status(d) if d.get("ok") else ("🚗 Pathfinder (status unavailable: %s)"
                                                  % d.get("reason", "?"))
        tg.send_inline(txt + "\n\nTap to control:", vehicle_button_rows(tid))
    elif cmd == "clear":
        state["chat"] = []; tg.send("🧹 Chat history cleared.")
    elif cmd == "chat":
        tg.send("💬 Just type a message and I'll reply — ask me anything about the inbox, "
                "a guest situation, or help drafting. /clear resets our chat.")
    elif cmd == "stop":
        # Reply best-effort FIRST (must not block the exit), then tear down the
        # launchd job so KeepAlive=true doesn't immediately relaunch us. Restart
        # later with scripts/install_agent.sh.
        safe_send(tg, "\U0001F6D1 Stopping the agent — it won't auto-restart. "
                      "Run scripts/install_agent.sh to bring it back.")
        subprocess.run(["launchctl", "bootout", "gui/%d/com.turo.cohost" % os.getuid()],
                       capture_output=True)
        sys.exit(0)
    elif cmd == "start":
        tg.send("\U0001F44B Running. Type to chat with me, or use /check /status /pause "
                "/resume /clear /stop.")
    else:
        tg.send("Type to chat with me. Commands: /check /status /pause /resume /clear /stop")


def handle_event(tg, state, ev):
    log("event: %s" % {k: v for k, v in ev.items() if k != "callback_id"})
    if ev["kind"] == "button":
        tid = ev["thread_id"]; tg.answer_callback(ev["callback_id"])
        if ev["action"] in ("unlock", "lock", "vstatus"):
            do_vehicle_action(tg, state, ev["action"], tid); return
        t = state["threads"].get(tid, {}); p = t.get("pending")
        if not p:
            tg.send("That message is no longer pending."); return
        if ev["action"] == "ok":
            do_send(tg, state, tid, p["draft"])
        elif ev["action"] == "skip":
            hdr = p.get("header") or ("thread %s" % tid)
            t["pending"] = None; tg.send("⏭️ Skipped — %s" % hdr)
        elif ev["action"] == "edit":
            begin_compose(state, tid, "await_edit")
            tg.send("✏️ Send the exact replacement text (sent verbatim) for:\n%s" % p.get("header", tid))
        elif ev["action"] == "regen":
            begin_compose(state, tid, "await_regen")
            tg.send("🔄 What should I change for:\n%s\nSend a hint "
                    "(e.g. 'say I'll get it tomorrow') — or 'go' for a fresh take." % p.get("header", tid))
        elif ev["action"] == "teach":
            begin_compose(state, tid, "await_teach")
            tg.send("🎓 What should I say/do in situations like this?\n%s\n"
                    "Explain it once — I'll save it as a rule for all future replies "
                    "and redraft this one." % p.get("header", tid))
    elif ev["kind"] == "text":
        tid, stage = route_text(state)
        consume_compose(state)
        if stage == "await_edit":
            do_send(tg, state, tid, ev["text"])
        elif stage == "await_regen":
            regenerate(tg, state, tid, ev["text"])
        elif stage == "await_teach":
            do_teach(tg, state, tid, ev["text"])
        else:
            chat_with_operator(tg, state, ev["text"])
    elif ev["kind"] == "photo":
        tg.send("🔎 Looking at your photo…")
        try:
            dest = os.path.join(ROOT, ".imgtmp", "tg_photo.jpg")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            tg.download_photo(ev["file_id"], dest)
            history = state.setdefault("chat", [])
            pend = [(v.get("pending") or {}).get("header") or k
                    for k, v in state["threads"].items() if v.get("pending")]
            reply = chat.analyze_image(dest, ev.get("caption", ""), history,
                                       "Pending cards: %s" % ("; ".join(pend) or "none"))
            history.append({"role": "Operator", "text": "[sent a photo] " + ev.get("caption", "")})
            history.append({"role": "Assistant", "text": reply})
            state["chat"] = history[-16:]
            tg.send(reply)
            _log_chat("[photo] " + ev.get("caption", ""), reply)
        except Exception as e:
            tg.send("⚠️ Couldn't analyze the photo: %s" % e)
    elif ev["kind"] == "command":
        handle_command(tg, state, ev["cmd"])


def scan_inbox(tg, state, cfg):
    """Read the inbox and card any new inbound messages. Raises on an unreadable
    inbox (suspended/locked tab, logged out) so the caller can track 'blindness'."""
    if not chrome.healthy():
        raise RuntimeError("no healthy Turo tab")
    listing = chrome.list_threads()
    if not listing:
        # The inbox always has threads; 0 means the tab didn't render (suspended/
        # backgrounded/locked) — treat as a failure, not "nothing to do".
        raise RuntimeError("inbox returned 0 threads (tab not rendering?)")
    listing_map = {i["id"]: i["text"] for i in listing}
    reconcile_echoes(state, listing_map)
    if not cfg.get("paused"):
        for tid in detect.candidates(listing, state):
            make_draft_and_card(tg, state, tid, listing_map.get(tid, ""))
            state["threads"].setdefault(tid, {"last_seen": "", "last_sent": "", "pending": None})
            state["threads"][tid]["last_seen"] = listing_map.get(tid, "")
    store.save_state(STATE, state)


def main():
    # Clear any orphaned keep-awake process from a prior instance before starting ours.
    subprocess.run(["pkill", "-f", "caffeinate -dimsu"], capture_output=True)
    main.scan_fail = 0      # consecutive failed inbox scans
    main.blind = False      # whether we've alerted the user that we can't read the inbox
    cfg = store.load_config(CONFIG)
    tg = Telegram(cfg["bot_token"], cfg["chat_id"])
    tg.set_commands([("check", "Scan the inbox now"), ("status", "What's pending"),
                     ("pathfinder", "Pathfinder status + lock/unlock"),
                     ("chat", "How to chat with me"), ("clear", "Reset our chat"),
                     ("pause", "Pause sending"), ("resume", "Resume sending"),
                     ("stop", "Stop the agent")])
    state = store.load_state(STATE)
    clear_stale_compose(state)  # a restart orphans any mid-compose card
    ensure_caffeinate()
    ensure_chrome()  # auto-resume: relaunch Chrome with flags + Turo window if needed
    if not state["threads"]:
        listing = chrome.list_threads()
        state = detect.seed(listing); store.save_state(STATE, state)
        tg.send("✅ Agent started — watching %d threads." % len(listing))
        log("cold start seeded %d threads" % len(listing))
    last_heartbeat = ""
    last_scan = 0.0
    while True:
        try:
            ensure_caffeinate()
            cfg = store.load_config(CONFIG)
            now = time.time()
            if now - last_scan >= cfg.get("poll_interval", 180):
                last_scan = now
                try:
                    scan_inbox(tg, state, cfg)
                    main.scan_fail = 0
                    if main.blind:
                        tg.send("✅ Inbox reading restored — back to watching.")
                        main.blind = False
                except Exception:
                    main.scan_fail += 1
                    log("scan failed (%d):\n%s" % (main.scan_fail, traceback.format_exc()))
                    if main.scan_fail >= 3 and not main.blind:
                        try:
                            ensure_chrome()  # self-heal: re-launch flags / reopen Turo tab
                        except Exception:
                            pass
                        tg.send("⚠️ I can't read the Turo inbox right now — the Chrome "
                                "tab is likely suspended (is the Mac screen locked, or "
                                "Chrome closed?). New guest messages are NOT being "
                                "detected until this clears. I'll tell you when it's back.")
                        main.blind = True
            hb = time.strftime("%Y-%m-%d")
            if time.strftime("%H:%M") == cfg.get("heartbeat_time", "09:00") and hb != last_heartbeat:
                tg.send("✅ Co-host agent running."); last_heartbeat = hb
            # Poll Telegram with a short long-poll so buttons feel responsive
            # between inbox scans.
            for ev in tg.poll(timeout=10):
                try:
                    handle_event(tg, state, ev)
                except Exception:
                    log("event error (%s):\n%s" % (ev.get("kind"), traceback.format_exc()))
            store.save_state(STATE, state)
        except SystemExit:
            raise
        except Exception:
            log("loop error:\n" + traceback.format_exc())
            time.sleep(5)


if __name__ == "__main__":
    main()
