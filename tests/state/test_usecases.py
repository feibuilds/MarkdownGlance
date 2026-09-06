import os
import os.path
import unittest
from unittest import mock

from MarkdownGlance.preview.application.ports import GroupRole, SurfaceHandle
from MarkdownGlance.preview.application.session_manager import SessionManager
from MarkdownGlance.preview.application.usecases import UseCases
from MarkdownGlance.preview.domain.contracts import (
    AssetKey,
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

    def id(self):
        return self._id

    def buffer_id(self):
        return -self._id

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

    def reveal(self, handle):
        self.revealed.append(handle.id)

    def update(self, handle, html):
        self.updates.append((handle.id, html))

    def apply_theme(self, handle, theme):
        self.themes[handle.id] = theme

    def set_heading_ratios(self, handle, ratios):
        pass

    def set_title(self, handle, title):
        pass

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

    def acquire(self, window, anchor, role, session_id, width_px=0.0):
        self.acquired.append((anchor, role, session_id, width_px))
        return anchor + 1

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


class Fixture(unittest.TestCase):
    """One window, one Markdown source, fakes for everything Sublime owns."""

    def setUp(self):
        self.source = View(10, filename=os.path.join(BASE, "source.md"))
        self.window = Window(1, self.source)
        self.windows = {1: self.window}
        self.backend = Backend(self.windows)
        self.layout = Layout()
        self.scheduler = Scheduler()
        self.manager = SessionManager(
            self.backend,
            self.layout,
            Resolver(),
            lambda identifier: self.windows.get(identifier),
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
        )


class UseCasesTest(Fixture):
    def test_open_repeat_open_and_switch_modes_keep_one_session(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        self.assertEqual(session.mode, PreviewMode.SIDE_BY_SIDE)
        self.assertEqual(len(self.manager.sessions_in(1)), 1)
        self.window._active = self.source.sheet()
        self.usecases.open_side_by_side(self.window)
        self.assertEqual(len(self.manager.sessions_in(1)), 1)
        self.window._active = self.backend.sheet_for(session.preview_surface)
        self.usecases.toggle_full_screen(self.window)
        self.assertEqual(session.mode, PreviewMode.FULL_SCREEN)
        self.assertNotIn(self.source.sheet().id(), self.backend.closed)

    def test_fullscreen_preview_toggle_closes_only_owned_surface(self):
        self.usecases.toggle_full_screen(self.window)
        session = self.manager.for_source(1, 10)
        preview_id = session.preview_surface.id
        self.usecases.toggle_full_screen(self.window)
        self.assertIsNone(self.manager.get(session.id))
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
        second._active = self.backend.sheet_for(session.preview_surface)
        self.usecases.adjust_zoom(second, 9.0)
        self.assertEqual(session.zoom, 3.0)
        self.assertEqual(reasons, ["open", "edit", "save"])

    def test_preview_commands_survive_a_sheet_id_that_is_not_the_view_id(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        sheet = self.backend.sheet_for(session.preview_surface)
        self.assertNotEqual(sheet.id(), session.preview_surface.id)
        self.window._active = sheet

        self.usecases.adjust_zoom(self.window, 0.5)
        self.assertEqual(session.zoom, 1.5)
        self.usecases.adjust_zoom(self.window, reset=True)
        self.assertEqual(session.zoom, 1.0)

        self.usecases.toggle_full_screen(self.window)
        self.assertEqual(session.mode, PreviewMode.FULL_SCREEN)
        self.window._active = self.backend.sheet_for(session.preview_surface)
        self.usecases.toggle_full_screen(self.window)
        self.assertIsNone(self.manager.get(session.id))
        self.assertIn(session.preview_surface.id, self.backend.closed)

    def test_absolute_editor_link_is_rejected(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        session.last_document = PreviewDocument(
            1, "", (), (), (), (OUTSIDE, "~/secret")
        )
        self.window._active = self.backend.sheet_for(session.preview_surface)
        with mock.patch.dict(os.environ, {"HOME": HOME, "USERPROFILE": HOME}):
            for index in (0, 1):
                self.usecases.open_relative(self.window, session.action_token, index)
        self.assertEqual(self.window.opened, [])

    def test_toc_navigation_uses_action_token_not_active_sheet(self):
        self.usecases.open_side_by_side(self.window)
        first = self.manager.for_source(1, 10)
        first.last_document = PreviewDocument(
            1,
            "",
            (Heading(2, "First", "first", 0, 0.5),),
            (),
            (),
            (),
        )

        second_source = View(20, filename=os.path.join(BASE, "second.md"))
        second_source._window = self.window
        self.usecases.open_side_by_side(self.window, second_source)
        second = self.manager.for_source(1, 20)
        second.last_document = PreviewDocument(
            1,
            "",
            (Heading(2, "Second", "second", 0, 0.5),),
            (),
            (),
            (),
        )
        self.window._active = Sheet(9999, SurfaceView(9999))

        self.usecases.navigate(self.window, first.action_token, "first")

        self.assertEqual(
            self.backend.navigations, [(first.preview_surface.id, "first")]
        )

    def test_toc_navigation_rejects_slug_outside_token_session(self):
        self.usecases.open_side_by_side(self.window)
        session = self.manager.for_source(1, 10)
        session.last_document = PreviewDocument(
            1,
            "",
            (Heading(2, "First", "first", 0, 0.5),),
            (),
            (),
            (),
        )

        self.usecases.navigate(self.window, session.action_token, "missing")

        self.assertEqual(self.backend.navigations, [])


class Snapshot:
    def __init__(self, markdown):
        self.markdown = markdown


class TocLifecycleTest(Fixture):
    """A table of contents is opened by a render, so it is closed by one too."""

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

    def test_render_opens_a_table_of_contents_beside_the_preview(self):
        session = self.open()
        self.assertIsNotNone(session.toc_surface)
        self.assertEqual(self.backend.roles[session.toc_surface.id], "toc")

    def test_a_closed_table_of_contents_is_not_reopened_by_the_next_render(self):
        session = self.open()
        toc_id = session.toc_surface.id
        self.backend.close(session.toc_surface)
        self.manager.surface_closed(toc_id)
        self.assertIsNone(session.toc_surface)

        self.usecases.present(session, session.last_document)

        self.assertIsNone(session.toc_surface)
        self.assertTrue(session.toc_dismissed)

    def test_the_setting_closes_a_table_of_contents_that_is_already_open(self):
        session = self.open()
        toc_id = session.toc_surface.id
        session.settings = RenderSettings(enable_toc=False)

        self.usecases.present(session, session.last_document)

        self.assertIsNone(session.toc_surface)
        self.assertIn(toc_id, self.backend.closed)

    def test_the_setting_off_opens_none_at_all(self):
        self.settings = RenderSettings()
        session = self.open()
        self.assertIsNone(session.toc_surface)

    def test_the_group_is_asked_for_the_width_the_entries_need(self):
        session = self.open()
        toc = [item for item in self.layout.acquired if item[1] == GroupRole.TOC]
        self.assertEqual(len(toc), 1)
        self.assertAlmostEqual(
            toc[0][3], toc_width_px(session.last_document.headings, 16)
        )
        self.assertGreater(toc[0][3], 0.0)

    def test_every_repaint_re_fits_the_group(self):
        session = self.open()
        group = self.backend.group_of(session.toc_surface)
        self.assertEqual(
            self.layout.fitted,
            [(group, GroupRole.TOC, toc_width_px(session.last_document.headings, 16))],
        )

        session.zoom = 2.0
        self.usecases.represent(session)

        self.assertEqual(
            self.layout.fitted[-1],
            (group, GroupRole.TOC, toc_width_px(session.last_document.headings, 32)),
        )

    def test_the_setting_off_asks_for_the_default_share(self):
        self.settings = RenderSettings(enable_toc=True, auto_width=False)
        session = self.open()
        self.assertIsNotNone(session.toc_surface)
        self.assertEqual([item[3] for item in self.layout.acquired], [0.0, 0.0])
        self.assertEqual([item[2] for item in self.layout.fitted], [0.0])

    def test_turning_the_setting_back_on_outlives_a_close(self):
        # The setting is the stronger switch, so it clears the session's own
        # dismissal rather than leaving the preview permanently without one.
        session = self.open()
        self.manager.surface_closed(session.toc_surface.id)
        session.settings = RenderSettings(enable_toc=False)
        self.usecases.present(session, session.last_document)
        session.settings = RenderSettings(enable_toc=True)

        self.usecases.present(session, session.last_document)

        self.assertIsNotNone(session.toc_surface)


class RepaintCostTest(TocLifecycleTest):
    """A repaint must not do work Sublime charges a full minihtml layout for."""

    def test_a_repaint_does_not_reveal_the_table_of_contents_again(self):
        session = self.open()
        # `reveal` focuses the group, the view, then the previous group back,
        # and each focus change makes Sublime fire `on_activated`, which reads
        # the theme and repaints -- landing here again. Creation reveals; a
        # repaint must not.
        self.assertEqual(self.backend.revealed, [session.toc_surface.id])

        self.usecases.present(session, session.last_document)
        self.usecases.represent(session)

        self.assertEqual(self.backend.revealed, [session.toc_surface.id])

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


class DiagramThemeTest(TocLifecycleTest):
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


class SurfaceColourSchemeTest(TocLifecycleTest):
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

    def test_the_source_scheme_reaches_the_preview_and_the_contents(self):
        session = self.open()

        self.assertEqual(
            self.backend.themes[session.preview_surface.id].scheme, self.SCHEME
        )
        self.assertEqual(
            self.backend.themes[session.toc_surface.id].scheme, self.SCHEME
        )

    def test_a_scheme_chosen_while_the_preview_is_open_still_reaches_it(self):
        session = self.open()
        moved = (("color_scheme", "MarkdownEditor-Yellow.sublime-color-scheme"),)
        self.usecases.theme_provider = lambda view: ThemeSnapshot(scheme=moved)

        self.usecases.theme_changed(self.source)

        self.assertEqual(self.backend.themes[session.preview_surface.id].scheme, moved)
        self.assertEqual(self.backend.themes[session.toc_surface.id].scheme, moved)


if __name__ == "__main__":
    unittest.main()
