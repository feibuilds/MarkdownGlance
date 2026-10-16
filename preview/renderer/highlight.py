"""Colour for fenced code, in the editor's own syntaxes and colour scheme.

The structural pass finds every fenced block that names a language and hands
them all to a `Highlighter` at once. What comes back for each block is its code
cut into runs, each carrying the style the colour scheme gives that run, and
the block's text is replaced with them: a span with an inline style where the
run looks different from the document's own text, the bare text where it does
not. Tokenising needs Sublime Text, so the highlighter lives in the adapter and
is injected; nothing here imports it, and a block it cannot colour stays the
plain text it was (ADR 0021).
"""

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..domain.contracts import ThemeSnapshot
from .minihtml import hold_spaces
from .model import ElementNode, Node, TextNode


@dataclass(frozen=True)
class CodeStyle:
    """What the colour scheme gives a run: the parts minihtml can draw."""

    foreground: str = ""
    bold: bool = False
    italic: bool = False


Run = Tuple[str, CodeStyle]
# The language as the fence names it, and the code inside the fence.
CodeBlock = Tuple[str, str]
# One answer per block, in order; None leaves that block plain.
Highlighter = Callable[
    [Sequence[CodeBlock], ThemeSnapshot], Sequence[Optional[Sequence[Run]]]
]

# A language goes back into a fence line, so it may not carry a backtick, a
# space or a newline. `c++`, `c#`, `objective-c` and `f#` all pass.
LANGUAGE = re.compile(r"^[\w+#.-]+$")
COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$")
_LEADING_BACKTICKS = re.compile(r"^[ \t]*(`+)", re.MULTILINE)


def fenced(language: str, code: str) -> Tuple[str, int, int]:
    """A Markdown fence holding `code`, and where the code begins and ends in it.

    The fence is longer than any run of backticks that opens a line of the
    code, so that no line of it can close the block early.
    """
    longest = max(
        (len(match.group(1)) for match in _LEADING_BACKTICKS.finditer(code)), default=0
    )
    ticks = "`" * max(3, longest + 1)
    opening = "{}{}\n".format(ticks, language)
    body = code if code.endswith("\n") else code + "\n"
    return (
        "{}{}{}\n".format(opening, body, ticks),
        len(opening),
        len(opening) + len(code),
    )


def style_attribute(style: CodeStyle) -> str:
    parts = []
    if COLOUR.match(style.foreground):
        parts.append("color: {}".format(style.foreground))
    if style.bold:
        parts.append("font-weight: bold")
    if style.italic:
        parts.append("font-style: italic")
    return "; ".join(parts)


def _plain(style: CodeStyle, theme: ThemeSnapshot) -> bool:
    return (
        not style.bold
        and not style.italic
        and (
            not COLOUR.match(style.foreground)
            or style.foreground.lower() == theme.foreground.lower()
        )
    )


def _merge(
    runs: Sequence[Run], theme: ThemeSnapshot, attributes: Dict[CodeStyle, str]
) -> List[Tuple[str, str]]:
    """Fewer, longer runs: every span is a box minihtml lays out on each paint.

    Each run becomes its text and the style attribute it needs, empty for a
    run in the document's own foreground, which is no span at all. Whitespace
    has no colour, so it joins the run before it, or the one after when it
    comes first; and neighbours that look alike become one. `attributes` holds
    each style's answer for the whole document, since a scheme has only a few.
    """
    merged: List[Tuple[str, str]] = []
    for text, style in runs:
        if not text:
            continue
        attribute = attributes.get(style)
        if attribute is None:
            attribute = attributes[style] = (
                "" if _plain(style, theme) else style_attribute(style)
            )
        if merged:
            last_text, last_attribute = merged[-1]
            if last_attribute == attribute or text.isspace():
                merged[-1] = (last_text + text, last_attribute)
                continue
            if last_text.isspace():
                merged[-1] = (last_text + text, attribute)
                continue
        merged.append((text, attribute))
    return merged


def _nodes(
    runs: Sequence[Run], theme: ThemeSnapshot, attributes: Dict[CodeStyle, str]
) -> List[Node]:
    return [
        ElementNode("span", {"style": attribute}, [TextNode(text)], generated=True)
        if attribute
        else TextNode(text)
        for text, attribute in _merge(runs, theme, attributes)
    ]


def _code_blocks(nodes: Sequence[Node]) -> List[Tuple[ElementNode, str, str]]:
    """Each `<pre><code class="language">` the document wrote, in order.

    A block the renderer made itself -- a formula shown as its source -- is
    not the author's code and is left alone.
    """
    found: List[Tuple[ElementNode, str, str]] = []
    for node in nodes:
        if not isinstance(node, ElementNode):
            continue
        if node.tag == "pre" and not node.generated and len(node.children) == 1:
            code = node.children[0]
            if isinstance(code, ElementNode) and code.tag == "code":
                pieces = [child for child in code.children if isinstance(child, TextNode)]
                classes = code.attrs.get("class", "").split()
                text = "".join(piece.text for piece in pieces)
                if (
                    len(pieces) == len(code.children)
                    and classes
                    and LANGUAGE.match(classes[0])
                    and text.strip()
                ):
                    found.append((code, classes[0], text))
            continue
        found.extend(_code_blocks(node.children))
    return found


def highlight(
    roots: Sequence[Node], theme: ThemeSnapshot, highlighter: Highlighter
) -> bool:
    """Colour every fenced block that names a language; True when any changed."""
    blocks = _code_blocks(roots)
    if not blocks:
        return False
    answers = highlighter([(language, text) for _, language, text in blocks], theme)
    attributes: Dict[CodeStyle, str] = {}
    changed = False
    for (code, _, text), runs in zip(blocks, answers):
        if runs is None or "".join(piece for piece, _ in runs) != text:
            continue
        # The spaces are held here, across the whole block, rather than by the
        # serialiser run by run: a run of two that a token boundary splits in
        # half is two single spaces to it, and minihtml would collapse them.
        held = hold_spaces(text)
        offset = 0
        cut: List[Run] = []
        for piece, style in runs:
            cut.append((held[offset : offset + len(piece)], style))
            offset += len(piece)
        code.children = _nodes(cut, theme, attributes)
        changed = True
    return changed
