"""Smallest scenario: open a document, wait for the preview, screenshot it.

Copy this file to start a new scenario. The checks read the live session, so
a phase can assert on what was rendered, not only on the picture.
"""

from mdglance_probe import phase


def start(ctx):
    ctx.open_fixture("preview.md")


def rendered(ctx, snap):
    return ctx.settled(snap)


def check(ctx, snap):
    return {
        "headings found": snap["headings"] == 3,
        "local image rendered": snap["images"] == 1,
        "no placeholder": snap["block_placeholders"] == 0,
        "no error card": snap["error_cards"] == 0,
    }


PHASES = [phase("preview", action=start, done=rendered, check=check)]
