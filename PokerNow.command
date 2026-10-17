#!/bin/bash
# Double-click launcher for the PokerNow hand-history tool (macOS).
# - creates the virtualenv on first run (uv if available, else python3 -m venv)
# - keeps all game data in ./data/<gameId>/ next to this file
# - reads ./.env for optional settings (e.g. POKERNOW_NPT=... to include your hole cards)
# - starts the web UI and opens it in your browser; close this window (or Ctrl-C) to stop

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# give this launcher the chip icon (Finder icons live in xattrs, which git doesn't keep)
if [ -f "$DIR/src/pokernow/static/chip.svg" ] && ! xattr "$0" 2>/dev/null | grep -q com.apple.ResourceFork; then
  osascript -l JavaScript -e 'ObjC.import("AppKit");
    $.NSWorkspace.sharedWorkspace.setIconForFileOptions(
      $.NSImage.alloc.initWithContentsOfFile("'"$DIR"'/src/pokernow/static/chip.svg"), "'"$DIR/$(basename "$0")"'", 0)' >/dev/null 2>&1 || true
fi

PORT="${POKERNOW_PORT:-8517}"
export POKERNOW_DATA_DIR="${POKERNOW_DATA_DIR:-$DIR/data}"
mkdir -p "$POKERNOW_DATA_DIR"

if [ -f "$DIR/.env" ]; then
  set -a; . "$DIR/.env"; set +a
fi

echo "PokerNow hand-history tool"
echo "  folder : $DIR"
echo "  data   : $POKERNOW_DATA_DIR"

if [ ! -x "$DIR/.venv/bin/pokernow" ]; then
  echo "First run: setting up the Python environment…"
  if command -v uv >/dev/null 2>&1; then
    uv venv -q "$DIR/.venv"
    uv pip install -q --python "$DIR/.venv/bin/python" -e "$DIR"
  else
    PY="$(command -v python3 || true)"
    if [ -z "$PY" ]; then
      echo "python3 not found. Install Python 3.11+ (https://www.python.org/downloads/) and double-click again."
      read -r -p "Press Enter to close…" _; exit 1
    fi
    "$PY" -m venv "$DIR/.venv"
    "$DIR/.venv/bin/pip" install -q --upgrade pip
    "$DIR/.venv/bin/pip" install -q -e "$DIR"
  fi
fi

# stop servers left by earlier double-clicks and close their Terminal windows
OLD_PIDS="$(pgrep -f "$DIR/.venv/bin/pokernow serve" || true)"
if [ -n "$OLD_PIDS" ]; then
  echo "  stopping the copy that was already running…"
  OLD_TTYS="$(for p in $OLD_PIDS; do ps -o tty= -p "$p" 2>/dev/null; done | grep -v '?' | sed 's|^ *|/dev/|' | sort -u)"
  kill $OLD_PIDS 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10; do pgrep -f "$DIR/.venv/bin/pokernow serve" >/dev/null || break; sleep 0.3; done
  pkill -9 -f "$DIR/.venv/bin/pokernow serve" 2>/dev/null || true
  for t in $OLD_TTYS; do
    osascript -e 'tell application "Terminal"
      repeat with w in (every window)
        if (count of tabs of w) is 1 and tty of tab 1 of w is "'"$t"'" then close w
      end repeat
    end tell' >/dev/null 2>&1 || true
  done
fi

# pick a free port if the default is busy
while lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; do PORT=$((PORT+1)); done

echo "  url    : http://127.0.0.1:$PORT/   (closing this window stops the server)"
if [ -n "$POKERNOW_NPT" ]; then echo "  login  : POKERNOW_NPT set — your own hole cards will be included"; else echo "  login  : anonymous (add POKERNOW_NPT=... to .env to include your hole cards)"; fi
echo

exec "$DIR/.venv/bin/pokernow" serve --host 127.0.0.1 --port "$PORT" --open
