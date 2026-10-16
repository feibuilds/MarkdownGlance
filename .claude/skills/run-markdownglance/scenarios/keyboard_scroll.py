"""Do the arrow keys, Page Up/Down and Home/End scroll a focused preview?

A surface is an empty buffer under one block phantom, so Sublime's own `move`
has no text to take the caret through, and every one of these keys did
nothing in a preview (#6). `mdglance_scroll` moves the viewport instead,
under the `mdglance.preview_focused` context, which only a keymap can see -- so
this presses the real keys with `xdotool` and reads the viewport off the Sublime
API after each.

It also checks the keys stay Sublime's in the source, reach the contents
panel, and follow the zoom.
"""

import subprocess
import threading

from mdglance_probe import phase

STATE = {"results": []}


def _container():
    from MarkdownGlance.preview.adapter.container import container

    return container


def _view_by_id(ctx, view_id):
    return next((view for view in ctx.window.views() if view.id() == view_id), None)


def _preview(ctx):
    stage = _container().manager.stage(ctx.window.id())
    return _view_by_id(ctx, stage.surface.id) if stage and stage.surface else None


def _panel(ctx):
    stage = _container().panel.stage(ctx.window.id())
    return _view_by_id(ctx, stage.surface.id) if stage and stage.surface else None


def _metrics(view, zoom):
    from MarkdownGlance.preview.renderer.stylesheet import line_px

    return {
        "line": line_px(zoom),
        "page": view.viewport_extent()[1] - line_px(zoom),
        "bottom": max(0.0, view.layout_extent()[1] - view.viewport_extent()[1]),
    }


def _press(keys):
    def run():
        subprocess.call(["xdotool", "key", "--clearmodifiers"] + keys.split())

    threading.Thread(target=run, daemon=True).start()


def _top(view):
    return view.viewport_position()[1]


def _close(a, b):
    # Sublime keeps the viewport on whole pixels, and an animated move does not
    # always round to the nearest one: 888.2 was seen to land at 889.
    return abs(a - b) <= 1.0


def start(ctx):
    ctx.run("close_all")
    ctx.window.set_layout(
        {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
    )
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", False)
    ctx.open_fixture("toc-long.md")


def rendered(ctx, snap):
    return snap.get("generation") is not None


def settled(ctx, snap):
    return True


# Each step presses keys in the focused preview and says where the top of the
# viewport must then be, from the top before the press and the metrics.
STEPS = [
    ("Down Down Down", lambda top, m: top + 3 * m["line"]),
    ("Up", lambda top, m: top - m["line"]),
    ("Next", lambda top, m: top + m["page"]),
    ("Prior", lambda top, m: top - m["page"]),
    ("End", lambda top, m: m["bottom"]),
    ("Down", lambda top, m: m["bottom"]),
    ("Home", lambda top, m: 0.0),
    ("Up", lambda top, m: 0.0),
    ("ctrl+End", lambda top, m: m["bottom"]),
    ("ctrl+Home", lambda top, m: 0.0),
]


def _record(ctx):
    """Read where the previous step landed."""
    pending = STATE.pop("pending", None)
    if pending is None:
        return
    label, view, expected = pending
    actual = _top(view)
    STATE["results"].append((label, expected, actual))
    ctx.note("{}: expected {:.1f}, got {:.1f}".format(label, expected, actual))


def _step(keys, expect, where, zoom_of):
    def action(ctx):
        _record(ctx)
        view = where(ctx)
        ctx.window.focus_view(view)
        top = _top(view)
        STATE["pending"] = (
            "{}. {} in the {}".format(
                len(STATE["results"]) + 1, keys, where.__name__.strip("_")
            ),
            view,
            expect(top, _metrics(view, zoom_of(ctx))),
        )
        _press(keys)

    return action


def _preview_zoom(ctx):
    return _container().manager.stage(ctx.window.id()).zoom


def _panel_zoom(ctx):
    return _container().panel.stage(ctx.window.id()).zoom


def refocus_from_source(ctx):
    """A keyboard-only reader gets back to the preview with Ctrl+K, V."""
    _record(ctx)
    ctx.window.focus_view(ctx.view)
    _press("ctrl+k v")


def refocused(ctx):
    active = ctx.window.active_view()
    STATE["refocused"] = active is not None and active.id() == _preview(ctx).id()


def in_source(ctx):
    _record(ctx)
    source = ctx.view
    ctx.window.focus_view(source)
    source.sel().clear()
    source.sel().add(0)
    STATE["source_before"] = _top(_preview(ctx))
    _press("Down")


def open_panel(ctx):
    preview = _preview(ctx)
    STATE["source_after"] = _top(preview)
    STATE["caret_row"] = ctx.view.rowcol(ctx.view.sel()[0].begin())[0]
    # Opens the panel and focuses it.
    ctx.run("mdglance_toggle_outline")


def zoom_preview(ctx):
    _record(ctx)
    preview = _preview(ctx)
    ctx.window.focus_view(preview)
    preview.set_viewport_position((0.0, 0.0), False)
    ctx.run("mdglance_zoom", {"delta": 1.0})


def report(ctx):
    _record(ctx)
    ctx.note(
        "Down in the source: preview {} -> {}, caret row {}".format(
            STATE.get("source_before"), STATE.get("source_after"),
            STATE.get("caret_row"),
        )
    )


def check(ctx, snap):
    checks = {}
    for label, expected, actual in STATE["results"]:
        checks["{} lands at {:.1f}".format(label, expected)] = _close(actual, expected)
    checks["Ctrl+K, V in the source focuses the preview"] = STATE.get("refocused")
    checks["Down in the source moves the caret, not the preview"] = (
        STATE.get("caret_row") == 1
        and STATE.get("source_before") == STATE.get("source_after")
    )
    return checks


PHASES = [phase("open", action=start, done=rendered, screenshot=False, timeout=30)]
for index, (keys, expect) in enumerate(STEPS):
    PHASES.append(
        phase(
            "preview-{}".format(index), action=_step(keys, expect, _preview, _preview_zoom),
            done=settled, screenshot=False, timeout=8,
        )
    )
PHASES += [
    phase(
        "refocus", action=refocus_from_source, done=settled, screenshot=False,
        timeout=8,
    ),
    phase("refocused", action=refocused, done=settled, screenshot=False, timeout=8),
    phase("source", action=in_source, done=settled, screenshot=False, timeout=8),
    phase("panel-open", action=open_panel, done=settled, screenshot=False, timeout=8),
    phase(
        "panel-end", action=_step("End", lambda top, m: m["bottom"], _panel, _panel_zoom),
        done=settled, screenshot=False, timeout=8,
    ),
    phase("zoom", action=zoom_preview, done=settled, screenshot=False, timeout=8),
    phase(
        "zoomed-down",
        action=_step("Down", lambda top, m: top + m["line"], _preview, _preview_zoom),
        done=settled, screenshot=False, timeout=8,
    ),
    phase("report", action=report, done=settled, check=check, timeout=8),
]
