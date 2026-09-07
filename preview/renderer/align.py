"""Pairing the source outline with the rendered table of contents.

The two heading lists come from different places. `scan_outline` reads the raw
buffer line by line, so it knows which *line* each heading is on and keeps the
Markdown as written. The renderer walks the parsed document, so it knows each
heading's *slug* and has stripped the inline markup away.

Where the two agree, an entry in either list can carry the reader to the
section in both panes at once: the caret to the line, the preview to the slug.
Where they do not, it must carry them to one and leave the other alone --
sending someone to the wrong section is worse than not moving.

They disagree more often than they look like they would. A heading inside a raw
`<h2>` block, or inside a block quote, is in the render and not in the scan; a
`#` inside a fence is in neither. Measured over this repository's 47 renderable
Markdown files the lists were the same length with the same levels every time,
which says only that the corpus has none of those -- one raw `<h2>` in a long
document would be enough to throw a positional pairing off by one for every
heading after it. So the pairing is a monotone alignment rather than a zip:
`difflib` finds the entries that match on level and text, in order, and
anything it cannot match is simply not paired.
"""

import difflib
import re
from typing import Dict, NamedTuple, Sequence

# `[text](url)`, `[text][ref]` and `[text]`, in that order: the renderer keeps
# only the text, so the source has to be reduced to it before comparing.
LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
REFERENCE = re.compile(r"\[([^\]]*)\]\[[^\]]*\]")
BRACKET = re.compile(r"\[([^\]]*)\]")
# Emphasis, code and strikethrough markers. Not a parser: this only has to
# agree with the renderer often enough to pair headings, and a heading it
# cannot pair still works, just in one pane.
MARKUP = re.compile(r"[`*_~]")


class HeadingLinks(NamedTuple):
    """Where each heading is, in whichever list you did not start from."""

    to_slug: Dict[int, str]
    to_line: Dict[str, int]

    def slug_for(self, ordinal: int):
        return self.to_slug.get(ordinal)

    def line_for(self, slug: str):
        return self.to_line.get(slug)


NOTHING = HeadingLinks({}, {})


def normalise(text: str) -> str:
    """A heading's text with the inline markup taken off and spaces collapsed."""
    text = LINK.sub(r"\1", text)
    text = REFERENCE.sub(r"\1", text)
    text = BRACKET.sub(r"\1", text)
    text = MARKUP.sub("", text)
    return " ".join(text.split())


def align(scanned: Sequence, rendered: Sequence) -> HeadingLinks:
    """Pair source headings with rendered ones, in order, where they match.

    `scanned` is `SourceHeading`s (level, text, ordinal, line); `rendered` is
    `Heading`s (level, text, slug, ordinal, position_ratio).
    """
    if not scanned or not rendered:
        return NOTHING
    left = [(item.level, normalise(item.text)) for item in scanned]
    right = [(item.level, normalise(item.text)) for item in rendered]
    to_slug: Dict[int, str] = {}
    to_line: Dict[str, int] = {}
    matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
    for start_left, start_right, size in matcher.get_matching_blocks():
        for offset in range(size):
            source = scanned[start_left + offset]
            target = rendered[start_right + offset]
            to_slug[source.ordinal] = target.slug
            to_line[target.slug] = source.line
    return HeadingLinks(to_slug, to_line)
