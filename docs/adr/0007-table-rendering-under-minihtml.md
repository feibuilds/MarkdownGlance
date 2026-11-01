# ADR 0007: Table rendering under minihtml

## Status

Accepted.

## Context

The four extras fixed in [ADR 0003](0003-markdown-dialect-and-parser.md) did not
include `tables`, so a GFM table reached the preview as one paragraph of literal
pipes. Enabling the extra alone does not help: the minihtml reference lists the
tags it implements and states that `<table>` is not among them, and it supports
no `width` property, so the host cannot lay out columns and neither can CSS.

The redesign anticipated this — §9.3 of the design allowed tables to "degrade to
rows if minihtml support proves insufficient" and left a compatibility fixture to
decide. This ADR records what the fixture decided.

## Measurements

Probes rendered in an `html_sheet` on Sublime Text 4200, Linux, X11, at 100% OS
scaling:

- a run of plain spaces collapses to one; a run of U+00A0 does not;
- in a monospace block, bold text, a `<code>` span with no padding, and a link
  all keep the same advance as plain text;
- `DejaVu Sans Mono` draws CJK from a proportional fallback at about 1.75 Latin
  advances, so a CJK cell drifts; `Noto Sans Mono CJK SC` draws it at exactly 2,
  and draws East Asian Ambiguous glyphs — the curly quotes, the em dash — at 2
  as well, which is wrong for an English table and right for a Chinese one;
- minihtml rounds the monospace advance up to whole pixels: with a 16 px root
  font the measured pitch is 10 px, not the 9.64 px that DejaVu Sans Mono's
  0.6023 em advance predicts. A budget computed from the unrounded advance
  overflows the preview and is wrapped by the host;
- a preview group measuring 904 px reported by `View.viewport_extent()` fits 82
  columns of that pitch inside the body and table chrome (5.16 rem in total).

## Decision

Add `tables` to the extras. After the structural pass, rewrite every `table`
subtree — from Markdown and from raw HTML alike — into a monospace block of
`div` rows and `span` cells, padding each cell to its column width with U+00A0.
Remove `table`, `tr`, `td` and `th` from the serialiser allowlist: nothing emits
them any more, and minihtml would render them as inline soup if anything did.

The character budget comes from the width of the preview group, measured with
`View.viewport_extent()` and carried on `RenderRequest.viewport_width`, so a
table fills its group. A table too wide for the budget is wrapped by the
renderer rather than by minihtml: the budget is shared over the columns, each
column keeping room for its longest unbreakable run, and each cell is broken
into as many padded lines as it needs. `table_max_columns` (default 200) is
only an upper bound, for a very wide screen; when the width cannot be measured
yet the budget falls back to 48 columns.

ST reports no view-resize event, so the container polls the measured budget of
every live session every 500 ms and asks for a re-render only when the column
count changes. That is cheap — one `viewport_extent()` call per preview — and it
is what makes a table re-fit when the window is maximised.

A table containing East Asian Wide or Fullwidth characters is marked
`md-table-cjk` and set in a CJK monospace font, and its ambiguous-width glyphs
count as two columns. Every other table keeps a Latin monospace font and counts
them as one.

## Consequences

- Column alignment holds for Latin, CJK and mixed text, for bold, code and link
  runs, and for the `:--`, `--:` and `:-:` alignments.
- Alignment is only as good as the font measurement: an emoji, an image in a
  cell, or a host without the configured monospace fonts can put a cell a
  fraction of a character out.
- The budget depends on a font advance the renderer cannot query. The constants
  cover the two stacks the stylesheet names; a host that substitutes a wider
  monospace font would overflow, which `table_max_columns` can bound.
- Resizing costs a re-render, delayed by up to the poll interval plus the usual
  debounce.
- Wrapping splits markup: `**one two**` becomes two `<strong>` runs when it
  breaks across lines. Glued runs such as `**bold**;` are kept together.

## Amendments, issue #9

The consequence above -- a host that substitutes a wider monospace font would
overflow -- was every Windows and macOS host with a CJK table. Neither ships
`Noto Sans Mono CJK` or `Sarasa Mono`, so `md-table-cjk` falls through to
`monospace` (Consolas, Menlo, Courier), whose advance is the Latin one, while
the budget was counted at 0.5 em: a fifth too many columns. A row with a space
in it was re-wrapped by the host; a row without one ran past the edge, and its
last cell was clipped. An emoji alone was enough to trigger it, since emoji
are East Asian Wide too.

- **The CJK budget assumes the CJK font only on Linux** (`CJK_FONT_SHIPS`),
  where desktop CJK support installs it. Elsewhere it is the Latin budget,
  which no fallback monospace font exceeds. A Windows or macOS reader who has
  installed one of the fonts gets a table a little narrower than the group; a
  Linux host without one still overflows.
- **Emoji do not make a table CJK.** They come from a colour font whichever
  stack is named, so they keep the Latin font and still count two columns.
  `_is_cjk` treats the wide characters below U+2E80 (except Hangul Jamo) and
  those from U+1F000 to U+1FFFF as emoji.
