# 24. Task-list checkboxes are theme-styled, read-only spans

Date: 2026-11-13

## Status

Accepted

## Context

Python-Markdown treats `[x]` and `[ ]` as ordinary list text unless the
`pymdownx.tasklist` extension is enabled. That extension emits HTML
`<input type="checkbox">` elements, but Sublime Text's minihtml does not
implement form controls. Passing those elements through would either leave the
source markers visible or drop the checkbox entirely.

## Decision

Enable `pymdownx.tasklist` and translate its checkbox input nodes into spans
with checked/unchecked classes. The preview stylesheet draws a theme-coloured
box and a check mark for completed items. The Markdown source remains
unchanged.

The preview is read-only: clicking a box cannot update the source. Users edit
`[x]` or `[ ]` in Markdown, and the live preview reflects the change.

## Consequences

- GFM-style task lists render as web-like checked and unchecked boxes in the
  native Sublime preview, including inside nested lists.
- No HTML form control, JavaScript, or extra dependency is introduced.
- This is visual representation only; browser-like checkbox interaction is
  outside minihtml's capabilities.
