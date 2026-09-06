"""Rewrite table trees into aligned monospace rows.

minihtml implements no ``<table>`` layout and no ``width`` property, so the host
cannot lay a table out and the renderer has to do the typesetting itself.
Measured on ST 4200 (Linux, X11): a monospace block keeps a constant advance for
plain, bold, ``<code>`` and link runs, and for East Asian characters at two
columns each; runs of plain spaces collapse but U+00A0 does not. Columns are
therefore padded to a fixed character width with U+00A0. Emoji come from a
colour font whose advance is not exactly two columns, so a cell holding one
can be a fraction of a character out.

A table wider than the preview would be re-wrapped by minihtml, which destroys
the alignment, so it is wrapped here instead: a budget of characters is shared
out over the columns, each cell is broken into as many lines as it needs, and
every physical line is padded on its own. A cell whose content cannot be
measured (an image) counts as zero columns.

The budget comes from the measured preview width, so a table fills the group it
is in and re-fits when the window is resized. `budgets()` converts pixels to
characters for both fonts the stylesheet can pick; when the width is not known
yet it falls back to a width that suits a narrow group.
"""

import math
import re
import unicodedata
from typing import List, Optional, Sequence, Tuple

from .model import ElementNode, Node, TextNode

NBSP = "\u00a0"
COLUMN_GAP = 2
MIN_COLUMN = 3
CELL_TAGS = frozenset(("td", "th"))
SECTION_TAGS = frozenset(("thead", "tbody", "tfoot"))
DROPPED_CELL_TAGS = frozenset(("br",))
WIDE_WIDTHS = frozenset(("W", "F"))

# Advance of one character as a fraction of the font size, for the two stacks
# in the stylesheet: DejaVu Sans Mono, and Noto Sans Mono CJK for a CJK table.
# minihtml rounds the advance up to whole pixels — measured 10 px, not 9.64,
# at a 16 px root — so `budgets` rounds the same way rather than overshooting.
LATIN_ADVANCE = 0.6023
CJK_ADVANCE = 0.5
# Body padding (1.5rem each side), table padding (1rem) and border (0.08rem).
CHROME_REM = 5.16
# One column for the scrollbar and for rounding in the host's own measurement.
SAFETY_COLUMNS = 1
FALLBACK_COLUMNS = 48

Row = Tuple[bool, List[ElementNode]]
# Width, node, and how the word joins the one before it: "space" (a line may
# break here, and a space is drawn when it does not), "none" (glued to it, as
# in `**bold**;`) or "break" (the tail of a word too long for its column).
Word = Tuple[int, Node, str]
SPACE, GLUED, BREAK = "space", "none", "break"


def _display_width(text: str, ambiguous: int = 1) -> int:
    """Character columns, counting East Asian Ambiguous glyphs as `ambiguous`.

    A table holding CJK is set in a CJK monospace font, which draws the
    ambiguous glyphs — curly quotes, the em dash — full width; the Latin-only
    font used otherwise draws them in one column.
    """
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        kind = unicodedata.east_asian_width(char)
        if kind in WIDE_WIDTHS:
            width += 2
        elif kind == "A":
            width += ambiguous
        else:
            width += 1
    return width


def _longest_unit(text: str, ambiguous: int) -> int:
    """The widest run that cannot be broken across lines.

    Latin words break at spaces only, but a wide glyph may start a line on its
    own, so a run of CJK never reserves more than one character of column.
    """
    longest = 0
    run = ""
    for piece in text.split():
        for char in piece:
            if unicodedata.east_asian_width(char) in WIDE_WIDTHS:
                longest = max(longest, _display_width(run, ambiguous), 2)
                run = ""
            else:
                run += char
        longest = max(longest, _display_width(run, ambiguous))
        run = ""
    return longest


def _has_wide(rows: Sequence[Row]) -> bool:
    return any(
        unicodedata.east_asian_width(char) in WIDE_WIDTHS
        for _, cells in rows
        for cell in cells
        for char in _cell_text(cell)
    )


def _cell_text(cell: ElementNode) -> str:
    pieces: List[str] = []

    def collect(nodes: Sequence[Node]) -> None:
        for child in nodes:
            if isinstance(child, TextNode):
                pieces.append(child.text)
            else:
                collect(child.children)

    collect(cell.children)
    # minihtml collapses runs of whitespace, so measure what it will render.
    return " ".join("".join(pieces).split())


def _rows(table: ElementNode) -> List[Row]:
    rows: List[Row] = []

    def visit(node: ElementNode, in_head: bool) -> None:
        for child in node.children:
            if not isinstance(child, ElementNode):
                continue
            if child.tag == "tr":
                cells = [
                    cell
                    for cell in child.children
                    if isinstance(cell, ElementNode) and cell.tag in CELL_TAGS
                ]
                header = in_head or (
                    bool(cells) and all(cell.tag == "th" for cell in cells)
                )
                rows.append((header, cells))
            elif child.tag in SECTION_TAGS:
                visit(child, in_head or child.tag == "thead")
            elif child.tag != "caption":
                visit(child, in_head)

    visit(table, False)
    return rows


def _caption(table: ElementNode) -> Optional[ElementNode]:
    for child in table.children:
        if isinstance(child, ElementNode) and child.tag == "caption":
            return ElementNode(
                "div",
                {"class": "md-table-caption"},
                list(child.children),
                generated=True,
            )
    return None


def _column_extents(rows: Sequence[Row], ambiguous: int) -> Tuple[List[int], List[int]]:
    """Per column: the width that needs no wrapping, and its longest word."""
    natural: List[int] = []
    longest: List[int] = []
    for _, cells in rows:
        for index, cell in enumerate(cells):
            text = _cell_text(cell)
            width = _display_width(text, ambiguous)
            word = _longest_unit(text, ambiguous)
            if index < len(natural):
                natural[index] = max(natural[index], width)
                longest[index] = max(longest[index], word)
            else:
                natural.append(width)
                longest.append(word)
    return natural, longest


def _allocate(natural: Sequence[int], longest: Sequence[int], budget: int) -> List[int]:
    """Share `budget` characters over the columns.

    Every column keeps room for its longest unbreakable run, so wrapping breaks
    between words rather than inside them; the columns with the most room to
    spare give up the rest, which keeps a narrow column whole while a wide one
    takes the wrapping.
    """
    count = len(natural)
    if not count:
        return []
    available = budget - COLUMN_GAP * (count - 1)
    if available >= sum(natural):
        return list(natural)
    available = max(available, MIN_COLUMN * count)
    floors = [
        max(MIN_COLUMN, min(longest[index], natural[index])) for index in range(count)
    ]
    if sum(floors) >= available:
        return [max(MIN_COLUMN, width) for width in _share(floors, available)]
    widths = list(natural)
    deficit = sum(widths) - available
    while deficit > 0:
        index = max(
            range(count), key=lambda column: (widths[column] - floors[column], -column)
        )
        if widths[index] <= floors[index]:
            break
        widths[index] -= 1
        deficit -= 1
    return widths


def _share(weights: Sequence[int], available: int) -> List[int]:
    """Split `available` characters in proportion to `weights`, losing none."""
    total = sum(weights)
    shares = [0] * len(weights)
    if available <= 0:
        return shares
    remaining = available
    for index in range(len(weights)):
        if index == len(weights) - 1:
            shares[index] = max(0, remaining)
        else:
            shares[index] = weights[index] * available // max(total, 1)
            remaining -= shares[index]
    return shares


def _chunks(text: str, width: int, ambiguous: int) -> List[str]:
    """Hard-split a word too long for its column, so it cannot overflow."""
    pieces: List[str] = []
    current = ""
    used = 0
    for char in text:
        size = _display_width(char, ambiguous)
        if current and used + size > width:
            pieces.append(current)
            current = ""
            used = 0
        current += char
        used += size
    if current:
        pieces.append(current)
    return pieces


def _clone_chain(node: Node, chain: Sequence[ElementNode]) -> Node:
    for element in reversed(chain):
        node = ElementNode(element.tag, dict(element.attrs), [node], generated=True)
    return node


def _words(cell: ElementNode, width: int, ambiguous: int) -> List[Word]:
    """Flatten a cell into wrappable words, each keeping its own markup.

    A word carries a clone of the elements it sits inside, so breaking a line
    inside a link or a bold run reopens that markup on the next line. Whether
    the source had whitespace before a word is carried with it, so a boundary
    such as `**bold**;` neither gains a space nor a line break.
    """
    words: List[Word] = []
    gap = [False]

    def visit(nodes: Sequence[Node], chain: Tuple[ElementNode, ...]) -> None:
        for child in nodes:
            if isinstance(child, TextNode):
                pieces = child.text.split()
                if not pieces:
                    gap[0] = gap[0] or bool(child.text)
                    continue
                leading = gap[0] or child.text[:1].isspace()
                for position, piece in enumerate(pieces):
                    joint = SPACE if position or leading else GLUED
                    for order, chunk in enumerate(_chunks(piece, width, ambiguous)):
                        words.append(
                            (
                                _display_width(chunk, ambiguous),
                                _clone_chain(TextNode(chunk), chain),
                                BREAK if order else joint,
                            )
                        )
                gap[0] = child.text[-1:].isspace()
            elif child.tag in DROPPED_CELL_TAGS:
                continue
            elif child.children:
                visit(child.children, chain + (child,))
            else:
                # Unmeasurable, and kept whole: an image or an empty element.
                words.append(
                    (0, _clone_chain(child, chain), SPACE if gap[0] else GLUED)
                )
                gap[0] = False

    visit(cell.children, ())
    return words


def _runs(words: Sequence[Word]) -> List[List[Word]]:
    """Group words that are glued to their neighbour and so cannot be split."""
    runs: List[List[Word]] = []
    for word in words:
        if runs and word[2] == GLUED:
            runs[-1].append(word)
        else:
            runs.append([word])
    return runs


def _lines(words: Sequence[Word], width: int) -> List[List[Word]]:
    lines: List[List[Word]] = []
    current: List[Word] = []
    used = 0
    for run in _runs(words):
        size = sum(word[0] for word in run)
        space = 1 if (current and run[0][2] == SPACE) else 0
        if current and used + space + size > width:
            lines.append(current)
            current = [(run[0][0], run[0][1], BREAK)] + list(run[1:])
            used = size
        else:
            current.extend(run)
            used += space + size
    if current:
        lines.append(current)
    return lines or [[]]


_TEXT_ALIGN = re.compile(r"text-align\s*:\s*(left|right|center)", re.I)


def _alignment(cell: ElementNode) -> str:
    # Python-Markdown 3.2 writes `align="right"`; 3.4 and later write
    # `style="text-align: right;"`. Package Control serves both, by host.
    align = cell.attrs.get("align", "")
    if not align:
        matched = _TEXT_ALIGN.search(cell.attrs.get("style", ""))
        align = matched.group(1) if matched else ""
    return align.lower()


def _padding(deficit: int, align: str) -> Tuple[int, int]:
    if deficit <= 0:
        return 0, 0
    if align == "right":
        return deficit, 0
    if align == "center":
        lead = deficit // 2
        return lead, deficit - lead
    return 0, deficit


def _cell_span(line: Sequence[Word], width: int, align: str, last: bool) -> ElementNode:
    used = sum(
        word[0] + (1 if index and word[2] == SPACE else 0)
        for index, word in enumerate(line)
    )
    lead, trail = _padding(width - used, align)
    if last:
        # Nothing follows on the line, so trailing padding would be invisible.
        trail = 0
    else:
        trail += COLUMN_GAP
    children: List[Node] = []
    if lead:
        children.append(TextNode(NBSP * lead))
    for index, word in enumerate(line):
        if index and word[2] == SPACE:
            children.append(TextNode(" "))
        children.append(word[1])
    if trail:
        children.append(TextNode(NBSP * trail))
    return ElementNode("span", {"class": "md-table-cell"}, children, generated=True)


def _row_nodes(row: Row, widths: Sequence[int], ambiguous: int) -> List[ElementNode]:
    header, cells = row
    wrapped = [
        _lines(_words(cell, widths[index], ambiguous), widths[index])
        for index, cell in enumerate(cells)
    ]
    height = max((len(lines) for lines in wrapped), default=1)
    classes = "md-table-row md-table-head" if header else "md-table-row"
    nodes: List[ElementNode] = []
    for line in range(height):
        spans: List[Node] = []
        for index, lines in enumerate(wrapped):
            spans.append(
                _cell_span(
                    lines[line] if line < len(lines) else [],
                    widths[index],
                    _alignment(cells[index]),
                    index == len(cells) - 1,
                )
            )
        nodes.append(ElementNode("div", {"class": classes}, spans, generated=True))
    return nodes


def budgets(viewport_width: float, rem_px: int, cap: int) -> Tuple[int, int]:
    """Characters that fit the preview, for the Latin and the CJK font.

    The two fonts have different advances, and which one a table uses is only
    known once its content has been read, so both are worked out here and the
    table picks one.
    """
    fallback = min(cap, FALLBACK_COLUMNS)
    if viewport_width <= 0 or rem_px <= 0:
        return fallback, fallback
    content = viewport_width - CHROME_REM * rem_px
    return tuple(  # type: ignore[return-value]
        max(
            MIN_COLUMN,
            min(cap, int(content // math.ceil(advance * rem_px)) - SAFETY_COLUMNS),
        )
        for advance in (LATIN_ADVANCE, CJK_ADVANCE)
    )


def _table_node(table: ElementNode, latin: int, cjk: int) -> ElementNode:
    rows = _rows(table)
    wide = _has_wide(rows)
    ambiguous = 2 if wide else 1
    natural, longest = _column_extents(rows, ambiguous)
    widths = _allocate(natural, longest, cjk if wide else latin)
    children: List[Node] = []
    caption = _caption(table)
    if caption is not None:
        children.append(caption)
    for index, row in enumerate(rows):
        nodes = _row_nodes(row, widths, ambiguous)
        last_head = row[0] and (index + 1 == len(rows) or not rows[index + 1][0])
        if last_head and nodes:
            nodes[-1].attrs["class"] += " md-table-rule"
        children.extend(nodes)
    classes = "md-table md-table-cjk" if wide else "md-table"
    return ElementNode("div", {"class": classes}, children, generated=True)


def replace_tables(nodes: List[Node], latin: int, cjk: int) -> None:
    """Replace every ``table`` subtree in place with aligned monospace rows."""
    for index, node in enumerate(list(nodes)):
        if not isinstance(node, ElementNode):
            continue
        if node.tag == "table":
            nodes[index] = _table_node(node, latin, cjk)
            continue
        replace_tables(node.children, latin, cjk)
