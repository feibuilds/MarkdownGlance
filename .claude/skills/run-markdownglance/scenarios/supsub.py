"""Raw <sup> and <sub> drawn as raised and lowered spans; judged from the picture."""

from mdglance_probe import phase


def start(ctx):
    ctx.open_fixture("supsub.md")


def rendered(ctx, snap):
    return ctx.settled(snap)


def check(ctx, snap):
    return {
        "headings found": snap["headings"] == 2,
        "no error card": snap["error_cards"] == 0,
    }


PHASES = [phase("supsub", action=start, done=rendered, check=check)]
