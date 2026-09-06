#!/usr/bin/env bash
# Launch the portable Sublime Text, let the MathProbe plugin walk its phases,
# screenshot the window between them, and exit. Evidence lands in ./evidence.
set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
EV="$ROOT/evidence"
mkdir -p "$EV"
rm -f "$EV"/*.done "$EV"/go* "$EV"/*.json "$EV"/*.png "$EV"/console.log

"$ROOT/sublime_text" --multiinstance >"$EV/console.log" 2>&1 &
ST_PID=$!
echo "sublime_text pid $ST_PID"

window_id() {
  # The preview shares the window; any top-level window of the process will do.
  xdotool search --all --onlyvisible --pid "$ST_PID" --name "Sublime Text" 2>/dev/null | head -1
}

wait_for() {
  local file="$1" limit="${2:-120}" i=0
  while [ ! -e "$file" ]; do
    sleep 1; i=$((i + 1))
    if [ "$i" -ge "$limit" ]; then echo "timeout waiting for $file"; return 1; fi
    if ! kill -0 "$ST_PID" 2>/dev/null; then echo "sublime_text exited early"; return 1; fi
  done
  return 0
}

shoot() {
  local name="$1" wid
  wid="$(window_id)"
  if [ -z "$wid" ]; then echo "no window for $name"; return; fi
  wmctrl -i -r "$wid" -e 0,0,0,1700,1000 2>/dev/null
  wmctrl -i -a "$wid" 2>/dev/null
  sleep 1.5
  import -window "$wid" "$EV/$name.png" 2>/dev/null && echo "shot $name ($wid)"
}

# Phase 1: math on, first render.
wait_for "$EV/phase1-math-on.done" 150 && shoot "phase1-math-on"
touch "$EV/go2"
# Phase 2: light colour scheme, formulas re-fetched in the new foreground.
wait_for "$EV/phase2-light-scheme.done" 120 && shoot "phase2-light-scheme"
touch "$EV/go3"
# Phase 3: diagnostics must not carry a formula.
wait_for "$EV/phase3-diagnostics.done" 60
touch "$EV/go4"
# Phase 4: math off, formulas read as source.
wait_for "$EV/phase4-math-off.done" 120 && shoot "phase4-math-off"
touch "$EV/go5"

for _ in $(seq 1 20); do kill -0 "$ST_PID" 2>/dev/null || break; sleep 1; done
if kill -0 "$ST_PID" 2>/dev/null; then echo "still running, terminating"; kill "$ST_PID"; fi
echo "done"; ls "$EV"
