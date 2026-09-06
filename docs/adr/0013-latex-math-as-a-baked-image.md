# ADR 0013: LaTeX math as a baked image

## Status

Accepted.

## Context

[Issue #2](https://github.com/pandadolphin/MarkdownGlance/issues/2) asks for
LaTeX math in the preview. The preview is drawn by minihtml, which runs no
JavaScript, lays out no MathML and decodes no SVG, so KaTeX and MathJax are
not available to it and neither is their output. What minihtml can show is a
PNG, and the package already has a path for an image a server typesets from
document text: Mermaid ([ADR 0005](0005-mermaid-default-and-privacy.md)).

Typesetting locally is not an option either. The plugin host has no TeX, no
matplotlib and no numpy, and the package accepts no dependency beyond the two
Package Control libraries it declares
([ADR 0012](0012-package-control-markdown-library.md)).

## Decision

- **Parsing** is `pymdownx.arithmatex` in generic mode, which is part of
  `pymdown-extensions` and so already installed. It finds `$...$`, `$$...$$`,
  `\(...\)` and `\[...\]` and wraps each in an element with class
  `arithmatex`; its default `smart_dollar` leaves `$5 and $6` alone. The
  extension is always on, so the dialect does not change with the setting:
  what changes is what the structural pass does with the element.

- **With `enable_math` off** (the default), a formula is shown as its source:
  inline as `<code class="math">$...$</code>`, display as a
  `<pre><code class="math">` block. This mirrors a disabled Mermaid fence,
  which stays readable code.

- **With `enable_math` on**, the structural pass replaces each element with an
  `img` whose `AssetKey` is of kind `MATH` and whose locator is a
  `math_server` URL carrying the formula. The default server is
  `https://latex.codecogs.com`, whose `png.image` endpoint takes the formula
  as the query string, honours `\dpi{}` and `\color[RGB]{}`, and draws on a
  transparent background. A display formula is prefixed with `\displaystyle`
  and collapsed to one line. The image goes through the same fetcher, policy,
  cache, executor and generation controls as a remote image or a diagram.

- **Colour.** The formula is typeset in the colour scheme's foreground, which
  is baked into the PNG the way a diagram's background is. The background is
  transparent, so only the foreground is part of the URL: a scheme change
  that moves the foreground re-renders a document with a formula in it, one
  that moves only the background does not.

- **Size.** The image is fetched at 230 dpi, twice the size it is shown at,
  and the serialiser halves its `width`, `height` and rem size, so that it is
  as crisp as the text beside it on a high-DPI display. LaTeX's 10 pt body at
  115 dpi is about the height of the preview's 16 px text.

- **Privacy** follows ADR 0005 exactly. `enable_math` defaults to `false`;
  `math_server` must be HTTPS; the settings file, the install note, the README
  and SECURITY.md say that enabling it sends formula source to the server; the
  first pending or failed formula in each render carries a one-time host-only
  caption; the locator is never logged, since its query string is the
  formula, and `AssetKey.safe_label` carries only the host.

- **Inline placement.** minihtml gives no control over an image's baseline, so
  an inline formula sits on the line as an image does, slightly high. While
  it loads, or when it cannot be fetched, its placeholder is a `span` rather
  than the block placeholder other assets get, so the sentence keeps its
  shape.

## Consequences

- A formula renders only with a network connection and only when the user has
  opted in, the same trade-off as a diagram. Offline or blocked, it reads as
  its source.
- Invalid LaTeX is a server error, which the preview shows as `Unavailable`.
  The server does not say what was wrong.
- `Open in Browser` now writes arithmatex's generic output, `\(...\)` and
  `\[...\]`, which is what MathJax and KaTeX auto-render expect. The page
  loads neither, so a browser shows the delimiters as text; adding a renderer
  to the export page is a separate change.
- The scope statement in CONTRIBUTING.md still holds: no browser, no WebView,
  no process, no new dependency. Like Mermaid, this is a network fetch of an
  image, under the same limits.
