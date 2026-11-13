# 25. Automatic previews are opt-in and follow active file loads

Date: 2026-11-13

## Status

Accepted

## Context

Some users want a preview every time they open a Markdown file, without
changing the package's default workflow for everyone. MarkdownGlance keeps one
preview per window, and its focus listener also handles switching between
already-open source tabs. Opening automatically on every activation would
therefore reopen a preview as soon as a user returned to the source after
closing it, and could let background tabs steal the preview.

## Decision

Add the opt-in `auto_open_preview_on_open` setting, defaulting to `false`.
When enabled, the load event opens a side-by-side preview only if the loaded
Markdown source is the active view. Ordinary activation continues to use the
existing follow-focus behavior and never opens a preview by itself.

## Consequences

- Users can opt into a side-by-side preview when they open a Markdown file.
- Returning to an already-open source tab does not reopen a closed preview or
  take focus from the view the user selected.
- A window still owns one preview; opening another active Markdown file
  retargets it rather than creating another preview tab.
