# 21. Fenced code is coloured by the editor's own syntaxes

Date: 2026-10-16

## Status

Accepted. Answers [#7](https://github.com/feibuilds/MarkdownGlance/issues/7).

## Context

A fenced block that names its language was shown as plain monospace text.
The request is the obvious one: colour it by that language, as GitHub and
every other Markdown viewer does.

minihtml has no highlighter of its own and no scripts, so the colour has to
be in the HTML: one `span` with a colour per token. What remained open was
where the tokens and the colours come from. Three answers were considered:

- **Pygments**, through `pymdownx.highlight`, which is already in the
  pipeline with `use_pygments` off (ADR 0003). Pygments is a Package Control
  library, so it could be declared beside the other two. But its colours are
  its own styles, not the user's colour scheme, so a code block would be the
  one part of the preview that does not follow the editor; its language names
  are Pygments' rather than the ones the editor recognises in the same fence;
  and it would be a third library to keep in step across two plugin hosts
  (ADR 0012), whose output is not `<pre><code class="lang">` and so is not a
  fenced block to the structural pass (`markdown_engine.py` turns it off for
  that reason).

- **The source view's own tokens.** The fences in the Markdown file are
  already tokenised, in the user's scheme, by the editor. But the render works
  on a snapshot of the text, on a worker, and the source changes under it; a
  rendered block has to be mapped back to a source region through list
  indentation and `> ` prefixes; and the result belongs to whatever the buffer
  held at the moment it was read, not to the generation being rendered.

- **A hidden view of our own**, given the code and asked for its tokens. This
  is the one taken.

## Decision

**Tokenise in a hidden output panel, as Markdown.** `SyntaxHighlighter`
(`adapter/highlighter.py`) writes every block a render has not seen before
into one panel as a Markdown fence -- the block's language on the opening
line, a fence longer than any backtick run inside it -- assigns the source's
own Markdown syntax and colour scheme to the panel, and reads
`extract_tokens_with_scopes` and `style_for_scope` back. The Markdown syntax
decides what the language is, by the same rule that colours the fence in the
source: `py` and `python` alike, every syntax the user has installed,
MarkdownEditing's table rather than the default one when that is the source's
syntax, and nothing for a language the editor does not know either. Each
token's style is the one the scheme gives it there, so the preview shows the
code the way the editor shows it inside the source.

The panel is created and destroyed within the call, so no Markdown buffer is
left for another package to act on; it is marked `is_widget` while it exists,
and this package's own listeners skip it by a setting of its own. It is
reached from the render worker -- the Sublime API may be called from any
thread -- under a lock, so two renders never write into it at once.

Measured on build 4215, the steady state is about 1 ms a batch for the panel's
life (create, write, tokenise, destroy) and about 2 ms to tokenise thirty
blocks. The first batch that meets a language pays to load that syntax, about
400 ms for nine at once, and the editor pays the same the first time it shows
such a fence.

**Answers are cached by theme, language and code**, 512 blocks, so that a
keystroke in one block tokenises that block and nothing else. The theme is
part of the key because the colours are; a failure is not cached, so a window
that was closing does not leave a document plain for good.

**The renderer stays pure.** `renderer/highlight.py` finds each
`<pre><code class="language">` the document wrote -- not a formula the
renderer shows as its source, not a Mermaid fence it has already made an
image -- asks an injected `Highlighter` for all of them in one call, and
replaces each block's text with the runs it gets back. Runs are merged before
they become spans, since every span is a box minihtml lays out on every
paint: whitespace joins its neighbour, alike neighbours become one, and a run
in the document's own foreground is no span at all. Runs of spaces are held as
U+00A0 across the whole block, because a run that a token boundary splits is
two single spaces to the serialiser, and minihtml collapses those. An answer
whose runs do not spell the block exactly is discarded and the block stays
plain; so does any block when the highlighter fails, with the traceback in the
console and in the diagnostics as `highlighter_error`.

The serialiser accepts a `style` attribute on a node the renderer generated,
and only there: a document's own `style` attributes are still dropped.

**A new theme re-renders.** The colours are written into the HTML at parse
time, the way a Mermaid diagram's background and a formula's foreground are
baked into their URLs, so `theme_changed` asks for a render when the document
is `highlighted`, not only a repaint.

**On by default**, behind `enable_syntax_highlighting`. Nothing leaves the
machine, and nothing runs that is not Sublime Text itself.

## Consequences

- Colours, languages and aliases follow the editor with no table of our own.
  A language the editor learns from a package the user installs is coloured
  in the preview too.
- The cost is boxes. On this repository's 68 KB design document -- 23 fenced
  blocks -- highlighting adds 2161 spans and takes the HTML from 141 KB to
  227 KB. Python render time on the worker goes from about 90 ms to about
  125 ms with every block cached, 183 ms with none. The minihtml layout is the
  cost that [preview-cpu.md](../preview-cpu.md) found heats a laptop: measured
  as `sublime_text` CPU over thirty forced full relayouts of the same
  document, it is 31-32 ms a relayout with highlighting off and 34-37 ms with
  it on -- a tenth or so more, well short of what the box count suggests.
  `enable_syntax_highlighting: false` takes all of it back.
- `ThemeSnapshot` carries the source's syntax path, and `PreviewDocument`
  carries `highlighted`.
- **Open in Browser** is unchanged: the exported page still shows fenced code
  plain. Highlighting it there would be a script in the page, the way Mermaid
  and KaTeX are, and is left for when it is asked for.
- Inline code is not coloured: it names no language.
