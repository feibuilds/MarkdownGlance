"""Do the zoom keys and the zoom wheel reach the preview you are reading?

You read a preview by scrolling it, and the wheel does not move the focus, so
the focus is on the source while your attention is on the preview. All three
paths have to work from there, and none of them is readable from `adjust_zoom`
alone: `Ctrl+=` depends on a keymap context and an `is_enabled`, and the wheel
depends on `mdglance.preview_focused` being asked about the view under the
pointer rather than the focused one. So this presses the real key and turns the
real wheel, and reads the stage's zoom.
"""

import subprocess
import threading

from mdglance_probe import phase

STATE = {}


def _stage(ctx):
    from MarkdownGlance.preview.adapter.container import container

    return container.manager.stage(ctx.window.id())


def _zoom(ctx):
    stage = _stage(ctx)
    return stage.zoom if stage is not None else None


def _surface_view(ctx):
    stage = _stage(ctx)
    if stage is None or stage.surface is None:
        return None
    return next(
        (view for view in ctx.window.views() if view.id() == stage.surface.id), None
    )


def _window_geometry():
    out = subprocess.check_output(
        ["xdotool", "search", "--all", "--onlyvisible", "--class", "sublime_text"],
        text=True,
    ).split()
    for window_id in out:
        info = subprocess.check_output(
            ["xdotool", "getwindowgeometry", "--shell", window_id], text=True
        )
        values = dict(
            line.split("=", 1) for line in info.strip().splitlines() if "=" in line
        )
        if int(values["WIDTH"]) > 400:
            return (
                int(values["X"]), int(values["Y"]),
                int(values["WIDTH"]), int(values["HEIGHT"]),
            )
    raise RuntimeError("no window")


def _ctrl_scroll_over_preview(ctx):
    """Ctrl-wheel with the pointer on the preview, the focus left elsewhere."""
    x, y, width, height = _window_geometry()
    layout = ctx.window.layout()
    c0, _, c1, _ = layout["cells"][1]
    left = x + width * layout["cols"][c0]
    right = x + width * layout["cols"][c1]
    point = (int(left + (right - left) * 0.5), int(y + height * 0.3))

    def run():
        subprocess.call(["xdotool", "mousemove", "--sync", str(point[0]), str(point[1])])
        subprocess.call(["xdotool", "keydown", "ctrl", "click", "4", "keyup", "ctrl"])

    threading.Thread(target=run, daemon=True).start()


def _press(keys):
    def run():
        subprocess.call(["xdotool", "key", "--clearmodifiers", keys])

    threading.Thread(target=run, daemon=True).start()


def start(ctx):
    ctx.run("close_all")
    ctx.window.set_layout(
        {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
    )
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", False)
    ctx.open_fixture("toc-alpha.md")


def rendered(ctx, snap):
    return snap.get("generation") is not None


def zoom_from_source(ctx):
    ctx.window.focus_view(ctx.view)
    STATE["source"] = ctx.view
    STATE["before_source"] = _zoom(ctx)
    _press("ctrl+equal")


def zoom_from_preview(ctx):
    STATE["after_source"] = _zoom(ctx)
    view = _surface_view(ctx)
    ctx.window.focus_view(view)
    STATE["before_preview"] = _zoom(ctx)
    _press("ctrl+equal")


def settled(ctx, snap):
    return True


def scroll_over_preview(ctx):
    STATE["after_preview"] = _zoom(ctx)
    ctx.window.focus_view(STATE["source"])
    STATE["before_wheel"] = _zoom(ctx)
    _ctrl_scroll_over_preview(ctx)


def report(ctx):
    STATE["after_wheel"] = _zoom(ctx)
    ctx.note(
        "ctrl+wheel over an unfocused preview: {} -> {}".format(
            STATE.get("before_wheel"), STATE.get("after_wheel")
        )
    )
    ctx.note(
        "source focused: {} -> {}".format(
            STATE.get("before_source"), STATE.get("after_source")
        )
    )
    ctx.note(
        "preview focused: {} -> {}".format(
            STATE.get("before_preview"), STATE.get("after_preview")
        )
    )


def check(ctx, snap):
    return {
        "zoom works with the source focused": (
            STATE.get("after_source") is not None
            and STATE.get("after_source") > STATE.get("before_source")
        ),
        "zoom works with the preview focused": (
            STATE.get("after_preview") is not None
            and STATE.get("after_preview") > STATE.get("before_preview")
        ),
        "ctrl+wheel over an unfocused preview zooms it": (
            STATE.get("after_wheel") is not None
            and STATE.get("after_wheel") > STATE.get("before_wheel")
        ),
    }


PHASES = [
    phase("open", action=start, done=rendered, screenshot=False, timeout=30),
    phase(
        "from-source", action=zoom_from_source, done=settled,
        screenshot=False, timeout=8,
    ),
    phase(
        "from-preview", action=zoom_from_preview, done=settled,
        screenshot=False, timeout=8,
    ),
    phase(
        "wheel", action=scroll_over_preview, done=settled,
        screenshot=False, timeout=8,
    ),
    phase("report", action=report, done=settled, check=check, timeout=8),
]
