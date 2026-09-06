import unittest

from MarkdownGlance.preview.application.ports import NavigationCapability, SurfaceHandle
from MarkdownGlance.preview.application.session import (
    CloseCause,
    PreviewSession,
    SessionState,
)
from MarkdownGlance.preview.application.session_manager import SessionManager
from MarkdownGlance.preview.domain.contracts import PreviewMode


class FakeBackend:
    navigation = NavigationCapability.PROGRAMMATIC

    def __init__(self):
        self.alive = set()
        self.closed = []

    def is_alive(self, handle):
        return handle.id in self.alive

    def close(self, handle):
        self.closed.append(handle.id)
        self.alive.discard(handle.id)

    def live_handles(self, window):
        return [SurfaceHandle("fake", item, window.id()) for item in self.alive]

    def group_of(self, handle):
        # A closed view has no group, exactly as the real backend reports it.
        if handle.id not in self.alive:
            return None
        return 2 if handle.id == 11 else 1


class FakeLayout:
    def __init__(self):
        self.releases = []

    def release(self, window, group, session_id, restore=True):
        self.releases.append((group, restore))

    def release_all(self, window, session_id, restore=True):
        self.releases.append((session_id, restore))


class FakeResolver:
    def __init__(self):
        self.forgot = []

    def forget_session(self, session_id):
        self.forgot.append(session_id)


class FakeWindow:
    def id(self):
        return 1


def session(identifier="s", buffer_id=2):
    return PreviewSession(
        identifier,
        1,
        buffer_id,
        3,
        SessionState.VISIBLE,
        requested_generation=1,
        completed_generation=1,
        successful_generation=1,
        last_document=object(),
    )


def staged(manager, backend, *sessions):
    """A window whose stage is showing the first of these documents."""
    stage = manager.open_stage(1, PreviewMode.SIDE_BY_SIDE)
    stage.surface = SurfaceHandle("fake", 10, 1)
    backend.alive.add(10)
    for item in sessions:
        manager.add(item)
    stage.showing = sessions[0].id
    return stage


class SessionManagerTest(unittest.TestCase):
    """One stage per window, holding the documents shown on it."""

    def setUp(self):
        self.backend = FakeBackend()
        self.layout = FakeLayout()
        self.resolver = FakeResolver()
        self.shown = []
        self.manager = SessionManager(
            self.backend,
            self.layout,
            self.resolver,
            lambda window_id: FakeWindow(),
            on_show=lambda stage, session: self.shown.append(session.id),
        )
        self.session = session()
        self.stage = staged(self.manager, self.backend, self.session)

    def test_source_close_closes_the_preview_when_it_was_the_last_document(self):
        self.manager.close(self.session, CloseCause.SOURCE_CLOSED)
        self.assertEqual(self.backend.closed, [10])
        self.assertNotIn(3, self.backend.closed)
        self.assertEqual(self.layout.releases, [(self.stage.id, True)])
        self.assertEqual(self.resolver.forgot, ["s"])
        self.assertIsNone(self.manager.stage(1))

    def test_closing_the_document_on_screen_shows_another(self):
        other = session("t", buffer_id=4)
        self.manager.add(other)

        self.manager.close(self.session, CloseCause.SOURCE_CLOSED)

        self.assertEqual(self.shown, ["t"])
        self.assertEqual(self.backend.closed, [])
        self.assertIsNotNone(self.manager.stage(1))

    def test_closing_a_document_that_is_not_on_screen_shows_nothing(self):
        other = session("t", buffer_id=4)
        self.manager.add(other)

        self.manager.close(other, CloseCause.SOURCE_CLOSED)

        self.assertEqual(self.shown, [])
        self.assertTrue(self.manager.stage(1).is_showing("s"))

    def test_window_close_skips_layout_restore(self):
        self.manager.close_window(1)
        self.assertEqual(self.layout.releases, [(self.stage.id, False)])

    def test_closing_the_preview_tab_ends_every_document(self):
        other = session("t", buffer_id=4)
        self.manager.add(other)
        self.backend.alive.discard(10)

        self.manager.surface_closed(10)

        self.assertEqual(self.manager.sessions_in(1), [])
        self.assertIsNone(self.manager.stage(1))
        # The view was already gone; closing it again is not this owner's job.
        self.assertEqual(self.backend.closed, [])

    def test_closing_the_preview_ourselves_closes_the_view(self):
        self.manager.close_preview(1)
        self.assertEqual(self.backend.closed, [10])
        self.assertIsNone(self.manager.stage(1))

    def test_the_surface_answers_with_the_document_on_it(self):
        self.assertIs(self.manager.for_surface(10), self.session)
        self.assertIsNone(self.manager.for_surface(99))

    def test_every_close_path_reaches_the_hook_the_panel_hangs_on(self):
        closed = []
        manager = SessionManager(
            self.backend,
            self.layout,
            FakeResolver(),
            lambda window_id: FakeWindow(),
            closed.append,
        )
        first = session()
        staged(manager, self.backend, first)
        manager.close(first, CloseCause.SOURCE_CLOSED)
        self.assertEqual(closed, [first])

    def test_reconcile_closes_only_proven_owned_orphan(self):
        orphan = 99
        self.backend.alive.add(orphan)
        self.manager.reconcile(FakeWindow())
        self.assertIn(orphan, self.backend.closed)
        # The stage's own surface is not an orphan.
        self.assertNotIn(10, self.backend.closed)

    def test_reconcile_ends_the_preview_when_its_view_is_gone(self):
        self.backend.alive.discard(10)

        self.manager.reconcile(FakeWindow())

        self.assertIsNone(self.manager.stage(1))
        self.assertEqual(self.manager.sessions_in(1), [])
