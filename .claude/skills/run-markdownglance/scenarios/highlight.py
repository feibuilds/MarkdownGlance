"""Fenced code in the editor's own colours (issue #7, ADR 0021).

Phases: render under the dark default scheme and see the fences that name a
language coloured and the others plain; switch to a light scheme and see the
code coloured again in it; copy diagnostics; turn highlighting off and see
every fence plain.
"""

import re

from mdglance_probe import phase

LIGHT_SCHEME = "Breakers.sublime-color-scheme"
SPAN = re.compile(r'<span style="([^"]*)">')
PANEL = "output.mdglance-highlight"


def _pres(snap):
    return re.findall(r"<pre>(.*?)</pre>", snap["body_html"], re.S)


def _colours(snap):
    return {
        match.group(1)
        for match in re.finditer(r"color: (#[0-9a-f]+)", snap["body_html"])
    }


def _highlighted(ctx):
    session = ctx.session()
    document = session.last_document if session is not None else None
    return bool(document is not None and document.highlighted)


def _panel_left_behind(ctx):
    return PANEL in ctx.window.panels()


def start(ctx):
    ctx.open_fixture("highlight.md")


def rendered(ctx, snap):
    return ctx.settled(snap) and bool(SPAN.search(snap["body_html"]))


def check_dark(ctx, snap):
    pres = _pres(snap)
    return {
        "eight blocks": len(pres) == 8,
        "six named languages coloured": all(SPAN.search(pre) for pre in pres[:6]),
        "no language and unknown language plain": not any(
            SPAN.search(pre) for pre in pres[6:]
        ),
        "keyword is styled": re.search(r'<span style="[^"]*">def ', pres[0])
        is not None,
        "inner backticks stay in the block": "```" in pres[5]
        and "not the end of the block" in pres[5],
        "several colours": len(_colours(snap)) >= 4,
        "document marked highlighted": _highlighted(ctx),
        "no panel left behind": not _panel_left_behind(ctx),
        "no error card": snap["error_cards"] == 0,
    }


class LightScheme:
    """Remembers the dark run's colours so the light run can be compared."""

    before = set()


def remember_then_switch(ctx):
    LightScheme.before = _colours(ctx.snapshot())
    ctx.set_setting("Preferences.sublime-settings", "color_scheme", LIGHT_SCHEME)


def recoloured(ctx, snap):
    return (
        ctx.settled(snap)
        and not snap["theme"]["is_dark"]
        and _colours(snap) != LightScheme.before
    )


def check_light(ctx, snap):
    return {
        "scheme is light": not snap["theme"]["is_dark"],
        "code coloured again": bool(_colours(snap))
        and _colours(snap) != LightScheme.before,
        "still six coloured blocks": sum(
            bool(SPAN.search(pre)) for pre in _pres(snap)
        )
        == 6,
    }


class Diagnostics:
    clipboard = ""


def copy_diagnostics(ctx):
    ctx.run("mdglance_copy_diagnostics")
    Diagnostics.clipboard = ctx.clipboard()


def check_diagnostics(ctx, snap):
    clip = Diagnostics.clipboard
    return {
        "setting reported": '"enable_syntax_highlighting": true' in clip,
        "no highlighter error": '"highlighter_error": null' in clip,
    }


def highlighting_off(ctx):
    ctx.set_setting(
        "MarkdownGlance.sublime-settings", "enable_syntax_highlighting", False
    )


def plain(ctx, snap):
    return ctx.settled(snap) and not SPAN.search(snap["body_html"])


def check_off(ctx, snap):
    return {
        "no styled run": not SPAN.search(snap["body_html"]),
        "eight blocks still": len(_pres(snap)) == 8,
        "document not marked highlighted": not _highlighted(ctx),
    }


PHASES = [
    phase("dark", action=start, done=rendered, check=check_dark),
    phase("light", action=remember_then_switch, done=recoloured, check=check_light),
    phase(
        "diagnostics",
        action=copy_diagnostics,
        check=check_diagnostics,
        screenshot=False,
    ),
    phase("off", action=highlighting_off, done=plain, check=check_off),
]
