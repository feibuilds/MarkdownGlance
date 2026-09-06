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
        # The owner holds group 1 for the session under test.
        self.held = {"s": {1}}

    def release(self, window, group, session_id, restore=True):
        self.releases.append((group, restore))

    def release_all(self, window, session_id, restore=True):
        for group in sorted(self.held.get(session_id, ()), reverse=True):
            self.release(window, group, session_id, restore=restore)


class FakeResolver:
    def __init__(self):
        self.forgot = []

    def forget_session(self, session_id):
        self.forgot.append(session_id)


class FakeWindow:
    def id(self):
        return 1


def session():
    return PreviewSession(
        "s",
        1,
        2,
        3,
        SurfaceHandle("fake", 10, 1),
        PreviewMode.SIDE_BY_SIDE,
        SessionState.VISIBLE,
        requested_generation=1,
        completed_generation=1,
        successful_generation=1,
        last_document=object(),
    )


class SessionManagerTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.backend.alive = {10}
        self.layout = FakeLayout()
        self.resolver = FakeResolver()
        self.manager = SessionManager(
            self.backend, self.layout, self.resolver, lambda window_id: FakeWindow()
        )
        self.session = session()
        self.manager.add(self.session)

    def test_source_close_closes_the_preview_never_the_source(self):
        self.manager.close(self.session, CloseCause.SOURCE_CLOSED)
        self.assertEqual(self.backend.closed, [10])
        self.assertNotIn(3, self.backend.closed)
        self.assertEqual(self.layout.releases, [(1, True)])
        self.assertEqual(self.resolver.forgot, ["s"])

    def test_preview_user_close_does_not_close_preview_again(self):
        self.backend.alive.discard(10)
        self.manager.close(self.session, CloseCause.PREVIEW_CLOSED_BY_USER)
        self.assertEqual(self.backend.closed, [])

    def test_window_close_skips_layout_restore(self):
        self.manager.close(self.session, CloseCause.WINDOW_CLOSED)
        self.assertEqual(self.layout.releases, [(1, False)])

    def test_closing_the_preview_ends_the_session(self):
        self.manager.surface_closed(10)
        self.assertIsNone(self.manager.get("s"))

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
        manager.add(first)
        manager.close(first, CloseCause.SOURCE_CLOSED)
        self.assertEqual(closed, [first])

    def test_reconcile_closes_only_proven_owned_orphan(self):
        orphan = 99
        self.backend.alive.add(orphan)
        self.manager.reconcile(FakeWindow())
        self.assertIn(orphan, self.backend.closed)
