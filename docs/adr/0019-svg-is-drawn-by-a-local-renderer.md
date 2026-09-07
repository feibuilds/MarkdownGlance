# 19. An SVG is drawn here, by a renderer of its own

Date: 2026-09-07

## Status

Accepted. Supersedes the second half of
[ADR 0017](0017-formats-minihtml-cannot-draw.md) -- "nothing rasterises the
image" -- and with it the "no external process" clause of the scope in
CONTRIBUTING.md, for this feature. The first half of ADR 0017 stands: the
formats minihtml cannot decode are still recognised by their bytes, and the
ones with no way through still name themselves.

## Context

ADR 0017 answered the report -- SVG images do not appear in the preview -- by
making the placeholder honest. That was the smaller half of the problem. The
reader's document still has a hole where the architecture diagram is, and the
badges at the top of a README are still three grey boxes.

The argument for refusing to rasterise rested on a promise the package makes
about itself rather than on anything the reader wants: no browser, no WebView,
no external process. It is a good promise for the *preview path* -- Markdown
in, minihtml out, on the UI thread -- and a poor reason to leave a class of
images undrawn. Two things were also checked and found not to be blockers:

- **Package Control can distribute a native dependency.** Its library
  mechanism carries Python modules, shared libraries and binaries, and version
  4 installs wheels from PyPI and from GitHub releases. What it does not do is
  make a PyPI name work by adding it to `dependencies.json`: the library has to
  be registered in a channel, with its versions and platforms declared. That is
  a maintenance job, not an obstacle in principle.
- **An in-process binding cannot serve the supported range today.** The
  package supports build 4200 and up; `.python-version` selects the 3.8 plugin
  host, and from build 4205 the newer host is Python 3.14. `resvg_py` 0.5.0 and
  CairoSVG 2.9.0 both require Python 3.10 or later, so neither can be installed
  into the 3.8 host that a supported build still runs.

Of the renderers, resvg is the one to build on: it is aimed at static SVG, it
is a single self-contained binary with no Cairo or system graphics stack
underneath it, and it is offered as a Rust library, a C library and a command
line tool, so the way it is called can change later without changing what the
reader sees. CairoSVG's Python API is the more convenient of the two, but the
dependency underneath it is not, and its own documentation limits its filter
and text support.

## Decision

**Draw the SVG here, as a PNG, and show that.** `assets/svg.py` holds the
whole of it behind one call -- bytes and a directory in, PNG bytes and the
factor they were drawn at out -- so that the rest of the package does not know
whether a library or a process produced them.

**Run it as a child process, for now.** The alternative is a native library in
the plugin host, which needs the Python-runtime work above before it can start.
A process also buys two things a binding would not: `subprocess.run(...,
timeout=...)` ends a run that will not finish, and a renderer that dies on a
malformed file takes a child with it rather than Sublime Text.

**One path for local and remote.** A local file is read as it always was; a
remote one is fetched under the existing scheme, redirect, timeout and size
limits. Whichever it is, the bytes that turn out to be SVG go to the same
renderer on this machine. Nothing is uploaded, no service or account is
involved, and the document's own image reference is left alone.

**Off the calling thread.** A local image is still read in the thread that
asked for it, which is where a PNG comes from today. An SVG cannot be: it needs
a process. `AssetResolver` hands it to the same pool a remote image uses, the
reader sees *Loading*, and the render that follows the drawing shows it. Two
documents referencing the same drawing wait on one run, as they do for a fetch.

**Drawn at twice the size, bounded by the limit that already exists.** The
renderer is asked for `--zoom 2` and the serialiser shows the image at half
what came back, so a diagram's text is as crisp as the text beside it on a
high-DPI display and survives a zoom step; this is what a formula already does
(ADR 0013). The factor is reduced when twice the intrinsic size would pass
`remote_max_dimension`, which is read out of the file's own `width`, `height`
or `viewBox` before anything is run, so a drawing that declares 20000 px does
not become a 40000 px raster in a subprocess.

**A local drawing may read its siblings; one from the network may not.** A
local SVG is drawn with `--resources-dir` set to the directory the file sits
in, so an `<image href="logo.png">` inside it resolves the way it does in a
browser. Anything from the network is drawn against an empty directory of the
package's own, so a relative reference in a file from elsewhere reaches nothing
on this machine.

**Three settings, and a path that is only a path.** `enable_svg` (on) turns the
feature off; `svg_renderer_path` names an executable when it is not on the
`PATH`; `svg_timeout_seconds` (10) bounds a run. The path setting is a path:
the arguments are the package's own, so a settings file cannot become a command
line.

**Three answers rather than one.** `AssetStatus.SVG_RENDERER_MISSING` -- *No
SVG renderer* -- when there is nothing to run; `AssetStatus.RENDER_FAILED` --
*Could not be drawn* -- when the renderer was there and did not produce an
image; and ADR 0017's *Not a PNG, JPEG or GIF* for the formats with no way
through, and for an SVG when the feature is switched off.

## Consequences

- The package now starts a process on the preview path when a document has an
  SVG in it. CONTRIBUTING.md and SECURITY.md say so; **Open in Browser** is no
  longer the only command that starts one.
- **A reader has to install resvg.** Nothing is bundled: the first version
  finds `resvg` on the `PATH` or takes a path from the settings, and says so in
  place when it finds neither. Upstream publishes Linux and macOS binaries for
  0.48.1 but no Windows one, so a Windows reader builds it or waits for the
  package to carry one. Registering a Package Control library that installs the
  renderer is the next step, and it can replace the process with a binding
  without changing anything above `assets/svg.py`.
- **Not every SVG a browser draws will appear as it does there.** Checked on
  0.48.1 against the samples that matter here: a shields.io badge, a Chinese
  architecture diagram with a gradient, a drop shadow and a transparent
  background, and a local drawing referencing a sibling PNG all come out
  right. `foreignObject` does not, and it fails quietly: the box is drawn and
  the HTML label inside it is missing, with no error to report, because that
  is what the renderer returns. Mermaid exports HTML labels by default, so a
  diagram exported that way is the case to watch. Animation and script are
  outside what resvg does at all. **Open in Browser** remains the escape
  route, and *Could not be drawn* covers the failures the renderer does
  report.
- The statuses that follow settings -- the two new ones, and the format one --
  are re-evaluated when the policy revision moves, so installing a renderer or
  turning the feature off changes what is on screen without a restart. A
  drawing already made is thrown away when `enable_svg` goes off, which is why
  a drawn asset is marked as such.
- The cache is unchanged: one entry per image locator, in memory, evicted by
  size, invalidated by a policy change. It does not carry the drawn size,
  because the drawn size does not depend on the pane -- an SVG is drawn once at
  twice its intrinsic size, not again at every zoom step.
- `detect()` now separates SVG from the rest of the family it reports, since
  SVG is the one with somewhere to go: `SvgImage` is a subclass of
  `UnsupportedImage`, so a caller that only asks whether it has a drawable
  image is unchanged.
