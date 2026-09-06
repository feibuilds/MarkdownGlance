# ADR 0011: The table of contents and the outline are sized to their content

## Status

Accepted. Extends ADR 0001 (presentation backend) and ADR 0010 (the source
outline), and reuses the measuring technique of ADR 0007 (tables under
minihtml).

Everything about the measuring holds after
[ADR 0014](0014-one-contents-panel-for-both-halves.md) merged the two surfaces
into one panel, and both measurements are still needed: the panel is measured
against whichever half is on screen, because the outline is monospace and
carries its `#` markers while the table of contents is not. What changed is the
count -- one `ROLE_SHARE` entry for one panel group, in place of 0.35 and 0.3
for two.

## Context

Both side surfaces took a fixed share of the group they were split from:
`ROLE_SHARE` gave the table of contents 0.35 and the outline 0.3. A share is a
poor unit for a list of headings. What the surface needs is the width of its
longest entry, which does not scale with the window: on a wide screen 0.3 is
far more than any outline needs, and the space comes out of the content the
user is actually reading.

Measured on this repository's own README at a 16 px root, in a 2560 px window:
the outline's longest entry, `### One Sublime Text default changes`, wants
about 456 px of a group that was being given 607 px. A quarter of that group
was empty, and it was empty in the middle of the window, not at its edge.

The two surfaces also inherited the preview's page margins — 1.5 rem of body
padding each side, plus 1 rem inside the table of contents' card — 83 px of
padding around a 250 px list.

minihtml offers no way to ask a phantom how wide it wants to be, and Sublime
Text reports no window width; a view reports only its own viewport.

## Decision

Size both surfaces from their content, and spend less of that size on padding.

- **`renderer/measure.py`** estimates the pixels the longest entry needs:
  per-character advances bucketed by character class for the proportional
  stack, the monospace advance of ADR 0007 for the outline, plus the
  `padding-left` each heading level carries in `resources/preview.css`. The
  advances target the stack that actually resolves — Ubuntu on Linux, Arial,
  Helvetica or Open Sans elsewhere, which agree to within a percent — and run
  about 5% over it. DejaVu Sans, the last fallback, is a tenth wider again; a
  host with nothing else may wrap its single longest entry, which the slack
  allowance is sized to absorb for all but the longest headings.
- **`LayoutOwner.acquire`** takes that width and converts it to a share of the
  cell it is splitting: `width / measured width of the anchor group`, since the
  cell's own fraction of the window cancels out. The role's old share becomes
  the **ceiling**, so this change can only ever make a group narrower than it
  was, and `ROLE_MINIMUM` is the floor, so a document of one-word headings
  still leaves a group that can be read and grabbed.
- **`LayoutOwner.fit`** re-runs that on every repaint, which covers editing a
  heading, zooming, and resizing the window. It moves the boundary only when
  the layout still matches the fingerprint the owner recorded: once the user
  has dragged the divider, where they put it wins for the life of the group.
  It refuses a boundary that another cell hangs off, so a row split elsewhere
  in the window is never dragged along, and it ignores moves under 1% of the
  window so an estimate that wobbles by a pixel does not relayout the window on
  every keystroke.
- **`stylesheet.PANEL_CSS`** trims the body padding to 0.8 rem for these two
  surfaces alone, and drops the card's margin. It lives beside `stylesheet()`
  rather than in `preview.css` because what it overrides is `body`, which no
  class can reach — each surface has its own phantom and so its own `<style>`.
- **`auto_width`** (default `true`) turns the whole thing off; with it off both
  surfaces ask for width 0.0, which `share_for` reads as "the role's share",
  and a group already on screen widens back to it.

## Consequences

The width is an estimate, and it is checked against real font metrics in
`tests/unit/test_measure.py` rather than against a screenshot. It leans wide by
design: overshooting costs a few pixels of preview, undershooting wraps a
heading, which is the thing being fixed.

A document whose longest heading genuinely needs the old share keeps it — this
README's table of contents is close to that case. The visible win is on the
outline, on wide windows, and on documents with short headings.

## Alternatives considered

**Ask minihtml.** There is no API for the natural width of a phantom, and no
event for a view being resized either; ADR 0007 already polls the viewport for
the same reason.

**Set the surfaces in the monospace stack so the width is exact.** It would
make the estimate unnecessary, and it would make the table of contents look
like a terminal listing rather than part of the rendered document.

**Fit once, at creation.** Simpler, but wrong within a keystroke: headings are
edited, the preview is zoomed, and the window is resized. Fitting on every
repaint costs one dictionary lookup and a fingerprint comparison when nothing
has changed.
