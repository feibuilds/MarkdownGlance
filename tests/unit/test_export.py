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

    def test_dialect_matches_the_preview(self):
        page = standalone_html("Text\n- a\n  - b\n\n| x |\n|---|\n| 1 |\n", "t", "")
        self.assertIn("<ul>\n<li>a<ul>\n<li>b</li>", page)
        self.assertIn("<table>", page)
