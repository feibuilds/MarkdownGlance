"""Fenced code coloured by a highlighter the renderer is handed.

The real highlighter tokenises in Sublime Text (`adapter/highlighter.py`) and
is exercised by the `highlight` scenario of the run-markdownglance skill. Here
a fake stands in for it, so that what the renderer does with an answer -- and
with a missing or a wrong one -- is pinned without Sublime.
"""

import re
import unittest

from MarkdownGlance.preview.application.render_pipeline import render
from MarkdownGlance.preview.domain.contracts import RenderSettings, ThemeSnapshot
from MarkdownGlance.preview.renderer.highlight import (
    CodeStyle,
    fenced,
    highlight,
    style_attribute,
)
from MarkdownGlance.preview.renderer.minihtml import NBSP
from MarkdownGlance.preview.renderer.model import ElementNode, TextNode

from .test_renderer import FakeResolver, request

THEME = ThemeSnapshot(foreground="#222222")
KEYWORD = CodeStyle("#c695c6", italic=True)
STRING = CodeStyle("#99c794")
PLAIN = CodeStyle("#222222")
TOKEN = re.compile(r"\w+|\s+|[^\w\s]")


class FakeHighlighter:
    """Splits code into words, spaces and punctuation, and colours a few."""

    def __init__(self, styles=None):
        self.styles = styles or {"def": KEYWORD, "return": KEYWORD, "'": STRING}
        self.calls = []

    def __call__(self, blocks, theme):
        self.calls.append((list(blocks), theme))
        return [
            tuple(
                (token, self.styles.get(token, PLAIN)) for token in TOKEN.findall(code)
            )
            for _, code in blocks
        ]


def rendered(markdown, highlighter, **settings):
    return render(
        request(markdown, settings=RenderSettings(**settings), theme=THEME),
        FakeResolver(),
        highlighter=highlighter,
    )


class FenceTest(unittest.TestCase):
    def test_the_code_sits_between_the_fence_lines(self):
        text, begin, end = fenced("python", "x = 1\n")

        self.assertEqual(text, "```python\nx = 1\n```\n")
        self.assertEqual(text[begin:end], "x = 1\n")

    def test_code_without_a_final_newline_still_closes_the_fence(self):
        text, begin, end = fenced("js", "f()")

        self.assertEqual(text, "```js\nf()\n```\n")
        self.assertEqual(text[begin:end], "f()")

    def test_a_backtick_line_in_the_code_cannot_close_the_fence(self):
        code = "s = '''\n```\n  ````\n'''\n"
        text, begin, end = fenced("python", code)

        self.assertTrue(text.startswith("`````python\n"))
        self.assertTrue(text.endswith("\n`````\n"))
        self.assertEqual(text[begin:end], code)


class StyleTest(unittest.TestCase):
    def test_colour_weight_and_slant(self):
        self.assertEqual(
            style_attribute(CodeStyle("#c695c6", bold=True, italic=True)),
            "color: #c695c6; font-weight: bold; font-style: italic",
        )

    def test_a_colour_that_is_not_hex_is_left_out(self):
        self.assertEqual(style_attribute(CodeStyle("red; background: url(x)")), "")
        self.assertEqual(style_attribute(CodeStyle("#11223344")), "color: #11223344")


class HighlightTest(unittest.TestCase):
    def test_a_fence_that_names_its_language_is_coloured(self):
        highlighter = FakeHighlighter()
        document = rendered("```python\ndef f():\n    return 'x'\n```\n", highlighter)

        self.assertEqual(
            highlighter.calls[0][0], [("python", "def f():\n    return 'x'")]
        )
        self.assertIs(highlighter.calls[0][1], THEME)
        # The space after `def` has no colour of its own and joins it.
        self.assertIn(
            '<span style="color: #c695c6; font-style: italic">def </span>f():',
            document.body_html,
        )
        self.assertIn('<span style="color: #99c794">&#x27;</span>x', document.body_html)
        self.assertTrue(document.highlighted)

    def test_text_in_the_document_foreground_is_not_a_span(self):
        document = rendered("```python\nf()\n```\n", FakeHighlighter())

        self.assertIn('<code class="python">f()</code>', document.body_html)

    def test_alike_neighbours_and_whitespace_join_one_span(self):
        styles = {"a": STRING, "b": STRING, "-": STRING}
        document = rendered("```text\na-b c\n```\n", FakeHighlighter(styles))

        # `a`, `-`, `b` and the space after them are one run; `c` is plain.
        self.assertIn('<span style="color: #99c794">a-b </span>c', document.body_html)

    def test_a_run_of_spaces_split_by_a_token_boundary_is_held(self):
        # `x` ends one run and the spaces after it begin another, in a scheme
        # where the two are coloured differently: each half is a single space
        # to the serialiser, which minihtml would collapse to one.
        highlighter = FakeHighlighter({"x": STRING, "  ": KEYWORD})
        document = rendered("```text\nx  y\n```\n", highlighter)

        self.assertIn("x" + NBSP * 2, document.body_html)
        self.assertNotIn("x  ", document.body_html)

    def test_blocks_are_asked_for_in_one_call_in_document_order(self):
        highlighter = FakeHighlighter()
        rendered(
            "```python\na\n```\n\n- item\n\n    ```js\n    b\n    ```\n\n"
            "> ```sh\n> c\n> ```\n",
            highlighter,
        )

        self.assertEqual(len(highlighter.calls), 1)
        self.assertEqual(
            [language for language, _ in highlighter.calls[0][0]],
            ["python", "js", "sh"],
        )

    def test_code_without_a_language_is_not_asked_for(self):
        highlighter = FakeHighlighter()
        document = rendered("```\nplain\n```\n\n    indented\n", highlighter)

        self.assertEqual(highlighter.calls, [])
        self.assertFalse(document.highlighted)

    def test_a_diagram_is_not_code_but_its_source_is(self):
        highlighter = FakeHighlighter()
        diagram = "```mermaid\ngraph TD; A-->B\n```\n"

        rendered(diagram, highlighter, enable_mermaid=True)
        self.assertEqual(highlighter.calls, [])

        rendered(diagram, highlighter)
        self.assertEqual(highlighter.calls[0][0][0][0], "mermaid")

    def test_a_formula_shown_as_its_source_is_not_coloured(self):
        highlighter = FakeHighlighter()
        rendered("$$\nx^2\n$$\n", highlighter)

        self.assertEqual(highlighter.calls, [])

    def test_switched_off_the_highlighter_is_never_asked(self):
        highlighter = FakeHighlighter()
        markdown = "```python\ndef f(): pass\n```\n"
        off = rendered(markdown, highlighter, enable_syntax_highlighting=False)

        self.assertEqual(highlighter.calls, [])
        self.assertEqual(off.body_html, rendered(markdown, None).body_html)
        self.assertFalse(off.highlighted)

    def test_a_block_without_an_answer_stays_plain(self):
        markdown = "```python\ndef f(): pass\n```\n\n```js\nf()\n```\n"
        document = rendered(markdown, lambda blocks, theme: [None] * len(blocks))

        self.assertEqual(document.body_html, rendered(markdown, None).body_html)
        self.assertFalse(document.highlighted)

    def test_runs_that_do_not_spell_the_code_are_not_used(self):
        markdown = "```python\ndef f(): pass\n```\n"
        wrong = lambda blocks, theme: [(("def f():", KEYWORD),) for _ in blocks]

        self.assertEqual(
            rendered(markdown, wrong).body_html, rendered(markdown, None).body_html
        )

    def test_a_language_that_cannot_go_back_into_a_fence_is_not_asked_for(self):
        highlighter = FakeHighlighter()
        code = ElementNode("code", {"class": "py`thon"}, [TextNode("x\n")])
        root = ElementNode("pre", {}, [code])

        self.assertFalse(highlight([root], THEME, highlighter))
        self.assertEqual(highlighter.calls, [])

    def test_the_documents_own_style_attribute_is_still_dropped(self):
        document = rendered('<span style="color: red">x</span>\n', FakeHighlighter())

        self.assertNotIn("style=", document.body_html)


if __name__ == "__main__":
    unittest.main()
