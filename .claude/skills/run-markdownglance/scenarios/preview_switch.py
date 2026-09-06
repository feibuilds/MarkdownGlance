"""One preview surface, two documents, and the scroll position of each.

With a surface per document Sublime kept each one's viewport for free. With one
surface the position has to be saved and put back by hand, as a fraction of the
document's height rather than a pixel -- the document is laid out again at
whatever width and zoom the pane has when it returns -- and the restore has to
wait a tick, because `layout_extent` straight after a repaint can still
describe the phantom that was there before.

This drives that: scroll the long document, switch to the short one, switch
back, and read the viewport.
"""

import os.path

from mdglance_probe import phase

STATE = {}


def _stage(ctx):
    from MarkdownGlance.preview.adapter.container import container

    return container.manager.stage(ctx.window.id())


def _surface_view(ctx):
    stage = _stage(ctx)
    if stage is None or stage.surface is None:
        return None
    return next(
        (view for view in ctx.window.views() if view.id() == stage.surface.id), None
    )


def _position(ctx):
    view = _surface_view(ctx)
    return view.viewport_position()[1] if view is not None else 0.0


def _height(ctx):
    view = _surface_view(ctx)
    return view.layout_extent()[1] if view is not None else 0.0


def _showing(ctx):
    stage = _stage(ctx)
    view = _surface_view(ctx)
    return view.name() if view is not None else None


def open_long(ctx):
    ctx.run("close_all")
    ctx.window.set_layout(
        {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
    )
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", False)
    ctx.open_fixture("toc-long.md")


def open_short(ctx):
    STATE["long"] = ctx.view
    ctx.window.focus_view(STATE["long"])
    ctx.open_fixture("toc-alpha.md")


def scroll_the_long_one(ctx):
    STATE["short"] = ctx.view
    ctx.window.focus_view(STATE["long"])


def scroll(ctx):
    view = _surface_view(ctx)
    STATE["target"] = _height(ctx) * 0.5
    view.set_viewport_position((0.0, STATE["target"]), False)


def switch_away(ctx):
    ctx.window.focus_view(STATE["short"])


def switch_back(ctx):
    ctx.window.focus_view(STATE["long"])


def rendered(ctx, snap):
    return snap.get("generation") is not None


def showing_long(ctx, snap):
    return _showing(ctx) == "Preview: toc-long.md" and _height(ctx) > 0


def showing_short(ctx, snap):
    return _showing(ctx) == "Preview: toc-alpha.md"


def scrolled(ctx, snap):
    return _position(ctx) > 0.0


def check_scrolled(ctx, snap):
    STATE["scrolled_to"] = _position(ctx)
    return {
        "the long document scrolled": STATE["scrolled_to"] > 0.0,
        "one preview surface": _stage(ctx) is not None,
    }


def check_short(ctx, snap):
    STATE["short_position"] = _position(ctx)
    return {
        "the short document is on the surface": showing_short(ctx, snap),
        "it starts at the top, not where the other was": (
            STATE["short_position"] < STATE["scrolled_to"] / 2
        ),
    }


def check_restored(ctx, snap):
    back = _position(ctx)
    STATE["back"] = back
    return {
        "the long document is back": showing_long(ctx, snap),
        "and so is where it was scrolled to": (
            abs(back - STATE["scrolled_to"]) < max(20.0, STATE["scrolled_to"] * 0.05)
        ),
    }


PHASES = [
    phase("long", action=open_long, done=rendered, screenshot=False, timeout=30),
    phase("short", action=open_short, done=rendered, screenshot=False, timeout=30),
    phase(
        "back-to-long",
        action=scroll_the_long_one,
        done=showing_long,
        screenshot=False,
        timeout=30,
    ),
    phase("scrolled", action=scroll, done=scrolled, check=check_scrolled, timeout=30),
    phase(
        "switched-away",
        action=switch_away,
        done=showing_short,
        check=check_short,
        timeout=30,
    ),
    phase(
        "switched-back",
        action=switch_back,
        done=showing_long,
        check=check_restored,
        timeout=30,
    ),
]
