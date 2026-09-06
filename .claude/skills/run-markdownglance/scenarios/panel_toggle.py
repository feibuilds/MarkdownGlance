"""The panel opened by hand, over a file with no preview at all.

`enable_toc` is off throughout, which is its default: it governs whether a
panel opens *by itself*, never what one the user asked for is allowed to show.
So the panel here opens on the source outline beside a file that has never
been rendered, gains its table-of-contents half the moment a preview appears
behind it, and closes on the third press of the toggle.

It is also the layout scenario. Opening the panel first is what makes the
preview split a second group rather than land inside the panel's, and what
makes closing the panel a cell removed from the middle of the window rather
than a layout put back; the last two phases count the groups after each.
"""

import os.path

from mdglance_probe import phase

STATE = {}


def _panels(ctx):
    from MarkdownGlance.preview.presentation.phantom_view import ROLE_KEY

    return [
        view
        for view in ctx.window.views()
        if view.settings().get(ROLE_KEY) == "panel"
    ]


def _half(ctx):
    """Which half the panel is painted with, read off its last paint.

    Matched on the opening tag, not the bare class name: the panel stylesheet
    carries rules for both halves whichever one is drawn.
    """
    from MarkdownGlance.preview.adapter.container import container

    stage = container.panel.stage(ctx.window.id())
    html = (
        container.backend._html.get(stage.surface.id, "")
        if stage is not None and stage.surface is not None
        else ""
    )
    if '<div class="table-of-contents' in html:
        return "contents"
    return "outline" if '<div class="source-outline' in html else None


def _groups(ctx):
    return len(ctx.window.layout()["cells"])


def open_source(ctx):
    ctx.run("close_all")
    ctx.window.set_layout(
        {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
    )
    # Off, as it ships. The toggle must not care.
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", False)
    # Opened without `open_fixture`, which would open the preview too.
    STATE["source"] = ctx.window.open_file(
        os.path.join(ctx.fixtures, "toc-alpha.md")
    )


def loaded(ctx, snap):
    return not STATE["source"].is_loading()


def toggle_on(ctx):
    ctx.window.focus_view(STATE["source"])
    ctx.run("mdglance_toggle_outline")


def open_preview(ctx):
    ctx.window.focus_view(STATE["source"])
    ctx.run("mdglance_open_side_by_side")


def toggle_off(ctx):
    ctx.window.focus_view(_panels(ctx)[0])
    ctx.run("mdglance_toggle_outline")


def panel_open(ctx, snap):
    return len(_panels(ctx)) == 1


def panel_gone(ctx, snap):
    return not _panels(ctx)


def rendered(ctx, snap):
    return len(_panels(ctx)) == 1 and _half(ctx) == "contents"


def check_outline_only(ctx, snap):
    return {
        "one panel": len(_panels(ctx)) == 1,
        "named for the document": _panels(ctx)[0].name() == "Contents: toc-alpha.md",
        "shows the outline": _half(ctx) == "outline",
        "no preview was opened": snap.get("session") is not True,
        "two groups": _groups(ctx) == 2,
    }


def check_contents_half(ctx, snap):
    return {
        "still one panel": len(_panels(ctx)) == 1,
        "shows the contents with the setting off": _half(ctx) == "contents",
        "three groups": _groups(ctx) == 3,
    }


def check_closed(ctx, snap):
    from MarkdownGlance.preview.adapter.container import container

    stage = container.manager.stage(ctx.window.id())
    return {
        "the panel is gone": not _panels(ctx),
        "its group went with it": _groups(ctx) == 2,
        "no empty pane is left": all(
            ctx.window.views_in_group(group) for group in range(_groups(ctx))
        ),
        "the source is still in the first group": (
            ctx.window.get_view_index(STATE["source"])[0] == 0
        ),
        "the preview came with its group": (
            container.backend.group_of(stage.surface) == 1
        ),
    }


def close_preview(ctx):
    from MarkdownGlance.preview.adapter.container import container

    STATE["preview"] = container.manager.stage(ctx.window.id()).surface.id
    ctx.window.run_command("close_by_index", {"group": 1, "index": 0})


def preview_gone(ctx, snap):
    return not any(view.id() == STATE["preview"] for view in ctx.window.views())


def check_one_group(ctx, snap):
    return {
        "the preview is gone": preview_gone(ctx, snap),
        "the window is back to one group": _groups(ctx) == 1,
        "the source is still open": STATE["source"] in ctx.window.views(),
    }


PHASES = [
    phase("source-only", action=open_source, done=loaded, screenshot=False),
    phase("panel-toggled-on", action=toggle_on, done=panel_open, check=check_outline_only),
    phase("preview-opened", action=open_preview, done=rendered, check=check_contents_half),
    phase("panel-toggled-off", action=toggle_off, done=panel_gone, check=check_closed),
    phase(
        "preview-closed",
        action=close_preview,
        done=preview_gone,
        check=check_one_group,
    ),
]
