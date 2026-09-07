"""Clicking a panel entry takes the reader to that section in *both* panes.

A preview is read by scrolling, and the wheel does not move the focus, so the
reader is looking at the preview while the source still has the focus and the
panel is showing the outline. Clicking an outline entry used to move only the
caret, and the jump the reader wanted never happened.

Both halves navigate both panes now. This drives each half in turn and reads
the caret and the preview's viewport, with the focus deliberately left on the
half that is *not* the one being asked to move the other pane.
"""

import os.path

from mdglance_probe import phase

STATE = {}


def _panel_stage(ctx):
    from MarkdownGlance.preview.adapter.container import container

    return container.panel.stage(ctx.window.id())


def _preview_view(ctx):
    from MarkdownGlance.preview.adapter.container import container

    stage = container.manager.stage(ctx.window.id())
    if stage is None or stage.surface is None:
        return None
    return next(
        (view for view in ctx.window.views() if view.id() == stage.surface.id), None
    )


def _preview_top(ctx):
    view = _preview_view(ctx)
    return view.viewport_position()[1] if view is not None else 0.0


def _caret_row(ctx):
    view = STATE["source"]
    return view.rowcol(view.sel()[0].begin())[0]


def _entries(ctx):
    """The panel's headings, from the record it is showing."""
    from MarkdownGlance.preview.adapter.container import container

    stage = _panel_stage(ctx)
    record = container.panel.showing(stage) if stage is not None else None
    return record


def start(ctx):
    ctx.run("close_all")
    ctx.window.set_layout(
        {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
    )
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", True)
    ctx.set_setting("MarkdownGlance.sublime-settings", "toc_minimum_length", 1)
    ctx.set_setting("MarkdownGlance.sublime-settings", "toc_minimum_headings", 1)
    ctx.open_fixture("toc-long.md")


def rendered(ctx, snap):
    return snap.get("generation") is not None and _panel_stage(ctx) is not None


def aim(ctx):
    STATE["source"] = ctx.view
    # The reader's real position: looking at the preview, focus on the source,
    # so the panel is on its outline half.
    ctx.window.focus_view(ctx.view)
    record = _entries(ctx)
    STATE["headings"] = [
        (item.ordinal, item.text, item.line) for item in record.headings
    ]
    STATE["aligned"] = dict(record.links.to_slug)
    ctx.note("{} headings, {} aligned".format(
        len(STATE["headings"]), len(STATE["aligned"])))


def on_outline(ctx, snap):
    stage = _panel_stage(ctx)
    return stage is not None and not stage.showing_preview


def click_outline_entry(ctx):
    """Section 30, deep enough that both panes have to move a long way."""
    from MarkdownGlance.preview.adapter.container import container

    STATE["before_caret"] = _caret_row(ctx)
    STATE["before_top"] = _preview_top(ctx)
    ordinal, text, line = STATE["headings"][30]
    STATE["target"] = (ordinal, text, line)
    container.panel.navigate(ctx.window, _panel_stage(ctx).action_token, line=line)


def moved(ctx, snap):
    return True


def check_outline_click(ctx, snap):
    STATE["after_caret"] = _caret_row(ctx)
    STATE["after_top"] = _preview_top(ctx)
    ctx.note("outline click: caret {} -> {}, preview {} -> {}".format(
        STATE["before_caret"], STATE["after_caret"],
        STATE["before_top"], STATE["after_top"]))
    return {
        "every heading aligned": len(STATE["aligned"]) == len(STATE["headings"]),
        "the panel was on its outline half": True,
        "the caret went to the section": STATE["after_caret"] == STATE["target"][2],
        "and so did the preview": STATE["after_top"] > STATE["before_top"],
        "the focus stayed on the source": (
            ctx.window.active_view().id() == STATE["source"].id()
        ),
    }


def click_contents_entry(ctx):
    """Now the other half, from the preview, back up to section 2."""
    from MarkdownGlance.preview.adapter.container import container

    ctx.window.focus_view(_preview_view(ctx))
    STATE["before_caret2"] = _caret_row(ctx)
    STATE["before_top2"] = _preview_top(ctx)
    ordinal, text, line = STATE["headings"][2]
    STATE["target2"] = (ordinal, text, line)
    slug = STATE["aligned"][ordinal]
    container.panel.navigate(ctx.window, _panel_stage(ctx).action_token, slug=slug)


def check_contents_click(ctx, snap):
    ctx.note("contents click: caret {} -> {}, preview {} -> {}".format(
        STATE["before_caret2"], _caret_row(ctx),
        STATE["before_top2"], _preview_top(ctx)))
    return {
        "the panel was on its contents half": _panel_stage(ctx).showing_preview,
        "the preview went back up": _preview_top(ctx) < STATE["before_top2"],
        "and the caret came with it": _caret_row(ctx) == STATE["target2"][2],
        "the focus stayed on the preview": (
            ctx.window.active_view().id() == _preview_view(ctx).id()
        ),
    }


PHASES = [
    phase("open", action=start, done=rendered, screenshot=False, timeout=30),
    phase("aim", action=aim, done=on_outline, screenshot=False, timeout=10),
    phase(
        "outline-entry-clicked",
        action=click_outline_entry,
        done=moved,
        check=check_outline_click,
        timeout=10,
    ),
    phase(
        "contents-entry-clicked",
        action=click_contents_entry,
        done=moved,
        check=check_contents_click,
        timeout=10,
    ),
]
