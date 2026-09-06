"""LaTeX math: manual test plan step 7, the Math paragraph, unattended.

Phases: render with math on under the dark default scheme; switch to a light
scheme and see every formula fetched again in the new foreground; copy
diagnostics and check nothing of a formula is in them; turn math off and see
the formulas read as source.
"""

from mdglance_probe import phase

LIGHT_SCHEME = "Breakers.sublime-color-scheme"
FORMULA_TOKENS = ("a^2", "frac", "int_0", "alpha", "codecogs.com/png")


def start(ctx):
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_math", True)
    ctx.open_fixture("math.md")


def rendered(ctx, snap):
    return ctx.settled(snap) and snap["images"] > 0


def check_on(ctx, snap):
    colours = {asset["colour"] for asset in snap["assets"]}
    return {
        "three formulas are images": snap["images"] == 3,
        "invalid formula is an inline placeholder": snap["inline_placeholders"] == 1
        and snap["unavailable"] == 1,
        "privacy caption shown once": snap["privacy_captions"] == 1,
        "four math assets": len(snap["assets"]) == 4
        and all(a["host"].endswith("/png.image") for a in snap["assets"]),
        "one display formula": sum(a["display"] for a in snap["assets"]) == 1,
        "all in one foreground colour": len(colours) == 1,
        "prices and code are not math": "costs $5 and $6" in snap["body_html"]
        and "<code>$x$</code>" in snap["body_html"],
        "no error card": snap["error_cards"] == 0,
    }


class LightScheme:
    """Remembers the dark run's assets so the light run can be compared."""

    before = None


def remember_then_switch(ctx):
    LightScheme.before = ctx.snapshot()["assets"]
    ctx.set_setting("Preferences.sublime-settings", "color_scheme", LIGHT_SCHEME)


def refetched(ctx, snap):
    return ctx.settled(snap) and snap["assets"] != LightScheme.before


def check_light(ctx, snap):
    colours = {asset["colour"] for asset in snap["assets"]}
    labels_before = {asset["label"] for asset in LightScheme.before or []}
    labels_after = {asset["label"] for asset in snap["assets"]}
    return {
        "scheme is light": not snap["theme"]["is_dark"],
        "every formula fetched again": labels_before.isdisjoint(labels_after)
        and len(labels_after) == 4,
        "new foreground colour": len(colours) == 1
        and colours != {a["colour"] for a in LightScheme.before or []},
        "still three images": snap["images"] == 3,
    }


class Diagnostics:
    clipboard = ""


def copy_diagnostics(ctx):
    ctx.run("mdglance_copy_diagnostics")
    Diagnostics.clipboard = ctx.clipboard()


def check_diagnostics(ctx, snap):
    clip = Diagnostics.clipboard
    return {
        "diagnostics copied": '"enable_math": true' in clip,
        "no formula in diagnostics": not any(t in clip for t in FORMULA_TOKENS),
    }


def math_off(ctx):
    ctx.set_setting("MarkdownGlance.sublime-settings", "enable_math", False)


def shown_as_source(ctx, snap):
    return snap["code_math"] > 0 and snap["images"] == 0


def check_off(ctx, snap):
    return {
        "four formulas as code": snap["code_math"] == 4,
        "no assets": not snap["assets"],
        "display block is pre": '<pre><code class="math">' in snap["body_html"],
    }


PHASES = [
    phase("math-on", action=start, done=rendered, check=check_on),
    phase(
        "light-scheme",
        action=remember_then_switch,
        done=refetched,
        check=check_light,
    ),
    phase(
        "diagnostics",
        action=copy_diagnostics,
        check=check_diagnostics,
        screenshot=False,
    ),
    phase("math-off", action=math_off, done=shown_as_source, check=check_off),
]
