import os.path
import pathlib
import unittest

from MarkdownGlance.preview.renderer.export import standalone_html

BASE_PATH = os.path.realpath(os.path.abspath(os.sep + "mdglance"))
BASE_URI = pathlib.Path(BASE_PATH).as_uri()


class StandaloneHtmlTest(unittest.TestCase):
    def test_page_is_complete_and_titled(self):
        page = standalone_html("# Title\n", "a <b>.md", BASE_PATH)
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("<title>a &lt;b&gt;.md</title>", page)

    def test_relative_assets_resolve_beside_the_source_with_no_base_element(self):
        # A `<base>` would also capture `#id` links and send them to the
        # directory, so every relative URL is resolved in the tree instead.
        page = standalone_html(
            "![i](img/a b.png) [n](../next.md#top) [r](https://x.test/p) [h](#title)\n",
            "t",
            BASE_PATH,
        )
        self.assertNotIn("<base", page)
        self.assertIn('src="{}/img/a b.png"'.format(BASE_URI), page)
        self.assertIn('href="{}#top"'.format(BASE_URI.rsplit("/", 1)[0] + "/next.md"), page)
        self.assertIn('href="https://x.test/p"', page)
        self.assertIn('href="#title"', page)

    def test_unsaved_source_leaves_relative_urls_alone(self):
        page = standalone_html("![i](img.png) [h](#x)", "untitled", "")
        self.assertIn('src="img.png"', page)
        self.assertIn('href="#x"', page)

    def test_heading_ids_match_the_preview(self):
        page = standalone_html("# Same\n\n# Same\n\n## Same\n\n# Ünïcode & co\n", "t", "")
        self.assertIn('<h1 id="same">', page)
        self.assertIn('<h1 id="same-2">', page)
        self.assertIn('<h2 id="same-3">', page)
        # The preview's slug, not Python-Markdown's toc one (`same_1`).
        self.assertNotIn("same_1", page)

    def test_mermaid_fence_becomes_a_mermaid_element(self):
        page = standalone_html("```mermaid\nflowchart LR\nA --" + "> B\n```\n", "t", "")
        self.assertIn('<pre class="mermaid">flowchart LR\nA --&gt; B</pre>', page)
        self.assertNotIn("language-mermaid", page)
        self.assertIn("mermaid@11.12.0/dist/mermaid.min.js", page)
        self.assertIn("mermaid.run()", page)
        self.assertNotIn("katex", page)

    def test_formulas_get_katex_with_pinned_integrity(self):
        page = standalone_html("Inline $x$\n\n$$\ny\n$$\n", "t", "")
        self.assertIn('<span class="arithmatex">\\(x\\)</span>', page)
        self.assertIn('<div class="arithmatex">\\[\ny\n\\]</div>', page)
        self.assertIn("katex@0.16.22/dist/katex.min.js", page)
        self.assertIn("contrib/auto-render.min.js", page)
        self.assertIn("renderMathInElement", page)
        self.assertNotIn("mermaid.min.js", page)
        for tag in page.split("<script")[1:]:
            head = tag.split(">", 1)[0]
            if "src=" in head:
                self.assertIn('integrity="sha384-', head)
                self.assertIn('crossorigin="anonymous"', head)

    def test_other_fences_and_plain_pages_load_nothing(self):
        page = standalone_html("```python\nx = 1\n```\n\nCosts $5 and $6.\n", "t", "")
        self.assertNotIn("<script", page)
        self.assertNotIn("<link", page)
        self.assertIn('<code class="language-python">', page)

    def test_dialect_matches_the_preview(self):
        page = standalone_html("Text\n- a\n  - b\n\n| x |\n|---|\n| 1 |\n", "t", "")
        self.assertIn("<ul>\n<li>a<ul>\n<li>b</li>", page)
        self.assertIn("<table>", page)
