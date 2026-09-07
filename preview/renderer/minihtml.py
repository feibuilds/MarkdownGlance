import json
import re
from html import escape
from typing import Dict, List, Sequence, Set
from urllib.parse import urlsplit

from ..domain.contracts import (
    AssetKey,
    AssetKind,
    AssetResult,
    AssetStatus,
    Failed,
    Pending,
    PreviewDocument,
    Ready,
    RenderRequest,
)
from ..assets.math import SCALE as MATH_SCALE
from .errors import asset_placeholder
from .model import ElementNode, Node, StructuredDoc, TextNode

# minihtml collapses runs of plain whitespace; a run of U+00A0 survives.
NBSP = "\u00a0"
_RUN_OF_SPACES = re.compile(" {2,}")

ALLOWED_TAGS = frozenset(
    (
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "a",
        "strong",
        "em",
        "b",
        "i",
        "code",
        "pre",
        "ul",
        "ol",
        "li",
        "blockquote",
        "img",
        "br",
        "hr",
        "span",
        "div",
    )
)
DROP_CONTENT_TAGS = frozenset(("script", "style", "iframe", "object", "embed"))
VOID_TAGS = frozenset(("img", "br", "hr"))
CLASS_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")


def _attr(value: str) -> str:
    return escape(value, quote=True)


def _class_value(value: str) -> str:
    return " ".join(token for token in value.split() if CLASS_TOKEN.match(token))


def _pre_text(value: str) -> str:
    """Serialise the text of a `pre` block, keeping its indentation.

    minihtml collapses a *run* of plain spaces to one but leaves a run of
    U+00A0 alone, which is how `tables.py` pads its columns and what ADR 0007
    measured on ST 4200. Emitting one element per space instead -- a
    background-coloured full stop -- also holds the width, but it costs
    minihtml a layout box per space: 5774 of them in this repository's own
    69 KB design document, which is most of the native CPU a repaint burns. A
    no-break space is a character, so it costs none.

    Only runs of two or more are rewritten. A single space between words does
    not collapse, and leaving it plain keeps the line's break opportunities:
    U+00A0 everywhere would stop a long code line wrapping at all, and minihtml
    gives a `pre` block no horizontal scrollbar to make up for it.
    """
    return _RUN_OF_SPACES.sub(
        lambda match: NBSP * len(match.group()), escape(value, quote=True)
    ).replace("\n", "<br />")


def _relative_action(request: RenderRequest, index: int) -> str:
    args = json.dumps(
        {"token": request.action_token, "path": index}, separators=(",", ":")
    )
    return "subl:mdglance_open_relative {}".format(args)


def _href(
    value: str,
    heading_slugs: Set[str],
    links: Sequence[str],
    request: RenderRequest,
) -> str:
    if value.startswith("#") and value[1:] in heading_slugs:
        return ' href="{}"'.format(_attr(value))
    parsed = urlsplit(value)
    if parsed.scheme in ("http", "https"):
        return ' href="{}"'.format(_attr(value))
    if value and not parsed.scheme and not value.startswith("#"):
        try:
            index = links.index(value)
        except ValueError:
            return ' class="blocked-link"'
        return ' href="{}"'.format(_attr(_relative_action(request, index)))
    return ' class="blocked-link"'


# Assets whose locator carries document text, and what the placeholder says
# about it the first time each appears in a render (ADR 0005).
PRIVACY_CAPTIONS = {
    AssetKind.MERMAID: "Diagram source is sent to {}",
    AssetKind.MATH: "Formula source is sent to {}",
}


def _serialise_image(
    node: ElementNode,
    results: Dict[AssetKey, AssetResult],
    privacy_seen: Set[AssetKind],
) -> str:
    key = node.asset_key
    result = results.get(key) if key is not None else None
    if isinstance(result, Ready):
        asset = result.asset
        # A formula is fetched at twice its size and shown at one, so that it
        # is as crisp as the text beside it on a high-DPI display. A drawn SVG
        # carries the same idea in the asset itself, at whatever factor the
        # renderer was given.
        scale = (
            MATH_SCALE
            if key is not None and key.kind == AssetKind.MATH
            else asset.pixel_scale
        )
        width, height = asset.width / scale, asset.height / scale
        attrs = [
            'src="{}"'.format(_attr(asset.data_uri)),
            'alt="{}"'.format(_attr(node.attrs.get("alt", ""))),
            'width="{}"'.format(int(width)),
            'height="{}"'.format(int(height)),
            'style="width: {:.4f}rem; height: {:.4f}rem"'.format(
                width / 16.0, height / 16.0
            ),
        ]
        return "<img {}>".format(" ".join(attrs))
    status = (
        AssetStatus.LOADING if isinstance(result, Pending) else AssetStatus.UNAVAILABLE
    )
    if isinstance(result, Failed):
        status = result.status
    privacy = None
    disclose = key is not None and key.kind in PRIVACY_CAPTIONS
    if disclose and key.kind not in privacy_seen:
        privacy_seen.add(key.kind)
        privacy = PRIVACY_CAPTIONS[key.kind].format(
            urlsplit(key.locator).hostname or "the configured server"
        )
    return asset_placeholder(
        status, privacy, inline=node.generated and bool(node.attrs.get("data-inline"))
    )


def _serialise_node(
    node: Node,
    results: Dict[AssetKey, AssetResult],
    heading_slugs: Set[str],
    links: Sequence[str],
    request: RenderRequest,
    privacy_seen: Set[AssetKind],
    in_pre: bool = False,
) -> str:
    if isinstance(node, TextNode):
        return _pre_text(node.text) if in_pre else escape(node.text, quote=True)
    if node.tag in DROP_CONTENT_TAGS:
        return ""
    if node.tag == "img":
        return _serialise_image(node, results, privacy_seen)
    body = "".join(
        _serialise_node(
            child,
            results,
            heading_slugs,
            links,
            request,
            privacy_seen,
            in_pre or node.tag == "pre",
        )
        for child in node.children
    )
    if node.tag not in ALLOWED_TAGS:
        return body

    attrs: List[str] = []
    class_value = _class_value(node.attrs.get("class", ""))
    if class_value:
        attrs.append('class="{}"'.format(_attr(class_value)))
    if node.tag in ("h1", "h2", "h3", "h4", "h5", "h6") and node.generated:
        attrs.append('id="{}"'.format(_attr(node.attrs.get("id", ""))))
    if node.tag == "a":
        attrs.append(
            _href(node.attrs.get("href", ""), heading_slugs, links, request).strip()
        )
    prefix = "<{}{}>".format(node.tag, " " + " ".join(attrs) if attrs else "")
    return (
        prefix if node.tag in VOID_TAGS else "{}{}</{}>".format(prefix, body, node.tag)
    )


def serialise(
    structured: StructuredDoc,
    results: Dict[AssetKey, AssetResult],
    request: RenderRequest,
) -> PreviewDocument:
    heading_slugs = {heading.slug for heading in structured.headings}
    privacy_seen: Set[AssetKind] = set()
    body = "".join(
        _serialise_node(
            node,
            results,
            heading_slugs,
            structured.links,
            request,
            privacy_seen,
        )
        for node in structured.roots
    ).replace("<br>", "<br />")
    pending = tuple(
        key for key in structured.asset_keys if isinstance(results.get(key), Pending)
    )
    return PreviewDocument(
        request.generation,
        body,
        structured.headings,
        structured.asset_keys,
        pending,
        structured.links,
    )
