"""Bring list layout to what Python-Markdown expects.

Python-Markdown nests a list item only when it is indented four columns past
its parent, and it does not start a list on the line after a paragraph.
Markdown as it is written for GitHub does both: a nested item sits two columns
in, under the parent's text, and a list follows its introducing sentence with
no blank line. markdown2 accepted both, so this preprocessor keeps such
documents rendering the way they did before the parser changed.

Each open list item records the column its content starts in, which is
CommonMark's rule for what belongs to it. A line indented at least that far is
the item's and is re-emitted at the four-column multiple Python-Markdown wants;
a marker line indented less closes the item and is a sibling of an enclosing
one. A blank line is put between a paragraph line and a marker that follows
it. A fenced block is passed through with the shift of the item that holds it
and its content otherwise untouched. See ADR 0012.
"""

import re
from typing import List, Optional, Tuple

from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor

TAB = 4
QUOTE = re.compile(r"^(?: {0,3}> ?)+")
MARKER = re.compile(r"^( *)([-+*]|\d{1,9}\.)( +|$)")
HR = re.compile(r"^ {0,3}([-*_])(?: *\1){2,} *$")
HEADING = re.compile(r"^ {0,3}#{1,6}(?: |$)")
FENCE = re.compile(r"^ *(`{3,}|~{3,})")

# (content column in the source, columns to add to lines that belong to it)
Item = Tuple[int, int]
# (fence character, fence length, columns to add to every line of the block)
Fence = Tuple[str, int, int]


def _shift(text: str, columns: int) -> str:
    if columns >= 0:
        return " " * columns + text
    stripped = text.lstrip(" ")
    return text[min(-columns, len(text) - len(stripped)) :]


def normalise(lines: List[str]) -> List[str]:
    out: List[str] = []
    stack: List[Item] = []
    fence: Optional[Fence] = None
    quote = ""
    in_list = False
    prev_blank = True
    for line in lines:
        matched = QUOTE.match(line)
        prefix = matched.group(0) if matched else ""
        key = prefix.replace(" ", "")
        if fence is not None and key != quote:
            # Inside a fence a `>` is text. Only the block's own quote prefix
            # is stripped, and a line without it is still the block's.
            prefix, key = "", quote
        rest = line[len(prefix) :]
        if key != quote:
            # A different block-quote depth is a different document.
            quote, stack, fence, in_list, prev_blank = key, [], None, False, True

        if fence is not None:
            char, length, shift = fence
            out.append(prefix + _shift(rest, shift))
            closing = FENCE.match(rest)
            if (
                closing
                and closing.group(1)[0] == char
                and len(closing.group(1)) >= length
                and not rest[closing.end() :].strip()
            ):
                fence = None
            continue

        if not rest.strip():
            out.append(line)
            prev_blank = True
            continue

        indent = len(rest) - len(rest.lstrip(" "))
        while stack and indent < stack[-1][0]:
            stack.pop()

        # A rule or a heading at the item's content column is the item's own;
        # one outside every open item ends the list.
        block = HR.match(rest) or HEADING.match(rest)
        if block and not stack:
            in_list, prev_blank = False, False
            out.append(line)
            continue

        marker = None if block else MARKER.match(rest)
        # Four columns past the enclosing content is an indented code block,
        # whatever the line looks like.
        code_col = stack[-1][0] + TAB if stack else TAB
        if marker and indent < code_col:
            depth = len(stack)
            if not in_list and not prev_blank:
                out.append(prefix.rstrip())
            spaces = len(marker.group(3))
            content_col = indent + len(marker.group(2)) + (spaces if 1 <= spaces <= 4 else 1)
            out.append(prefix + " " * (TAB * depth) + rest[indent:])
            stack.append((content_col, TAB * (depth + 1) - content_col))
            in_list, prev_blank = True, False
            continue

        if stack:
            shift = stack[-1][1]
        else:
            shift = 0
            if prev_blank:
                in_list = False
        out.append(prefix + _shift(rest, shift))
        prev_blank = False
        opening = FENCE.match(rest)
        if opening:
            fence = (opening.group(1)[0], len(opening.group(1)), shift)
    return out


class ListPreprocessor(Preprocessor):
    def run(self, lines: List[str]) -> List[str]:
        return normalise(lines)


class ListExtension(Extension):
    def extendMarkdown(self, md) -> None:  # type: ignore[override]
        # After normalize_whitespace (30) has expanded tabs; before the fence
        # preprocessor (25) reads indentation.
        md.preprocessors.register(ListPreprocessor(md), "mdglance_lists", 27)
