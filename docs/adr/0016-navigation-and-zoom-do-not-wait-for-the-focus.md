# 16. Navigation and zoom follow attention, not focus

Date: 2026-09-07

## Status

Accepted. Corrects a premise of
[ADR 0014](0014-one-contents-panel-for-both-halves.md), whose panel is
unchanged; only what a click on it does.

## Context

A user reported that the only way to focus the preview is to click its tab,
which reads as pointless now that there is exactly one preview tab
([ADR 0015](0015-one-preview-and-one-panel-per-window.md)), and asked for a
click on the preview's content to focus it instead.

Measured in a real Sublime Text with synthetic pointer clicks, reading
`window.active_view()` by id:

| clicked | focus moves |
| --- | --- |
| the preview's rendered content | no |
| the bare strip of view below the phantom | yes |
| the preview's tab | yes |
| (control) the source's text | yes, caret moved |

The content is one `LAYOUT_BLOCK` minihtml phantom and it consumes the press;
the view never sees it. The only click hook a phantom has is `<a href>`
(`PhantomViewBackend._navigator`), and wrapping the body in one anchor would
nest anchors inside the heading links and give every paragraph link styling.
So the request cannot be granted as put.

Asked what the focus was *for*, the user said: to get the panel onto its
table-of-contents half, so that clicking a heading jumps to that section; and
to make the zoom keys act on the preview.

That reframes the defect. **A preview is read by scrolling, and the wheel does
not move the focus.** So the reader is looking at the preview while the source
still holds the focus, the panel is therefore showing its outline half, and
clicking an outline entry moved the caret and left the preview where it was.
The jump never happened. Focus tracks where you last clicked or typed;
attention tracks what you are reading. ADR 0014 keyed behaviour on the first
and the user needs the second, and no amount of making the preview easier to
focus would have fixed that -- they would still have to remember to click it.

## Decision

**A panel entry is a place in the document, not a place in one pane.** Clicking
one moves the caret to its line *and* scrolls the preview to it, from either
half, whichever view has the focus. Neither move takes the focus: `reveal_line`
sets a selection and centres it, and scrolling the preview is a viewport move.
An in-body `#slug` link click moves the caret too, for the same reason.

The two lists are paired by a **monotone alignment** on (level, normalised
text), in `renderer/align.py`, not by ordinal. Over this repository's 47
renderable Markdown files the lists were always the same length with the same
levels -- but a heading inside a raw `<h2>` block or a block quote is in the
render and not in the scan (both measured), and one of those in a long document
would put a positional pairing off by one for every heading after it. `difflib`
finds the entries that correspond, in order; anything it cannot pair navigates
only its own pane. The source text has its inline markup stripped first: 9 of
those 47 files have a heading that differs only by that.

For zoom, the keys reach the preview from the Markdown source as well, under a
new `mdglance.preview_open` context -- so the binding costs the user their font
size key only while there is a preview in the window for it to act on.
`mdglance.preview_focused` is now asked about the view the event is *about*
rather than the window's active sheet, which for a mouse binding is the view
under the pointer: `Ctrl`-scrolling a preview you are reading zooms it without
focusing it first.

## Consequences

- Clicking a panel entry moves the source caret even when the reader is in the
  preview. No buffer edit, no undo entry, but any selection or multi-caret in
  the source is replaced, and Sublime records no jump, so `jump_back` will not
  return you. Both were already true of the outline half.
- `ctrl+0` is deliberately **not** bound in the source: it falls through to
  `focus_side_bar`, which has no other default key on Linux. Reset zoom still
  works from inside the preview or the panel.
- With a preview open, `ctrl+=` and `ctrl+-` in a Markdown source no longer
  reach Sublime's own font size -- which, note, changes the *global*
  `font_size` preference and writes it to `Preferences.sublime-settings`, and
  never had any effect on the preview, whose root font size is pinned in
  `renderer/stylesheet.py`. The menu and any non-Markdown view still reach it.
- Focus still decides which *half* the panel draws, and still decides nothing
  else. That distinction is now presentational: which typeface, and which
  "you are here".
