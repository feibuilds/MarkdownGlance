"""Two documents previewed at once: the panels follow the focus.

A document has three groups -- source, preview, panel -- and every document in
the window shares each of them, so the tabs left in front would otherwise
belong to whichever was previewed last. Each phase focuses one view and reads
the name of whatever Sublime has at the front of the two shared groups, checks
that the focus stayed where it was put (`reveal` moves it away and back), and
checks which half of the panel is on screen: the source outline while a source
has the focus, the rendered table of contents while a preview has it.
"""

from mdglance_probe import phase

STATE = {}


def _by_role(ctx, role):
    """Every plugin-owned view of one role in the window, by name."""
    from MarkdownGlance.preview.presentation.phantom_view import ROLE_KEY

    return {
        view.name(): view
        for view in ctx.window.views()
        if view.settings().get(ROLE_KEY) == role
    }


def _groups(ctx, role):
    return {ctx.window.get_view_index(view)[0] for view in _by_role(ctx, role).values()}


def _front(ctx, role):
    """The name of the view of that role the user can actually see."""
    groups = _groups(ctx, role)
    if len(groups) != 1:
        return None
    active = ctx.window.active_view_in_group(groups.pop())
    return active.name() if active is not None else None


def _half(ctx):
    """Which half the panel in front is painted with, read off its HTML.

    Matched on the opening tag, not the bare class name: the panel stylesheet
    carries rules for both halves whichever one is drawn.
    """
    from MarkdownGlance.preview.adapter.container import container

    view = _by_role(ctx, "panel").get(_front(ctx, "panel"))
    panel = container.panel.for_surface(view.id()) if view is not None else None
    html = container.backend._html.get(panel.surface.id, "") if panel else ""
    if '<div class="table-of-contents' in html:
        return "contents"
    return "outline" if '<div class="source-outline' in html else None


def _fronts(ctx, document, half):
    return {
        "preview in front is {}".format(document): _front(ctx, "preview")
        == "Preview: {}.md".format(document),
        "panel in front is {}".format(document): _front(ctx, "panel")
        == "Contents: {}.md".format(document),
        "panel shows the {}".format(half): _half(ctx) == half,
    }


def _focus_held(ctx, view):
    return {"focus stayed put": ctx.window.active_view() == view}


def open_alpha(ctx):
    # The profile remembers its layout, so start from one empty cell or the
    # groups here are the ones the previous run left behind.
    ctx.run("close_all")
    ctx.window.set_layout(
        {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}
    )
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", True)
    ctx.set_setting("MarkdownGlance.sublime-settings", "toc_minimum_length", 1)
    ctx.set_setting("MarkdownGlance.sublime-settings", "toc_minimum_headings", 1)
    ctx.open_fixture("toc-alpha.md")


def open_beta(ctx):
    STATE["alpha"] = ctx.view
    # Opening the preview left the focus on it; without this the second source
    # would open in the preview's group rather than beside the first source.
    ctx.window.focus_view(STATE["alpha"])
    ctx.open_fixture("toc-beta.md")


def focus_alpha_source(ctx):
    STATE["beta"] = ctx.view
    ctx.window.focus_view(STATE["alpha"])


def focus_alpha_panel(ctx):
    ctx.window.focus_view(_by_role(ctx, "panel")["Contents: toc-alpha.md"])


def focus_beta_preview(ctx):
    ctx.window.focus_view(_by_role(ctx, "preview")["Preview: toc-beta.md"])


def rendered(ctx, snap):
    return ctx.settled(snap)


def both_open(ctx, snap):
    return ctx.settled(snap) and len(_by_role(ctx, "panel")) == 2


def check_beta_front(ctx, snap):
    checks = {
        "two previews": len(_by_role(ctx, "preview")) == 2,
        "two panels": len(_by_role(ctx, "panel")) == 2,
        "one group holds the previews": len(_groups(ctx, "preview")) == 1,
        "one group holds the panels": len(_groups(ctx, "panel")) == 1,
        "three groups per document, not four": len(ctx.window.layout()["cells"]) == 3,
    }
    checks.update(_fronts(ctx, "toc-beta", "contents"))
    return checks


def check_alpha_front(ctx, snap):
    checks = _fronts(ctx, "toc-alpha", "outline")
    checks.update(_focus_held(ctx, STATE["alpha"]))
    return checks


def check_alpha_from_panel(ctx, snap):
    checks = _fronts(ctx, "toc-alpha", "outline")
    checks.update(
        _focus_held(ctx, _by_role(ctx, "panel")["Contents: toc-alpha.md"])
    )
    return checks


def check_beta_from_preview(ctx, snap):
    checks = _fronts(ctx, "toc-beta", "contents")
    checks.update(_focus_held(ctx, _by_role(ctx, "preview")["Preview: toc-beta.md"]))
    return checks


PHASES = [
    phase("alpha-only", action=open_alpha, done=rendered),
    phase("beta-opened", action=open_beta, done=both_open, check=check_beta_front),
    phase(
        "alpha-source-focused",
        action=focus_alpha_source,
        done=both_open,
        check=check_alpha_front,
    ),
    phase(
        "alpha-panel-focused",
        action=focus_alpha_panel,
        done=both_open,
        check=check_alpha_from_panel,
    ),
    phase(
        "beta-preview-focused",
        action=focus_beta_preview,
        done=both_open,
        check=check_beta_from_preview,
    ),
]
