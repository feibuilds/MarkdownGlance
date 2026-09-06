"""A standalone HTML page for a browser.

The preview itself never leaves the editor; this is the one place the parser's
output is written for something other than minihtml. It is the document as
the parser produced it, the way MarkdownPreview would render it, with the
same heading ids the preview gives (so a link that works in one works in the
other) and every relative image and link resolved beside the source file.

There is deliberately no `<base>`: a document base URL also captures `#id`
links, which would then leave the page for the source directory.
"""

import html
import pathlib
from typing import Dict, Optional
from urllib.parse import urljoin, urlsplit

from .markdown_engine import build_markdown
from .structure import _slug

STYLE = """
:root { color-scheme: light dark; }
body {
  max-width: 48rem; margin: 2rem auto; padding: 0 1rem;
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", sans-serif;
}
pre, code { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.9em; }
pre { padding: 0.75rem 1rem; overflow-x: auto; background: rgba(127,127,127,0.12); }
code { background: rgba(127,127,127,0.12); padding: 0.1em 0.3em; border-radius: 3px; }
pre code { background: none; padding: 0; }
blockquote { margin: 0; padding: 0 1rem; border-left: 0.25rem solid rgba(127,127,127,0.4); }
table { border-collapse: collapse; }
th, td { border: 1px solid rgba(127,127,127,0.4); padding: 0.3rem 0.6rem; }
img { max-width: 100%; }
"""

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")


def _is_relative(url: str) -> bool:
    parsed = urlsplit(url)
    return bool(url) and not parsed.scheme and not url.startswith(("#", "//"))


def _make_extension(base_uri: Optional[str]):
    from markdown.extensions import Extension
    from markdown.treeprocessors import Treeprocessor

    class PageProcessor(Treeprocessor):
        def run(self, root):
            counts: Dict[str, int] = {}
            for element in root.iter():
                if element.tag in HEADINGS:
                    base = _slug("".join(element.itertext()))
                    counts[base] = counts.get(base, 0) + 1
                    count = counts[base]
                    element.set("id", base if count == 1 else "{}-{}".format(base, count))
                elif base_uri and element.tag in ("img", "a"):
                    name = "src" if element.tag == "img" else "href"
                    value = element.get(name, "")
                    if _is_relative(value):
                        element.set(name, urljoin(base_uri, value))

    class PageExtension(Extension):
        def extendMarkdown(self, md):  # type: ignore[override]
            # After inline processing (priority 20), so the tree is complete.
            md.treeprocessors.register(PageProcessor(md), "mdglance_page", 5)

    return PageExtension()


def standalone_html(source: str, title: str, base_dir: str) -> str:
    base_uri = pathlib.Path(base_dir).resolve().as_uri() + "/" if base_dir else None
    body = build_markdown([_make_extension(base_uri)]).convert(source)
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>{title}</title>\n<style>{style}</style>\n</head>\n"
        "<body>\n{body}\n</body>\n</html>\n"
    ).format(title=html.escape(title), style=STYLE, body=body)
