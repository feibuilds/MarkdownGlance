# MarkdownGlance architecture

## Boundaries

`adapter` translates Sublime commands and events into use cases. `application`
owns sessions, scheduling and orchestration through ports. `domain`, `renderer`
and `assets` are independently testable Python. `presentation` owns native
surfaces and layout bookkeeping.

The selected backend is a read-only scratch `View` containing one block
`Phantom`. Heading position ratios provide programmatic TOC navigation. Layout
ownership is fingerprinted; restoration occurs only for an empty, unchanged,
plugin-created group after its last holder closes.

A window outlives the process that arranged it: Sublime persists the layout and
not the scratch surfaces standing in it. `presentation/window_record.py` keeps
one entry in `window.settings()` -- the groups this package made, under their
roles, the cell count they were made in, and the document and zoom on the
preview -- which Sublime does persist. On the way back in, `UseCases.restore`
fills those panes again and `LayoutOwner.reclaim` takes away the ones it
cannot. See [ADR 0018](adr/0018-groups-outlive-the-process-that-made-them.md).

The table of contents and the outline are sized to their content rather than to
a fixed share of the window. `renderer/measure.py` estimates the pixels the
longest entry needs from per-character advances, and `LayoutOwner.acquire` and
`LayoutOwner.fit` turn that into the boundary between the group and the one it
was split from — never wider than the role's share, never past the point where
the fingerprint says the user has moved the divider by hand.

A `PreviewSession` is a document, not a pane: its generations, its parsed
document, its assets, its theme. The pane is a `PreviewStage`, one per window,
holding the surface, which document is on it, and everything that belongs to
the viewport rather than to any document -- the mode, the zoom, the table
budget measured from its width, and where each document was scrolled to. That
is what lets a window hold ten Markdown files and one preview tab.
`SessionManager` owns the stages and decides which document goes on one; the
use cases paint it, through `on_show`. Every paint asks `_showing_stage` first,
so a document rendered while nobody is looking at it -- a Replace All across a
project, a reload from disk -- reaches the panel's heading list and no surface.

A second, independent surface is the contents panel: `application/panel.py`
splits the same way -- a `PanelDocument` per Markdown buffer, a `PanelStage`
per window -- reaching the host only through injected read-text, read-caret and
reveal-line callables. It shares the
backend, the layout owner and the stylesheet with the preview, and nothing
else: no render, no assets, no generations. `SessionManager.reconcile` asks
`foreign_surface` before closing an owned surface it does not recognise, which
is how panel surfaces survive a sweep run for previews.

The panel draws one of two halves, chosen by which tab the window has settled
on. With the source focused it draws the outline `renderer/outline.py` scans
out of the raw Markdown -- ATX and setext headings by line, so every entry maps
to a row the caret can move to -- and with the preview focused it draws
`renderer/toc.py`'s table of contents over the headings the last render
produced. `UseCases.present` pushes each rendered document in through
`document_rendered`; the panel never reaches back for one, and a preview that
closes takes only the half that belonged to it. Both halves are one surface in
one group, so switching is a repaint and nothing moves on screen.

## Reliability and safety

Each immutable `RenderRequest` contains a generation. A session has at most one
render in flight; edits coalesce and the newest requested generation dispatches
immediately after completion. Results return to the UI thread and are applied
only to a live session at its current generation.

Asset fetching uses a separate four-worker executor, a 64 MiB in-memory LRU,
30-second negative caching, HTTPS by default, at most five redirects, a 15-second
timeout, 10 MiB response limit, and 4096 px dimension limit. Only
`AssetKey.safe_label` is diagnostic-safe; Mermaid and math locators are never
logged, since each carries document text.

Decision details and experiment evidence are in the repository-level
`docs/adr/` directory.
