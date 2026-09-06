"""The two step 10 checks the pre-fix run could not make.

Zoom, a heading typed while the panel is open and a window resize all said
nothing before: both panels were pinned by issue #4 and could not follow
anything. And the divider drag went through `window.set_layout`, which is not
bounded the way a real drag is.

This runs on the fixed build and drags the divider with real X11 pointer
events. Two things the first attempts got wrong, both recorded here because
they cost a run each:

- The portable profile remembers its window layout, so a run inherits the
  previous one's splits. Every run now starts from one group.
- The press has to land on the divider, which is a few pixels wide. Computed
  from a stale `cols` it landed on the minimap instead, where a drag scrolls
  the file and changes nothing else.
"""

import os
import subprocess
import threading
import time

from mdglance_probe import phase

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linux-fixtures")
ONE_GROUP = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
NARROW = (1280, 900)
DRAG_BY = 120


class State:
    window = None
    since = 0.0
    result = {}
    measurements = {}
    drag = {}


# -- shelling out, always off the UI thread --------------------------------


def spawn(script, key):
    """Run a shell script on a worker; `State.result['done']` says when."""
    State.result = {"done": False}
    result = State.result

    def worker():
        try:
            done = subprocess.run(
                ["bash", "-c", script], capture_output=True, timeout=60
            )
            result[key] = {
                "script": script,
                "returncode": done.returncode,
                "stderr": done.stderr.decode("utf-8", "replace").strip()[:400],
            }
        except Exception as error:  # noqa: BLE001
            result[key] = {"script": script, "error": repr(error)}
        result["done"] = True

    threading.Thread(target=worker, daemon=True).start()


def query(args):
    """A read-only X query; safe on the UI thread because nothing waits on us."""
    return subprocess.run(args, capture_output=True, timeout=20).stdout.decode()


def find_window():
    ids = query(
        ["xdotool", "search", "--all", "--pid", str(os.getppid()), "--name", "Sublime Text"]
    ).split()
    return ids[-1] if ids else None


def geometry():
    values = dict(
        line.split("=", 1)
        for line in query(
            ["xdotool", "getwindowgeometry", "--shell", State.window]
        ).strip().splitlines()
        if "=" in line
    )
    return {k: int(v) for k, v in values.items() if v.lstrip("-").isdigit()}


# -- reporting --------------------------------------------------------------


def layout_report(window):
    layout = window.layout()
    groups = []
    for index in range(window.num_groups()):
        view = window.active_view_in_group(index)
        groups.append(
            {
                "group": index,
                "cell": list(layout["cells"][index]),
                "width_px": round(float(view.viewport_extent()[0]), 1) if view else 0.0,
                "names": [
                    (s.view().name() if s.view() else "")
                    or os.path.basename((s.view().file_name() or "") if s.view() else "")
                    or "?"
                    for s in window.sheets_in_group(index)
                ],
            }
        )
    return {"cols": [round(c, 6) for c in layout["cols"]], "groups": groups}


def outline_session(ctx):
    return ctx.container().outline.for_source(ctx.window.id(), ctx.view.buffer_id())


def measure(ctx, label):
    session = outline_session(ctx)
    group = ctx.container().backend.group_of(session.surface) if session else None
    view = ctx.window.active_view_in_group(group) if group is not None else None
    report = {
        "layout": layout_report(ctx.window),
        "outline_group": group,
        "outline_px": round(float(view.viewport_extent()[0]), 1) if view else 0.0,
        "zoom": round(session.zoom, 3) if session else None,
        "geometry": geometry() if State.window else {},
    }
    State.measurements[label] = report
    return report


def px(label):
    return State.measurements[label]["outline_px"]


# -- phases -----------------------------------------------------------------


def start(ctx):
    State.since = time.time()
    State.window = find_window()
    for view in list(ctx.window.views()):
        view.set_scratch(True)
        view.close()
    ctx.window.set_layout(ONE_GROUP)
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", True)
    ctx.set_setting("MarkdownGlance.sublime-settings", "auto_width", True)
    ctx.view = ctx.window.open_file(os.path.join(FIXTURES, "tiny.md"))
    ctx._preview_pending = True


def toc_open(ctx, snap):
    session = ctx.session()
    return ctx.settled(snap) and session is not None and session.toc_surface is not None


def open_outline(ctx):
    State.since = time.time()
    ctx.window.focus_view(ctx.view)
    ctx.run("mdglance_toggle_outline")


def outline_ready(ctx, snap):
    session = outline_session(ctx)
    return session is not None and bool(session.headings) and time.time() > State.since + 2


def base_check(ctx, snap):
    report = measure(ctx, "base")
    return {
        "the run started from one group": len(report["layout"]["groups"]) == 4,
        "the outline is near the 156 px it asks for": 120 <= report["outline_px"] <= 210,
    }


def after(seconds):
    def done(ctx, snap):
        return time.time() > State.since + seconds

    return done


def zoom_in(ctx):
    State.since = time.time()
    session = outline_session(ctx)
    if session is not None:
        ctx.container().backend.focus(session.surface)
    ctx.run("mdglance_zoom", {"delta": 0.25})


def zoom_check(ctx, snap):
    report = measure(ctx, "zoom")
    return {
        "the outline's zoom rose": report["zoom"] == 1.25,
        "the group grew with it": report["outline_px"] > px("base") + 10,
    }


def zoom_reset(ctx):
    State.since = time.time()
    ctx.run("mdglance_zoom", {"reset": True})


def reset_check(ctx, snap):
    report = measure(ctx, "reset")
    return {
        "the zoom went back to 1.0": report["zoom"] == 1.0,
        "and so did the width": abs(report["outline_px"] - px("base")) <= 12,
    }


def type_heading(ctx):
    ctx.window.focus_view(ctx.view)
    ctx.view.run_command("append", {"characters": "\n\n## A longer entry\n"})


def typed_ready(ctx, snap):
    session = outline_session(ctx)
    return session is not None and any(h.text == "A longer entry" for h in session.headings)


def typed_check(ctx, snap):
    report = measure(ctx, "typed")
    return {"the group followed the longer heading": report["outline_px"] > px("reset") + 10}


def drag_divider(offset):
    """A real pointer drag on the boundary the outline shares with the source.

    `cols * WIDTH` puts the press within a few pixels of the divider, and the
    divider's hot spot is only a few pixels wide, so the offsets are tried in
    turn until the layout actually moves. A press that misses lands on the
    minimap, where a drag scrolls the file and changes no boundary.
    """

    def action(ctx):
        State.since = time.time()
        if State.drag.get("moved"):
            State.result = {"done": True}
            return
        _drag_once(ctx, offset)

    return action


def _drag_once(ctx, offset):
    report = measure(ctx, "pre-drag")
    box = report["geometry"]
    cell = report["layout"]["groups"][report["outline_group"]]["cell"]
    x = box["X"] + int(report["layout"]["cols"][cell[0]] * box["WIDTH"]) + offset
    y = box["Y"] + box["HEIGHT"] // 2
    steps = "; ".join(
        "xdotool mousemove --sync {} {}; sleep 0.12".format(x - step, y)
        for step in range(20, DRAG_BY + 1, 20)
    )
    script = (
        "xdotool windowactivate --sync {w}; sleep 0.8; "
        "xdotool mousemove --sync {x} {y}; sleep 0.6; xdotool mousedown 1; sleep 0.4; "
        "{steps}; sleep 0.4; xdotool mouseup 1"
    ).format(w=State.window, x=x, y=y, steps=steps)
    State.drag.setdefault("attempts", []).append({"x": x, "offset": offset})
    State.drag.setdefault("cols_before", report["layout"]["cols"])
    State.drag.update({"x": x, "y": y, "by": DRAG_BY})
    spawn(script, "drag")


def drag_done(ctx, snap):
    return State.result.get("done", False) and time.time() > State.since + 4


def drag_check(last):
    def check(ctx, snap):
        report = measure(ctx, "dragged")
        moved = report["layout"]["cols"] != State.drag["cols_before"]
        if moved:
            State.drag["moved"] = True
            State.drag["cols_after"] = report["layout"]["cols"]
            State.drag["outline_px"] = report["outline_px"]
        State.drag["command"] = State.result.get("drag")
        if not last and not moved:
            return {}  # another offset still to try
        return {
            "the pointer drag moved the divider": bool(State.drag.get("moved")),
            "and widened the outline": State.drag.get("outline_px", 0)
            > State.measurements["base"]["outline_px"] + 40,
        }

    return check


def type_again(ctx):
    ctx.window.focus_view(ctx.view)
    ctx.view.run_command("append", {"characters": "\n\n## After the drag\n"})


def typed_again(ctx, snap):
    session = outline_session(ctx)
    return session is not None and any(h.text == "After the drag" for h in session.headings)


def held_check(ctx, snap):
    report = measure(ctx, "after-repaint")
    return {
        "a repaint did not move the divider back": report["layout"]["cols"]
        == State.measurements["dragged"]["layout"]["cols"]
    }


def shrink(ctx):
    State.since = time.time()
    spawn(
        "xdotool windowsize {w} {x} {y}".format(
            w=State.window, x=NARROW[0], y=NARROW[1]
        ),
        "resize",
    )


def resize_check(ctx, snap):
    report = measure(ctx, "resized")
    ctx.write(
        "followups.json", {"measurements": State.measurements, "drag": State.drag}
    )
    return {
        "the window really shrank": report["geometry"].get("WIDTH", 10 ** 6)
        <= NARROW[0] + 40,
        "the outline followed it down": report["outline_px"] < px("after-repaint"),
        "without collapsing": report["outline_px"] >= 80,
    }


PHASES = [
    phase("base", action=start, done=toc_open, check=lambda c, s: {"toc opened": True}),
    phase("panels", action=open_outline, done=outline_ready, check=base_check),
    phase("zoom", action=zoom_in, done=after(3), check=zoom_check, timeout=25),
    phase("zoom-reset", action=zoom_reset, done=after(3), check=reset_check, timeout=25),
    phase("typed", action=type_heading, done=typed_ready, check=typed_check),
    phase(
        "drag-0", action=drag_divider(0), done=drag_done, check=drag_check(False),
        timeout=60, screenshot=False,
    ),
    phase(
        "drag-plus", action=drag_divider(5), done=drag_done, check=drag_check(False),
        timeout=60, screenshot=False,
    ),
    phase(
        "drag-minus", action=drag_divider(-5), done=drag_done, check=drag_check(False),
        timeout=60, screenshot=False,
    ),
    phase(
        "dragged", action=drag_divider(10), done=drag_done, check=drag_check(True),
        timeout=60,
    ),
    phase("after-repaint", action=type_again, done=typed_again, check=held_check),
    phase("resized", action=shrink, done=drag_done, check=resize_check, timeout=40),
]
