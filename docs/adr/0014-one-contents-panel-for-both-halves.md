# 14. One contents panel, showing the half the focus asks for

Date: 2026-09-07

## Status

Accepted. Supersedes the two-surface arrangement in
[ADR 0010](0010-source-outline-and-ctrl-shift-b.md), whose toggle, key and
Zed-style three-press behaviour all survive; only what they open has changed.

## Context

There were two heading lists. The table of contents belonged to a
`PreviewSession`, was built from the rendered document, took a group of its
own, and scrolled the preview when clicked. The outline (ADR 0010) belonged to
a source buffer, was scanned out of the raw Markdown, took a *second* group of
its own, followed the caret, and moved the caret when clicked.

One document with both open therefore occupied four editor groups, and the two
lists showed nearly the same headings. Worse, whichever list you were not using
sat in front of you: with two documents previewed at once, each shared group's
front tab belonged to whichever document was opened last, which the focus fix
of 2026-09-06 addressed by revealing the right tab. Revealing the right tab of
the wrong list is not much of an answer.

The difference between the two was never the list. It was two behaviours:
**where a click goes**, and **whether there is a "you are here"**. Both follow
the focus, not the surface.

## Decision

One panel per document, one panel group per window, one surface, two halves:

- **Source focused** -- the outline. Scanned from the buffer, follows the
  caret, clicking moves the caret. It works with no preview open at all, which
  is why the panel is keyed on the source buffer and not on a preview session.
- **Preview focused** -- the table of contents. The last render's headings;
  clicking scrolls the preview.

Switching halves is a repaint of one surface, not a reveal of another tab.
`GroupRole.TOC` and `GroupRole.OUTLINE` collapse into `GroupRole.PANEL`, and
`LayoutOwner.acquire_panel` walks right from the document's own group, past
groups this owner made for previews, stopping at the first group it did not
make: one panel group per window, and never a tab in a pane the user opened.

`enable_toc` now governs only whether a panel opens **by itself**. One opened
with `Ctrl+Shift+B` shows both halves whichever way the setting is set: a panel
the user asked for that emptied half of itself on a focus change would be
stranger than one that does not.

## Consequences

- A document with everything open takes three groups, not four.
- `PreviewSession` loses `toc_surface`, `toc_group` and `toc_dismissed`, and
  `SessionManager` loses `drop_toc`. The panel keeps its own dismissal set,
  cleared when the preview closes or when the user asks for a panel again.
- The command id stays `mdglance_toggle_outline` and the key stays
  `Ctrl+Shift+B`: people have had them bound since 0.3.0. The palette caption
  and the context key (`mdglance.panel_focused`) do change.
- The tab is named `Contents: <file>` in both halves. Renaming it on every
  focus change would be the flicker this decision exists to avoid.
- Two defects fell out of the restructure and are fixed with it. `LayoutOwner`
  reused *any* group of its own to the right of the source, so opening a
  preview after the panel put the preview inside the panel's group, and the
  command looked as though it had done nothing; a group is now reused only for
  its own role. And `window.new_file()` focuses the view it makes, so a panel
  opened by a render took the caret with it; the focus is now read before the
  surface exists and given back afterwards.
- Still open: closing the panel after the layout has moved leaves an empty
  pane. See [the note](../todos/empty-pane-after-a-panel-closes.md).
