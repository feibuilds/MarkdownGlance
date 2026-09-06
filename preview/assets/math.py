import re
from string import hexdigits
from typing import Tuple
from urllib.parse import quote

from ..domain.contracts import ThemeSnapshot

# minihtml runs no JavaScript and draws no MathML or SVG, so a formula reaches
# the preview the way a Mermaid diagram does: as a PNG a server typeset. The
# server draws it on a transparent background, so only the foreground colour
# has to travel; the preview's own background shows through.
DARK_FALLBACK = (238, 238, 238)
LIGHT_FALLBACK = (34, 34, 34)

# The image is fetched at twice the size it is shown at and scaled down by
# the serialiser, so that it stays crisp on a high-DPI display next to text
# that is. 115 dpi makes LaTeX's 10 pt body roughly the height of 16 px text.
SCALE = 2
DPI = 115 * SCALE

_WHITESPACE = re.compile(r"\s+")


def foreground_rgb(theme: ThemeSnapshot) -> Tuple[int, int, int]:
    """The colour scheme's foreground as the RGB triple the server takes."""
    colour = theme.foreground.lstrip("#")
    if len(colour) in (3, 4):
        colour = "".join(digit * 2 for digit in colour[:3])
    colour = colour[:6]
    if len(colour) == 6 and all(digit in hexdigits for digit in colour):
        return (int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16))
    return DARK_FALLBACK if theme.is_dark else LIGHT_FALLBACK


def formula_appearance(theme: ThemeSnapshot) -> Tuple[int, int, int]:
    """The part of a theme that reaches the image: same triple, same image.

    Two themes that agree here share a URL, and a cached formula; two that do
    not need a new one fetched, since the colour is baked into the PNG.
    """
    return foreground_rgb(theme)


def normalise_formula(formula: str) -> str:
    """One line, single-spaced: what a display block carries on several."""
    return _WHITESPACE.sub(" ", formula).strip()


def math_image_url(
    formula: str, display: bool, server: str, theme: ThemeSnapshot
) -> str:
    red, green, blue = formula_appearance(theme)
    source = "\\dpi{{{}}}\\color[RGB]{{{},{},{}}}{}{}".format(
        DPI,
        red,
        green,
        blue,
        "\\displaystyle " if display else "",
        normalise_formula(formula),
    )
    return "{}/png.image?{}".format(server.rstrip("/"), quote(source, safe=""))
