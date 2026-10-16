"""The phantom backend, against a stub of the sliver of the Sublime API it uses.

`PhantomSet.update` identifies a phantom by the tuple
`(region, content, layout, on_navigate)`. A callback built fresh on each
repaint never compares equal to the one already on screen, so the set erases
the phantom and adds it back and minihtml lays the whole document out again --
on a 69 KB document that is ~180 KB of HTML re-parsed for nothing. These tests
pin the two properties that stop it: one callback per surface, and no call at
all when the HTML has not changed.
"""

import sys
import types
import unittest


def _install_sublime_stub():
    if "sublime" in sys.modules and hasattr(sys.modules["sublime"], "_is_mdglance_stub"):
        return sys.modules["sublime"]

    module = types.ModuleType("sublime")
    module._is_mdglance_stub = True
    module.LAYOUT_BLOCK = 1

    class Region:
        def __init__(self, a, b=None):
            self.a = a
            self.b = a if b is None else b

        def to_tuple(self):
            return (self.a, self.b)

        def __eq__(self, other):
            return isinstance(other, Region) and self.to_tuple() == other.to_tuple()

    class Phantom:
        def __init__(self, region, content, layout, on_navigate=None):
            self.region = region
            self.content = content
            self.layout = layout
            self.on_navigate = on_navigate

        def to_tuple(self):
            return (self.region.to_tuple(), self.content, self.layout, self.on_navigate)

    class PhantomSet:
        """Mirrors the identity rule of the real one, and counts the adds."""

        def __init__(self, view, key=""):
            self.view = view
            self.key = key
            self.phantoms = []
            self.added = 0

        def update(self, phantoms):
            current = {p.to_tuple() for p in self.phantoms}
            for phantom in phantoms:
                if phantom.to_tuple() not in current:
                    self.added += 1
            self.phantoms = list(phantoms)

    module.Region = Region
    module.Phantom = Phantom
    module.PhantomSet = PhantomSet
    module.windows = lambda: []
    sys.modules["sublime"] = module
    return module


SUBLIME = _install_sublime_stub()

from MarkdownGlance.preview.application.ports import SurfaceHandle  # noqa: E402
from MarkdownGlance.preview.domain.contracts import ThemeSnapshot  # noqa: E402
from MarkdownGlance.preview.presentation.phantom_view import (  # noqa: E402
    PhantomViewBackend,
    scroll_target,
)
from MarkdownGlance.preview.renderer.stylesheet import line_px  # noqa: E402


class Settings:
    def __init__(self):
        self.values = {}
        self.writes = []

    def set(self, key, value):
        self.writes.append((key, value))
        self.values[key] = value

    def get(self, key, default=None):
        return self.values.get(key, default)

    def has(self, key):
        return key in self.values

    def erase(self, key):
        self.values.pop(key, None)


class View:
    def __init__(self, identifier):
        self._id = identifier
        self._settings = Settings()

    def id(self):
        return self._id

    def settings(self):
        return self._settings


class PhantomViewBackendTest(unittest.TestCase):
    def setUp(self):
        self.links = []
        self.backend = PhantomViewBackend(
            lambda handle, href: self.links.append((handle.id, href))
        )
        self.view = View(7)
        self.handle = SurfaceHandle("phantom_view", 7, 1)
        self.backend._view = lambda handle: self.view
        self.backend._window_view = lambda handle: (None, self.view)

    def phantom_set(self):
        return self.backend._phantoms[self.handle.id]

    def test_the_same_html_is_added_once_however_often_it_is_pushed(self):
        for _ in range(5):
            self.backend.update(self.handle, "<p>same</p>")
        self.assertEqual(self.phantom_set().added, 1)

    def test_changed_html_is_added_again(self):
        self.backend.update(self.handle, "<p>one</p>")
        self.backend.update(self.handle, "<p>two</p>")
        self.assertEqual(self.phantom_set().added, 2)

    def test_html_that_returns_to_a_previous_value_still_repaints(self):
        self.backend.update(self.handle, "<p>one</p>")
        self.backend.update(self.handle, "<p>two</p>")
        self.backend.update(self.handle, "<p>one</p>")
        self.assertEqual(self.phantom_set().added, 3)

    def test_the_navigate_callback_is_stable_across_repaints(self):
        self.backend.update(self.handle, "<p>one</p>")
        first = self.phantom_set().phantoms[0].on_navigate
        self.backend.update(self.handle, "<p>two</p>")
        second = self.phantom_set().phantoms[0].on_navigate
        self.assertIs(first, second)

    def test_the_callback_still_reaches_the_link_handler_with_its_handle(self):
        self.backend.update(self.handle, "<p>one</p>")
        self.phantom_set().phantoms[0].on_navigate("#slug")
        self.assertEqual(self.links, [(7, "#slug")])

    def test_every_repaint_is_reported_with_its_size_and_cost(self):
        paints = []
        backend = PhantomViewBackend(
            lambda handle, href: None,
            lambda handle, size, ms, skipped: paints.append((size, skipped)),
        )
        backend._view = lambda handle: self.view
        html = "<p>one</p>"

        backend.update(self.handle, html)
        backend.update(self.handle, html)
        backend.update(self.handle, "<p>two</p>")

        self.assertEqual(
            paints, [(len(html), False), (len(html), True), (len("<p>two</p>"), False)]
        )

    def test_a_dead_surface_reports_nothing(self):
        paints = []
        backend = PhantomViewBackend(None, lambda *args: paints.append(args))
        backend._view = lambda handle: None

        backend.update(self.handle, "<p>one</p>")

        self.assertEqual(paints, [])

    def test_closing_a_surface_forgets_its_callback_and_its_html(self):
        self.backend.update(self.handle, "<p>one</p>")
        self.view.close = lambda: None
        self.backend.close(self.handle)
        self.assertNotIn(self.handle.id, self.backend._navigators)
        self.assertNotIn(self.handle.id, self.backend._html)


class ColourSchemeTest(unittest.TestCase):
    """The phantom reads `var(--background)` and the rest from the colour
    scheme of the view it sits in, so the source's scheme has to be put on the
    surface for a Markdown file that MarkdownEditing has given one of its own.
    """

    SCHEME = (
        ("color_scheme", "MarkdownEditor.sublime-color-scheme"),
        ("dark_color_scheme", "MarkdownEditor-Dark.sublime-color-scheme"),
    )

    def setUp(self):
        self.backend = PhantomViewBackend()
        self.view = View(7)
        self.handle = SurfaceHandle("phantom_view", 7, 1)
        self.backend._view = lambda handle: self.view

    def test_every_named_scheme_setting_lands_on_the_surface(self):
        self.backend.apply_theme(self.handle, ThemeSnapshot(scheme=self.SCHEME))

        self.assertEqual(self.view.settings().writes, list(self.SCHEME))

    def test_a_scheme_already_in_place_is_not_written_again(self):
        # Sublime re-resolves the scheme on every write, and this runs on
        # every repaint -- including the ones the viewport poll asks for.
        self.backend.apply_theme(self.handle, ThemeSnapshot(scheme=self.SCHEME))
        self.backend.apply_theme(self.handle, ThemeSnapshot(scheme=self.SCHEME))

        self.assertEqual(self.view.settings().writes, list(self.SCHEME))

    def test_a_moved_scheme_is_written(self):
        self.backend.apply_theme(self.handle, ThemeSnapshot(scheme=self.SCHEME))
        moved = (("color_scheme", "MarkdownEditor-Yellow.sublime-color-scheme"),)

        self.backend.apply_theme(self.handle, ThemeSnapshot(scheme=moved))

        self.assertEqual(self.view.settings().writes[-1:], list(moved))

    def test_a_dead_surface_is_left_alone(self):
        self.backend._view = lambda handle: None

        self.backend.apply_theme(self.handle, ThemeSnapshot(scheme=self.SCHEME))

        self.assertEqual(self.view.settings().writes, [])


class ScrollTargetTest(unittest.TestCase):
    """A surface is an empty buffer under one phantom, so the navigation keys
    move the viewport rather than a caret (#6). Heights are those measured on
    `toc-long.md` in build 4215: a 519 px viewport over a 4688 px document."""

    VIEWPORT = 519.0
    EXTENT = 4688.0
    BOTTOM = EXTENT - VIEWPORT
    LINE = 24.8

    def target(self, top, by, forward):
        return scroll_target(top, self.VIEWPORT, self.EXTENT, by, forward, self.LINE)

    def test_an_arrow_moves_one_line(self):
        self.assertEqual(self.target(100.0, "lines", True), 124.8)
        self.assertEqual(self.target(100.0, "lines", False), 75.2)

    def test_a_page_keeps_one_line_of_the_last_on_screen(self):
        self.assertEqual(self.target(0.0, "pages", True), self.VIEWPORT - self.LINE)
        self.assertEqual(self.target(1000.0, "pages", False), 1000.0 - 494.2)

    def test_home_and_end_go_to_either_end(self):
        self.assertEqual(self.target(1000.0, "document", False), 0.0)
        self.assertEqual(self.target(1000.0, "document", True), self.BOTTOM)

    def test_neither_end_is_overshot(self):
        self.assertEqual(self.target(10.0, "lines", False), 0.0)
        self.assertEqual(self.target(10.0, "pages", False), 0.0)
        self.assertEqual(self.target(self.BOTTOM - 5.0, "lines", True), self.BOTTOM)
        self.assertEqual(self.target(self.BOTTOM, "pages", True), self.BOTTOM)

    def test_a_document_shorter_than_the_viewport_stays_put(self):
        for by in ("lines", "pages", "document"):
            for forward in (True, False):
                self.assertEqual(
                    scroll_target(0.0, 519.0, 300.0, by, forward, self.LINE), 0.0
                )

    def test_a_page_in_a_viewport_shorter_than_two_lines_still_moves(self):
        self.assertEqual(scroll_target(0.0, 30.0, 4688.0, "pages", True, 24.8), 24.8)

    def test_a_line_follows_the_zoom(self):
        self.assertEqual(line_px(1.0), 24.8)
        self.assertEqual(line_px(2.0), 49.6)


class ScrollView(View):
    def __init__(self, identifier, top=0.0):
        super().__init__(identifier)
        self.position = (0.0, top)
        self.moves = []

    def viewport_position(self):
        return self.position

    def viewport_extent(self):
        return (339.0, 519.0)

    def layout_extent(self):
        return (331.0, 4688.0)

    def set_viewport_position(self, xy, animate=True):
        self.moves.append((xy, animate))
        self.position = xy


class BackendScrollTest(unittest.TestCase):
    def setUp(self):
        self.backend = PhantomViewBackend()
        self.view = ScrollView(7, top=100.0)
        self.handle = SurfaceHandle("phantom_view", 7, 1)
        self.backend._view = lambda handle: self.view

    def test_an_arrow_is_not_animated_so_a_held_key_keeps_up(self):
        self.backend.scroll(self.handle, "lines", True, 24.8)
        self.assertEqual(self.view.moves, [((0.0, 124.8), False)])

    def test_a_page_and_an_end_are_animated(self):
        self.backend.scroll(self.handle, "pages", True, 24.8)
        self.backend.scroll(self.handle, "document", False, 24.8)
        self.assertEqual(
            self.view.moves, [((0.0, 100.0 + 494.2), True), ((0.0, 0.0), True)]
        )

    def test_presses_accumulate(self):
        for _ in range(3):
            self.backend.scroll(self.handle, "lines", True, 24.8)
        self.assertAlmostEqual(self.view.position[1], 100.0 + 3 * 24.8)

    def test_a_dead_surface_is_left_alone(self):
        self.backend._view = lambda handle: None
        self.backend.scroll(self.handle, "lines", True, 24.8)
        self.assertEqual(self.view.moves, [])


if __name__ == "__main__":
    unittest.main()
