"""Does the Windows width finding reproduce on Linux?

Windows measured, on a 1920x1080 window with a preview, a table of contents
and an outline all open over `long.md`: table of contents 192 px, outline
72 px, columns `[0.0, 0.5, 0.825, 0.9475, 1.0]` -- the outline taking exactly
`ROLE_SHARE[OUTLINE]` of the *table of contents'* cell rather than of the
source's. This scenario opens the same two fixtures the same way and writes
the same numbers, so the two hosts can be compared directly.

Run with the skill's driver:

    .claude/skills/run-markdownglance/drive.sh <this file>
"""

import os

from mdglance_probe import phase

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linux-fixtures")


def _sheet_name(sheet):
    view = sheet.view()
    if view is None:
        return "(not a view)"
    return view.name() or os.path.basename(view.file_name() or "") or "Untitled"


def layout_report(window):
    layout = window.layout()
    groups = []
    for index in range(window.num_groups()):
        view = window.active_view_in_group(index)
        groups.append(
            {
                "group": index,
                "cell": list(layout["cells"][index]),
                "width_px": round(float(view.viewport_extent()[0]), 1) if view else 0.0,
                "names": [_sheet_name(s) for s in window.sheets_in_group(index)],
            }
        )
    return {
        "cols": [round(value, 6) for value in layout["cols"]],
        "num_groups": window.num_groups(),
        "groups": groups,
    }


def _width_of(window, group):
    view = window.active_view_in_group(group) if group is not None else None
    return round(float(view.viewport_extent()[0]), 1) if view else 0.0


def panels(ctx):
    """Where the table of contents and the outline ended up, and how wide."""
    container = ctx.container()
    session = ctx.session()
    toc_group = (
        container.backend.group_of(session.toc_surface)
        if session is not None and session.toc_surface is not None
        else None
    )
    outline = (
        container.outline.for_source(ctx.window.id(), ctx.view.buffer_id())
        if ctx.view is not None
        else None
    )
    outline_group = (
        container.backend.group_of(outline.surface) if outline is not None else None
    )
    return {
        "toc": {"group": toc_group, "width_px": _width_of(ctx.window, toc_group)},
        "outline": {
            "group": outline_group,
            "width_px": _width_of(ctx.window, outline_group),
            "headings": [h.text for h in outline.headings] if outline else [],
        },
    }


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


def record(name):
    """Write the numbers, and assert the Windows result on this host."""

    def check(ctx, snap):
        report = {"layout": layout_report(ctx.window), "panels": panels(ctx)}
        ctx.write(name + "-widths.json", report)
        cols = report["layout"]["cols"]
        outline_group = report["panels"]["outline"]["group"]
        toc_group = report["panels"]["toc"]["group"]
        share = None
        if len(cols) >= 4:
            # The outline's cell as a fraction of its cell plus the one to its
            # left, which is the table of contents when the finding holds.
            share = (1.0 - cols[-2]) / (1.0 - cols[-3])
        return {
            "table of contents is open": toc_group is not None,
            "outline is open": outline_group is not None,
            "outline sits to the right of the toc": (
                toc_group is not None
                and outline_group is not None
                and outline_group != toc_group
            ),
            "outline took the role share of the toc cell (0.3)": (
                share is not None and abs(share - 0.3) < 0.02
            ),
            "outline is a sliver (<100px)": report["panels"]["outline"]["width_px"] < 100,
            "toc cannot show the long entry (<250px)": (
                report["panels"]["toc"]["width_px"] < 250
            ),
        }

    return check


PHASES = [
    phase(
        "long-both-panels",
        action=open_document("long.md"),
        done=toc_open,
        check=lambda ctx, snap: {"table of contents opened": toc_open(ctx, snap)},
    ),
    phase(
        "long-outline-added",
        action=open_outline,
        done=outline_open,
        check=record("long"),
    ),
]
