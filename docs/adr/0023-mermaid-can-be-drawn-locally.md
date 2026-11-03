# 23. A Mermaid diagram can be drawn here

Date: 2026-10-29

## Status

Proposed. Extends [ADR 0005](0005-mermaid-default-and-privacy.md), which
stands for the server path, and takes the shape of
[ADR 0019](0019-svg-is-drawn-by-a-local-renderer.md).

## Context

Turning diagrams on sends their source to `mermaid_server`. Two command line
tools draw a diagram with no service at all: **merman-cli**, a native Rust
implementation of Mermaid with its own rasteriser, and **mmdc**, from
mermaid-cli, which runs Mermaid itself in a headless Chromium.

## Decision

**A setting names the renderer, and set, it replaces the server.**
`mermaid_renderer_path` is empty by default, which keeps ADR 0005's behaviour.
It names an executable -- a path, or a bare name looked up on the `PATH` --
never a command line. `enable_mermaid` stays the switch, off by default.

**Local means local.** With a renderer named, a diagram's locator is
`mermaid-local:<payload>?theme=…&bgColor=…`, which only the renderer's job
reads; nothing builds a server URL. A renderer that is missing, fails or times
out says so in place -- *No Mermaid renderer*, *Could not be drawn*, *Timed
out* -- and nothing falls back to the network. No privacy caption is shown.

**PNG straight from the renderer, with mmdc's arguments.** `-i - -o - -e png
-t <theme> -b #<bg> -c <config> -s <scale> -q`, diagram on stdin and PNG on
stdout. merman-cli accepts mmdc's arguments, so the package does not tell the
two apart. Not SVG through resvg: both tools write flowchart labels into
`<foreignObject>`, which resvg drops without an error, leaving every box and
none of the text.

**The look of mermaid.ink.** Theme and background come from
`diagram_appearance()`, so a colour scheme change behaves as it does with the
server. `mermaid_look` (`classic` by default) pins Mermaid's look in the
payload, for the server and a local renderer alike, because merman follows
Mermaid 12, whose default `neo` look draws gradient borders and shadows. mmdc
has no flag for it, so it goes in a `-c` file written for the run and removed
after it.

**Drawn as an SVG is.** On the asset pool, not the UI thread, bounded by
`mermaid_timeout_seconds` (default 10), at twice the size it is shown at with
`pixel_scale` to match, and drawn again smaller if that is over
`remote_max_dimension`. The locator carries the diagram and its appearance,
so the asset cache keeps one PNG per diagram and appearance, and typing
elsewhere in the document does not redraw it.

## What each renderer cannot draw

- **merman-cli** (0.9.2 checked): every diagram type, zenuml and the beta
  types included. Inline HTML in a label -- `<b>`, `<i>` -- is drawn as plain
  text, and a Font Awesome icon (`fa:fa-car`) is dropped without an error.
  Text width is estimated rather than measured, so a label can wrap where a
  browser would not.
- **mmdc** is Mermaid in Chromium and draws what Mermaid draws. Its cost is a
  browser per run -- about 0.9 s per diagram on an Apple Silicon Mac, around
  2 s on a first run, against about 0.5 s for merman-cli -- plus Node and a
  Chromium download to install it.

## Consequences

- Diagrams can be on with nothing leaving the machine.
- The package starts a process in a third place: opt-in, bounded by a
  timeout, and given only its own arguments.
- Editing a diagram draws each version the debounce lets through. The cache
  and the in-flight table stop an unchanged one being drawn twice, not a
  changing one being drawn often.
- The renderer's stderr is not shown; a syntax error reads *Could not be
  drawn*. Showing the message would need a failed asset to carry text.
