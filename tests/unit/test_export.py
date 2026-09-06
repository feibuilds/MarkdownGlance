import os.path
import pathlib
import unittest

from MarkdownGlance.preview.renderer.export import standalone_html

BASE_PATH = os.path.realpath(os.path.abspath(os.sep + "mdglance"))


class StandaloneHtmlTest(unittest.TestCase):
    def test_page_is_complete_titled_and_based_on_the_source_directory(self):
        page = standalone_html("# Title\n\n![i](img.png)\n", "a <b>.md", BASE_PATH)
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("<title>a &lt;b&gt;.md</title>", page)
        self.assertIn('<base href="{}/">'.format(pathlib.Path(BASE_PATH).as_uri()), page)
        self.assertIn('<h1 id="title">Title</h1>', page)
        self.assertIn('src="img.png"', page)

    def test_unsaved_source_has_no_base(self):
        self.assertNotIn("<base", standalone_html("x", "untitled", ""))

    def test_dialect_matches_the_preview(self):
        page = standalone_html("Text\n- a\n  - b\n\n| x |\n|---|\n| 1 |\n", "t", "")
        self.assertIn("<ul>\n<li>a<ul>\n<li>b</li>", page)
        self.assertIn("<table>", page)
