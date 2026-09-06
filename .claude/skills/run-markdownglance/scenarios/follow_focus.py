"""Several documents, one preview: the pane follows the focus.

A window has three groups -- source, preview, panel -- and exactly one preview
tab however many Markdown files are open in it. Each phase focuses one view and
checks that the preview is titled for, and painted with, the focused document;
that the focus stayed where it was put; and which half of the panel is on
screen: the source outline while a source has the focus, the rendered table of
contents while a preview has it.

The last phase opens a third document as a plain file, with no preview ever
opened for it, which is the case the report came in as.
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


def _preview_body(ctx):
    """The HTML on the one preview surface, so the *document* can be checked
    rather than only the tab's name."""
    from MarkdownGlance.preview.adapter.container import container

    stage = container.manager.stage(ctx.window.id())
    if stage is None or stage.surface is None:
        return ""
    return container.backend._html.get(stage.surface.id, "")


def _panel_body(ctx):
    from MarkdownGlance.preview.adapter.container import container

    stage = container.panel.stage(ctx.window.id())
    if stage is None or stage.surface is None:
        return ""
    return container.backend._html.get(stage.surface.id, "")


def _half(ctx):
    """Which half the panel is painted with, read off its HTML.

    Matched on the opening tag, not the bare class name: the panel stylesheet
    carries rules for both halves whichever one is drawn.
    """
    html = _panel_body(ctx)
    if '<div class="table-of-contents' in html:
        return "contents"
    return "outline" if '<div class="source-outline' in html else None


def _fronts(ctx, document, half):
    title = document.split("-")[-1].capitalize() + " document"
    return {
        "one preview tab": len(_by_role(ctx, "preview")) == 1,
        "one panel tab": len(_by_role(ctx, "panel")) == 1,
        "preview is titled {}".format(document): _front(ctx, "preview")
        == "Preview: {}.md".format(document),
        "preview is painted with {}".format(document): title in _preview_body(ctx),
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
    ctx.window.focus_view(list(_by_role(ctx, "panel").values())[0])


def focus_the_preview(ctx):
    ctx.window.focus_view(list(_by_role(ctx, "preview").values())[0])


def open_gamma(ctx):
    """A third document, opened as a plain file: no preview of its own."""
    import os.path

    ctx.window.focus_view(STATE["beta"])
    STATE["gamma"] = ctx.window.open_file(
        os.path.join(ctx.fixtures, "toc-gamma.md")
    )


def gamma_followed(ctx, snap):
    return (
        not STATE["gamma"].is_loading()
        and _front(ctx, "preview") == "Preview: toc-gamma.md"
        and _front(ctx, "panel") == "Contents: toc-gamma.md"
        and "Gamma document" in _preview_body(ctx)
        and "Gamma one" in _panel_body(ctx)
    )


def check_gamma(ctx, snap):
    checks = _fronts(ctx, "toc-gamma", "outline")
    checks.update(_focus_held(ctx, STATE["gamma"]))
    checks.update(
        {
            "three documents, still one preview tab": (
                len(_by_role(ctx, "preview")) == 1
            ),
            "three documents, still one panel tab": (
                len(_by_role(ctx, "panel")) == 1
            ),
            "still three groups": len(ctx.window.layout()["cells"]) == 3,
        }
    )
    return checks


def rendered(ctx, snap):
    return ctx.settled(snap)


def both_open(ctx, snap):
    return ctx.settled(snap) and len(_by_role(ctx, "panel")) == 1


def check_beta_front(ctx, snap):
    checks = {
        "two documents, one preview tab": len(_by_role(ctx, "preview")) == 1,
        "two documents, one panel tab": len(_by_role(ctx, "panel")) == 1,
        "three groups, not four": len(ctx.window.layout()["cells"]) == 3,
    }
    checks.update(_fronts(ctx, "toc-beta", "contents"))
    return checks


def check_alpha_front(ctx, snap):
    checks = _fronts(ctx, "toc-alpha", "outline")
    checks.update(_focus_held(ctx, STATE["alpha"]))
    return checks


def check_alpha_from_panel(ctx, snap):
    checks = _fronts(ctx, "toc-alpha", "outline")
    checks.update(_focus_held(ctx, list(_by_role(ctx, "panel").values())[0]))
    return checks


def check_preview_keeps_its_document(ctx, snap):
    """Focusing the preview does not change what is on it.

    There is one preview and it belongs to the document the window is on, so
    clicking it is a request to read that document, not to swap it. What does
    change is the panel: the preview has the focus, so it shows the rendered
    table of contents rather than the source outline.
    """
    checks = _fronts(ctx, "toc-alpha", "contents")
    checks.update(_focus_held(ctx, list(_by_role(ctx, "preview").values())[0]))
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
        "preview-focused",
        action=focus_the_preview,
        done=both_open,
        check=check_preview_keeps_its_document,
    ),
    phase(
        "gamma-opened",
        action=open_gamma,
        done=gamma_followed,
        check=check_gamma,
    ),
]
