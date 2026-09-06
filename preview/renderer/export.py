"""A standalone HTML page for a browser.

The preview itself never leaves the editor; this is the one place the parser's
output is written for something other than minihtml. It is the document as
the parser produced it, the way MarkdownPreview would render it, with heading
ids so that in-page links work and a `base` so that relative images resolve
beside the source file.
"""

import html
import pathlib

import markdown

from .lists import ListExtension
from .markdown_engine import MARKDOWN_EXTENSIONS

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


def standalone_html(source: str, title: str, base_dir: str) -> str:
    engine = markdown.Markdown(extensions=[*MARKDOWN_EXTENSIONS, "toc", ListExtension()])
    body = engine.convert(source)
    base = (
        '<base href="{}/">\n'.format(pathlib.Path(base_dir).resolve().as_uri())
        if base_dir
        else ""
    )
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>{title}</title>\n{base}<style>{style}</style>\n</head>\n"
        "<body>\n{body}\n</body>\n</html>\n"
    ).format(title=html.escape(title), base=base, style=STYLE, body=body)
