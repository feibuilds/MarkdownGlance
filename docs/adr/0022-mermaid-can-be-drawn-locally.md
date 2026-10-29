# 22. A Mermaid diagram can be drawn here

Date: 2026-10-29

## Status

Accepted. Extends [ADR 0005](0005-mermaid-default-and-privacy.md), which
stands for the server path, and follows the shape of
[ADR 0019](0019-svg-is-drawn-by-a-local-renderer.md).

## Context

A Mermaid diagram reaches the preview as a PNG baked by `mermaid_server`, so
turning diagrams on means sending their source to mermaid.ink or to a server
of the reader's own. Running mermaid.ink locally is not a way round that: the
setting accepts HTTPS only, the plugin host's default SSL context does not
trust a locally minted certificate, and the server itself is a Koa service
driving headless Chrome -- more to run, and more listening on a port, than a
preview should ask for.

Two command line renderers can draw a diagram as a PNG with no service at
all:

- **merman-cli**, a native Rust implementation of Mermaid's parser, layout
  and SVG output, with its own rasteriser. A single binary, about 30 ms for a
  typical diagram. It does not run a browser, so text measurement and HTML
  labels can differ slightly from Mermaid in one.
- **mmdc**, from mermaid-cli, which runs Mermaid itself in headless Chrome.
  Exact, but it starts a browser on every run: a second or more, and Node and
  a Chrome download to install.

merman-cli accepts mmdc's arguments as well as its own, and produces the same
PNG for them.

## Decision

**A setting names the renderer; set, it replaces the server.**
`mermaid_renderer_path` is empty by default, which keeps ADR 0005's
behaviour. A bare name is looked up on the `PATH`, anything else is a path to
an executable. As with `svg_renderer_path`, it names an executable and never a
command line.

**One command line, mmdc's.** `-i - -o - -e png -t <theme> -b #<bg> -s <scale>
-q`, with the diagram on stdin and the PNG on stdout. Both renderers accept
it, so the package does not need to know which one it has. The renderer's
own directory is put first on the child's `PATH`, so that mmdc, a Node script,
finds the `node` a global npm install put beside it.

**The locator carries the diagram, under a scheme of its own.**
`mermaid-local:<payload>?theme=…&bgColor=…`, with the server's payload. The
theme pair is part of it for the reason it is part of the URL: the image is
baked, and two schemes that differ there need two images. It is never opened;
the job that runs the renderer reads the diagram back out of it. The policy
lets it through whenever `enable_mermaid` is on, and the serialiser shows no
privacy caption for it.

**Drawn as an SVG is.** Off the UI thread on the network pool, at twice the
size it is shown at, with `mermaid_timeout_seconds` (default 10) ending a run
that will not finish. A PNG over `remote_max_dimension` is drawn once more at
whatever factor fits, down to one, and is *Too large* only after that.

**The look is pinned, to `classic` by default.** merman follows Mermaid 12,
whose default is the gradient-bordered `neo` look; mermaid.ink runs Mermaid 11,
whose default is `classic`. `mermaid_look` goes into the diagram's payload,
and so into its locator and the server's URL alike, and reaches a local
renderer as a `-c` configuration file written for the run and removed after
it: mmdc has no flag for it. Changing renderer therefore does not change how a
diagram looks.

**Two statuses of its own.** *No Mermaid renderer*, which follows settings
and is re-evaluated when the policy revision moves, and *Could not be drawn*
with a note pointing at the diagram's syntax, which is what a non-zero exit
almost always means while the reader is typing.

## Consequences

- Diagrams can be on with nothing leaving the machine, which is what the
  privacy caption and the opt-in default existed to warn about.
- The package starts a process in a third place. It is opt-in, bounded by a
  timeout, and given only its own arguments.
- merman-cli's output is close to Mermaid's but not identical; mmdc is there
  for a reader who needs the browser's rendering and can wait for it.
- The renderer's stderr is not shown. A syntax error reads *Could not be
  drawn*; the message itself is a possible follow-up, and would need a way
  for a failed asset to carry text.
