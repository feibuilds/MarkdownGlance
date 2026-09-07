# 17. An image minihtml cannot draw says so, and nothing rasterises it

Date: 2026-09-07

## Status

Accepted in part. Records the limit
[ADR 0013](0013-latex-math-as-a-baked-image.md) worked around for formulas,
and the two ways of lifting it that were considered and refused.

The naming below still holds. The refusal does not:
[ADR 0019](0019-svg-is-drawn-by-a-local-renderer.md) draws an SVG with a local
renderer, so "nothing rasterises the image" and the consequences that follow
from it are superseded for SVG. The other formats named here -- WebP, BMP,
TIFF, ICO, AVIF, HEIC -- are still reported rather than drawn.

## Context

A user reported that SVG images do not appear in the preview, while the same
document opened with **Open in Browser** shows them.

minihtml decodes PNG, JPEG and GIF and nothing else: the official
documentation lists exactly those three, and it was confirmed on build 4200
that an SVG in an `img` draws as a broken-image icon whether it arrives as a
`file://` path, a base64 `data:` URI or an unencoded one. There is no
JavaScript, no `svg` element and no CSS image path to fall back on, and
Sublime's own `image_file_patterns` does not list `svg` either, so opening the
file as an image in the editor is not an escape route. This is the same wall
ADR 0013 hit for MathML and KaTeX, and ADR 0005 for Mermaid's own SVG output.

What was wrong was the report. `detect()` in `assets/images.py` identifies an
image by its signature, and anything it did not recognise raised
`InvalidImage`, which both call sites folded into `AssetStatus.UNAVAILABLE` --
"Unavailable", the same words as a missing file or a dead link. The reader was
told the wrong thing about a file that is present and intact.

The common case is not a local drawing. It is a remote badge: the three
shields.io badges at the top of this project's own README are SVG, and so is
most of what a README links from a badge service.

## Decision

**Name the failure.** `detect()` sniffs the formats a browser draws and this
preview cannot -- SVG, WebP, BMP, TIFF, ICO and the ISO base media family
(AVIF, HEIC) -- and raises `UnsupportedImage`, a subclass of `InvalidImage` so
that a caller which only asks for a drawable image is unchanged. The two that
report a status to the reader, `AssetResolver._read_local` and
`ImageFetcher.fetch`, catch it first and return a new
`AssetStatus.UNSUPPORTED_FORMAT`, whose placeholder reads:

> **Not a PNG, JPEG or GIF** — The preview cannot draw it; Open in Browser can.

The detection is by bytes, not by extension: a `.svg` may be a renamed PNG and
a `.png` may be an SVG, and the MIME type in the `data:` URI has to match the
bytes either way. SVG is found by walking the prologue -- BOM, XML
declaration, comments, DOCTYPE -- to the root element, rather than by
searching for `<svg`, so that an HTML error page served where an image was
expected is still reported as the broken link it is even when it has an inline
icon in it.

**Nothing rasterises the image.** Two ways of actually drawing an SVG were
considered and both refused:

- *Converting locally* with `rsvg-convert`, Inkscape, CairoSVG or headless
  Chromium, behind an opt-in setting. This contradicts the scope this project
  publishes -- "no browser, no WebView, no external process" in CONTRIBUTING.md,
  and "Open in Browser is the one command that starts a process" in
  SECURITY.md -- and an opt-in does not lift that, because the promise is about
  the preview path itself. It would also move local images off the UI thread
  and onto the executor, since a subprocess cannot run there; a user-supplied
  command line is an arbitrary-execution hole in a settings file; an SVG is
  untrusted input and every one of those converters either fetches external
  references or has a CVE history, or both; and the users it would help are
  the ones on a machine that already has such a tool, rarely Windows.

- *Converting remotely*, through an image proxy, in the manner of ADR 0005 and
  ADR 0013. A diagram or a formula is text the document's own author wrote and
  the user chose to send; an image is a file that may be private, and the
  proxy pattern only reaches `http(s)` URLs anyway, never the local file that
  prompted the report.

The escape route is the one the reporter had already found: **Open in
Browser** writes the parser's own output, which never passes through
`detect()`, so every format the browser draws survives into the exported page.

## Consequences

- A reader with an SVG or a WebP in a document is told what the file is and
  what to do about it, and can convert it to PNG or export the page. Neither
  the package's dependencies nor its process count changes.
- The new status is not in `POLICY_DERIVED`: it does not depend on settings,
  so a settings change does not re-evaluate it. It is negatively cached for
  the usual 30 seconds like any other failure, which costs one re-read of a
  local file's first 2 KiB and no network.
- `detect()` now reads 2 KiB rather than 32 bytes, to see past an SVG
  prologue. Every binary signature it knows still lies in the first 12.
- WebP in particular changes behaviour without anyone asking: it is common on
  the web today and used to read as "Unavailable".
