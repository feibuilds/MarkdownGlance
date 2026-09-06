import os
import os.path
import unittest
from unittest import mock

from MarkdownGlance.preview.application.ports import GroupRole, SurfaceHandle
from MarkdownGlance.preview.application.session_manager import SessionManager
from MarkdownGlance.preview.application.usecases import UseCases
from MarkdownGlance.preview.domain.contracts import (
    AssetKey,
    DiagnosticStage,
    AssetKind,
    Heading,
    PreviewDocument,
    PreviewMode,
    RenderSettings,
    ThemeSnapshot,
)
from MarkdownGlance.preview.renderer.measure import toc_width_px

# Paths that are absolute on every host, so the suite runs from any of them.
BASE = os.path.realpath(os.path.abspath(os.sep + "mdglance"))
OUTSIDE = os.path.abspath(os.sep + "mdglance-outside")
HOME = os.path.abspath(os.sep + "mdglance-home")


class Sheet:
    def __init__(self, identifier, view):
        self._id = identifier
        self._view = view

    def id(self):
        return self._id

    def view(self):
        return self._view


class SurfaceView:
    """A plugin-owned preview/TOC view, as seen through its sheet."""

    def __init__(self, identifier):
        self._id = identifier
        self._window = None

    def id(self):
        return self._id

    def buffer_id(self):
        return -self._id

    def window(self):
        return self._window

    def match_selector(self, point, selector):
        return False


class View:
    def __init__(self, identifier, name="source.md", filename=None, markdown=True):
        self._id = identifier
        self._name = name
        self._filename = filename
        self.markdown = markdown
        self._sheet = Sheet(identifier + 100, self)
        self._window = None

    def id(self):
        # A view id is not a buffer id and not a sheet id: three id spaces.
        return self._id + 200

    def buffer_id(self):
        return self._id

    def sheet(self):
        return self._sheet

    def window(self):
        return self._window

    def name(self):
        return self._name

    def file_name(self):
        return self._filename

    def match_selector(self, point, selector):
        return self.markdown


class Window:
    def __init__(self, identifier, source, folders=()):
        self._id = identifier
        self.source = source
        source._window = self
        self._active = source.sheet()
        self.opened = []
        self.focused = []
        self._folders = list(folders)

    def id(self):
        return self._id

    def active_sheet(self):
        return self._active

    def active_view(self):
        return self._active.view()

    def get_view_index(self, view):
        return (0, 0)

    def views(self):
        return [self.source]

    def focus_view(self, view):
        self._active = view.sheet()
        self.focused.append(view)

    def open_file(self, path):
        self.opened.append(path)

    def folders(self):
        return list(self._folders)


class Backend:
    def __init__(self, windows):
        self.windows = windows
        self.next_id = 1000
        self.handles = {}
        self.groups = {}
        self.roles = {}
        self.closed = []
        self.focused = []
        self.navigations = []
        self.updates = []
        self.revealed = []
        self.scrolled_to = {}
        self.titles = []
        self.themes = {}

    def create(self, window, group, title, session_id):
        self.next_id += 1
        handle = SurfaceHandle("fake", self.next_id, window.id())
        self.handles[handle.id] = (handle, session_id)
        self.groups[handle.id] = group
        return handle

    def set_role(self, handle, role):
        self.roles[handle.id] = role

    def focus(self, handle):
        self.focused.append(handle.id)
        window = self.windows[handle.window_id]
        window._active = self.sheet_for(handle)

    def sheet_for(self, handle):
        # Sublime numbers sheets and views separately; never reuse the view id.
        return Sheet(handle.id + 5000, SurfaceView(handle.id))

    def owner_of(self, sheet_or_view):
        if sheet_or_view is None:
            return None
        view = sheet_or_view.view() if hasattr(sheet_or_view, "view") else sheet_or_view
        item = self.handles.get(view.id()) if view is not None else None
        return item[1] if item else None

    def role_of(self, sheet_or_view):
        if sheet_or_view is None:
            return None
        view = sheet_or_view.view() if hasattr(sheet_or_view, "view") else sheet_or_view
        return self.roles.get(view.id()) if view is not None else None

    def move(self, handle, group):
        self.groups[handle.id] = group

    def scroll_ratio(self, handle):
        return self.scrolled_to.get(handle.id, 0.0)

    def restore_scroll(self, handle, ratio):
        self.scrolled_to[handle.id] = ratio

    def reveal(self, handle):
        self.revealed.append(handle.id)

    def scroll_ratio(self, handle):
        return self.scrolled_to.get(handle.id, 0.0)

    def restore_scroll(self, handle, ratio):
        self.scrolled_to[handle.id] = ratio

    def update(self, handle, html):
        self.updates.append((handle.id, html))

    def apply_theme(self, handle, theme):
        self.themes[handle.id] = theme

    def set_heading_ratios(self, handle, ratios):
        pass

    def set_title(self, handle, title):
        self.titles.append((handle.id, title))

    def navigate(self, handle, slug):
        self.navigations.append((handle.id, slug))
        return True

    def is_alive(self, handle):
        return handle.id in self.handles

    def close(self, handle):
        self.closed.append(handle.id)
        self.handles.pop(handle.id, None)

    def group_of(self, handle):
        return self.groups.get(handle.id)

    def live_handles(self, window):
        return [
            item[0]
            for item in self.handles.values()
            if item[0].window_id == window.id()
        ]


class Layout:
    def __init__(self):
        self.acquired = []
        self.fitted = []
        self.releases = []
        # Which groups this owner is holding for whom, the way the real one
        # tracks holders: the callers no longer keep group numbers of their own.
        self.held = {}

    def acquire(self, window, anchor, role, session_id, width_px=0.0):
        self.acquired.append((anchor, role, session_id, width_px))
        self.held.setdefault(session_id, set()).add(anchor + 1)
        return anchor + 1

    def acquire_panel(self, window, anchor_group, session_id, width_px=0.0):
        self.acquired.append((anchor_group, GroupRole.PANEL, session_id, width_px))
        self.held.setdefault(session_id, set()).add(anchor_group + 1)
        return anchor_group + 1

    def release_all(self, window, session_id, restore=True):
        for group in sorted(self.held.pop(session_id, ()), reverse=True):
            self.release(window, group, session_id, restore=restore)

    def fit(self, window, group, role, width_px):
        self.fitted.append((group, role, width_px))

    def is_owned(self, window, group):
        return True

    def release(self, window, group, session_id, restore=True):
        self.releases.append((window.id(), group, restore))


class Scheduler:
    def __init__(self):
        self.requests = []

    def request_render(self, session_id, reason):
        self.requests.append((session_id, reason))


class Resolver:
    def forget_session(self, session_id):
        pass


class Panel:
    """The panel controller, as the use cases see it: a place to hand a
    rendered document and a close. It owns its own surface and lifetime."""

    def __init__(self):
        self.rendered = []
        self.closed = []
        self.shown = []

    def document_rendered(self, window_id, buffer_id, document):
        self.rendered.append((window_id, buffer_id, document))

    def document_closed(self, window_id, buffer_id):
        self.closed.append((window_id, buffer_id))

    def heading_shown(self, window_id, buffer_id, slug):
        self.shown.append((window_id, buffer_id, slug))


class Fixture(unittest.TestCase):
    """One window, one Markdown source, fakes for everything Sublime owns."""

    def setUp(self):
        self.source = View(10, filename=os.path.join(BASE, "source.md"))
        self.window = Window(1, self.source)
        self.windows = {1: self.window}
        self.backend = Backend(self.windows)
        self.layout = Layout()
        self.scheduler = Scheduler()
        self.panel = Panel()
        self.manager = SessionManager(
            self.backend,
            self.layout,
            Resolver(),
            lambda identifier: self.windows.get(identifier),
            # What the container wires: every path that ends a preview tells
            # the panel that its table-of-contents half has nothing behind it.
            lambda session: self.panel.document_closed(
                session.window_id, session.source_buffer_id
            ),
            on_show=lambda stage, session: self.usecases.show(stage, session),
        )
        self.usecases = UseCases(
            self.manager,
            self.scheduler,
            self.backend,
            self.layout,
            lambda session, generation: None,
            RenderSettings,
            lambda view: ThemeSnapshot(),
            lambda view, session_id: None,
            "",
            self.panel,
        )

    def stage(self, window_id=1):
        return self.manager.stage(window_id)

    def surface(self, window_id=1):
        stage = self.stage(window_id)
        return stage.surface if stage is not None else None

    def focus_surface(self, window=None, window_id=1):
        """Put the window's focus on the one preview surface."""
        window = window or self.windows[window_id]
        window._active = self.backend.sheet_for(self.surface(window_id))
        return window._active


class UseCasesTest(Fixture):
    def test_open_repeat_open_and_switch_modes_keep_one_session(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        self.assertEqual(self.stage().mode, PreviewMode.SIDE_BY_SIDE)
        self.assertEqual(len(self.manager.sessions_in(1)), 1)
        self.window._active = self.source.sheet()
        self.usecases.open_side_by_side(self.window)
        self.assertEqual(len(self.manager.sessions_in(1)), 1)
        self.focus_surface()
        self.usecases.toggle_full_screen(self.window)
        self.assertEqual(self.stage().mode, PreviewMode.FULL_SCREEN)
        self.assertIs(self.manager.get(session.id), session)
        self.assertNotIn(self.source.sheet().id(), self.backend.closed)

    def test_fullscreen_preview_toggle_closes_only_owned_surface(self):
        self.usecases.toggle_full_screen(self.window)
        session = self.manager.for_source(1, 10)
        preview_id = self.surface().id
        self.focus_surface()
        self.usecases.toggle_full_screen(self.window)
        self.assertIsNone(self.manager.get(session.id))
        self.assertIsNone(self.stage())
        self.assertIn(preview_id, self.backend.closed)
        self.assertNotIn(self.source.sheet().id(), self.backend.closed)

    def test_saved_unsaved_and_zoom_paths(self):
        unsaved = View(20, name="Untitled", filename=None)
        second = Window(2, unsaved, (os.path.join(BASE, "project"),))
        self.windows[2] = second
        self.usecases.open_side_by_side(second)
        session = self.manager.for_source(2, 20)
        self.assertEqual(session.base_path, os.path.join(BASE, "project"))
        self.usecases.source_modified(unsaved)
        unsaved._filename = os.path.join(BASE, "saved.md")
        self.usecases.source_saved(unsaved)
        self.assertEqual(session.base_path, BASE)
        reasons = [
            reason for sid, reason in self.scheduler.requests if sid == session.id
        ]
        self.assertEqual(reasons, ["open", "edit", "save"])
        self.focus_surface(second, 2)
        self.usecases.adjust_zoom(second, 9.0)
        self.assertEqual(self.stage(2).zoom, 3.0)
        self.assertEqual(reasons, ["open", "edit", "save"])

    def test_preview_commands_survive_a_sheet_id_that_is_not_the_view_id(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        sheet = self.backend.sheet_for(self.surface())
        self.assertNotEqual(sheet.id(), self.surface().id)
        self.window._active = sheet

        self.usecases.adjust_zoom(self.window, 0.5)
        self.assertEqual(self.stage().zoom, 1.5)
        self.usecases.adjust_zoom(self.window, reset=True)
        self.assertEqual(self.stage().zoom, 1.0)

        surface_id = self.surface().id
        self.usecases.toggle_full_screen(self.window)
        self.assertEqual(self.stage().mode, PreviewMode.FULL_SCREEN)
        self.focus_surface()
        self.usecases.toggle_full_screen(self.window)
        self.assertIsNone(self.manager.get(session.id))
        self.assertIn(surface_id, self.backend.closed)

    def test_absolute_editor_link_is_rejected(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        session.last_document = PreviewDocument(
            1, "", (), (), (), (OUTSIDE, "~/secret")
        )
        self.focus_surface()
        with mock.patch.dict(os.environ, {"HOME": HOME, "USERPROFILE": HOME}):
            for index in (0, 1):
                self.usecases.open_relative(self.window, session.action_token, index)
        self.assertEqual(self.window.opened, [])

    def test_the_panel_scrolls_the_document_on_the_stage(self):
        self.usecases.open_side_by_side(self.window)
        first = self.manager.for_source(1, 10)
        first.last_document = PreviewDocument(
            1, "", (Heading(2, "First", "first", 0, 0.5),), (), (), ()
        )
        # The focus is somewhere else entirely; the panel names the document.
        self.window._active = Sheet(9999, SurfaceView(9999))

        self.assertTrue(self.usecases.scroll_preview(1, 10, "first"))

        self.assertEqual(self.backend.navigations, [(self.surface().id, "first")])

    def test_a_document_that_is_not_on_the_stage_scrolls_nowhere(self):
        # One surface: a document that is not on it has nothing to scroll, and
        # scrolling the surface would move whatever is.
        self.usecases.open_side_by_side(self.window)
        second_source = View(20, filename=os.path.join(BASE, "second.md"))
        second_source._window = self.window
        self.usecases.open_side_by_side(self.window, second_source)
        first = self.manager.for_source(1, 10)
        first.last_document = PreviewDocument(
            1, "", (Heading(2, "First", "first", 0, 0.5),), (), (), ()
        )
        self.backend.navigations = []

        self.assertFalse(self.usecases.scroll_preview(1, 10, "first"))

        self.assertEqual(self.backend.navigations, [])

    def test_a_slug_outside_the_document_scrolls_nowhere(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        session.last_document = PreviewDocument(
            1, "", (Heading(2, "First", "first", 0, 0.5),), (), (), ()
        )

        self.assertFalse(self.usecases.scroll_preview(1, 10, "missing"))

        self.assertEqual(self.backend.navigations, [])

    def test_a_link_clicked_in_the_preview_body_tells_the_panel(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        session.last_document = PreviewDocument(
            1, "", (Heading(2, "First", "first", 0, 0.5),), (), (), ()
        )

        self.usecases.navigate_for_surface(self.surface().id, "first")

        self.assertEqual(self.panel.shown, [(1, 10, "first")])


class Snapshot:
    def __init__(self, markdown):
        self.markdown = markdown


class RenderedSessionTest(Fixture):
    """A session that has rendered once, for the tests that need a document.

    What the table of contents does with that document is the panel
    controller's, and is tested in `test_panel.py`; from here a render is
    something handed over.
    """

    LONG = "#" * 4000

    def setUp(self):
        super().setUp()
        self.usecases.source_snapshot = lambda session, generation: Snapshot(self.LONG)
        self.settings = RenderSettings(enable_toc=True)
        self.usecases.settings_provider = lambda: self.settings

    def document(self):
        return PreviewDocument(
            1,
            "<p>body</p>",
            tuple(
                Heading(2, "H{}".format(index), "h{}".format(index), index, 0.1 * index)
                for index in range(4)
            ),
            (),
            (),
            (),
        )

    def open(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        session.settings = self.settings
        session.last_document = self.document()
        self.usecases.present(session, session.last_document)
        return session

    def test_a_render_hands_the_document_to_the_panel(self):
        session = self.open()
        self.assertEqual(
            self.panel.rendered, [(1, 10, session.last_document)]
        )

    def test_closing_the_session_tells_the_panel_its_document_is_gone(self):
        session = self.open()
        self.usecases.source_closed(self.source)
        self.assertEqual(self.panel.closed, [(1, 10)])
        self.assertIsNone(self.manager.get(session.id))


class RepaintCostTest(RenderedSessionTest):
    """A repaint must not do work Sublime charges a full minihtml layout for."""

    def test_a_repaint_reveals_nothing(self):
        session = self.open()
        # `reveal` focuses the group, the view, then the previous group back,
        # and each focus change makes Sublime fire `on_activated`, which reads
        # the theme and repaints -- landing here again. A repaint must not
        # move a tab; only a focus change does, through `reveal_preview`.
        self.assertEqual(self.backend.revealed, [])

        self.usecases.present(session, session.last_document)
        self.usecases.represent(session)

        self.assertEqual(self.backend.revealed, [])

    def test_an_unchanged_theme_does_not_repaint(self):
        session = self.open()
        before = len(self.backend.updates)

        self.usecases.theme_changed(self.source)

        self.assertEqual(len(self.backend.updates), before)

    def test_a_changed_theme_still_repaints(self):
        session = self.open()
        before = len(self.backend.updates)
        self.usecases.theme_provider = lambda view: ThemeSnapshot(background="#101010")

        self.usecases.theme_changed(self.source)

        self.assertGreater(len(self.backend.updates), before)
        self.assertEqual(session.theme.background, "#101010")


class StageTest(RenderedSessionTest):
    """One surface per window, showing the focused document."""

    def source_view(self, identifier=20, name="second.md"):
        view = View(identifier, name=name, filename=os.path.join(BASE, name))
        view._window = self.window
        self.window._active = view.sheet()
        return view

    def test_two_documents_share_one_surface(self):
        first = self.open()
        surface = self.surface()
        second_source = self.source_view()

        self.usecases.open_side_by_side(self.window, second_source)

        second = self.manager.for_source(1, 20)
        self.assertIs(self.surface(), surface)
        self.assertEqual(len(self.manager.sessions_in(1)), 2)
        self.assertTrue(self.stage().is_showing(second.id))
        self.assertFalse(self.stage().is_showing(first.id))

    def test_the_surface_is_titled_for_the_document_on_it(self):
        self.open()
        self.usecases.open_side_by_side(self.window, self.source_view())
        self.assertEqual(self.backend.titles[-1][1], "Preview: second.md")

    def test_only_one_group_is_ever_acquired(self):
        self.open()
        acquired = len(self.layout.acquired)

        self.usecases.open_side_by_side(self.window, self.source_view())

        self.assertEqual(len(self.layout.acquired), acquired)

    def test_a_hidden_document_does_not_paint_over_the_one_on_screen(self):
        """Find in Files, a reload from disk, Auto Save: all render a document
        nobody is looking at, and the result must not land on the surface."""
        first = self.open()
        self.usecases.open_side_by_side(self.window, self.source_view())
        painted = len(self.backend.updates)

        self.usecases.present(first, first.last_document)

        self.assertEqual(len(self.backend.updates), painted)
        self.assertEqual(self.panel.rendered[-1][1], 10)

    def test_a_hidden_document_still_reaches_the_panel(self):
        first = self.open()
        self.usecases.open_side_by_side(self.window, self.source_view())
        self.panel.rendered = []

        self.usecases.present(first, first.last_document)

        self.assertEqual(self.panel.rendered, [(1, 10, first.last_document)])

    def test_an_error_for_a_hidden_document_is_not_painted(self):
        first = self.open()
        self.usecases.open_side_by_side(self.window, self.source_view())
        painted = len(self.backend.updates)

        self.usecases.present_error(first, DiagnosticStage.PARSE, "boom")

        self.assertEqual(len(self.backend.updates), painted)

    def test_where_each_document_was_scrolled_to_comes_back_with_it(self):
        first = self.open()
        surface = self.surface()
        self.backend.scrolled_to[surface.id] = 0.4
        second_source = self.source_view()

        self.usecases.open_side_by_side(self.window, second_source)
        self.assertEqual(self.stage().scroll[first.id], 0.4)
        # The second document starts at the top, not at the first's position.
        self.assertEqual(self.backend.scrolled_to[surface.id], 0.0)

        self.usecases.open_side_by_side(self.window, self.source)
        self.assertEqual(self.backend.scrolled_to[surface.id], 0.4)

    def test_zoom_belongs_to_the_pane_not_the_document(self):
        self.open()
        self.focus_surface()
        self.usecases.adjust_zoom(self.window, 0.5)

        self.usecases.open_side_by_side(self.window, self.source_view())

        self.assertEqual(self.stage().zoom, 1.5)

    def test_closing_the_document_on_screen_shows_another(self):
        first = self.open()
        second_source = self.source_view()
        self.usecases.open_side_by_side(self.window, second_source)
        second = self.manager.for_source(1, 20)

        self.usecases.source_closed(second_source)

        self.assertIsNone(self.manager.get(second.id))
        self.assertTrue(self.stage().is_showing(first.id))
        self.assertNotIn(self.surface().id, self.backend.closed)

    def test_closing_the_last_document_closes_the_preview(self):
        self.open()
        surface = self.surface()

        self.usecases.source_closed(self.source)

        self.assertIsNone(self.stage())
        self.assertIn(surface.id, self.backend.closed)

    def test_closing_the_preview_tab_ends_every_document_in_the_window(self):
        self.open()
        self.usecases.open_side_by_side(self.window, self.source_view())
        surface = self.surface()
        self.backend.close(surface)

        self.manager.surface_closed(surface.id)

        self.assertEqual(self.manager.sessions_in(1), [])
        self.assertIsNone(self.stage())


class FollowFocusTest(RenderedSessionTest):
    """The preview shows the focused document, whatever it is."""

    def focus(self, view):
        self.window._active = view.sheet() if hasattr(view, "sheet") else Sheet(0, view)
        return view

    def other(self, identifier=30, markdown=True):
        view = View(
            identifier,
            filename=os.path.join(BASE, "other.md"),
            markdown=markdown,
        )
        view._window = self.window
        return view

    def test_focusing_a_document_with_no_preview_renders_it_onto_the_stage(self):
        self.open()
        other = self.other()

        self.usecases.follow_focus(self.focus(other))

        session = self.manager.for_source(1, 30)
        self.assertIsNotNone(session)
        self.assertTrue(self.stage().is_showing(session.id))
        self.assertEqual(self.scheduler.requests[-1], (session.id, "open"))

    def test_focusing_a_document_that_has_one_shows_it_without_rendering(self):
        first = self.open()
        other = self.other()
        self.usecases.follow_focus(self.focus(other))
        requests = len(self.scheduler.requests)

        self.usecases.follow_focus(self.focus(self.source))

        self.assertTrue(self.stage().is_showing(first.id))
        self.assertEqual(len(self.scheduler.requests), requests)

    def test_following_never_takes_the_focus(self):
        self.open()
        other = self.other()
        self.focus(other)
        self.backend.focused = []

        self.usecases.follow_focus(other)

        self.assertEqual(self.backend.focused, [])

    def test_a_window_with_no_preview_opens_nothing(self):
        other = self.other()

        self.usecases.follow_focus(self.focus(other))

        self.assertEqual(self.manager.sessions_in(1), [])

    def test_full_screen_follows_too(self):
        # The preview stands in for the source there, sharing its tab strip.
        # Leaving it on another file is the inconsistency, not the fix.
        self.usecases.toggle_full_screen(self.window)
        other = self.other()

        self.usecases.follow_focus(self.focus(other))

        session = self.manager.for_source(1, 30)
        self.assertIsNotNone(session)
        self.assertTrue(self.stage().is_showing(session.id))

    def test_a_view_that_is_not_markdown_shows_nothing_new(self):
        first = self.open()

        self.usecases.follow_focus(self.focus(self.other(31, markdown=False)))

        self.assertIsNone(self.manager.for_source(1, 31))
        self.assertTrue(self.stage().is_showing(first.id))

    def test_a_view_the_window_has_not_settled_on_shows_nothing(self):
        first = self.open()
        other = self.other()
        self.focus(self.source)

        self.usecases.follow_focus(other)

        self.assertIsNone(self.manager.for_source(1, 30))
        self.assertTrue(self.stage().is_showing(first.id))


class DiagramThemeTest(RenderedSessionTest):
    """A Mermaid diagram is an image the server baked for one background, so a
    change of colour scheme has to fetch it again. Everything else in the
    document is recoloured by a repaint alone.
    """

    DIAGRAM = AssetKey(AssetKind.MERMAID, "https://mermaid.test/img/abc?bgColor=ffffff")

    def with_diagram(self):
        session = self.open()
        document = session.last_document
        session.last_document = PreviewDocument(
            document.generation,
            document.body_html,
            document.headings,
            (self.DIAGRAM,),
            (),
            (),
        )
        return session

    def renders(self, session):
        return [reason for sid, reason in self.scheduler.requests if sid == session.id]

    def test_a_new_background_fetches_the_diagram_again(self):
        session = self.with_diagram()
        before = self.renders(session)
        self.usecases.theme_provider = lambda view: ThemeSnapshot(
            background="#101010", is_dark=True
        )

        self.usecases.theme_changed(self.source)

        self.assertEqual(self.renders(session), before + ["theme"])

    def test_a_theme_the_diagram_cannot_see_only_repaints(self):
        session = self.with_diagram()
        before = self.renders(session)
        updates = len(self.backend.updates)
        # Same background and same is_dark: the diagram URL is unchanged, and
        # only the document's own palette has moved.
        self.usecases.theme_provider = lambda view: ThemeSnapshot(accent="#ff0000")

        self.usecases.theme_changed(self.source)

        self.assertEqual(self.renders(session), before)
        self.assertGreater(len(self.backend.updates), updates)

    def test_a_document_without_a_diagram_only_repaints(self):
        session = self.open()
        before = self.renders(session)
        self.usecases.theme_provider = lambda view: ThemeSnapshot(
            background="#101010", is_dark=True
        )

        self.usecases.theme_changed(self.source)

        self.assertEqual(self.renders(session), before)


class FormulaThemeTest(DiagramThemeTest):
    """A formula is baked in one foreground colour on a transparent background,
    so it is the foreground, not the background, that makes it stale.
    """

    DIAGRAM = AssetKey(AssetKind.MATH, "https://math.test/png.image?abc")

    def test_a_new_background_fetches_the_diagram_again(self):
        # Overrides the diagram case: the formula cannot see the background.
        session = self.with_diagram()
        before = self.renders(session)
        self.usecases.theme_provider = lambda view: ThemeSnapshot(
            background="#101010", is_dark=True
        )

        self.usecases.theme_changed(self.source)

        self.assertEqual(self.renders(session), before)

    def test_a_new_foreground_fetches_the_formula_again(self):
        session = self.with_diagram()
        before = self.renders(session)
        self.usecases.theme_provider = lambda view: ThemeSnapshot(foreground="#cdd6f4")

        self.usecases.theme_changed(self.source)

        self.assertEqual(self.renders(session), before + ["theme"])


class SurfaceColourSchemeTest(RenderedSessionTest):
    """A Markdown file can carry a colour scheme of its own -- MarkdownEditing
    writes one into `Markdown.sublime-settings`, and it beats the global one.
    Every surface has to be put on that scheme: minihtml resolves a phantom's
    colour variables against the view the phantom sits in, so a surface left on
    the defaults renders the document in the wrong palette.
    """

    SCHEME = (("color_scheme", "MarkdownEditor.sublime-color-scheme"),)

    def setUp(self):
        super().setUp()
        self.usecases.theme_provider = lambda view: ThemeSnapshot(scheme=self.SCHEME)

    def test_the_source_scheme_reaches_the_preview(self):
        session = self.open()

        self.assertEqual(
            self.backend.themes[self.surface().id].scheme, self.SCHEME
        )

    def test_a_scheme_chosen_while_the_preview_is_open_still_reaches_it(self):
        session = self.open()
        moved = (("color_scheme", "MarkdownEditor-Yellow.sublime-color-scheme"),)
        self.usecases.theme_provider = lambda view: ThemeSnapshot(scheme=moved)

        self.usecases.theme_changed(self.source)

        self.assertEqual(self.backend.themes[self.surface().id].scheme, moved)


if __name__ == "__main__":
    unittest.main()
