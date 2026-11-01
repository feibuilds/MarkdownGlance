import os.path
import re
import unicodedata
import unittest
from unittest import mock

from MarkdownGlance.preview.application.render_pipeline import render
from MarkdownGlance.preview.renderer import tables
from MarkdownGlance.preview.renderer.tables import budgets
from MarkdownGlance.preview.domain.contracts import (
    AssetStatus,
    Failed,
    RenderRequest,
    RenderSettings,
    ThemeSnapshot,
)

BASE_PATH = os.path.realpath(os.path.abspath(os.sep + "mdglance"))
ROW = re.compile(r'<div class="(md-table-row[^"]*)">(.*?)</div>')
CELL = re.compile(r'<span class="md-table-cell">(.*?)</span>')
TAG = re.compile(r"<[^>]+>")
PAD = "\u00a0"

SOURCES = """| Source | What we take | What we do not take as fact |
| --- | --- | --- |
| Lab 305 pt.1 (2026-08-13) | Demo-first, skip the capital, tourist towns, \
600-1,500 band, 2 revisions | Unverified revenue, exact model names |
| List-It NZBN stats (June 2026) | 753,070 entities; 16.1% have a website \
**on the register**; trades 155,145 | No website on NZBN is not no website |
"""

CJK = """| 中文表头 | 说明 | Note |
| --- | --- | --- |
| 预览 | 等宽对齐 | ok |
| 混合 abc | 中文 123 | fine |
"""

# Issue #9: wide enough to wrap, with one wide glyph in the header.
LONG_HEADER = "very " * 19 + "very long header"
EMOJI_HEADER = """| h1 | emoji 😀 | {} | x |
|:--|--:|:-:|---|
| a | b | c | d |
""".format(LONG_HEADER)
CJK_HEADER = """| 日本語 | h2 | {} | x |
|:--|--:|:-:|---|
| a | b | c | d |
""".format(LONG_HEADER)


class FakeResolver:
    def resolve(self, keys, session_id):
        return {key: Failed(AssetStatus.UNAVAILABLE) for key in keys}


def request(markdown, settings=None, viewport_width=0.0):
    return RenderRequest(
        "session",
        7,
        markdown,
        BASE_PATH,
        1.0,
        settings or RenderSettings(),
        ThemeSnapshot(),
        "opaque-token",
        viewport_width,
    )


def body(markdown, settings=None, viewport_width=0.0):
    return render(request(markdown, settings, viewport_width), FakeResolver()).body_html


def rows(markdown, settings=None, viewport_width=0.0):
    """Each rendered line as (classes, list of cell texts, markup stripped)."""
    return [
        (
            match.group(1),
            [TAG.sub("", cell) for cell in CELL.findall(match.group(2))],
        )
        for match in ROW.finditer(body(markdown, settings, viewport_width))
    ]


def width(text, ambiguous=1):
    """An independent width oracle, so the renderer cannot grade itself."""
    total = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        kind = unicodedata.east_asian_width(char)
        total += 2 if kind in ("W", "F") else (ambiguous if kind == "A" else 1)
    return total


class TableTest(unittest.TestCase):
    def test_pipe_table_becomes_rows_and_not_literal_pipes(self):
        html = body("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
        self.assertIn('<div class="md-table">', html)
        self.assertNotIn("<table", html)
        self.assertNotIn("| a | b |", html)
        self.assertEqual(
            [
                [cell.replace(PAD, "").strip() for cell in cells]
                for _, cells in rows("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
            ],
            [["a", "b"], ["1", "2"]],
        )

    def test_header_is_marked_and_ruled_once(self):
        classes = [
            class_value
            for class_value, _ in rows("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
        ]
        self.assertEqual(classes.count("md-table-row md-table-head md-table-rule"), 1)
        self.assertEqual(classes[-1], "md-table-row")

    def test_columns_are_the_same_width_on_every_line(self):
        measured = [[width(cell) for cell in cells] for _, cells in rows(SOURCES)]
        self.assertGreater(len(measured), 3)
        # The last column carries no trailing padding, so it is free to vary.
        self.assertEqual(len({tuple(line[:-1]) for line in measured}), 1, measured)

    def test_a_wide_table_is_wrapped_within_the_budget(self):
        settings = RenderSettings(table_max_columns=40)
        for _, cells in rows(SOURCES, settings):
            self.assertLessEqual(sum(width(cell) for cell in cells), 40, cells)

    def test_a_narrow_table_keeps_one_line_per_row(self):
        self.assertEqual(len(rows("| Month | Jobs |\n| --- | --- |\n| 1 | few |\n")), 2)

    def test_markup_boundaries_do_not_gain_a_space(self):
        html = body(SOURCES)
        self.assertIn("register</strong>;", html)
        self.assertNotIn("register</strong> ;", html)

    def test_alignment_pads_on_the_correct_side(self):
        markdown = (
            "| a | bbbb | cccc | d |\n| :-- | --: | :-: | --- |\n"
            "| 1 | 22 | 3 | x |\n"
        )
        cells = rows(markdown)[-1][1]
        self.assertTrue(cells[0].startswith("1"), cells)
        self.assertTrue(cells[1].startswith(PAD + PAD + "22"), cells)
        self.assertTrue(cells[2].startswith(PAD) and PAD + PAD in cells[2], cells)

    def test_links_in_cells_stay_navigable(self):
        markdown = (
            "| Source | Note |\n| --- | --- |\n"
            "| [site](https://example.test) | [next](notes/next.md) |\n"
        )
        document = render(request(markdown), FakeResolver())
        self.assertEqual(document.links, ("notes/next.md",))
        self.assertIn('href="https://example.test"', document.body_html)
        self.assertIn("mdglance_open_relative", document.body_html)

    def test_wrapping_reopens_markup_on_the_next_line(self):
        markdown = (
            "| Note |\n| --- |\n" "| **one two three four five six seven eight** |\n"
        )
        settings = RenderSettings(table_max_columns=20)
        self.assertGreater(len(rows(markdown, settings)), 2)
        self.assertGreater(body(markdown, settings).count("<strong>"), 1)

    def test_cjk_table_uses_the_wide_font_and_counts_wide_glyphs(self):
        html = body(CJK)
        self.assertIn('class="md-table md-table-cjk"', html)
        measured = [
            [width(cell, ambiguous=2) for cell in cells] for _, cells in rows(CJK)
        ]
        self.assertEqual(len({tuple(line[:-1]) for line in measured}), 1, measured)

    def test_a_latin_table_keeps_the_latin_font(self):
        html = body("| a | b |\n| --- | --- |\n| 1 | 2 |\n")
        self.assertIn('class="md-table"', html)
        self.assertNotIn("md-table-cjk", html)

    def test_an_emoji_does_not_put_a_table_in_the_cjk_font(self):
        # It comes from a colour font whichever stack the table names.
        for emoji in ("😀", "⭐", "☕", "🈁"):
            html = body("| a {} | b |\n| --- | --- |\n| 1 | 2 |\n".format(emoji))
            self.assertNotIn("md-table-cjk", html, emoji)

    def test_cjk_beside_an_emoji_still_takes_the_cjk_font(self):
        for text in ("中文 😀", "かな", "한국어", "１２", "ᄀ"):
            html = body("| {} | b |\n| --- | --- |\n| 1 | 2 |\n".format(text))
            self.assertIn("md-table-cjk", html, text)

    def test_an_emoji_header_wraps_within_the_latin_budget(self):
        # Issue #9: the emoji used to buy the table the CJK budget, a fifth
        # wider than the Latin font it is drawn in, and the host re-wrapped it.
        columns = budgets(950.0, 16, 200)[0]
        self.assertNotIn("md-table-cjk", body(EMOJI_HEADER, viewport_width=950.0))
        for _, cells in rows(EMOJI_HEADER, viewport_width=950.0):
            self.assertLessEqual(sum(width(cell) for cell in cells), columns, cells)

    def test_without_the_cjk_font_a_cjk_table_wraps_within_the_latin_budget(self):
        with mock.patch.object(tables, "CJK_FONT_SHIPS", False):
            columns = budgets(950.0, 16, 200)[0]
            lines = rows(CJK_HEADER, viewport_width=950.0)
        for _, cells in lines:
            self.assertLessEqual(sum(width(cell, 2) for cell in cells), columns, cells)

    def test_cjk_wraps_between_characters(self):
        markdown = "| 说明 | b |\n| --- | --- |\n| 一二三四五六七八九十 | x |\n"
        lines = rows(markdown, RenderSettings(table_max_columns=16))
        self.assertGreater(len(lines), 2)
        for _, cells in lines:
            self.assertLessEqual(sum(width(cell, 2) for cell in cells), 16, cells)

    def test_raw_html_tables_are_rewritten_too(self):
        html = body("<table><tr><th>a</th></tr><tr><td>1</td></tr></table>")
        self.assertNotIn("<table", html)
        self.assertIn("md-table", html)

    def test_ragged_and_empty_cells_do_not_raise(self):
        html = body("| a | b | c |\n| --- | --- | --- |\n| 1 |  |\n|  |  |  |\n")
        self.assertIn("md-table", html)

    def test_a_caption_is_kept_above_the_rows(self):
        html = body("<table><caption>Cap</caption><tr><td>1</td></tr></table>")
        self.assertIn('<div class="md-table-caption">Cap</div>', html)


class BudgetTest(unittest.TestCase):
    def test_an_unmeasured_preview_falls_back_to_a_narrow_width(self):
        self.assertEqual(budgets(0.0, 16, 200), (48, 48))

    def test_a_wider_preview_buys_more_columns(self):
        narrow = budgets(400.0, 16, 200)
        wide = budgets(1200.0, 16, 200)
        self.assertLess(narrow[0], wide[0])
        self.assertLess(narrow[1], wide[1])

    def test_the_cjk_font_fits_more_columns_than_the_latin_one(self):
        with mock.patch.object(tables, "CJK_FONT_SHIPS", True):
            latin, cjk = budgets(900.0, 16, 200)
        self.assertGreater(cjk, latin)

    def test_a_host_without_the_cjk_font_counts_cjk_at_the_latin_advance(self):
        # Windows and macOS ship none of the CJK stack, so a CJK table there is
        # set in `monospace`, no narrower than the Latin font (issue #9).
        with mock.patch.object(tables, "CJK_FONT_SHIPS", False):
            latin, cjk = budgets(900.0, 16, 200)
        self.assertEqual(cjk, latin)

    def test_the_advance_is_rounded_up_to_whole_pixels(self):
        # A 904 px preview measured on ST 4200: 82 columns of 10 px fit inside
        # it, not the 85 that an unrounded 9.64 px advance would suggest.
        self.assertEqual(budgets(904.0, 16, 200)[0], 81)

    def test_the_setting_caps_the_measured_width(self):
        self.assertEqual(budgets(1600.0, 16, 40)[0], 40)

    def test_zoom_costs_columns(self):
        self.assertLess(budgets(904.0, 24, 200)[0], budgets(904.0, 16, 200)[0])


class ViewportFitTest(unittest.TestCase):
    def test_a_measured_preview_widens_the_table(self):
        unmeasured = rows(SOURCES)
        measured = rows(SOURCES, viewport_width=1200.0)
        self.assertLess(len(measured), len(unmeasured))
        widest = max(sum(width(cell) for cell in cells) for _, cells in measured)
        self.assertGreater(widest, 48)

    def test_the_table_never_exceeds_what_the_preview_can_show(self):
        columns = budgets(700.0, 16, 200)[0]
        for _, cells in rows(SOURCES, viewport_width=700.0):
            self.assertLessEqual(sum(width(cell) for cell in cells), columns, cells)
