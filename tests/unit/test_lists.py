import unittest

from MarkdownGlance.preview.renderer.lists import normalise


def run(text):
    return "\n".join(normalise(text.split("\n")))


class ListNormaliserTest(unittest.TestCase):
    """The shapes GitHub-flavoured Markdown takes that Python-Markdown does not.

    Python-Markdown nests on four columns and needs a blank line before a
    list; these are the two-column and cuddled forms rewritten to that.
    """

    def test_two_column_nesting_becomes_four(self):
        self.assertEqual(run("- a\n  - b\n    - c\n- d"), "- a\n    - b\n        - c\n- d")

    def test_four_column_nesting_is_unchanged(self):
        text = "- a\n    - b\n        - c\n- d"
        self.assertEqual(run(text), text)

    def test_ordered_item_content_column_counts_the_marker_width(self):
        self.assertEqual(run("1. a\n   - b\n10. c\n    - d"), "1. a\n    - b\n10. c\n    - d")
        # Two columns under `1.` is not the content column, so not a child.
        self.assertEqual(run("1. a\n  - b"), "1. a\n- b")

    def test_continuation_paragraph_and_code_follow_the_item(self):
        self.assertEqual(
            run("- a\n\n  para\n\n      code\n- b"),
            "- a\n\n    para\n\n        code\n- b",
        )

    def test_lazy_continuation_is_left_alone(self):
        self.assertEqual(run("- a\nlazy\n- b"), "- a\nlazy\n- b")

    def test_list_cuddled_to_a_paragraph_gets_a_blank_line(self):
        self.assertEqual(run("Text\n- a\n- b"), "Text\n\n- a\n- b")
        self.assertEqual(run("Text\n1. a"), "Text\n\n1. a")
        self.assertEqual(run("Text\n* a"), "Text\n\n* a")

    def test_a_dash_without_a_space_is_not_a_marker(self):
        text = "Text\n-not a list\n2.not a list"
        self.assertEqual(run(text), text)

    def test_a_paragraph_after_a_blank_line_ends_the_list(self):
        self.assertEqual(run("- a\n\nPara\n- b"), "- a\n\nPara\n\n- b")

    def test_a_heading_or_rule_ends_the_list(self):
        self.assertEqual(run("- a\n# H\n- b"), "- a\n# H\n\n- b")
        self.assertEqual(run("- a\n\n---\n- b"), "- a\n\n---\n\n- b")

    def test_a_rule_is_not_an_item(self):
        for rule in ("* * *", "- - -", "***"):
            self.assertEqual(run("Text\n\n" + rule), "Text\n\n" + rule)

    def test_indented_code_is_not_a_list(self):
        text = "Para\n\n    - looks like an item"
        self.assertEqual(run(text), text)
        text = "- a\n\n      - code inside the item"
        self.assertEqual(run(text), "- a\n\n        - code inside the item")

    def test_fence_inside_an_item_moves_with_it_and_keeps_its_content(self):
        self.assertEqual(
            run("- a\n\n  ```py\n  x = 1\n    y = 2\n  - not a list\n  ```\n- b"),
            "- a\n\n    ```py\n    x = 1\n      y = 2\n    - not a list\n    ```\n- b",
        )

    def test_top_level_fence_is_untouched(self):
        text = "```\n- a\n  - b\nText\n- c\n```"
        self.assertEqual(run(text), text)

    def test_tilde_fence_closes_only_on_its_own_character(self):
        # The backtick line and the item stay inside the block; the list that
        # follows the block is separated from it like one after a paragraph.
        self.assertEqual(run("~~~\n```\n- a\n~~~\n- b"), "~~~\n```\n- a\n~~~\n\n- b")

    def test_block_quote_is_its_own_document(self):
        self.assertEqual(run("> Text\n> - a\n>   - b"), "> Text\n>\n> - a\n>     - b")
        # Leaving the quote resets the list.
        self.assertEqual(run("> - a\n\nText\n- b"), "> - a\n\nText\n\n- b")
