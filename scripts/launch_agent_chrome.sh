#!/bin/bash
# Relaunch Chrome with anti-throttle flags and open a dedicated Turo inbox window.
# The flags keep an occluded/background window rendering and accepting input, so the
# agent can drive Turo invisibly while you use other apps (no focus-stealing).
# Re-run this after a reboot or a normal Chrome restart to re-apply the flags.
set -e
FLAGS="--disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling"
INBOX="https://turo.com/us/en/inbox/messages"

echo "Quitting Chrome (tabs restore via session / Cmd-Shift-T)…"
osascript -e 'tell application "Google Chrome" to quit' 2>/dev/null || true
for i in $(seq 1 30); do pgrep -x "Google Chrome" >/dev/null || break; sleep 0.5; done
sleep 1

echo "Relaunching Chrome with anti-throttle flags…"
open -a "Google Chrome" --args $FLAGS
sleep 4

echo "Opening dedicated Turo window…"
osascript -e "tell application \"Google Chrome\"
  make new window
  set URL of active tab of front window to \"$INBOX\"
end tell"
sleep 3

echo "=== flags applied? (should print the flag) ==="
ps aux | grep "[C]hrome" | grep -o "disable-backgrounding-occluded-windows" | head -1 || echo "FLAGS NOT FOUND"
