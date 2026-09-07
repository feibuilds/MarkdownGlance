import unittest

from MarkdownGlance.preview.application.panel import PanelController
from MarkdownGlance.preview.application.ports import GroupRole, SurfaceHandle
from MarkdownGlance.preview.domain.contracts import (
    Heading,
    PreviewDocument,
    RenderSettings,
    ThemeSnapshot,
)
from MarkdownGlance.preview.renderer.measure import outline_width_px, toc_width_px

SOURCE = "# One\n\ntext\n\n## Two\n\nmore\n"


class View:
    def __init__(self, identifier, window, buffer_id=None, markdown=True, text=SOURCE):
        self._id = identifier
        self._window = window
        self._buffer = buffer_id if buffer_id is not None else identifier
        self._markdown = markdown
        self.text = text
        self.row = 0
        self.name_value = "doc.md"

    def id(self):
        return self._id

    def buffer_id(self):
        return self._buffer

    def window(self):
        return self._window

    def match_selector(self, point, selector):
        return self._markdown and selector == "text.html.markdown"

    def name(self):
        return self.name_value

    def file_name(self):
        return None


class Window:
    def __init__(self):
        self._views = []
        self.active = None
        self.focused = []
        self._layout = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}

    def id(self):
        return 1

    def add(self, view):
        self._views.append(view)
        return view

    def views(self):
        return list(self._views)

    def layout(self):
        return self._layout

    def get_view_index(self, view):
        return (0, 0)

    def active_sheet(self):
        return Sheet(self.active)

    def active_view(self):
        return self.active

    def focus_view(self, view):
        self.focused.append(view.id())
        self.active = view


class Sheet:
    def __init__(self, view):
        self._view = view

    def view(self):
        return self._view


class Session:
    """Only what the panel reads off a preview session."""

    def __init__(self, source_buffer_id):
        self.source_buffer_id = source_buffer_id


class Backend:
    def __init__(self):
        self.next_id = 100
        self.alive = set()
        self.html = {}
        self.groups = {}
        self.roles = {}
        self.titles = {}
        self.focused = []
        self.closed = []
        self.themes = {}

    def create(self, window, group, title, session_id):
        self.next_id += 1
        self.alive.add(self.next_id)
        self.titles[self.next_id] = title
        self.groups[self.next_id] = group
        return SurfaceHandle("fake", self.next_id, window.id())

    def group_of(self, handle):
        return self.groups.get(handle.id)

    def set_role(self, handle, role):
        self.roles[handle.id] = role

    def set_title(self, handle, title):
        self.titles[handle.id] = title

    def update(self, handle, html):
        self.html[handle.id] = html

    def apply_theme(self, handle, theme):
        self.themes[handle.id] = theme

    def is_alive(self, handle):
        return handle.id in self.alive

    def focus(self, handle):
        self.focused.append(handle.id)

    def close(self, handle):
        self.closed.append(handle.id)
        self.alive.discard(handle.id)

    def live_handles(self, window):
        return [SurfaceHandle("fake", item, window.id()) for item in sorted(self.alive)]


class Layout:
    def __init__(self):
        self.acquired = []
        self.released = []
        self.fitted = []
        self.owned = True
        # Which groups this owner is holding for whom, the way the real one
        # tracks holders: the callers no longer keep group numbers of their own.
        self.held = {}

    def acquire_panel(self, window, anchor_group, session_id, width_px=0.0):
        self.acquired.append((anchor_group, GroupRole.PANEL, session_id, width_px))
        self.held.setdefault(session_id, set()).add(1)
        return 1

    def release_all(self, window, session_id, restore=True):
        for group in sorted(self.held.pop(session_id, ()), reverse=True):
            self.release(window, group, session_id, restore=restore)

    def fit(self, window, group, role, width_px):
        self.fitted.append((group, role, width_px))

    def is_owned(self, window, group):
        return self.owned

    def release(self, window, group, session_id, restore=True):
        self.released.append((group, session_id, restore))


class Clock:
    def __init__(self):
        self.pending = {}
        self.cancelled = []
        self._next = 0

    def call_later(self, delay_ms, callback):
        self._next += 1
        self.pending[self._next] = (delay_ms, callback)
        return self._next

    def cancel(self, handle):
        if handle is not None:
            self.cancelled.append(handle)
            self.pending.pop(handle, None)

    def run_all(self):
        for _, callback in list(self.pending.values()):
            callback()
        self.pending.clear()


class PanelControllerTest(unittest.TestCase):
    """One panel per window, over the document the window is on."""

    def setUp(self):
        self.window = Window()
        self.backend = Backend()
        self.layout = Layout()
        self.clock = Clock()
        self.source = self.window.add(View(1, self.window))
        self.window.active = self.source
        self.reveals = []
        self.settings = RenderSettings(update_delay_ms=50)
        self.previews = {}
        self.previews_by_id = {}
        self.scrolled = []
        self.scrollable = True
        self.controller = PanelController(
            self.backend,
            self.layout,
            self.clock,
            lambda window_id: self.window if window_id == 1 else None,
            lambda: self.settings,
            lambda view: ThemeSnapshot(),
            lambda view: view.text,
            lambda view: view.row,
            lambda view, line: self.reveals.append((view.id(), line)),
            "/* css */",
            lambda surface_id: self.previews.get(surface_id),
            self.scroll,
        )

    def scroll(self, window_id, buffer_id, slug):
        """The real one answers whether the preview actually moved."""
        self.scrolled.append((window_id, buffer_id, slug))
        return self.scrollable

    # -- helpers ---------------------------------------------------------

    def stage(self):
        return self.controller.stage(1)

    def surface(self):
        stage = self.stage()
        return stage.surface if stage is not None else None

    def html(self):
        return self.backend.html.get(self.surface().id, "")

    def record(self, view=None):
        view = view or self.source
        return self.controller.document(1, view.buffer_id())

    def focus(self, view):
        self.window.active = view
        return view

    def focus_panel(self):
        view = View(self.surface().id, self.window, markdown=False)
        self.window.active = view
        return view

    def other(self, identifier=2, markdown=True, text="# Other\n\n## Two\n"):
        view = self.window.add(
            View(identifier, self.window, markdown=markdown, text=text)
        )
        view.name_value = "other.md"
        return view

    def preview_view(self, identifier=90, buffer_id=None):
        """A preview surface for a document, as the panel sees it focused."""
        view = self.previews_by_id.get(identifier)
        if view is None:
            view = View(identifier, self.window, buffer_id=-identifier, markdown=False)
            self.window.add(view)
            self.previews[identifier] = Session(
                buffer_id if buffer_id is not None else self.source.buffer_id()
            )
            self.previews_by_id[identifier] = view
        return view

    # The texts and levels the fixture's own SOURCE has, so that the two
    # heading lists align the way a real document's do.
    TEXTS = (("One", 1), ("Two", 2), ("Three", 3), ("Four", 4))

    def document(self, count=2):
        headings = tuple(
            Heading(level, text, "h{}".format(index), index, 0.1)
            for index, (text, level) in enumerate(self.TEXTS[:count])
        )
        return PreviewDocument(1, "<p>body</p>", headings, (), (), ())

    def render(self, view=None, count=2, focused="preview"):
        """What `UseCases.present` hands the panel after a render."""
        view = view or self.source
        if focused == "preview":
            self.window.active = self.preview_view(buffer_id=view.buffer_id())
        rendered = self.document(count)
        self.controller.document_rendered(1, view.buffer_id(), rendered)
        return rendered

    # -- opening ---------------------------------------------------------

    def test_toggle_opens_a_panel_in_its_own_group_and_focuses_it(self):
        self.controller.toggle(self.window)
        stage = self.stage()
        self.assertIsNotNone(stage)
        self.assertEqual(
            [item[:3] for item in self.layout.acquired],
            [(0, GroupRole.PANEL, stage.id)],
        )
        self.assertEqual(self.backend.roles[stage.surface.id], "panel")
        self.assertEqual(self.backend.titles[stage.surface.id], "Contents: doc.md")
        self.assertEqual(self.backend.focused, [stage.surface.id])
        self.assertIn("source-outline", self.html())
        self.assertIn("/* css */", self.html())

    def test_the_group_is_asked_for_the_width_the_entries_need(self):
        self.controller.toggle(self.window)
        wanted = outline_width_px(self.record().headings, 16)
        self.assertGreater(wanted, 0.0)
        self.assertAlmostEqual(self.layout.acquired[0][3], wanted)
        self.assertEqual(self.layout.fitted, [(1, GroupRole.PANEL, wanted)])

    def test_an_edit_re_fits_the_group(self):
        self.controller.toggle(self.window)
        self.source.text = "# One\n\n## A much longer heading than before\n"
        self.controller.refresh_for_source(self.source)
        self.clock.run_all()
        self.assertEqual(
            self.layout.fitted[-1],
            (1, GroupRole.PANEL, outline_width_px(self.record().headings, 16)),
        )
        self.assertGreater(self.layout.fitted[-1][2], self.layout.fitted[0][2])

    def test_the_setting_off_asks_for_the_default_share(self):
        self.settings = RenderSettings(update_delay_ms=50, auto_width=False)
        self.controller.toggle(self.window)
        self.assertEqual(self.layout.acquired[0][3], 0.0)
        self.assertEqual(self.layout.fitted, [(1, GroupRole.PANEL, 0.0)])

    def test_a_non_markdown_view_opens_nothing(self):
        self.focus(self.window.add(View(2, self.window, markdown=False)))
        self.controller.toggle(self.window)
        self.assertIsNone(self.stage())

    def test_asked_for_from_the_preview_it_opens_over_that_document(self):
        self.focus(self.preview_view())

        self.controller.toggle(self.window)

        self.assertEqual(self.stage().showing, self.source.buffer_id())

    def test_second_press_from_the_source_focuses_the_open_panel(self):
        self.controller.toggle(self.window)
        surface = self.surface()
        self.controller.toggle(self.window)
        self.assertEqual(self.backend.focused, [surface.id, surface.id])
        self.assertEqual(self.backend.closed, [])

    def test_press_while_the_panel_is_focused_closes_it_and_returns_focus(self):
        self.controller.toggle(self.window)
        surface = self.surface()
        self.focus_panel()
        self.controller.toggle(self.window)
        self.assertEqual(self.backend.closed, [surface.id])
        self.assertIsNone(self.stage())
        self.assertEqual(self.window.focused[-1], self.source.id())
        self.assertEqual([item[0] for item in self.layout.released], [1])

    # -- content ---------------------------------------------------------

    def test_the_heading_holding_the_caret_is_active(self):
        self.source.row = 5
        self.controller.toggle(self.window)
        self.assertIn("source-outline-active", self.html())

    def test_caret_moves_repaint_only_when_the_heading_changes(self):
        self.controller.toggle(self.window)
        painted = self.html()
        self.source.row = 2
        self.controller.sync_caret(self.source)
        self.assertEqual(self.html(), painted)
        self.source.row = 6
        self.controller.sync_caret(self.source)
        self.assertNotEqual(self.html(), painted)

    def test_the_caret_in_a_document_that_is_not_on_screen_repaints_nothing(self):
        self.controller.toggle(self.window)
        other = self.other()
        self.controller.focus_changed(self.focus(other))
        painted = self.html()
        self.source.row = 6

        self.controller.sync_caret(self.source)

        self.assertEqual(self.html(), painted)

    def test_edits_repaint_once_the_debounce_elapses(self):
        self.controller.toggle(self.window)
        self.source.text = "# One\n\n## Two\n\n### Three\n"
        self.controller.refresh_for_source(self.source)
        self.assertNotIn("Three", self.html())
        self.assertEqual(self.clock.pending[1][0], 50)
        self.clock.run_all()
        self.assertIn("Three", self.html())

    def test_a_later_edit_cancels_the_pending_repaint(self):
        self.controller.toggle(self.window)
        self.controller.refresh_for_source(self.source)
        self.controller.refresh_for_source(self.source)
        self.assertEqual(self.clock.cancelled, [1])
        self.assertEqual(len(self.clock.pending), 1)

    def test_a_renamed_source_renames_the_panel(self):
        self.controller.toggle(self.window)
        self.source.name_value = "other.md"
        self.controller.source_renamed(self.source)
        self.assertEqual(self.backend.titles[self.surface().id], "Contents: other.md")

    # -- navigation ------------------------------------------------------

    def test_clicking_an_entry_reveals_that_line_and_marks_it_active(self):
        self.controller.toggle(self.window)
        self.controller.navigate(self.window, self.stage().action_token, line=4)
        self.assertEqual(self.reveals, [(1, 4)])
        self.assertEqual(self.record().active, 1)

    def test_a_stale_token_or_line_navigates_nowhere(self):
        self.controller.toggle(self.window)
        self.controller.navigate(self.window, "wrong", line=4)
        self.controller.navigate(self.window, self.stage().action_token, line=99)
        self.assertEqual(self.reveals, [])

    def test_zoom_applies_only_while_the_panel_is_focused(self):
        self.controller.toggle(self.window)
        self.assertFalse(self.controller.adjust_zoom(self.window, 0.1))
        self.focus_panel()
        self.assertTrue(self.controller.adjust_zoom(self.window, 0.5))
        self.assertIn("font-size: 24px", self.html())
        self.assertTrue(self.controller.adjust_zoom(self.window, reset=True))
        self.assertIn("font-size: 16px", self.html())

    # -- lifecycle -------------------------------------------------------

    def test_closing_the_only_source_closes_its_panel(self):
        self.controller.toggle(self.window)
        surface = self.surface()
        self.controller.source_closed(self.source)
        self.assertEqual(self.backend.closed, [surface.id])
        self.assertIsNone(self.stage())

    def test_closing_the_source_on_screen_shows_another(self):
        other = self.other()
        self.controller.toggle(self.window)
        self.controller.focus_changed(self.focus(other))
        self.assertEqual(self.stage().showing, other.buffer_id())

        self.controller.source_closed(other)

        self.assertEqual(self.backend.closed, [])
        self.assertEqual(self.stage().showing, self.source.buffer_id())
        self.assertEqual(self.backend.titles[self.surface().id], "Contents: doc.md")

    def test_closing_the_surface_releases_the_group_without_closing_twice(self):
        self.controller.toggle(self.window)
        surface = self.surface()
        self.assertTrue(self.controller.surface_closed(surface.id))
        self.assertEqual(self.backend.closed, [])
        self.assertEqual([item[0] for item in self.layout.released], [1])
        self.assertFalse(self.controller.owns_surface(surface.id))

    def test_an_unknown_surface_is_not_claimed(self):
        self.assertFalse(self.controller.surface_closed(999))

    def test_reconcile_drops_a_panel_whose_view_vanished(self):
        self.controller.toggle(self.window)
        self.backend.alive.discard(self.surface().id)
        self.controller.reconcile(self.window)
        self.assertIsNone(self.stage())
        self.assertEqual([item[0] for item in self.layout.released], [1])

    def test_window_close_and_unload_close_every_panel(self):
        self.controller.toggle(self.window)
        surface = self.surface()
        self.controller.close_window(1)
        self.assertEqual(self.backend.closed, [surface.id])
        self.assertIsNone(self.stage())
        self.controller.close_all()
        self.assertEqual(self.backend.closed, [surface.id])

    def test_the_panel_is_put_on_the_source_colour_scheme(self):
        # minihtml resolves the phantom's colour variables against the surface,
        # so a panel left on the global scheme would ignore the one
        # MarkdownEditing gave the source.
        scheme = (("color_scheme", "MarkdownEditor.sublime-color-scheme"),)
        self.controller.theme_provider = lambda view: ThemeSnapshot(scheme=scheme)

        self.controller.toggle(self.window)

        self.assertEqual(self.backend.themes[self.surface().id].scheme, scheme)


class OneRegionTest(PanelControllerTest):
    """One surface, two halves, several documents."""

    def setUp(self):
        super().setUp()
        self.settings = RenderSettings(
            update_delay_ms=50,
            enable_toc=True,
            toc_minimum_length=1,
            toc_minimum_headings=1,
        )

    # -- opening by itself ------------------------------------------------

    def test_a_render_opens_the_panel_on_the_table_of_contents(self):
        self.render()
        self.assertIsNotNone(self.stage())
        self.assertIn("table-of-contents", self.html())
        self.assertNotIn('<div class="source-outline', self.html())

    def test_the_setting_off_opens_none_at_all(self):
        self.settings = RenderSettings(update_delay_ms=50, enable_toc=False)
        self.render()
        self.assertIsNone(self.stage())

    def test_a_document_below_the_threshold_opens_none(self):
        self.settings = RenderSettings(
            update_delay_ms=50, enable_toc=True, toc_minimum_headings=9
        )
        self.render()
        self.assertIsNone(self.stage())

    def test_a_panel_the_user_closed_is_not_reopened_by_the_next_render(self):
        self.render()
        self.assertTrue(self.controller.surface_closed(self.surface().id))
        self.render()
        self.assertIsNone(self.stage())

    def test_the_user_asking_again_clears_the_dismissal(self):
        self.render()
        self.controller.surface_closed(self.surface().id)
        self.focus(self.source)
        self.controller.toggle(self.window)
        self.assertIsNotNone(self.stage())

    def test_a_panel_nobody_asked_for_does_not_take_the_caret(self):
        # `window.new_file()` focuses the view it makes, so a panel opened by a
        # render would otherwise land the caret in it.
        preview = self.focus(self.preview_view())

        self.render()

        self.assertIs(self.window.active, preview)
        self.assertEqual(self.backend.focused, [])

    # -- the two halves ---------------------------------------------------

    def test_focusing_the_source_shows_the_outline_and_the_preview_the_contents(self):
        self.render()
        self.controller.focus_changed(self.focus(self.source))
        self.assertIn('<div class="source-outline', self.html())

        self.controller.focus_changed(self.focus(self.preview_view()))
        self.assertIn('<div class="table-of-contents', self.html())

    def test_a_render_while_the_source_has_the_focus_leaves_the_outline(self):
        self.controller.toggle(self.window)

        self.render(focused="source")

        self.assertIn('<div class="source-outline', self.html())

    def test_focusing_the_panel_itself_leaves_the_half_it_is_showing(self):
        self.render()
        painted = self.html()

        self.controller.focus_changed(self.focus_panel())

        self.assertEqual(self.html(), painted)

    def test_a_view_the_window_has_not_settled_on_moves_nothing(self):
        self.render()
        painted = self.html()
        self.focus(self.preview_view())

        self.controller.focus_changed(self.source)

        self.assertEqual(self.html(), painted)

    def test_with_no_preview_open_the_panel_stays_on_the_outline(self):
        self.controller.toggle(self.window)

        self.controller.focus_changed(self.focus(self.preview_view()))

        self.assertIn('<div class="source-outline', self.html())

    def test_a_hand_opened_panel_shows_contents_with_the_setting_off(self):
        # The setting governs whether a panel opens by itself. One the user
        # asked for would be strange if half of it were empty.
        self.settings = RenderSettings(update_delay_ms=50, enable_toc=False)
        self.controller.toggle(self.window)
        self.render(focused="source")

        self.controller.focus_changed(self.focus(self.preview_view()))

        self.assertIn('<div class="table-of-contents', self.html())

    # -- several documents ------------------------------------------------

    def test_one_surface_serves_every_document_in_the_window(self):
        self.render()
        surface = self.surface()
        other = self.other()

        self.controller.focus_changed(self.focus(other))

        self.assertIs(self.surface(), surface)
        self.assertEqual(self.stage().showing, other.buffer_id())
        self.assertEqual(len(self.layout.acquired), 1)

    def test_the_tab_is_named_for_the_document_on_it(self):
        self.render()
        other = self.other()

        self.controller.focus_changed(self.focus(other))

        self.assertEqual(self.backend.titles[self.surface().id], "Contents: other.md")

    def test_switching_documents_shows_that_document_headings(self):
        self.render()
        other = self.other()

        self.controller.focus_changed(self.focus(other))

        self.assertIn("Other", self.html())
        self.assertNotIn("One", self.html())

    def test_a_render_for_a_document_that_is_not_on_screen_paints_nothing(self):
        self.render()
        other = self.other()
        self.controller.focus_changed(self.focus(other))
        painted = self.html()

        self.render(count=4)

        self.assertEqual(self.html(), painted)
        # But its headings are kept, ready for when it comes back.
        self.assertEqual(len(self.record().document), 4)

    def test_a_document_with_no_render_of_its_own_shows_only_the_outline(self):
        self.render()
        other = self.other()
        self.controller.focus_changed(self.focus(other))

        self.controller.focus_changed(
            self.focus(self.preview_view(91, buffer_id=other.buffer_id()))
        )

        self.assertIn('<div class="source-outline', self.html())

    # -- width ------------------------------------------------------------

    def test_each_half_is_measured_with_its_own_typeface(self):
        rendered = self.render()
        self.assertAlmostEqual(
            self.layout.fitted[-1][2], toc_width_px(rendered.headings, 16)
        )

        self.controller.focus_changed(self.focus(self.source))

        self.assertAlmostEqual(
            self.layout.fitted[-1][2], outline_width_px(self.record().headings, 16)
        )

    # -- navigation --------------------------------------------------------

    def test_clicking_a_contents_entry_scrolls_the_preview(self):
        self.render()

        self.controller.navigate(self.window, self.stage().action_token, slug="h1")

        self.assertEqual(self.scrolled, [(1, self.source.buffer_id(), "h1")])
        self.assertEqual(self.record().active_slug, "h1")
        self.assertIn("table-of-contents-active", self.html())

    def test_a_slug_that_is_not_in_the_document_scrolls_nowhere(self):
        self.render()

        self.controller.navigate(self.window, self.stage().action_token, slug="missing")

        self.assertEqual(self.scrolled, [])

    def test_clicking_an_outline_entry_also_scrolls_the_preview(self):
        """The point of the change: a preview is read by scrolling, which
        leaves the focus on the source, so the outline is the half in front --
        and it used to move only the caret."""
        self.render(focused="source")

        self.controller.navigate(self.window, self.stage().action_token, line=4)

        self.assertEqual(self.reveals, [(1, 4)])
        self.assertEqual(self.scrolled, [(1, self.source.buffer_id(), "h1")])
        self.assertEqual(self.record().active_slug, "h1")
        self.assertEqual(self.record().active, 1)

    def test_clicking_a_contents_entry_also_moves_the_caret(self):
        self.render()

        self.controller.navigate(self.window, self.stage().action_token, slug="h1")

        self.assertEqual(self.reveals, [(1, 4)])
        self.assertEqual(self.record().active, 1)

    def test_an_entry_the_alignment_could_not_pair_moves_only_its_own_pane(self):
        # A heading in a raw `<h2>` block or a block quote is in the render and
        # not in the scan; pairing by position would send the reader to the
        # wrong section, so it is not paired at all.
        self.render()
        record = self.record()
        record.document = record.document + (
            Heading(2, "Raw", "raw", len(record.document), 0.9),
        )
        record.realign()

        self.controller.navigate(self.window, self.stage().action_token, slug="raw")

        self.assertEqual(self.scrolled, [(1, self.source.buffer_id(), "raw")])
        self.assertEqual(self.reveals, [])

    def test_a_preview_that_did_not_move_does_not_claim_the_highlight(self):
        self.render()
        self.scrollable = False

        self.controller.navigate(self.window, self.stage().action_token, slug="h1")

        self.assertIsNone(self.record().active_slug)

    def test_the_caret_carries_the_other_half_highlight_with_it(self):
        # Otherwise switching to the table of contents shows the heading you
        # were at three sections ago.
        self.render(focused="source")
        self.source.row = 6

        self.controller.sync_caret(self.source)

        self.assertEqual(self.record().active_slug, "h1")

    def test_a_link_clicked_in_the_preview_moves_the_caret_too(self):
        self.render()

        self.controller.heading_shown(1, self.source.buffer_id(), "h1")

        self.assertEqual(self.reveals, [(1, 4)])
        self.assertEqual(self.record().active, 1)

    def test_a_link_clicked_in_the_preview_highlights_that_heading(self):
        self.render()

        self.controller.heading_shown(1, self.source.buffer_id(), "h1")

        self.assertIn("table-of-contents-active", self.html())

    # -- lifecycle ---------------------------------------------------------

    def test_closing_the_preview_drops_the_contents_half(self):
        self.render()
        self.assertIn('<div class="table-of-contents', self.html())

        self.controller.document_closed(1, self.source.buffer_id())

        self.assertIsNotNone(self.stage())
        self.assertIn('<div class="source-outline', self.html())

    def test_turning_the_setting_off_closes_a_panel_the_render_opened(self):
        self.render()
        surface = self.surface()
        self.settings = RenderSettings(update_delay_ms=50, enable_toc=False)

        self.controller.settings_changed()

        self.assertEqual(self.backend.closed, [surface.id])

    def test_turning_the_setting_off_keeps_a_panel_the_user_opened(self):
        self.controller.toggle(self.window)
        self.settings = RenderSettings(update_delay_ms=50, enable_toc=False)

        self.controller.settings_changed()

        self.assertEqual(self.backend.closed, [])
