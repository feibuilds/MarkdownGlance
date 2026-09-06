# 15. One preview and one panel per window, showing the focused document

Date: 2026-09-07

## Status

Accepted. Completes the direction of
[ADR 0014](0014-one-contents-panel-for-both-halves.md), which merged the two
side panels into one; this merges the *tabs*.

## Context

A `PreviewSession` owned a surface, and there was a session per Markdown
buffer. A window with three files open therefore had three "Preview: x.md"
tabs and, after ADR 0014, three "Contents: x.md" tabs -- each group's front tab
a matter of which document had been touched last. Two commits went into
deciding which tab should be in front and stopping the decision from
oscillating (`c6f59c6`, `b986f20`).

The argument was the wrong one to settle. A preview is not a document; it is a
view onto the current document. The same is true of the panel. Every editor
that ships a preview or an outline treats it that way, and the report that
started this said so plainly: with three files open the source group, the
preview group and the panel group could each be showing a different file.

Several things the code kept per session were per *pane* all along and were
wrong because of it. Zoom was per document and jumped when you switched files.
A window resize asked every open document to re-render for a width only one of
them was measured at. And a document rendering while nobody looked at it -- a
Replace All across a project, a reload from disk -- painted whatever finished
last onto whichever tab was in front.

## Decision

Split the document from the pane it is shown in.

- `PreviewStage` (`application/stage.py`), one per window: the surface, the
  document on it, the mode, the zoom, the table budget measured from its own
  width, and where each document was scrolled to when it was last shown.
- `PreviewSession` keeps what is genuinely per document -- generations, the
  parsed document, pending assets, theme, base path -- and loses
  `preview_surface`, `mode`, `zoom` and `table_budget`.
- `PanelStage` and `PanelDocument` split the panel the same way, and for the
  same reasons.
- `SessionManager` owns the stages, answers `for_surface` with the document on
  the surface, and decides which document goes on the stage; painting it is
  the use cases' job, reached through an `on_show` callback.

Focusing a Markdown source shows it. A document the window has never rendered
gets a session and a render; one it has already rendered is a repaint, which is
what makes switching back and forth cheap. The tab is retitled for what is on
it -- unlike the two halves of ADR 0014, where the name would have flickered
between two names for the same file, here the name *is* the answer to "what am
I looking at".

Every paint goes through a check that the document is the one on the stage, so
a hidden document's render reaches the panel's heading list and nothing else.

## Consequences

- A window has three groups and three tabs' worth of chrome however many
  Markdown files are open in it.
- `PhantomViewBackend.reveal` is gone, along with the focus round-trip that
  produced a 56-second ping-pong and the guards written to contain it. There is
  nothing left to reveal.
- Closing the preview tab closes the preview for the window; closing the
  source that is on screen puts another document up, and only the last one
  takes the surface down.
- Scroll position is saved as a fraction of the document's height, not a
  pixel: the document is laid out again at whatever width and zoom the pane has
  when it returns. There is no event for "minihtml has finished laying out",
  and `layout_extent` straight after `PhantomSet.update` can still describe the
  previous phantom, so the restore happens on the next tick and the document is
  at the top for that one frame.
- Measured before deciding, on this repository's own 69 KB design document:
  a switch between two rendered documents costs 0.1--0.5 ms of plugin time,
  against 227 ms to render one for the first time. The render is the expensive
  half, it is cached per document, and it was already being paid.
- Comparing two previews side by side is gone. It was available by dragging a
  tab into another group and is not worth a mode.
- Zoom is per pane, so it no longer jumps between documents; a resize asks for
  one render rather than one per document.
