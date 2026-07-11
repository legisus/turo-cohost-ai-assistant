#!/usr/bin/env python3
"""Path A driver: operate the user's REAL, already-logged-in Chrome.

Why not Selenium: Turo/Cloudflare blocks Selenium-spawned Chrome on sight
(automation fingerprint). The real human session is never blocked.

Two guarantees that make this safe to run while the user works on the PC:
  1. We act ONLY on a dedicated Turo tab, found by URL match each call --
     never the user's active tab.
  2. We NEVER call `activate` -- AppleScript `execute ... javascript` and
     `set URL of tab` run in the background and do not steal focus.

Subcommands:
  find                       -> prints WIN TAB or NO_TURO_TAB
  list                       -> JSON array of {id, text} latest threads
  read <thread_id>           -> thread innerText tail (after last "Conversation with")
  setmsg <thread_id> <b64>   -> set composer text (base64/UTF-8); prints read-back value
  send <thread_id>           -> press Enter to send; prints post-send textarea value

Reply text is passed base64-encoded to sidestep all shell/AppleScript/JS
escaping (emoji and newlines included).
"""
import base64
import subprocess
import sys

INBOX = "https://turo.com/us/en/inbox/messages"


def osa(script: str) -> str:
    """Run an AppleScript via osascript (read from stdin). Returns stdout."""
    p = subprocess.run(["osascript", "-"], input=script,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("osascript failed: " + p.stderr.strip())
    return p.stdout.rstrip("\n")


def _find_tab():
    """Return (win_index, tab_index) of the dedicated Turo tab, or None.

    Prefers an inbox tab; falls back to any turo.com tab. 1-based indices,
    matched fresh every call so it survives the user opening/closing tabs.
    """
    script = r'''
    tell application "Google Chrome"
      set best to ""
      set fallback to ""
      set wc to count of windows
      repeat with wi from 1 to wc
        set tc to count of tabs of window wi
        repeat with ti from 1 to tc
          set u to URL of tab ti of window wi
          if u contains "turo.com" then
            if fallback is "" then set fallback to ((wi as text) & " " & (ti as text))
            if u contains "/inbox" then
              set best to ((wi as text) & " " & (ti as text))
              exit repeat
            end if
          end if
        end repeat
        if best is not "" then exit repeat
      end repeat
      if best is not "" then return best
      return fallback
    end tell
    '''
    out = osa(script).strip()
    if not out:
        return None
    wi, ti = out.split()
    return int(wi), int(ti)


def _esc(js: str) -> str:
    """Escape JS source for embedding in an AppleScript double-quoted string."""
    return js.replace("\\", "\\\\").replace('"', '\\"')


def run_js(js: str) -> str:
    tab = _find_tab()
    if tab is None:
        print("NO_TURO_TAB")
        sys.exit(2)
    wi, ti = tab
    script = (
        'tell application "Google Chrome"\n'
        f'  execute tab {ti} of window {wi} javascript "{_esc(js)}"\n'
        'end tell'
    )
    return osa(script)


def nav(url: str):
    """Point the dedicated tab at `url` WITHOUT stealing focus.

    AppleScript `set URL of tab` activates Chrome (pulls it to the front);
    navigating via `execute javascript` (location.href) does not. This is what
    lets the agent drive Turo in a background window while the user works."""
    run_js("window.location.href='%s'" % url)


def _focus_tab():
    """Make Turo the ACTIVE tab of its own window WITHOUT stealing focus (no
    `activate`, no window reorder). In the dedicated-window setup, Chrome is
    launched with --disable-backgrounding-occluded-windows etc., so the active
    tab of a hidden window keeps rendering and accepts input — letting the user
    work in other apps while the agent drives Turo invisibly."""
    tab = _find_tab()
    if tab is None:
        return
    wi, ti = tab
    osa('tell application "Google Chrome" to set active tab index of window %d to %d'
        % (wi, ti))


LIST_JS = (
    '(function(){var seen={},out=[];'
    # Turo links inbox rows as /reservation/<id>/messages (current) or .../thread/<id>
    # (SPA route, only present when the virtualized list is laid out). Match both.
    '[].forEach.call(document.querySelectorAll('
    '\'a[href*="/reservation/"],a[href*="thread/"]\'),'
    'function(a){var m=a.href.match(/(?:reservation|thread)\\/(\\d+)/);if(!m)return;'
    'var id=m[1];var tx=a.innerText.trim().replace(/\\s+/g," ");'
    # drop pagination anchors (empty/numeric text) and duplicate ids:
    'if(!tx||/^\\d+$/.test(tx)||seen[id])return;seen[id]=1;'
    'out.push({id:id,text:tx.slice(0,200)});});'
    'return JSON.stringify(out);})()'
)

# Extract the open conversation via the deploy-stable testid prefix.
# Direction signals, most reliable first:
#   - outbound: OUR account's own sent messages render as right-aligned bubbles.
#     They carry NO "(Host)/(Guest)" tag and NO avatar, so this geometry is the only
#     reliable way to tell them apart from a received message (fixes the self-reply
#     bug where our own message was drafted as if a guest sent it). Found by locating
#     the rounded message bubble and comparing its gap to the row's left vs right edge.
#   - tag: received messages end with "- <Name> (Host)|(Guest)", but Turo only appends
#     this to the LAST message of a consecutive same-sender group — so its ABSENCE
#     does NOT imply a message is ours (a grouped guest line can be untagged too).
# If the bubble can't be measured we leave outbound=false (fail toward drafting; never
# silently drop a guest message on a geometry glitch).
CONV_JS = (
    '(function(){var ms=document.querySelectorAll('
    '\'[data-testid^="message-animations_"]\');'
    'var out=[];[].forEach.call(ms,function(m){'
    'var tx=(m.innerText||"").trim();if(!tx)return;'
    # avatar alt = sender name (profile img on images.turo.com/media); a
    # reservation image == a photo the guest attached.
    'var avatar="",photo=false;'
    '[].forEach.call(m.querySelectorAll("img"),function(i){'
    'var src=i.getAttribute("src")||"",alt=i.getAttribute("alt")||"";'
    'if(/images\\.turo\\.com\\/media/.test(src)&&alt)avatar=alt;'
    'if(/reservation\\/image|\\/thumb/.test(src))photo=true;});'
    'var tag=/\\(Host\\)/.test(tx)?"host":(/\\(Guest\\)/.test(tx)?"guest":"");'
    # right-aligned bubble => our own outbound message
    'var mr=m.getBoundingClientRect(),bubble=null;'
    '[].forEach.call(m.querySelectorAll("*"),function(k){if(bubble)return;'
    'var br=parseFloat(getComputedStyle(k).borderTopLeftRadius)||0;'
    'var kr=k.getBoundingClientRect();'
    'if(br>=6&&kr.width>30&&(k.innerText||"").length>3)bubble=k;});'
    'var outbound=false;if(bubble){var b=bubble.getBoundingClientRect();'
    'outbound=(b.left-mr.left)>(mr.right-b.right);}'
    'out.push({text:tx,avatar:avatar,photo:photo,tag:tag,outbound:outbound});});'
    'return JSON.stringify(out);})()'
)


# The trip's pickup/drop-off location lives in a structured "Location" block in
# the thread header (label element whose exact text is "Location", followed by the
# address). We read THAT element specifically — grepping page text is unreliable
# because host instruction templates mention many addresses (airport lots, home-base streets, …).
LOC_JS = (
    '(function(){var v="";'
    '[].forEach.call(document.querySelectorAll("p,span,div,strong,h1,h2,h3"),function(e){'
    'if(v)return;'
    'if((e.innerText||"").trim()==="Location"){'
    'var p=e.parentElement;'
    'var s=(((p?p.innerText:"")||"").replace(/^Location\\s*/,"")'
    '.split("\\n").map(function(x){return x.trim();}).filter(Boolean))[0];'
    'if(s)v=s;}});return v;})()'
)


# Extract trip facts from a /reservation/<id> page: vehicle, pickup/dropoff
# date+time, and Turo's own status sentence. The trip pickup/dropoff render as
# title-case "Wed, Jun 17" + "1:30 AM" pairs (no year); message timestamps are
# UPPERCASE with a year ("WED, JUN 17, 2026") so they don't match and won't be
# mistaken for the trip window.
TRIP_JS = (
    '(function(){'
    'var L=(document.body.innerText||"").split("\\n")'
    '.map(function(s){return s.trim();}).filter(Boolean);'
    'var makes=/(Nissan|Tesla|Ford|Honda|Toyota|Subaru|Acura|Volvo|Volkswagen|'
    'BMW|Kia|Chevrolet|Lexus|Hyundai|Mazda|Jeep|Audi|Mercedes|Dodge|GMC)/i;'
    'var veh="";'
    'for(var i=0;i<L.length;i++){if(makes.test(L[i])&&/20\\d\\d/.test(L[i])){veh=L[i];break;}}'
    'var dre=/^[A-Z][a-z]{2}, [A-Z][a-z]{2} \\d{1,2}$/;'
    'var tre=/^\\d{1,2}:\\d{2}\\s?(AM|PM)$/i;'
    'var pairs=[];'
    'for(var j=0;j<L.length-1;j++){if(dre.test(L[j])&&tre.test(L[j+1]))'
    'pairs.push({date:L[j],time:L[j+1]});}'
    # Authoritative trip state is the "Booked/Past/Cancelled trip" label.
    'var tt="";'
    'for(var m=0;m<L.length;m++){if(/^(Booked|Past|Cancelled) trip$/i.test(L[m]))'
    '{tt=L[m];break;}}'
    # Informational status sentence — must mention "trip" so the "CANCELLATION
    # POLICY" section header is not mistaken for a trip state.
    'var st="";'
    'for(var k=0;k<L.length;k++){if(/\\btrip\\b/i.test(L[k])&&/(starts in|'
    'in progress|hours? left|minutes? left|ended|checked in|cancel)/i.test(L[k]))'
    '{st=L[k];break;}}'
    'return JSON.stringify({vehicle:veh,tripType:tt,pickup:pairs[0]||null,'
    'dropoff:pairs[1]||null,status:st});'
    '})()'
)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"

    if cmd == "find":
        tab = _find_tab()
        print("NO_TURO_TAB" if tab is None else "WIN %d TAB %d" % tab)

    elif cmd == "list":
        # Navigate to the inbox first (read/last leave the tab on a thread page),
        # then poll until the SPA renders the thread rows (avoids a 0-result race).
        import time, json
        nav(INBOX)
        result = "[]"
        for _ in range(8):
            time.sleep(1.5)
            result = run_js(LIST_JS)
            try:
                if json.loads(result):
                    break
            except Exception:
                pass
        print(result)

    elif cmd in ("read", "last"):
        import time, json
        tid = sys.argv[2]
        _focus_tab()  # backgrounded tab renders messages out of order
        nav("%s/thread/%s" % (INBOX, tid))
        # poll until messages render (avoids the "undefined"/too-short-wait bug)
        msgs = []
        for _ in range(8):
            time.sleep(1.5)
            raw = run_js(CONV_JS)
            try:
                msgs = json.loads(raw)
            except Exception:
                msgs = []
            if msgs:
                break
        if cmd == "last":
            print(json.dumps(msgs[-1] if msgs else
                             {"text": "", "avatar": "", "photo": False, "tag": "",
                              "outbound": False}))
        else:
            # Prepend the trip's actual pickup/drop-off location (structured field
            # in the thread header) so the draft can pick LAX vs home-parking rules
            # by the REAL location, not by guessing.
            loc = (run_js(LOC_JS) or "").strip()
            if loc:
                print("📍 Trip pickup/drop-off location: %s" % loc)
            for m in msgs:
                who = m.get("avatar") or (m.get("tag") or "?")
                pic = " [PHOTO ATTACHED]" if m.get("photo") else ""
                print("%s: %s%s" % (who, m["text"], pic))

    elif cmd == "trip":
        # Read-only: extract vehicle + pickup/dropoff + status from the
        # reservation page. Used by the remote lock/unlock verification gate.
        import time, json
        tid = sys.argv[2]
        _focus_tab()
        nav("https://turo.com/us/en/reservation/%s" % tid)
        info = {}
        for _ in range(8):
            time.sleep(1.5)
            try:
                info = json.loads(run_js(TRIP_JS))
            except Exception:
                info = {}
            if info.get("vehicle") or info.get("pickup"):
                break
        print(json.dumps(info))

    elif cmd == "setmsg":
        # CRITICAL: navigate to the TARGET thread first, then verify the URL inside
        # the JS before touching the composer — otherwise the reply lands on whatever
        # thread the tab happened to be showing (wrong-customer bug).
        import time
        tid = sys.argv[2]
        b64 = sys.argv[3]
        _focus_tab()
        nav("%s/thread/%s" % (INBOX, tid))
        for _ in range(8):  # wait for the composer on the correct thread
            time.sleep(1.5)
            if run_js('(function(){return document.querySelector("textarea")?"Y":"N";})()') == "Y":
                break
        js = (
            '(function(){'
            'if(location.href.indexOf("%s")<0)return"WRONG_THREAD";'
            'var t=decodeURIComponent(escape(atob("%s")));'
            'var ta=document.querySelector("textarea");'
            'if(!ta)return"NO_TEXTAREA";'
            'var set=Object.getOwnPropertyDescriptor('
            'HTMLTextAreaElement.prototype,"value").set;'
            'set.call(ta,t);'
            'ta.dispatchEvent(new Event("input",{bubbles:true}));'
            'return ta.value;'
            '})()'
        ) % (tid, b64)
        print(run_js(js))

    elif cmd == "send":
        # Hard guard: refuse to press Enter unless the tab is ON the target thread.
        tid = sys.argv[2]
        _focus_tab()
        js = (
            '(function(){'
            'if(location.href.indexOf("%s")<0)return"WRONG_THREAD";'
            'var ta=document.querySelector("textarea");'
            'if(!ta)return"NO_TEXTAREA";'
            'ta.focus();'
            '["keydown","keypress","keyup"].forEach(function(ty){'
            'ta.dispatchEvent(new KeyboardEvent(ty,{key:"Enter",'
            'keyCode:13,which:13,bubbles:true,cancelable:true}));});'
            'return ta.value;'
            '})()'
        ) % tid
        print(run_js(js))

    else:
        print("unknown command: %s" % cmd)
        sys.exit(1)


if __name__ == "__main__":
    main()
