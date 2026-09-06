"""Issue #4 after the fix: neither panel is measured against the other.

Before, with a table of contents open, the outline was split out of it and both
collapsed: `short.md` asked for 161 px and 186 px and was given 95 px and
30 px. The outline now splits the source group instead, so each panel borders a
group that is not a panel.

`long.md` is here for the other half of the story: its 84-character heading
asks for 945 px, which `share_for` caps at the role share on purpose, so that
entry still wraps and should.
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

# What `measure.py` says these two documents want, at zoom 1.0.
WANTED = {"short.md": {"toc": 161, "outline": 186}, "long.md": {"toc": 722, "outline": 945}}


def open_document(name):
    def action(ctx):
        ctx.set_setting("MarkdownGlance.sublime-settings", "enable_toc", True)
        ctx.set_setting("MarkdownGlance.sublime-settings", "auto_width", True)
        ctx.view = ctx.window.open_file(os.path.join(FIXTURES, name))
        ctx._preview_pending = True

    return action


def toc_open(ctx, snap):
    session = ctx.session()
    return ctx.settled(snap) and session is not None and session.toc_surface is not None


def open_outline(ctx):
    ctx.window.focus_view(ctx.view)
    ctx.run("mdglance_toggle_outline")


def outline_open(ctx, snap):
    outline = ctx.container().outline.for_source(ctx.window.id(), ctx.view.buffer_id())
    return outline is not None and bool(outline.headings)


def source_group(ctx):
    return ctx.window.get_view_index(ctx.view)[0]


def record(name):
    def check(ctx, snap):
        report = {"layout": layout_report(ctx.window), "panels": panels(ctx)}
        report["source_group"] = source_group(ctx)
        report["wanted"] = WANTED[name]
        ctx.write(name.replace(".md", "") + "-fixed-widths.json", report)

        cells = report["layout"]["groups"]
        outline_group = report["panels"]["outline"]["group"]
        toc_group = report["panels"]["toc"]["group"]
        outline_px = report["panels"]["outline"]["width_px"]
        toc_px = report["panels"]["toc"]["width_px"]
        # The outline's left edge is the source's right edge: it was split out
        # of the source, not out of the table of contents.
        outline_left = cells[outline_group]["cell"][0] if outline_group is not None else None
        source_right = cells[report["source_group"]]["cell"][2]
        checks = {
            "both panels are open": None not in (toc_group, outline_group),
            "the outline borders the source": outline_left == source_right,
            "the outline is not a sliver": outline_px >= 150,
            "the table of contents is not a sliver": toc_px >= 120,
        }
        if name == "short.md":  # noqa: SIM102 - reads better spelled out
            # Both fit inside their role share, so both should get exactly
            # what they asked for, give or take the group's own chrome.
            checks["short headings get the width they ask for"] = (
                abs(outline_px - WANTED[name]["outline"]) <= 40
                and abs(toc_px - WANTED[name]["toc"]) <= 40
            )
        return checks

    return check


# One document per run: a second one opened into the same window lands in
# whichever group has focus -- the outline panel -- and the measurement is then
# of a window nobody would have.
DOCUMENT = os.environ.get("MDG_DOC", "short.md")
STEM = DOCUMENT.replace(".md", "")

PHASES = [
    phase(
        STEM + "-preview",
        action=open_document(DOCUMENT),
        done=toc_open,
        check=lambda ctx, snap: {"table of contents opened": toc_open(ctx, snap)},
    ),
    phase(STEM + "-outline", action=open_outline, done=outline_open, check=record(DOCUMENT)),
]
