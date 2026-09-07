# Security policy

## Supported versions

The latest released version is the only one that receives fixes.

## Reporting a vulnerability

Report privately through GitHub's
[security advisory form](https://github.com/pandadolphin/MarkdownGlance/security/advisories/new).
Please do not open a public issue for a vulnerability. Expect an
acknowledgement within a week.

## What the package touches

MarkdownGlance renders Markdown inside Sublime Text. Two features leave the
machine, and both are bounded:

- **Remote images** are fetched off the UI thread under scheme, redirect,
  timeout, payload and dimension limits, and are cached only in memory.
  Insecure schemes are blocked by default.
- **Mermaid rendering** is disabled by default. Enabling it sends diagram
  source to the configured Mermaid server.
- **LaTeX math rendering** is disabled by default. Enabling it sends formula
  source to the configured math server.

**SVG images** are converted to PNG by a renderer on your machine — `resvg`
on the `PATH`, or the executable named by `svg_renderer_path`. The setting is
a path, not a command line: the arguments are the package's own. The image is
never uploaded. The renderer is run off the UI thread with a timeout, its
output is bounded by the same dimension limit as any other image, and it is
given the document's own directory only for a local file, so an SVG from the
network cannot pull a file of yours into the image. `"enable_svg": false`
stops it running at all.

`MarkdownGlance: Open in Browser` starts a process too: it writes the document
as a standalone page under the temporary directory and hands it to the default
browser. The page is the parser's own output, not the
sanitised body the preview shows, since it is the user's own file opened
locally. Raw HTML and scripts in that file run in the browser, as they would in
any other Markdown-to-browser tool. When the document has a Mermaid fence or
a formula, the page also loads Mermaid and KaTeX from `cdn.jsdelivr.net`, at
a pinned release with a subresource integrity hash, and renders them in the
browser; the document itself is not sent to the CDN or anywhere else.

`MarkdownGlance: Copy Diagnostics` redacts source text, paths, URLs and Mermaid
payloads before anything reaches the clipboard.
