import unittest

from MarkdownGlance.preview.application.render_pipeline import render
from MarkdownGlance.preview.renderer.export import standalone_html
from MarkdownGlance.preview.renderer import parse
from MarkdownGlance.tests.unit.test_renderer import FakeResolver, request


def preview(source):
    return render(request(source), FakeResolver()).body_html


class NumberedListTest(unittest.TestCase):
    def test_sequential_numbers_and_repeated_source_numbers(self):
        for source in (
            "1. first\n2. second\n3. third",
            "1. first\n1. second\n1. third",
        ):
            html = preview(source)
            for number, word in enumerate(("first", "second", "third"), 1):
                self.assertIn(
                    'class="mg-ordered-item">{}. {}'.format(number, word), html
                )
            self.assertNotIn("<ol", html)
            self.assertNotIn("<li", html)

    def test_non_one_start_and_digit_boundary(self):
        for start in (0, 4, 9):
            html = preview("{}. first\n1. second\n1. third".format(start))
            for number, word in enumerate(("first", "second", "third"), start):
                self.assertIn("{}. {}".format(number, word), html)

    def test_mixed_nesting_has_independent_counters(self):
        html = preview(
            "4. outer\n   - bullet\n     7. inner\n     1. next\n   - other\n1. end"
        )
        for text in ("4. outer", "7. inner", "8. next", "5. end"):
            self.assertIn(text, html)
        self.assertEqual(html.count("<ul>"), 1)
        self.assertEqual(html.count("<li>"), 2)
        self.assertEqual(html.count('class="mg-ordered-list"'), 2)

    def test_adjacent_list_types_stay_separate(self):
        for source in ("1. number\n\n- bullet", "- bullet\n\n4. number"):
            html = preview(source)
            self.assertIn("<ul>\n<li>bullet</li>\n</ul>", html)
            self.assertEqual(html.count('class="mg-ordered-item"'), 1)

    def test_loose_item_number_stays_in_first_paragraph(self):
        html = preview(
            "1. **first** and [link](https://example.test)\n\n   continuation\n\n1. second"
        )
        self.assertIn("<p>1. <strong>first</strong>", html)
        self.assertIn("<p>continuation</p>", html)
        self.assertIn("<p>2. second</p>", html)
        self.assertIn('href="https://example.test"', html)

    def test_fenced_code_is_unchanged(self):
        html = preview("```text\n1. code\n4. still code\n```")
        self.assertIn("1. code<br />4. still code", html)
        self.assertNotIn("mg-ordered", html)

    def test_raw_start_validation_and_safe_attributes(self):
        for start, expected in (("bad", 1), ("-2", -2), ("4", 4)):
            html = preview(
                '<ol start="{}" style="color:red"><li><p>first</p><p>next</p></li></ol>'.format(
                    start
                )
            )
            self.assertIn("<p>{}. first</p>".format(expected), html)
            self.assertNotIn("style=", html)

    def test_images_and_inline_code_survive(self):
        html = preview("1. `code` ![image](pic.png)")
        self.assertIn("1. <code>code</code>", html)
        self.assertEqual(
            len(parse(request("1. `code` ![image](pic.png)")).asset_keys), 1
        )

    def test_browser_export_retains_native_numbered_lists(self):
        html = standalone_html("4. first\n1. second", "Lists", "/mdglance")
        self.assertIn('<ol start="4">', html)
        self.assertNotIn("mg-ordered", html)
