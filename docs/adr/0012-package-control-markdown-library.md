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

## Amendments, Sublime Text 4213

Build 4213, stable on 2026-09-21, replaced the Python 3.8 plugin host with
Python 3.14 and turned the 3.3 host off. `.python-version` stays `3.8`: the
API Environments documentation maps it to 3.14 on these builds, and build
4200 reads any value it does not know as 3.3. Measured on build 4215, Linux,
on 2026-10-10:

- **The pair served to 3.14 has moved.** The channel gives Python 3.13 and
  3.14 `Markdown` 3.11 and `pymdown-extensions` 12.1; 3.3 and 3.8 still get
  3.2.2 and 8.1.1. CI and CONTRIBUTING pin the new pair. The suite, 457
  tests, passes on it, on the 3.10.3 / 11.0.2 it replaces, and on the 3.8
  pair.
- **A library that is found is not always one that imports.** The 3.14
  host's `sys.path` holds `Lib/python314`, then `Lib/python38`, then
  `Lib/python33`. With only the 3.8 pair on disk, `find_spec` finds Markdown
  3.2.2, which fails inside its own import under Python 3.12 and later, and
  the preview opened on a card reading "Parse / AttributeError: 'EntryPoints'
  object has no attribute 'get'".

  Package Control 4.2.8 keeps most users out of that state. On the first
  start after the upgrade it emptied `Lib/python38`, installed the 3.14 pair
  and asked for a restart, all within five seconds, and a preview opened
  after that in the same session. The state is left standing where that
  clean-up does not run: Package Control absent or disabled, its
  `remove_orphaned_environments` setting off, or libraries put in place by
  hand.

  A command now builds the engine before it runs. When that fails a dialog
  gives the exception, where each library was found, the Python that
  directory was filled for, and the fix, and no preview is opened. A preview
  that Sublime Text restores at startup renders without a command, so its
  error card asks the same question and carries the fix in place of the
  pointer to the traceback. The lookup at plugin load is unchanged and loads
  nothing: that start is when Package Control is installing, and a dialog
  then would be a second one saying the same thing.
- **The newer host is faster with nothing changed.** The 100 KiB benchmark
  timed inside the plugin host, minimum of 30 samples after 3 warm-ups, both
  on the same loaded machine:

  | Host | Parser | min |
  | --- | --- | --- |
  | 4200, Python 3.8.12 | Markdown 3.2.2 + pymdown-extensions 8.1.1 | 393 ms |
  | 4215, Python 3.14.6 | Markdown 3.11 + pymdown-extensions 12.1 | 258 ms |
