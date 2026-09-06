import re
import unicodedata
from html.parser import HTMLParser
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urlsplit, urlunsplit

from ..domain.contracts import (
    AssetKey,
    AssetKind,
    Heading,
    RenderRequest,
    ThemeSnapshot,
)
from ..domain.paths import HOST
from .markdown_engine import MarkdownEngine, default_engine
from .model import ElementNode, Node, StructuredDoc, TextNode
from .stylesheet import root_font_px
from .tables import budgets, replace_tables

# The theme reaches the builder because a mermaid.ink diagram is baked at
# request time: it cannot adapt to the preview background the way CSS does.
MermaidUrlBuilder = Callable[[str, str, ThemeSnapshot], str]

VOID_TAGS = frozenset(("br", "hr", "img"))
HEADING_TAGS = frozenset(("h1", "h2", "h3", "h4", "h5", "h6"))


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.roots: List[Node] = []
        self.stack: List[ElementNode] = []

    def _append(self, node: Node) -> None:
        (self.stack[-1].children if self.stack else self.roots).append(node)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        node = ElementNode(
            tag.lower(), {key.lower(): value or "" for key, value in attrs}
        )
        self._append(node)
        if node.tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(
        self, tag: str, attrs: List[Tuple[str, Optional[str]]]
    ) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1].tag == tag.lower():
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._append(TextNode(data))

    def handle_entityref(self, name: str) -> None:
        self._append(TextNode("&{};".format(name)))

    def handle_charref(self, name: str) -> None:
        self._append(TextNode("&#{};".format(name)))

    def handle_comment(self, data: str) -> None:
        return


def _walk(nodes: Sequence[Node]) -> Iterable[ElementNode]:
    for node in nodes:
        if isinstance(node, ElementNode):
            yield node
            yield from _walk(node.children)


def _raw_text(node: ElementNode) -> str:
    pieces: List[str] = []

    def collect(nodes: Sequence[Node]) -> None:
        for child in nodes:
            if isinstance(child, TextNode):
                pieces.append(child.text)
            else:
                collect(child.children)

    collect(node.children)
    return "".join(pieces)


def _text(node: ElementNode) -> str:
    return _raw_text(node).strip()


def _slug(text: str) -> str:
    normal = unicodedata.normalize("NFKD", text).casefold()
    normal = "".join(char for char in normal if not unicodedata.combining(char))
    normal = re.sub(r"[^\w\- ]+", "", normal, flags=re.UNICODE)
    return re.sub(r"[-\s]+", "-", normal).strip("-") or "section"


def _asset_key(source: str, request: RenderRequest) -> Optional[AssetKey]:
    parsed = urlsplit(source)
    if parsed.scheme in ("http", "https"):
        hostname = (parsed.hostname or "").lower()
        port = parsed.port
        default_port = (parsed.scheme.lower() == "https" and port == 443) or (
            parsed.scheme.lower() == "http" and port == 80
        )
        if ":" in hostname and not hostname.startswith("["):
            hostname = "[{}]".format(hostname)
        host = (
            hostname if default_port or port is None else "{}:{}".format(hostname, port)
        )
        if parsed.username or parsed.password:
            return None
        canonical = urlunsplit(
            (parsed.scheme.lower(), host, parsed.path or "/", parsed.query, "")
        )
        return AssetKey(AssetKind.REMOTE_IMAGE, canonical)
    if parsed.scheme == "file":
        if parsed.netloc not in ("", "localhost"):
            return None
        return AssetKey(AssetKind.LOCAL_IMAGE, HOST.normalise(unquote(parsed.path)))
    if parsed.scheme or source.startswith("data:"):
        return None
    if parsed.netloc:
        return None
    local_source = unquote(parsed.path)
    if request.base_path is None:
        return AssetKey(AssetKind.LOCAL_IMAGE, HOST.expand(local_source))
    return AssetKey(
        AssetKind.LOCAL_IMAGE,
        HOST.resolve(request.base_path, local_source),
    )


def _fence_classes(pre: ElementNode, code: Node) -> List[str]:
    """Reduce a fenced block to `<pre><code class="lang">`.

    superfences writes `class="highlight"` on the `pre` and prefixes the
    language with `language-`; neither is styled here, and the bare language
    is what the Mermaid check and the body HTML have always carried.
    """
    pre.attrs["class"] = " ".join(
        token for token in pre.attrs.get("class", "").split() if token != "highlight"
    )
    if not isinstance(code, ElementNode) or code.tag != "code":
        return []
    classes = [
        token[len("language-") :] if token.startswith("language-") else token
        for token in code.attrs.get("class", "").split()
    ]
    code.attrs["class"] = " ".join(classes)
    return classes


def _replace_mermaid(
    nodes: List[Node],
    request: RenderRequest,
    mermaid_url_builder: Optional[MermaidUrlBuilder],
) -> None:
    for index, node in enumerate(list(nodes)):
        if not isinstance(node, ElementNode):
            continue
        if node.tag == "pre" and len(node.children) == 1:
            code = node.children[0]
            classes = _fence_classes(node, code)
            if (
                isinstance(code, ElementNode)
                and code.tag == "code"
                and "mermaid" in classes
                and request.settings.enable_mermaid
                and mermaid_url_builder is not None
            ):
                url = mermaid_url_builder(
                    _raw_text(code),
                    request.settings.mermaid_server,
                    request.theme,
                )
                key = AssetKey(AssetKind.MERMAID, url)
                nodes[index] = ElementNode(
                    "p",
                    {"class": "mermaid-diagram"},
                    [
                        ElementNode(
                            "img",
                            {"alt": "Mermaid diagram"},
                            [],
                            asset_key=key,
                            generated=True,
                        )
                    ],
                    generated=True,
                )
                continue
        _replace_mermaid(node.children, request, mermaid_url_builder)


def parse(
    request: RenderRequest,
    engine: Optional[MarkdownEngine] = None,
    mermaid_url_builder: Optional[MermaidUrlBuilder] = None,
) -> StructuredDoc:
    parser = _TreeParser()
    parser.feed((engine or default_engine()).convert(request.markdown))
    parser.close()
    _replace_mermaid(parser.roots, request, mermaid_url_builder)

    elements = list(_walk(parser.roots))
    total_text = max(sum(len(_text(element)) for element in elements), 1)
    position = 0
    slug_counts: Dict[str, int] = {}
    headings: List[Heading] = []
    assets: List[AssetKey] = []
    links: List[str] = []

    for element in elements:
        text = _text(element)
        if element.tag in HEADING_TAGS:
            base = _slug(text)
            slug_counts[base] = slug_counts.get(base, 0) + 1
            count = slug_counts[base]
            slug = base if count == 1 else "{}-{}".format(base, count)
            element.attrs["id"] = slug
            element.generated = True
            headings.append(
                Heading(
                    int(element.tag[1]),
                    text,
                    slug,
                    len(headings),
                    min(1.0, position / total_text),
                )
            )
        if element.tag == "img" and element.asset_key is None:
            element.asset_key = _asset_key(element.attrs.get("src", ""), request)
        if element.asset_key is not None and element.asset_key not in assets:
            assets.append(element.asset_key)
        if element.tag == "a":
            href = element.attrs.get("href", "")
            parsed = urlsplit(href)
            if (
                href
                and not parsed.scheme
                and not href.startswith("#")
                and href not in links
            ):
                links.append(href)
        position += max(len(text), 1)

    # After the walk: the alignment padding is layout, not document text.
    latin, cjk = budgets(
        request.viewport_width,
        root_font_px(request.zoom),
        request.settings.table_max_columns,
    )
    replace_tables(parser.roots, latin, cjk)

    return StructuredDoc(
        tuple(parser.roots), tuple(headings), tuple(assets), tuple(links)
    )
