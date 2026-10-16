from typing import Dict, Tuple

from ..domain.contracts import ThemeSnapshot

# The settings that name a view's colour scheme. `color_scheme` is the whole
# answer unless it reads "auto", in which case Sublime picks between the other
# two by the OS appearance, so all three travel together.
SCHEME_KEYS = ("color_scheme", "dark_color_scheme", "light_color_scheme")


def _luminance(color: str) -> float:
    try:
        red, green, blue = (int(color[index : index + 2], 16) for index in (1, 3, 5))
    except (TypeError, ValueError):
        return 1.0
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0


def _scheme(view) -> Tuple[Tuple[str, str], ...]:
    settings = view.settings()
    named = ((key, settings.get(key)) for key in SCHEME_KEYS)
    return tuple((key, value) for key, value in named if isinstance(value, str))


def theme_snapshot(view) -> ThemeSnapshot:
    style: Dict[str, str] = view.style() or {}
    background = style.get("background", "#ffffff")
    foreground = style.get("foreground", "#222222")
    accent = style.get("accent", style.get("bluish", "#4f8cc9"))
    syntax = view.syntax()
    return ThemeSnapshot(
        background,
        foreground,
        _luminance(background) < 0.5,
        accent,
        _scheme(view),
        syntax.path if syntax is not None else "",
    )
