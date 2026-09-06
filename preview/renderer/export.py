"""A standalone HTML page for a browser.

The preview itself never leaves the editor; this is the one place the parser's
output is written for something other than minihtml. It is the document as
the parser produced it, the way MarkdownPreview would render it, with the
same heading ids the preview gives (so a link that works in one works in the
other) and every relative image and link resolved beside the source file.

There is deliberately no `<base>`: a document base URL also captures `#id`
links, which would then leave the page for the source directory.

A browser can typeset what minihtml cannot, so the page renders Mermaid
fences with Mermaid and formulas with KaTeX, both loaded from jsDelivr at a
pinned version with a subresource integrity hash, and only when the document
has something for them. Both render in the browser; nothing of the document
is sent anywhere. Offline, a diagram stays readable source and a formula
keeps its delimiters.
"""

import html
import pathlib
import re
from typing import Dict, Optional
from urllib.parse import quote, urljoin, urlsplit

from ..domain.paths import HOST
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
pre.mermaid[data-processed] { background: none; text-align: center; }
"""

HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# Pinned releases with their subresource integrity hashes; bump both together.
KATEX = "https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.12.0/dist/mermaid.min.js"
INTEGRITY = {
    "katex.min.css": "sha384-5TcZemv2l/9On385z///+d7MSYlvIEw9FuZTIdZ14vJLqWphw7e7ZPuOiCHJcFCP",
    "katex.min.js": "sha384-cMkvdD8LoxVzGF/RPUKAcvmm49FQ0oxwDF3BGKtDXcEc+T1b2N+teh/OJfpU0jr6",
    "auto-render.min.js": "sha384-hCXGrW6PitJEwbkoStFjeJxv+fSOOQKOPbJxSfM6G5sWZjAyWhXiTIIAmQqnlLlh",
    "mermaid.min.js": "sha384-o+g/BxPwhi0C3RK7oQBxQuNimeafQ3GE/ST4iT2BxVI4Wzt60SH4pq9iXVYujjaS",
}

KATEX_HEAD = (
    '<link rel="stylesheet" href="{base}katex.min.css" integrity="{css}" crossorigin="anonymous">\n'
    '<script defer src="{base}katex.min.js" integrity="{js}" crossorigin="anonymous"></script>\n'
    '<script defer src="{base}contrib/auto-render.min.js" integrity="{auto}" crossorigin="anonymous"></script>\n'
).format(
    base=KATEX,
    css=INTEGRITY["katex.min.css"],
    js=INTEGRITY["katex.min.js"],
    auto=INTEGRITY["auto-render.min.js"],
)
MERMAID_HEAD = (
    '<script defer src="{}" integrity="{}" crossorigin="anonymous"></script>\n'
).format(MERMAID, INTEGRITY["mermaid.min.js"])

# Runs after the deferred scripts. arithmatex wrote `\(...\)` and `\[...\]`,
# so those are the only delimiters KaTeX is given; `$` in prose stays prose.
RENDER_SCRIPT = r"""<script>
document.addEventListener("DOMContentLoaded", function () {
  if (window.renderMathInElement) {
    renderMathInElement(document.body, {
      delimiters: [
        {left: "\\(", right: "\\)", display: false},
        {left: "\\[", right: "\\]", display: true}
      ],
      throwOnError: false
    });
  }
  if (window.mermaid) {
    var dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    mermaid.initialize({startOnLoad: false, theme: dark ? "dark" : "default"});
    mermaid.run();
  }
});
</script>"""


def _drive_uri(url: str) -> Optional[str]:
    """`C:/x.png` as the `file:` URL a browser can actually open.

    `urlsplit` reads the drive letter as a scheme, so such a source is neither
    relative nor a URL, and the page would otherwise carry it through as
    `C:/x.png`, which no browser resolves.
    """
    if not HOST.is_drive_absolute(url):
        return None
    # Built from the flavour rather than from `pathlib`, whose concrete class
    # follows the interpreter's own platform and cannot express this path off
    # Windows at all.
    return "file:///" + quote(url.replace("\\", "/"), safe="/:")


def _is_relative(url: str) -> bool:
    parsed = urlsplit(url)
    return bool(url) and not parsed.scheme and not url.startswith(("#", "//"))


# superfences stashes a fence as raw HTML and puts it back after the tree
# processors have run, so the fence is only reachable in the final HTML.
MERMAID_FENCE = re.compile(
    r'<pre class="highlight"><code class="language-mermaid">(.*?)</code></pre>',
    re.S,
)


def _mermaid_fences(body: str) -> str:
    """`<pre class="highlight"><code class="language-mermaid">` to `<pre class="mermaid">`.

    Mermaid takes the text of every `.mermaid` element; the entities inside
    (`--&gt;`) decode to the arrows the diagram wrote.
    """
    return MERMAID_FENCE.sub(r'<pre class="mermaid">\1</pre>', body)


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
                elif element.tag in ("img", "a"):
                    name = "src" if element.tag == "img" else "href"
                    value = element.get(name, "")
                    drive = _drive_uri(value)
                    if drive is not None:
                        element.set(name, drive)
                    elif base_uri and _is_relative(value):
                        element.set(name, urljoin(base_uri, value))

    class PageExtension(Extension):
        def extendMarkdown(self, md):  # type: ignore[override]
            # After inline processing (priority 20), so the tree is complete.
            md.treeprocessors.register(PageProcessor(md), "mdglance_page", 5)

    return PageExtension()


def standalone_html(source: str, title: str, base_dir: str) -> str:
    base_uri = pathlib.Path(base_dir).resolve().as_uri() + "/" if base_dir else None
    body = _mermaid_fences(build_markdown([_make_extension(base_uri)]).convert(source))
    has_math = 'class="arithmatex"' in body
    has_mermaid = 'class="mermaid"' in body
    head = (KATEX_HEAD if has_math else "") + (MERMAID_HEAD if has_mermaid else "")
    script = "\n" + RENDER_SCRIPT if has_math or has_mermaid else ""
    return (
        "<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\">\n"
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>{title}</title>\n<style>{style}</style>\n{head}</head>\n"
        "<body>\n{body}{script}\n</body>\n</html>\n"
    ).format(
        title=html.escape(title), style=STYLE, head=head, body=body, script=script
    )
