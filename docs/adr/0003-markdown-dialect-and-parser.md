# ADR 0003: Markdown dialect and parser

## Status

Accepted; the parser choice is superseded by
[ADR 0012](0012-package-control-markdown-library.md), which moves it to the
Package Control `Markdown` library. The dialect and the characterized
behaviour below still hold.

## Decision

Vendor the existing `markdown2` 2.3.9 under `lib/` and retain its
MIT notice. Use exactly these extras:

```text
fenced-code-blocks
highlightjs-lang
cuddled-lists
header-ids
tables
```

`tables` was added after the first release; minihtml cannot lay a table out, so
the structural pass typesets one itself. See
[ADR 0007](0007-table-rendering-under-minihtml.md).

`header-ids` is not trusted as final identity: the structured pass rewrites all
heading ids with deterministic, document-unique slugs. Markdown-generated and
raw HTML both pass through the same allowlisted serializer.

Replace BeautifulSoup with a purpose-built stdlib `HTMLParser` tree. This is a
packaging and runtime-boundary decision, not a dialect change. The existing
package's `bs4` dependency is installed only in its Python 3.3 environment on
the test machine; MarkdownGlance imports and renders without external Python
dependencies in ST 4200's Python 3.8.12 host.

## Characterized behavior

The unit fixture matrix covers headings, duplicate headings, paragraphs,
emphasis, links, block quotes, fenced and inline code, lists, raw HTML,
Unicode, malformed input, Mermaid fences, TOC hierarchy, pre whitespace,
extensionless image detection, relative links, and blocked schemes.

Expected differences from the old renderer are intentional:

- raw HTML attributes and URL schemes are sanitized;
- headings receive stable unique ids;
- remote assets are non-blocking typed dependencies rather than renderer I/O;
- Mermaid defaults off pending explicit privacy opt-in.

## Compatibility

- Linux ST 4200 / Python 3.8.12: import, rendering smoke, and selected-backend
  contract passed.
- CPython 3.10: pure suite passed during implementation.
- CPython 3.14: pure suite passes; dev-build GUI testing is optional forward
  evidence and does not block release acceptance.

The committed 100 KiB benchmark is intentionally retained as a performance
baseline. A local comparison found `markdown2` 2.5.0 (the newest release that
supports Python 3.8) slower than 2.3.9 on this fixture, so dependency churn is
not accepted as an unproven optimization. The initial p95 reference target is
not a release gate; measured results and deviations remain in verification
evidence.
