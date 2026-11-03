import base64
import json
from string import hexdigits
from typing import Tuple
from urllib.parse import parse_qs, urlsplit

from ..domain.contracts import LOCAL_MERMAID_SCHEME, RenderSettings, ThemeSnapshot

# mermaid.ink renders on a transparent background unless asked otherwise, and
# its light theme draws sequence message labels straight onto it in #333. On a
# dark colour scheme those labels disappear while the filled actor boxes stay,
# so the diagram has to be told which way round the preview is.
DARK_FALLBACK = "1e1e1e"
LIGHT_FALLBACK = "ffffff"


def background_hex(theme: ThemeSnapshot) -> str:
    """The six hex digits mermaid.ink takes for `bgColor`, alpha dropped."""
    colour = theme.background.lstrip("#")
    if len(colour) in (3, 4):
        colour = "".join(digit * 2 for digit in colour[:3])
    colour = colour[:6]
    if len(colour) == 6 and all(digit in hexdigits for digit in colour):
        return colour.lower()
    return DARK_FALLBACK if theme.is_dark else LIGHT_FALLBACK


def diagram_appearance(theme: ThemeSnapshot) -> Tuple[str, str]:
    """The part of a theme that reaches the image: same pair, same diagram.

    The server bakes the image, so unlike the preview's own HTML it cannot be
    re-coloured by a repaint. Two themes that agree here share a URL, and a
    cached diagram; two that do not need a new one fetched.
    """
    return ("dark" if theme.is_dark else "default", background_hex(theme))


def _encode(diagram: str, name: str, look: str) -> str:
    payload = json.dumps(
        {"code": diagram, "mermaid": {"theme": name, "look": look}},
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def mermaid_image_url(
    diagram: str, server: str, theme: ThemeSnapshot, look: str = "classic"
) -> str:
    name, background = diagram_appearance(theme)
    return "{}/img/{}?type=png&bgColor={}".format(
        server.rstrip("/"), _encode(diagram, name, look), background
    )


def local_mermaid_locator(
    diagram: str, theme: ThemeSnapshot, look: str = "classic"
) -> str:
    """The locator of a diagram drawn on this machine (ADR 0023).

    The same payload as the server's URL, under a scheme of our own: the
    diagram and the pair from `diagram_appearance` are the whole of what the
    image depends on, so two themes that agree share it as they share a URL.
    """
    name, background = diagram_appearance(theme)
    return "{}:{}?theme={}&bgColor={}".format(
        LOCAL_MERMAID_SCHEME, _encode(diagram, name, look), name, background
    )


def parse_local_mermaid_locator(locator: str) -> Tuple[str, str, str, str]:
    """The diagram, theme name, background hex and look a local locator
    carries."""
    parts = urlsplit(locator)
    if parts.scheme != LOCAL_MERMAID_SCHEME:
        raise ValueError("not a local Mermaid locator")
    encoded = parts.path
    payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    state = json.loads(payload.decode("utf-8"))
    query = parse_qs(parts.query)
    look = state["mermaid"].get("look", "classic")
    return state["code"], query["theme"][0], query["bgColor"][0], look


def mermaid_locator(
    diagram: str, settings: RenderSettings, theme: ThemeSnapshot
) -> str:
    """Where a diagram comes from: the local renderer when one is named, the
    server otherwise."""
    if settings.mermaid_renderer_path.strip():
        return local_mermaid_locator(diagram, theme, settings.mermaid_look)
    return mermaid_image_url(
        diagram, settings.mermaid_server, theme, settings.mermaid_look
    )
