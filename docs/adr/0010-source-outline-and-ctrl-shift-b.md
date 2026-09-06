# ADR 0010: An outline over the Markdown source, on `Ctrl+Shift+B`

## Status

Accepted, and superseded in part by
[ADR 0014](0014-one-contents-panel-for-both-halves.md) on 2026-09-07: the
outline is now one half of a single contents panel rather than a surface and a
group of its own. The key, the toggle behaviour and everything below about
*why* a source outline exists at all still hold; the second group and
`acquire_beside` do not.

Extends ADR 0001 (presentation backend) and ADR 0009 (the one key this package
takes outside its own views).

## Context

The table of contents built in `renderer/toc.py` comes out of the parsed
preview document. It therefore exists only once a preview is open and a render
has succeeded, it appears only when `toc_minimum_length` and
`toc_minimum_headings` are both met, and it navigates the *preview*.

None of that helps the case this decision is about: a long Markdown file being
written, with no preview open, where the user wants to see the shape of the
document and jump around inside the source. Zed calls that the outline panel;
it lists the raw headings beside the editor, marks the one holding the cursor,
and moves the cursor when an entry is clicked.

## Decision

Ship a second, independent surface: the **outline**, over the source buffer.

- `renderer/outline.py` scans raw Markdown line by line — ATX and setext
  headings, skipping fenced code and YAML front matter — and returns
  `SourceHeading(level, text, ordinal, line)`. A line number, not a position
  ratio, because the target is a text buffer with a caret, not a rendered page.
- `application/outline.py` owns `OutlineController`, keyed by source buffer.
  An outline is deliberately not a `PreviewSession`: it needs no render, no
  asset resolution, and no generation bookkeeping, and it must work for a file
  that has never been previewed. It reaches the Sublime API only through three
  injected callables — read the text, read the caret row, reveal a line.
- The surface is the same phantom-in-a-scratch-view backend the preview uses,
  with role `outline`, so theming, closing and layout ownership are unchanged.
  It is acquired *beside* everything already in the row (`acquire_beside`), so
  an outline never lands as a second tab in the preview's group.
- `SessionManager.reconcile` closes owned surfaces it does not recognise. It
  now asks `foreign_surface` first, which is how outline surfaces survive a
  sweep run for previews.

## The key

`Ctrl+Shift+B` / `Cmd+Shift+B`, guarded by `mdglance.markdown_source` or
`mdglance.outline_focused`, and toggling the way Zed's does: open and focus,
focus if already open, close on a press from inside it.

Sublime Text's default for that stroke is `build` with `select: true` — the
**Build With…** picker. Measured in build 4200:

| Binding | Sublime Text default |
| --- | --- |
| `ctrl+shift+b` | `build` (`select: true`), i.e. Build With… |
| `ctrl+b` | `build` |

The override is narrow in the same way ADR 0009's is: it applies while a
Markdown source view or this package's own outline is focused, and nowhere
else. Markdown has no build system, so Build With… in a Markdown buffer costs
a user nothing they were using, and `Ctrl+B` — plain Build — is untouched
everywhere. The key was requested explicitly because it is what Zed binds the
outline panel to, and matching it is the whole point of the feature.

The `SINGLE_STROKE_OUTSIDE_PREVIEW` gate in `tests/unit/test_package_identity.py`
names this key, so a third one cannot be added without a decision like this.

## Consequences

- Two different lists of headings ship in one package. They are not merged:
  the TOC navigates the rendered preview by position ratio and appears
  automatically; the outline navigates the source by line and appears only
  when asked. Both can be open at once, in separate groups.
- The scanner is a second Markdown parser, of one construct. It is a line
  scanner over raw text on purpose — it has to run on a buffer mid-edit, must
  never block the UI thread, and must report lines that markdown2's HTML
  cannot give back.
- One outline per source buffer. It follows the caret and the edits of that
  buffer, and is revealed when its source is activated; it does not re-target
  itself at whatever file is now in front, which is where it differs from
  Zed's single dockable panel.
- `Ctrl+Shift+B` no longer opens Build With… in a Markdown buffer. The
  binding is one entry in **Preferences → Package Settings → MarkdownGlance →
  Key Bindings**, and `MarkdownGlance: Toggle Outline` is in the command
  palette without it.
