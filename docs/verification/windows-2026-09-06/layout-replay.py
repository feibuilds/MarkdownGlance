#!/usr/bin/env python3
"""Replay the group splits the Windows run measured, using the real layout code.

The widths measured in the guest could in principle be a Windows font or DPI
artefact. They are not: `presentation/layout.py` is pure arithmetic over
fractions of the window, and replaying the same three splits here reproduces
the same columns the guest reported. Run from the parent of the checkout:

    python3 -m MarkdownGlance.docs.verification.windows_2026_09_06.layout_replay

or just `python3 layout-replay.py` from this directory.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..", "..")))

from MarkdownGlance.preview.application.ports import GroupRole  # noqa: E402
from MarkdownGlance.preview.presentation.layout import (  # noqa: E402
    ROLE_SHARE,
    rightmost_in_row,
    share_for,
    split_cell,
)

WINDOW_PX = 1920.0
SINGLE = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}


def width_px(layout, group):
    c0, _, c1, _ = layout["cells"][group]
    return (layout["cols"][c1] - layout["cols"][c0]) * WINDOW_PX


def main():
    layout = SINGLE
    print("start                       cols={}".format(layout["cols"]))

    # The preview splits the source group; nothing is measured yet, so it takes
    # the role's default share.
    layout, preview = split_cell(layout, 0, ROLE_SHARE[GroupRole.PREVIEW])
    print("preview beside source       cols={}".format([round(c, 4) for c in layout["cols"]]))

    # The table of contents splits the preview's group.
    toc_wanted = 235.0  # what the guest's estimate asked for, in pixels
    share = share_for(GroupRole.TOC, toc_wanted, width_px(layout, preview))
    layout, toc = split_cell(layout, preview, share)
    print(
        "toc beside preview          cols={}  toc={:.0f}px".format(
            [round(c, 4) for c in layout["cols"]], width_px(layout, toc)
        )
    )

    # The outline anchors on the source group -- and `acquire_beside` walks
    # right from there to the last group in the row, which is now the table of
    # contents. So the outline is carved out of the narrowest group in the
    # window rather than out of the source.
    anchor = rightmost_in_row(layout, 0)
    print("outline anchor group        {} ({})".format(anchor, "the TOC" if anchor == toc else "the source"))
    outline_wanted = 300.0
    share = share_for(GroupRole.OUTLINE, outline_wanted, width_px(layout, anchor))
    layout, outline = split_cell(layout, anchor, share)
    print(
        "outline beside toc          cols={}".format([round(c, 4) for c in layout["cols"]])
    )
    print(
        "final                       source={:.0f}px preview={:.0f}px toc={:.0f}px outline={:.0f}px".format(
            width_px(layout, 0),
            width_px(layout, preview),
            width_px(layout, toc),
            width_px(layout, outline),
        )
    )
    # The exact columns depend on what the width estimate asked for, which is
    # font-dependent and therefore differs between hosts. The shape does not:
    # whatever the table of contents ends up with, the outline takes the role
    # share of *that*, not of the source group.
    toc_cell = layout["cols"][layout["cells"][toc][2]] - layout["cols"][layout["cells"][toc][0]]
    outline_cell = (
        layout["cols"][layout["cells"][outline][2]]
        - layout["cols"][layout["cells"][outline][0]]
    )
    print()
    print(
        "outline cell / (toc + outline cell) = {:.3f}, the outline role share {}".format(
            outline_cell / (toc_cell + outline_cell), ROLE_SHARE[GroupRole.OUTLINE]
        )
    )
    print("The guest measured cols [0.0, 0.5, 0.825, 0.9475, 1.0]: the same shape,")
    print("with 0.9475 = 1 - (1 - 0.825) * 0.3. Nothing above reads a font, a DPI")
    print("or a platform, so this is not a Windows-only result.")


if __name__ == "__main__":
    main()
