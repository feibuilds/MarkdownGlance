"""The same document and the same outline, with no table of contents.

The companion to `linux-widths.py`. If the outline is narrow there simply
because four groups do not fit, it will be narrow here too. If it is narrow
because it is carved out of the table of contents' group, it will be wide
here, since the only group to its left is then the preview's.
"""

import os

from mdglance_probe import phase

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "linux_widths",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "linux-widths.py"),
)
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)

FIXTURES = _shared.FIXTURES
layout_report = _shared.layout_report
panels = _shared.panels


def open_document(ctx):
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", False)
    ctx.set_setting("MarkdownGlance.sublime-settings", "auto_width", True)
    ctx.view = ctx.window.open_file(os.path.join(FIXTURES, "long.md"))
    ctx._preview_pending = True


def no_toc(ctx, snap):
    session = ctx.session()
    return ctx.settled(snap) and session is not None and session.toc_surface is None


def open_outline(ctx):
    ctx.window.focus_view(ctx.view)
    ctx.run("mdglance_toggle_outline")


def outline_open(ctx, snap):
    outline = ctx.container().outline.for_source(ctx.window.id(), ctx.view.buffer_id())
    return outline is not None and bool(outline.headings)


def check(ctx, snap):
    report = {"layout": layout_report(ctx.window), "panels": panels(ctx)}
    ctx.write("no-toc-widths.json", report)
    return {
        "no table of contents": report["panels"]["toc"]["group"] is None,
        "outline is open": report["panels"]["outline"]["group"] is not None,
        "outline is readable (>=150px)": report["panels"]["outline"]["width_px"] >= 150,
        "three groups only": report["layout"]["num_groups"] == 3,
    }


PHASES = [
    phase(
        "no-toc-preview",
        action=open_document,
        done=no_toc,
        check=lambda ctx, snap: {"no table of contents": ctx.session().toc_surface is None},
    ),
    phase("no-toc-outline", action=open_outline, done=outline_open, check=check),
]
