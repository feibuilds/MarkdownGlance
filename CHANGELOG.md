# Changelog

All notable changes to MarkdownGlance are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- The preview and the table of contents now follow the focus. Two documents
  previewed at once share one preview group and one table-of-contents group, so
  the tabs left in front used to be whichever document was previewed last, and
  they stayed there while you read the other file. Focusing a Markdown source,
  its preview or its table of contents now brings that document's other
  surfaces forward, without moving the focus off what you clicked. In Full
  Screen the preview shares the source's own group and is left alone.

- Numbered lists now display explicit numbers in the minihtml preview, including
  non-1 starts and nested lists. Loose items keep the number in their first
  paragraph. Adjacent ordered and unordered lists separated by a blank line
  retain their own list types. Wrapped lines do not yet use hanging indents.

## [0.4.2] - 2026-09-06

### Added

- **LaTeX math, off by default.** `$...$` and `$$...$$` (and `\(...\)`,
  `\[...\]`) are recognised by `pymdownx.arithmatex`, which is already
  installed with `pymdown-extensions`. With `"enable_math": true` each formula
  is fetched from `math_server` (`https://latex.codecogs.com`) as a PNG typeset
  in the colour scheme's foreground, the way a Mermaid diagram is, under the
  same HTTPS, timeout, size, cache and one-time privacy caption rules. Off, a
  formula is shown as its source in a code span or block. Asked for in
  [#2](https://github.com/pandadolphin/MarkdownGlance/issues/2); see
  [ADR 0013](docs/adr/0013-latex-math-as-a-baked-image.md).

- **`Open in Browser` renders Mermaid diagrams and LaTeX math.** A Mermaid
  fence used to reach the browser as a code block, and a formula as text.
  The page now loads Mermaid and KaTeX from jsDelivr, at a pinned release
  with a subresource integrity hash, and only when the document has a
  diagram or a formula; both render in the browser, so nothing of the
  document is sent anywhere, and the setting for the preview does not
  apply. Offline, a diagram stays readable source and a formula keeps its
  `\(...\)` delimiters.

## [0.4.1] - 2026-09-06

Fixes from a review of 0.4.0 before it was verified in Sublime Text; none of
them changes the channel entry.

### Fixed

- **A Mermaid fence stopped being a diagram when Pygments was installed.**
  superfences hands every fenced block to Pygments whenever it can be
  imported, and Pygments is a Package Control library other packages (for one,
  MarkdownPreview) install. Highlighted, a block is a `div` with no `code`
  element and no language class, so the preview saw code where a diagram was
  asked for. Pygments is now switched off explicitly, and a test holds it off.

- **`Open in Browser` sent `#heading` links to the directory.** The page
  carried a `<base>` so that relative images resolved beside the source, and
  a base URL captures fragment links too. Relative images and links are now
  resolved in the tree and the `<base>` is gone. The page also gives headings
  the ids the preview does (`same`, `same-2`), not Python-Markdown's
  (`same_1`), so a link that works in one works in the other.

- **Two list-shape mistakes in the preprocessor.** A code line starting with
  `>` inside a fence reset the fence and let the lines after it be rewritten
  as a list; and a heading or rule at an item's content column ended the list
  instead of belonging to the item. Both now render as they did in 0.3.1.

- **Missing libraries are a message, not a dead package.** The parser was
  imported at load, so a manual install without the libraries failed to load
  at all and left a traceback in the console. The libraries are now looked up
  without being imported; at load, and again on the first command, a dialog
  says which are missing and to run **Package Control: Satisfy Libraries**
  and restart. The README's manual steps now satisfy the libraries before the
  restart rather than after.

- **`Open in Browser` reports a browser that would not start**, with the path
  of the page it wrote, instead of claiming success; the page and its
  directory are created private to the user on hosts that honour modes, and
  the file is replaced rather than followed.

## [0.4.0] - 2026-09-06

### Changed

- **The parser is now the Package Control `Markdown` library** (Python-Markdown,
  with `pymdown-extensions` for fenced code) instead of a vendored copy of
  `markdown2`, as the channel review asked. Package Control installs both
  beside the package; a manual install needs them too, see the README. A
  small preprocessor keeps GitHub-flavoured lists rendering as before:
  two-column nested items, a list cuddled to the paragraph above it, and a
  fenced block inside an item. Rendering of the repository's own 24 Markdown
  files is identical apart from three corrections: a code block no longer ends
  in a blank line, `[Unreleased]`-style reference links resolve, and
  `a_b_c` no longer becomes `a<em>b</em>c`. The 100 KiB benchmark is 5% faster.
  [ADR 0012](docs/adr/0012-package-control-markdown-library.md) records the
  decision and what each host receives.

- **Package Control messages are down to the install note.** The per-release
  notes are gone; a release will carry one only when it needs something from
  you, kept to a few lines with a link to this changelog.

### Added

- **`MarkdownGlance: Open in Browser`** writes the document as a standalone
  page under the temporary directory and opens it in the default browser, for
  the moment a page has to be seen at browser width or handed to someone. The
  preview itself is unchanged and still never leaves the editor.

## [0.3.1] - 2026-09-02

### Changed

- Documentation only; no code, settings or key bindings change, and rendering
  is byte-for-byte what 0.3.0 produced. **Manual installation now has a route
  that does not need Git**: download the source ZIP from the latest release,
  rename the unzipped folder to `MarkdownGlance`, and move it into the
  directory **Preferences → Browse Packages…** opens. The Installation section
  also says plainly that the Package Control
  [submission is still pending](https://github.com/sublimehq/package_control_channel/pull/9539),
  and the README's preview screenshot is a light and dark pair, so it follows
  the colour scheme of whoever is reading it.

- [ADR 0002](docs/adr/0002-product-and-package-name.md) gains an addendum
  recording why `MarkdownPreviewPlus` and `MarkdownPreviewExtended` were
  considered and rejected, and that the name is frozen once the Package Control
  channel pull request is merged. `docs/` is `export-ignore`'d, so this reaches
  the repository only.

## [0.3.0] - 2026-08-30

### Added

- **`enable_toc`, and it defaults to `false`.** The table of contents beside
  the preview takes an editor group of its own, which is a lot to spend without
  being asked for; set it to `true` for the old behaviour, where a document
  past `toc_minimum_length` and `toc_minimum_headings` gets one.

- **`auto_width`, defaulting to `true`.** The table of contents and the outline
  are given the width their longest heading needs instead of a fixed share of
  the window, so the rest goes to the content. It is a ceiling, not a target:
  neither group is ever wider than it used to be. Dragging the divider yourself
  turns it off for that group, and setting `auto_width` to `false` restores the
  fixed share everywhere. See
  [ADR 0011](docs/adr/0011-panel-width-fits-its-content.md).

- **`mdglance_copy_diagnostics` now reports what a repaint cost.** The payload
  carries `recent_renders` -- the Python half, with the size of the Markdown in
  and the HTML out -- and `recent_paints`, the wall clock around
  `PhantomSet.update` together with the size of the HTML and whether the paint
  was skipped as unchanged. With `debug_logging` on, each paint is printed to
  the console as it happens. The paint number is a floor: it covers the layout
  only to the extent Sublime does that work synchronously.

### Changed

- **A Mermaid diagram now follows the editor's colour scheme.** The request
  asked mermaid.ink for the light theme on a transparent background, so on a
  dark scheme every label drawn straight onto that background — sequence
  messages, loop and note text — was near-black on near-black while the filled
  actor boxes stayed readable. The request now carries the Mermaid `dark` theme
  and the preview's own background colour when the scheme is dark. The scheme
  is read from the Markdown view, so one chosen with `MarkdownEditing: Select
  Color Scheme` wins over the global `UI: Select Color Scheme`, exactly as it
  does in the editor. A diagram is baked by the server and cannot be recoloured
  by a repaint, so changing scheme under an open preview now renders the
  document again for the new diagram URLs instead of leaving the old images in
  place.

- The table of contents and the outline no longer carry the preview's page
  margins. They are lists in a narrow group, so they get 0.8rem of padding
  rather than the document's 1.5rem, and the table of contents loses the margin
  above its card.

- Closing the table of contents now keeps it closed for that preview. It used
  to reappear within a second, because every render reopens one for a document
  that qualifies and the viewport poll renders again as soon as the preview
  grows into the group just given back. A close is remembered until the preview
  itself is closed and reopened, or until `enable_toc` is switched off and on.

### Performance

- **A repaint no longer costs a full minihtml layout when nothing changed.**
  `PhantomSet.update` identifies a phantom by its region, content, layout *and*
  its `on_navigate` callback, and the backend built that callback fresh on
  every repaint, so the set never recognised the phantom already on screen: it
  erased it and added it back, and Sublime laid the whole document out again.
  One callback per surface now lives for the life of the surface, and identical
  HTML is dropped before it reaches the phantom set at all. Repaints arrive
  from the viewport poll, from a theme re-read on every focus change and from
  every table-of-contents render, so most of them were doing no work worth the
  layout.

- **Indentation in a code block no longer costs an element per space.** minihtml
  collapses a run of spaces, which the serialiser held open with one
  background-coloured `<i class="space">.</i>` per space -- 5774 of them in this
  repository's own 69 KB design document, more than half of every element on the
  page. A run of two or more spaces is now a run of U+00A0, the technique
  [ADR 0007](docs/adr/0007-table-rendering-under-minihtml.md) already measured
  for table padding. Single spaces stay plain, so a long code line keeps its
  wrap points. The document's HTML falls from 296 KB to 178 KB and its element
  count from 9332 to 3558.

- **Repainting the table of contents no longer spins the window's focus.** It
  called `reveal`, which focuses the group, then the view, then the previous
  group back; each of those makes Sublime fire `on_activated`, which re-reads
  the theme and repaints -- landing back in the same place. Creation and a mode
  switch still reveal the tab; a repaint does not. A theme that has not changed
  is also no longer a reason to repaint.

- **The vendored parser drew a megabyte-sized hash salt.** Upstream markdown2
  writes `SECRET_SALT = bytes(randint(0, 1000000))`, which is not a random salt
  but a zero-filled buffer of random *length*, re-hashed on each of the several
  hundred `_hash_text` calls a parse makes. The draw happens once per
  `plugin_host`, so the same document parsed in 123 ms or in 1628 ms depending
  on the launch. Three random bytes keep the intent.

### Fixed

- **The preview, the table of contents and the outline now follow the colour
  scheme the Markdown file itself resolved.** A Markdown buffer usually has one
  of its own -- `markdownediting: select color scheme` writes `color_scheme`
  into `Markdown.sublime-settings`, and a syntax-specific setting beats the
  global `ui: select color scheme` -- but every surface is a plain scratch view,
  so it inherited the global scheme instead. That is the scheme minihtml
  resolves `var(--background)`, `var(--foreground)` and `var(--bluish)` against,
  and `preview.css` is built out of those three, so the whole page was painted
  in the wrong palette: a light MarkdownEditing scheme over a dark editor read
  as a dark preview beside a light source. Each surface is now put on the
  source's scheme, and re-put on it whenever the source's moves.

- Closing the table of contents from its tab left its empty group behind. The
  group was released by asking the backend which group the surface was in, but
  the view is already gone by then and a dead handle has no group, so nothing
  was released and the pane stayed on screen. The session now records the group
  it placed the table of contents in and falls back to it.

## [0.2.1] - 2026-08-29

### Changed

- Documentation only; no code, settings or key bindings change. The README now
  opens with a screenshot of the preview, its Mermaid diagram, an aligned table
  and the table of contents beside them, and the outline screenshot shows the
  outline reading this repository's own README. Both images live in
  `docs/screenshots/`, which `export-ignore` keeps out of the installed
  package.

## [0.2.0] - 2026-08-29

### Added

- **An outline of the Markdown source**, on `Ctrl+Shift+B` / `Cmd+Shift+B` and
  as `MarkdownGlance: Toggle Outline` in the command palette. It lists the
  headings as they are written in the buffer, in a group of its own beside the
  file, marks the one holding the caret, re-scans as you type, and moves the
  caret to a heading when its entry is clicked. It needs no preview and no
  successful render, which is what separates it from the table of contents
  inside the preview. The key toggles the way Zed's outline panel does — open
  and focus, focus, then close from inside — and shadows Sublime Text's
  **Build With…** only while a Markdown source view or an outline this package
  created is focused. See
  [ADR 0010](docs/adr/0010-source-outline-and-ctrl-shift-b.md).

## [0.1.4] - 2026-08-29

### Changed

- The **Settings** menu item and the `Preferences: MarkdownGlance Settings`
  palette entry now call `edit_settings` with `base_file` directly, the form
  every other package uses, instead of routing through a package command.
- The vendored copy of markdown2 no longer carries its command-line mainline.
  A Sublime Text package never runs it, and it brought `optparse`, a
  `Markdown.pl` comparison through `subprocess.Popen` and a `sys.path` insert
  with it. Two regex literals are raw strings now, so recent Python versions
  stop warning about invalid escape sequences. The library API is unchanged.

### Removed

- The `mdglance_open_settings` command. Anything bound to it should call
  `edit_settings` with
  `"base_file": "${packages}/MarkdownGlance/MarkdownGlance.sublime-settings"`.

## [0.1.3] - 2026-08-29

### Fixed

- **The Full Screen toggle is `Ctrl+Shift+V` again** (`Cmd+Shift+V` on macOS).
  The `Ctrl+K`, `Shift+V` chord that 0.1.2 moved it to never fired: Sublime Text
  lists it in the command palette but does not dispatch it, and its own keymap
  binds no chord whose second key is bare or shift-only. Taking the key back
  costs Paste and Indent while a Markdown source view is focused, where
  **Edit → Paste and Indent** still runs it by name; removing one entry from
  **Preferences → Package Settings → MarkdownGlance → Key Bindings** undoes it.
  See [ADR 0009](docs/adr/0009-full-screen-toggle-returns-to-ctrl-shift-v.md).

## [0.1.2] - 2026-08-28

### Changed

- **The Full Screen toggle moved from `Ctrl+Shift+V` to `Ctrl+K`, `Shift+V`**
  (`Cmd+K`, `Shift+V` on macOS). `Ctrl+Shift+V` is Sublime Text's own Paste and
  Indent, and a context that fires exactly while you are editing Markdown is
  exactly when you reach for it. The new chord collides with nothing on any
  platform. See [ADR 0008](docs/adr/0008-default-key-bindings.md).

## [0.1.1] - 2026-08-28

### Added

- **Preferences → Package Settings → MarkdownGlance → Key Bindings**, and the
  matching `Preferences: MarkdownGlance Key Bindings` palette entry, both
  opening the defaults beside your overrides.

### Changed

- The settings entry is now `Preferences: MarkdownGlance Settings`, following
  the convention the rest of Sublime Text uses.
- The installed package no longer carries the documentation, the ADRs or the
  test suite — 310 KB instead of 3.2 MB.

### Removed

- `Run Contract Tests` and `Run Benchmark` no longer appear in the command
  palette. They are developer commands; run them from the console with
  `window.run_command("mdglance_run_contract_tests")`.

## [0.1.0] - 2026-08-28

First public release.

### Added

- Same-window live Markdown preview for saved and unsaved buffers, in either a
  Side-by-Side or a Full Screen editor group.
- Theme-aware styling that follows the active color scheme, and per-session
  zoom.
- A separate, navigable table of contents.
- Local images, and remote images fetched asynchronously under scheme,
  redirect, timeout, payload and dimension limits, cached only in memory.
- GFM tables, typeset to the measured width of the preview.
- Opt-in Mermaid rendering, disabled by default; diagram source reaches the
  configured server only once it is enabled.
- `MarkdownGlance: Copy Diagnostics`, which redacts source text, paths, URLs
  and Mermaid payloads.

[Unreleased]: https://github.com/pandadolphin/MarkdownGlance/compare/0.4.2...HEAD
[0.4.2]: https://github.com/pandadolphin/MarkdownGlance/compare/0.4.1...0.4.2
[0.4.1]: https://github.com/pandadolphin/MarkdownGlance/compare/0.4.0...0.4.1
[0.4.0]: https://github.com/pandadolphin/MarkdownGlance/compare/0.3.1...0.4.0
[0.3.1]: https://github.com/pandadolphin/MarkdownGlance/compare/0.3.0...0.3.1
[0.3.0]: https://github.com/pandadolphin/MarkdownGlance/compare/0.2.1...0.3.0
[0.2.1]: https://github.com/pandadolphin/MarkdownGlance/compare/0.2.0...0.2.1
[0.2.0]: https://github.com/pandadolphin/MarkdownGlance/compare/0.1.4...0.2.0
[0.1.4]: https://github.com/pandadolphin/MarkdownGlance/compare/0.1.3...0.1.4
[0.1.3]: https://github.com/pandadolphin/MarkdownGlance/compare/0.1.2...0.1.3
[0.1.2]: https://github.com/pandadolphin/MarkdownGlance/compare/0.1.1...0.1.2
[0.1.1]: https://github.com/pandadolphin/MarkdownGlance/compare/0.1.0...0.1.1
[0.1.0]: https://github.com/pandadolphin/MarkdownGlance/releases/tag/0.1.0
