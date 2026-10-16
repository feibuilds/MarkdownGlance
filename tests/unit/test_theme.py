"""What a `ThemeSnapshot` takes off a source view.

The palette answers what the document is painted in; `scheme` answers what the
*surface* has to be put on, because minihtml resolves a phantom's colour
variables against the view the phantom sits in rather than against the source.
"""

import unittest

from MarkdownGlance.preview.adapter.theme import theme_snapshot


class Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class Syntax:
    def __init__(self, path):
        self.path = path


class View:
    def __init__(self, style, settings=None, syntax=None):
        self._style = style
        self._settings = Settings(settings or {})
        self._syntax = syntax

    def style(self):
        return self._style

    def settings(self):
        return self._settings

    def syntax(self):
        return self._syntax


class ThemeSnapshotTest(unittest.TestCase):
    def test_the_palette_comes_from_the_view_style(self):
        theme = theme_snapshot(
            View({"background": "#1e1e2e", "foreground": "#cdd6f4", "accent": "#89b4fa"})
        )

        self.assertEqual(theme.background, "#1e1e2e")
        self.assertEqual(theme.foreground, "#cdd6f4")
        self.assertEqual(theme.accent, "#89b4fa")
        self.assertTrue(theme.is_dark)

    def test_a_light_background_is_not_dark(self):
        self.assertFalse(theme_snapshot(View({"background": "#ccccce"})).is_dark)

    def test_accent_falls_back_to_the_bluish_colour(self):
        theme = theme_snapshot(View({"bluish": "#4078f2"}))

        self.assertEqual(theme.accent, "#4078f2")

    def test_the_markdown_syntax_travels_with_the_palette(self):
        # Fenced code is tokenised by the source's own Markdown syntax, which
        # is MarkdownEditing's rather than the default one when it is installed.
        path = "Packages/MarkdownEditing/syntaxes/Markdown.sublime-syntax"

        self.assertEqual(theme_snapshot(View({}, syntax=Syntax(path))).syntax, path)
        self.assertEqual(theme_snapshot(View({})).syntax, "")

    def test_the_scheme_the_source_resolved_travels_with_the_palette(self):
        # `markdownediting: select color scheme` writes `color_scheme` into
        # `Markdown.sublime-settings`, which beats the global Preferences one.
        theme = theme_snapshot(
            View({}, {"color_scheme": "MarkdownEditor.sublime-color-scheme"})
        )

        self.assertEqual(
            theme.scheme, (("color_scheme", "MarkdownEditor.sublime-color-scheme"),)
        )

    def test_an_auto_scheme_carries_both_halves_it_chooses_between(self):
        theme = theme_snapshot(
            View(
                {},
                {
                    "color_scheme": "auto",
                    "dark_color_scheme": "Mariana.sublime-color-scheme",
                    "light_color_scheme": "Celeste.sublime-color-scheme",
                },
            )
        )

        self.assertEqual(
            theme.scheme,
            (
                ("color_scheme", "auto"),
                ("dark_color_scheme", "Mariana.sublime-color-scheme"),
                ("light_color_scheme", "Celeste.sublime-color-scheme"),
            ),
        )

    def test_a_view_with_no_scheme_settings_carries_none(self):
        self.assertEqual(theme_snapshot(View({})).scheme, ())


if __name__ == "__main__":
    unittest.main()
