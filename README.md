# MarkdownGlance

[![CI](https://github.com/pandadolphin/MarkdownGlance/actions/workflows/markdown-glance.yml/badge.svg)](https://github.com/pandadolphin/MarkdownGlance/actions/workflows/markdown-glance.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Sublime Text](https://img.shields.io/badge/Sublime%20Text-4200%2B-orange.svg)](https://www.sublimetext.com/)

See your Markdown as you write, right inside Sublime Text 4. Keep a live
preview beside your text, or switch to a full-screen preview to read without
distractions. No browser needed.

<picture>
  <source media="(prefers-color-scheme: light)" srcset="docs/screenshots/preview-and-toc-light.png">
  <img alt="Markdown preview in Sublime Text, showing headings, a table and a Mermaid diagram, with a clickable table of contents on the right" src="docs/screenshots/preview-and-toc-dark.png">
</picture>

A preview with the optional table of contents enabled. Colours follow your
editor's color scheme, in both [dark](docs/screenshots/preview-and-toc-dark.png)
and [light](docs/screenshots/preview-and-toc-light.png) themes.

## Features

- **Preview as you type**, even before you've saved the file.
- **Read your way**: side-by-side or full-screen preview, with adjustable zoom.
- **Keep your theme**: the preview follows your editor's colours.
- **Navigate long documents** with one panel that shows the source outline
  while you edit and the preview's table of contents while you read.
- **One preview, whatever you have open**: the preview and the contents panel
  follow you between files rather than piling up a tab each.
- **View images and tables**, including local and remote images.
- **Add diagrams and formulas** with optional Mermaid and LaTeX math support.
- **Open in Browser** when you want to see the document as a web page.

## Requirements

Sublime Text build 4200 or newer, on Linux, macOS or Windows, with Package
Control installed to manage the required libraries.

## Installation

### Package Control

The [Package Control submission is still pending](https://github.com/sublimehq/package_control_channel/pull/9539).
Until it is approved, use one of the manual methods below.

### Manual installation

#### Download a ZIP

No Git or command line is needed.

1. Go to the [latest release](https://github.com/pandadolphin/MarkdownGlance/releases/latest).
2. Under **Assets**, download **Source code (zip)** and unzip it.
3. Rename the extracted folder to exactly `MarkdownGlance`, removing the
   version number from its name.
4. In Sublime Text, open **Preferences → Browse Packages…** and move the
   `MarkdownGlance` folder into the window that opens.
5. Open the Command Palette (**Tools → Command Palette…**) and run
   **Package Control: Satisfy Libraries**. This installs the libraries needed
   for the preview.
6. Restart Sublime Text.

To update, replace the old `MarkdownGlance` folder with the new release and
repeat steps 5–6.

#### Using Git

Open **Preferences → Browse Packages…**, then open a terminal in that directory
and run:

```bash
git clone https://github.com/pandadolphin/MarkdownGlance.git MarkdownGlance
```

Run **Package Control: Satisfy Libraries** from the Command Palette, then
restart Sublime Text.

#### Open your first preview

Open a Markdown file, then run **MarkdownGlance: Open Preview to the Side**
from the Command Palette. The preview updates as you type.

If a dialog reports missing libraries, run **Package Control: Satisfy
Libraries** again and restart Sublime Text.

## Commands

All commands are available from the Command Palette. On macOS, use `Cmd`
instead of `Ctrl` for the shortcuts below.

| Command | Shortcut |
| --- | --- |
| MarkdownGlance: Open Preview to the Side | `Ctrl+K`, then `V` |
| MarkdownGlance: Toggle Preview | `Ctrl+Shift+V` |
| MarkdownGlance: Toggle Contents Panel | `Ctrl+Shift+B` |
| MarkdownGlance: Zoom In / Out / Reset Zoom | `Ctrl+=`, `Ctrl+-`, `Ctrl+0` |
| Preferences: MarkdownGlance Settings | — |
| Preferences: MarkdownGlance Key Bindings | — |
| MarkdownGlance: Copy Diagnostics | — |
| MarkdownGlance: Open in Browser | — |

**Toggle Preview** switches between your Markdown text and a full-screen
preview. To zoom, click the preview first, then use the zoom keys or hold
`Ctrl`/`Cmd` and scroll. Closing a preview leaves your source files open.

A window has one preview, however many Markdown files you have open in it. It
shows whichever one you are working on and is named for it, and it remembers
where you had scrolled to in each. Files you have not looked at yet are
rendered the first time you focus them; after that, switching between them is
immediate.

**Open in Browser** creates a temporary HTML page and opens it in your default
browser. It can display diagrams and formulas even when they are disabled in
the live preview. See [Network and privacy](#network-and-privacy) for how these
are rendered and how embedded scripts are handled.

### Changes to default shortcuts

While you're editing Markdown, `Ctrl+Shift+V` opens the preview instead of
**Paste and Indent**, and `Ctrl+Shift+B` opens the contents panel instead of
**Build With…**. These shortcuts also work inside the preview and the panel.
They don't change shortcuts in other source files.

Normal paste (`Ctrl+V`) and build (`Ctrl+B`) still work. **Paste and Indent**
is also available from the **Edit** menu. To customise the shortcuts, run
**Preferences: MarkdownGlance Key Bindings** and add your preferred bindings
in the user file.

## The contents panel

Press `Ctrl+Shift+B` for a list of the document's headings beside it. Click one
to go to it. There is one panel per window, showing the file you are working
on, and it shows the half that matches whatever you are looking at:

- **Editing the source** — the headings of the file as you have written them,
  updating as you type, with your current section highlighted. Clicking one
  moves the caret. This works with no preview open at all.
- **Reading the preview** — the headings of the rendered document. Clicking
  one scrolls the preview.

![The contents panel beside the source, with the current heading highlighted](docs/screenshots/source-outline.png)

The shortcut opens and focuses the panel. If it's already open, the shortcut
focuses it; press it again from inside the panel to close it.

With `"enable_toc": true` in settings, the panel also opens by itself for
previews that meet the length and heading thresholds (`toc_minimum_length` and
`toc_minimum_headings`). That setting governs only whether it opens on its
own; one you opened yourself shows both halves whichever way it is set.
Closing its tab hides it until you ask for it again.

The panel adjusts its width to fit the headings. Drag the divider if you
prefer to set the width yourself.

## Settings

Run **Preferences: MarkdownGlance Settings** from the Command Palette. The
left pane explains every setting; add your choices in the right pane and save.

Common options:

| Setting | What it does | Default |
| --- | --- | --- |
| `enable_toc` | Open the contents panel by itself for longer previews | `false` |
| `enable_mermaid` | Render Mermaid diagrams using an online service | `false` |
| `enable_math` | Render LaTeX formulas using an online service | `false` |
| `auto_width` | Fit the contents panel's width to its headings | `true` |

Before enabling diagrams or math, read [Network and privacy](#network-and-privacy).

## Tables

Markdown tables appear as aligned columns in a fixed-width font and adjust to
the preview's width. For a traditional web-style table, use **Open in Browser**.

## Math

Set `"enable_math": true` to display LaTeX formulas written as `$...$`
(inline) or `$$...$$` (a separate block). Formulas appear as images that match
your editor's colours. With math disabled, you'll see the original formula
text instead.

## Network and privacy

Regular Markdown text is rendered inside Sublime Text. Features that access
the network are:

- **Remote images** are downloaded from their URLs. Insecure HTTP images are
  blocked by default, downloads have time and size limits, and downloaded
  images are cached only in memory.
- **Diagrams and math in the live preview** are off by default. Enabling them
  sends the diagram or formula text and a theme colour to the configured
  service: `mermaid_server` (default: `https://mermaid.ink`) or `math_server`
  (default: `https://latex.codecogs.com`).
- **Open in Browser** downloads Mermaid and KaTeX from jsDelivr when needed,
  then renders diagrams and formulas in your browser without sending their
  text to a rendering service. Remote images may still load from their URLs.
  The exported page preserves embedded HTML and scripts, so only use this
  command with documents you trust.

**Copy Diagnostics** leaves out document text, file paths, URLs, and diagram
and formula contents.

## Documentation

- [Migrating from MarkdownLivePreview](docs/migration.md)
- [Changelog](CHANGELOG.md)
- [Security policy](SECURITY.md)
- [Architecture](docs/architecture.md)
- [Architecture decision records](docs/adr) — implementation details and design decisions
- [Manual test plan](docs/manual-test-plan.md)

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md)
for setup, testing, and pull request guidance. When reporting a problem,
include what you expected, what happened, and the output of
**MarkdownGlance: Copy Diagnostics**.

## Acknowledgements

Inspired by [MarkdownLivePreview](https://github.com/math2001/MarkdownLivePreview)
by Mathieu Paturel. Thank you for showing how useful a Markdown preview inside
Sublime Text can be. MarkdownGlance is an independent implementation for
Sublime Text 4.

## My Markdown workflow

I use [Auto Save After Delay](https://github.com/pandadolphin/sublime-auto-save-after-delay)
alongside MarkdownGlance. MarkdownGlance keeps the preview up to date while I
write; Auto Save After Delay saves the file when I pause typing.

## License

MIT. See [LICENSE](LICENSE). The `Markdown` and `pymdown-extensions` libraries
are installed through Package Control and have their own licenses.
