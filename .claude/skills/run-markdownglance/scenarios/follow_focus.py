"""Two documents previewed at once: the front tabs follow the focus.

Every session stacks its preview in one group and its table of contents in
another, so without `UseCases.reveal_surfaces` the tabs left in front are
whichever document was previewed last, and they stay there while the user
reads the other file. Each phase focuses one of the six views and reads the
name of whatever Sublime has at the front of the two shared groups -- and
checks that the focus stayed where it was put, since `reveal` moves it away
and back again.
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


def _fronts(ctx, document):
    return {
        "preview in front is {}".format(document): _front(ctx, "preview")
        == "Preview: {}.md".format(document),
        "contents in front is {}".format(document): _front(ctx, "toc")
        == "TOC: {}.md".format(document),
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


def focus_alpha_contents(ctx):
    ctx.window.focus_view(_by_role(ctx, "toc")["TOC: toc-alpha.md"])


def focus_beta_preview(ctx):
    ctx.window.focus_view(_by_role(ctx, "preview")["Preview: toc-beta.md"])


def rendered(ctx, snap):
    return ctx.settled(snap)


def both_open(ctx, snap):
    return ctx.settled(snap) and len(_by_role(ctx, "toc")) == 2


def check_beta_front(ctx, snap):
    checks = {
        "two previews": len(_by_role(ctx, "preview")) == 2,
        "two tables of contents": len(_by_role(ctx, "toc")) == 2,
        "one group holds the previews": len(_groups(ctx, "preview")) == 1,
        "one group holds the tables of contents": len(_groups(ctx, "toc")) == 1,
    }
    checks.update(_fronts(ctx, "toc-beta"))
    return checks


def check_alpha_front(ctx, snap):
    checks = _fronts(ctx, "toc-alpha")
    checks.update(_focus_held(ctx, STATE["alpha"]))
    return checks


def check_alpha_from_contents(ctx, snap):
    checks = _fronts(ctx, "toc-alpha")
    checks.update(_focus_held(ctx, _by_role(ctx, "toc")["TOC: toc-alpha.md"]))
    return checks


def check_beta_from_preview(ctx, snap):
    checks = _fronts(ctx, "toc-beta")
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
        "alpha-contents-focused",
        action=focus_alpha_contents,
        done=both_open,
        check=check_alpha_from_contents,
    ),
    phase(
        "beta-preview-focused",
        action=focus_beta_preview,
        done=both_open,
        check=check_beta_from_preview,
    ),
]
