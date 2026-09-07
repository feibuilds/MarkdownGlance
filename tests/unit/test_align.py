import unittest

from MarkdownGlance.preview.domain.contracts import Heading, SourceHeading
from MarkdownGlance.preview.renderer.align import align, normalise


def scanned(*items):
    """(level, text, line) triples, as `scan_outline` would number them."""
    return tuple(
        SourceHeading(level, text, ordinal, line)
        for ordinal, (level, text, line) in enumerate(items)
    )


def rendered(*items):
    """(level, text, slug) triples, as the renderer would number them."""
    return tuple(
        Heading(level, text, slug, ordinal, 0.1 * ordinal)
        for ordinal, (level, text, slug) in enumerate(items)
    )


class NormaliseTest(unittest.TestCase):
    def test_inline_markup_comes_off(self):
        # The renderer keeps a heading's text, not its Markdown; measured over
        # this repository, 9 of 47 files have at least one heading that differs
        # only by this.
        self.assertEqual(normalise("An outline on `Ctrl+Shift+B`"),
                         "An outline on Ctrl+Shift+B")
        self.assertEqual(normalise("[Unreleased]"), "Unreleased")
        self.assertEqual(normalise("*Emphasis* and **strong**"),
                         "Emphasis and strong")

    def test_a_link_keeps_only_its_text(self):
        self.assertEqual(normalise("See [the plan](docs/plan.md)"), "See the plan")
        self.assertEqual(normalise("See [the plan][plan]"), "See the plan")

    def test_whitespace_is_collapsed(self):
        self.assertEqual(normalise("Two   spaces\tand a tab"), "Two spaces and a tab")


class AlignTest(unittest.TestCase):
    def test_lists_that_match_pair_up_both_ways(self):
        links = align(
            scanned((1, "One", 0), (2, "Two", 4)),
            rendered((1, "One", "one"), (2, "Two", "two")),
        )
        self.assertEqual(links.slug_for(1), "two")
        self.assertEqual(links.line_for("two"), 4)

    def test_markup_does_not_stop_a_pairing(self):
        links = align(
            scanned((2, "On `Ctrl+Shift+B`", 3)),
            rendered((2, "On Ctrl+Shift+B", "on-ctrl-shift-b")),
        )
        self.assertEqual(links.slug_for(0), "on-ctrl-shift-b")

    def test_a_heading_only_the_renderer_sees_pairs_nothing(self):
        """A raw `<h2>` block, or one inside a block quote.

        Measured: both put a heading in the render that `scan_outline` never
        sees. Pairing by position would send every heading after it to the
        wrong section.
        """
        links = align(
            scanned((1, "One", 0), (2, "Two", 6)),
            rendered((1, "One", "one"), (2, "Raw", "raw"), (2, "Two", "two")),
        )
        self.assertEqual(links.slug_for(0), "one")
        self.assertEqual(links.slug_for(1), "two")
        self.assertIsNone(links.line_for("raw"))

    def test_a_heading_only_the_scan_sees_pairs_nothing(self):
        links = align(
            scanned((1, "One", 0), (2, "Only", 4), (2, "Two", 8)),
            rendered((1, "One", "one"), (2, "Two", "two")),
        )
        self.assertEqual(links.slug_for(0), "one")
        self.assertIsNone(links.slug_for(1))
        self.assertEqual(links.slug_for(2), "two")
        self.assertEqual(links.line_for("two"), 8)

    def test_the_same_text_at_a_different_level_is_not_a_pair(self):
        links = align(
            scanned((2, "Status", 3)),
            rendered((3, "Status", "status")),
        )
        self.assertEqual(links, align((), ()))

    def test_duplicate_headings_keep_their_own_slugs(self):
        links = align(
            scanned((2, "Same", 2), (2, "Same", 6)),
            rendered((2, "Same", "same"), (2, "Same", "same-2")),
        )
        self.assertEqual(links.slug_for(0), "same")
        self.assertEqual(links.slug_for(1), "same-2")
        self.assertEqual(links.line_for("same-2"), 6)

    def test_either_list_empty_pairs_nothing(self):
        self.assertEqual(align((), rendered((1, "One", "one"))).to_slug, {})
        self.assertEqual(align(scanned((1, "One", 0)), ()).to_line, {})


if __name__ == "__main__":
    unittest.main()
