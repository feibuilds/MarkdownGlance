#!/usr/bin/env bash
# Run one scenario in the portable Sublime Text and collect evidence.
#
#   .claude/skills/run-markdownglance/drive.sh <scenario> [--root DIR] [--xvfb] [--keep]
#
#   <scenario>  a name under scenarios/ (math, preview) or a path to a .py
#   --root DIR  the profile setup.sh built (default $MDGLANCE_ST_ROOT or /tmp/mdglance-st)
#   --xvfb      run under a private X server; no display needed (xvfb-run)
#   --keep      leave Sublime Text open at the end instead of exiting it
#
# Evidence lands in ROOT/evidence/<scenario>-<timestamp>/: one JSON snapshot
# and, where the phase asks, one PNG per phase, plus console.log. The exit
# code is summarise.py's: 0 only when every phase finished and every check
# passed. The probe inside Sublime Text drives the app; this script only
# waits, screenshots the window between phases, and lets the next one go.
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${MDGLANCE_ST_ROOT:-/tmp/mdglance-st}"
XVFB=0
KEEP=0
SCENARIO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --xvfb) XVFB=1; shift ;;
    --keep) KEEP=1; shift ;;
    *) SCENARIO="$1"; shift ;;
  esac
done
[ -n "$SCENARIO" ] || { echo "usage: drive.sh <scenario> [--root DIR] [--xvfb] [--keep]"; exit 2; }
case "$SCENARIO" in
  */*|*.py) SCENARIO_FILE="$(cd "$(dirname "$SCENARIO")" && pwd)/$(basename "$SCENARIO")" ;;
  *) SCENARIO_FILE="$SKILL_DIR/scenarios/$SCENARIO.py" ;;
esac
[ -e "$SCENARIO_FILE" ] || { echo "no scenario $SCENARIO_FILE"; exit 2; }
[ -x "$ROOT/sublime_text" ] || { echo "no portable Sublime Text at $ROOT; run setup.sh"; exit 2; }
for tool in xdotool wmctrl import; do
  command -v "$tool" >/dev/null || { echo "missing $tool (apt: xdotool wmctrl imagemagick)"; exit 2; }
done

if [ "$XVFB" = 1 ] && [ -z "${MDGLANCE_UNDER_XVFB:-}" ]; then
  command -v xvfb-run >/dev/null || { echo "missing xvfb-run (apt: xvfb)"; exit 2; }
  export MDGLANCE_UNDER_XVFB=1
  exec xvfb-run -a -s "-screen 0 1700x1000x24" "$0" "$SCENARIO_FILE" --root "$ROOT" $([ "$KEEP" = 1 ] && echo --keep)
fi

NAME="$(basename "$SCENARIO_FILE" .py)"
EV="$ROOT/evidence/$NAME-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$EV"
python3 - "$ROOT/probe.json" "$SCENARIO_FILE" "$EV" "$SKILL_DIR/fixtures" "$KEEP" <<'EOF'
import json, sys
path, scenario, evidence, fixtures, keep = sys.argv[1:]
json.dump({"scenario": scenario, "evidence": evidence, "fixtures": fixtures,
           "keep_open": keep == "1"}, open(path, "w"), indent=2)
EOF

"$ROOT/sublime_text" --multiinstance >"$EV/console.log" 2>&1 &
ST_PID=$!
echo "sublime_text pid $ST_PID, evidence $EV"

window_id() {
  # --all: every condition must hold. Without it xdotool ORs them and finds
  # any other Sublime Text window on the desktop.
  xdotool search --all --onlyvisible --pid "$ST_PID" --name "Sublime Text" 2>/dev/null | head -1
}

wait_for() { # wait_for <file> <seconds>
  local i=0
  while [ ! -e "$1" ]; do
    sleep 1; i=$((i + 1))
    [ -e "$1" ] && return 0
    [ "$i" -lt "$2" ] || { echo "timeout waiting for $(basename "$1")"; return 1; }
    kill -0 "$ST_PID" 2>/dev/null || { echo "sublime_text exited before $(basename "$1")"; return 1; }
  done
}

shoot() { # shoot <phase>
  local wid
  wid="$(window_id)"
  [ -n "$wid" ] || { echo "no window to shoot for $1"; return; }
  wmctrl -i -r "$wid" -e 0,0,0,1700,1000 2>/dev/null
  wmctrl -i -a "$wid" 2>/dev/null
  sleep 1.5
  import -window "$wid" "$EV/$1.png" 2>/dev/null && echo "shot $1.png"
}

if wait_for "$EV/phases.json" 60; then
  while IFS=$'\t' read -r phase screenshot timeout; do
    if wait_for "$EV/$phase.done" "$((timeout + 30))"; then
      [ "$screenshot" = "True" ] && shoot "$phase"
    fi
    touch "$EV/go-$phase"
  done < <(python3 -c 'import json,sys
for p in json.load(open(sys.argv[1])): print(p["name"], p["screenshot"], p["timeout"], sep="\t")' "$EV/phases.json")
fi

if [ "$KEEP" = 1 ]; then
  echo "leaving sublime_text $ST_PID open"
else
  wait_for "$EV/exit.done" 30 || true
  for _ in $(seq 1 15); do kill -0 "$ST_PID" 2>/dev/null || break; sleep 1; done
  kill -0 "$ST_PID" 2>/dev/null && { echo "still running, terminating"; kill "$ST_PID"; }
fi
rm -f "$ROOT/probe.json"
python3 "$SKILL_DIR/summarise.py" "$EV"
