"""An SVG is drawn by the local renderer, and says so when it cannot be.

Five images in one document: a local drawing that references a sibling PNG, a
remote SVG badge, a PNG as the control, a WebP that nothing here draws, and a
path that does not exist. Three phases walk the settings that decide the
outcome, in the order a reader would meet them.

`no-renderer` points `svg_renderer_path` at nothing, so the two SVGs read "No
SVG renderer" while the WebP still reads "Not a PNG, JPEG or GIF" and the
missing file still reads "Unavailable" -- three different answers, which is
the point. `drawn` points the setting at the real renderer: both SVGs become
images. `svg-off` turns the feature off, and the drawing already made goes
back to being a format the preview does not draw.

The badge is fetched, so this scenario needs the network, and it needs a
`resvg` on the PATH for its second and third phases.
"""

import shutil

from mdglance_probe import phase

SETTINGS = "MarkdownGlance.sublime-settings"
MISSING = "No SVG renderer"
UNSUPPORTED = "Not a PNG, JPEG or GIF"
ABSENT = "/nonexistent/resvg"


def without_renderer(ctx):
    ctx.set_setting(SETTINGS, "svg_renderer_path", ABSENT)
    ctx.open_fixture("svg.md")


def with_renderer(ctx):
    found = shutil.which("resvg") or ""
    ctx.note("resvg on the PATH: {!r}".format(found))
    ctx.set_setting(SETTINGS, "svg_renderer_path", found)


def svg_off(ctx):
    ctx.set_setting(SETTINGS, "enable_svg", False)


def settled_with(images):
    def done(ctx, snap):
        return ctx.settled(snap) and snap["images"] == images

    return done


def named(ctx, snap):
    body = snap["body_html"]
    return {
        "only the png draws": snap["images"] == 1,
        "both svgs ask for a renderer": body.count(MISSING) == 2,
        "the webp names its format instead": body.count(UNSUPPORTED) == 1,
        "the missing file is still unavailable": snap["unavailable"] == 1,
        "one placeholder per undrawn image": snap["block_placeholders"] == 4,
        "no error card": snap["error_cards"] == 0,
    }


def drawn(ctx, snap):
    body = snap["body_html"]
    return {
        "the two svgs and the png are images": snap["images"] == 3,
        "nothing asks for a renderer": body.count(MISSING) == 0,
        "the webp still names its format": body.count(UNSUPPORTED) == 1,
        "the missing file is still unavailable": snap["unavailable"] == 1,
        "no error card": snap["error_cards"] == 0,
    }


def off(ctx, snap):
    body = snap["body_html"]
    return {
        "only the png draws": snap["images"] == 1,
        "the drawing made earlier is put back": body.count(UNSUPPORTED) == 3,
        "and no renderer is asked for": body.count(MISSING) == 0,
        "the missing file is still unavailable": snap["unavailable"] == 1,
    }


PHASES = [
    phase("no-renderer", action=without_renderer, done=settled_with(1), check=named),
    phase("drawn", action=with_renderer, done=settled_with(3), check=drawn),
    phase("svg-off", action=svg_off, done=settled_with(1), check=off),
]
