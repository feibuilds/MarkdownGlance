# ADR 0012: Depend on the Package Control Markdown library

## Status

Accepted. Supersedes the parser choice in
[ADR 0003](0003-markdown-dialect-and-parser.md); the dialect, the extras it
lists and the characterized behaviour stand.

## Context

The channel review of the Package Control submission
([sublimehq/package_control_channel#9539](https://github.com/sublimehq/package_control_channel/pull/9539))
asked that the package not vendor a Markdown parser when the ecosystem
[offers one](https://packages.sublimetext.com/libraries?q=markdown). The
ecosystem has no `markdown2`. It has `Markdown` (Python-Markdown) and
`pymdown-extensions`, and the channel serves a different release to each
plugin host:

| Host | `Markdown` | `pymdown-extensions` |
| --- | --- | --- |
| Python 3.3 | 3.2.2 | 8.1.1 |
| Python 3.8 (build 4200, `.python-version`) | 3.2.2 (2020) | 8.1.1 |
| Python 3.13 / 3.14 (build 4201 and later) | 3.10.3 | 11.0.2 |

So the switch is a dialect change, and the code has to run against both
release pairs.

## Decision

- `dependencies.json` declares `Markdown` and `pymdown-extensions` for every
  host and platform; `lib/` and `THIRD_PARTY_NOTICES.md` are gone.
- The engine is `markdown.Markdown` with `pymdownx.superfences` and `tables`.
  superfences rather than the core `fenced_code` because a fence inside a list
  item is a code block only with it.
- `renderer/lists.py` is a preprocessor of our own, registered between
  Python-Markdown's whitespace normaliser and the fence preprocessor. It
  rewrites two things Python-Markdown does not accept and GitHub-flavoured
  files rely on: an item nested two columns under its parent's content becomes
  four columns, and a list on the line after a paragraph gets a blank line.
  The content column of each open item, CommonMark's rule for what belongs to
  it, decides what moves; fenced blocks move with their item and are otherwise
  untouched.
- The structural pass reduces superfences' `class="highlight"` and
  `language-x` to the bare `x` the body HTML has always carried, and reads
  table alignment from either `align` (3.2.2) or `style="text-align"` (3.4 and
  later).
- The engine is reset before each conversion and converts under a lock: the
  instance keeps state, and two render workers exist.
- CI installs the pair each host receives: 3.2.2 / 8.1.1 under Python 3.8 and
  3.10.3 / 11.0.2 under 3.14. Markdown 3.2.2 does not import on 3.12 or later.

## Evidence

- The suite is 259 tests and passes on both pairs.
- The repository's own 24 Markdown files rendered through the old engine and
  the new one and compared with inter-block whitespace ignored: 16 identical,
  the other 8 differ only in three ways, each a correction. A fenced block no
  longer ends in a trailing `<br />`; `[Unreleased]`-style reference links
  defined at the end of the file resolve; `a_b_c` in prose is no longer
  `a<em>b</em>c`.
- The 100 KiB benchmark, Python 3.8.20, Linux, 100 samples after 3 warm-ups:

  | Parser | p50 | p95 |
  | --- | --- | --- |
  | markdown2 2.3.9 (vendored) | 302.973 ms | 317.328 ms |
  | Markdown 3.2.2 + pymdown-extensions 8.1.1 | 286.541 ms | 301.925 ms |

## Consequences

- A manual install needs the two libraries; Package Control installs them.
- Tests need them installed with pip; CONTRIBUTING says which versions.
- Accepted differences: a fenced block's text no longer ends in a newline (the
  Mermaid payload changes accordingly), `1)` is not an ordered-list marker,
  and a nested item must sit at least at its parent's content column, which
  is CommonMark's rule and stricter than markdown2 was.
- The salt-size test that guarded a markdown2 performance trap is gone with
  the parser.

## Amendments, 0.4.1

A review of 0.4.0 before it was verified in Sublime Text found four defects,
each reproduced against both library pairs and fixed:

- **Pygments.** superfences hands every fenced block to Pygments whenever it
  can be imported, and Pygments is a Package Control library that other
  packages (MarkdownPreview among them) install into the same host. The
  highlighted form is `<div class="highlight"><pre>` with no `code` element
  and no language, so a Mermaid fence was no longer a diagram. The engine now
  registers `pymdownx.highlight` with `use_pygments: False`, and a test holds
  that on the live engine. CI environments carry only the declared libraries
  and could not have seen this.
- **Libraries are never imported at module level.** `markdown` and `pymdownx`
  are looked up with `importlib.util.find_spec` at load and on the first
  command; when absent, a dialog names them and the fix. Before, a manual
  install without them failed to import at all. The engine is built on first
  use.
- **Two preprocessor mistakes.** A `>` line inside a fence was read as a
  change of quote depth and reset the fence; a heading or rule at an item's
  content column ended the list. The fence is now checked before the quote
  prefix, and a rule or heading ends the list only outside every open item.
- **The browser page** had a `<base>`, which also captured `#id` links. It now
  resolves relative images and links in the tree, gives headings the preview's
  slugs (`same-2`, not toc's `same_1`), is written private to the user, and
  reports a browser that would not start.
