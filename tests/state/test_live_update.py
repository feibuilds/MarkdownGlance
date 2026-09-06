"""End-to-end check of the edit -> debounce -> render -> present loop.

Wires the real SessionManager, GenerationScheduler and UseCases together with
the fakes from tests/state/test_usecases.py, then drives them exactly as
SourceAndSurfaceListener.on_modified_async does.
"""
import os
import unittest

from MarkdownGlance.tests.state.test_usecases import (
    BASE,
    Backend,
    Layout,
    Resolver,
    View,
    Window,
)
from MarkdownGlance.preview.application.scheduler import GenerationScheduler
from MarkdownGlance.preview.application.session_manager import SessionManager
from MarkdownGlance.preview.application.usecases import UseCases
from MarkdownGlance.preview.domain.contracts import (
    PreviewDocument, PreviewMode, RenderRequest, RenderSettings, ThemeSnapshot,
)
from concurrent.futures import Future


class ManualExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, request):
        future = Future()
        self.calls.append((fn, request, future))
        return future

    def run_all(self):
        """Complete every outstanding render, as the render pool would."""
        while True:
            pending = [c for c in self.calls if not c[2].done()]
            if not pending:
                return
            for fn, request, future in pending:
                future.set_result(fn(request))


class Clock:
    def __init__(self):
        self.calls = []

    def call_later(self, delay, callback):
        handle = {"active": True, "callback": callback, "delay": delay}
        self.calls.append(handle)
        return handle

    def cancel(self, handle):
        handle["active"] = False

    def fire_all(self):
        for handle in list(self.calls):
            if handle["active"]:
                handle["active"] = False
                handle["callback"]()


class LiveUpdateTest(unittest.TestCase):
    def setUp(self):
        self.text = "# One\n"
        self.source = View(10, filename=os.path.join(BASE, "source.md"))
        self.window = Window(1, self.source)
        self.windows = {1: self.window}
        self.backend = Backend(self.windows)
        self.layout = Layout()
        self.clock = Clock()
        self.executor = ManualExecutor()
        self.manager = SessionManager(
            self.backend, self.layout, Resolver(),
            lambda identifier: self.windows.get(identifier),
            on_show=lambda stage, session: self.usecases.show(stage, session),
        )
        self.scheduler = GenerationScheduler(
            self.manager.get,
            self.snapshot,
            self.render,
            lambda session, doc: self.usecases.present(session, doc),
            lambda session, stage, msg: self.usecases.present_error(session, stage, msg),
            self.executor,
            self.clock,
            lambda callback: callback(),      # UI thread runs inline
        )
        self.usecases = UseCases(
            self.manager, self.scheduler, self.backend, self.layout,
            self.snapshot,
            lambda: RenderSettings(enable_toc=False),
            lambda view: ThemeSnapshot(),
            lambda view, session_id: None,
            "",
        )

    def snapshot(self, session, generation):
        return RenderRequest(
            session.id, generation, self.text, session.base_path,
            self.manager.stage(session.window_id).zoom,
            session.settings, session.theme, session.action_token,
        )

    def render(self, request):
        return PreviewDocument(
            request.generation, "<p>{}</p>".format(request.markdown.strip()),
            (), (), (), (),
        )

    def settle(self):
        for _ in range(10):
            self.clock.fire_all()
            self.executor.run_all()

    def bodies(self):
        return [html for _, html in self.backend.updates]

    def test_typing_repaints_the_preview_without_saving(self):
        self.usecases.open_side_by_side(self.window)
        self.settle()
        self.assertIn("<p># One</p>", self.bodies()[-1])

        # Type. No save, no command -- just what on_modified_async delivers.
        self.text = "# One\n\n## Two\n"
        self.usecases.source_modified(self.source)
        self.settle()
        self.assertIn("## Two", self.bodies()[-1])

    def test_debounce_coalesces_a_burst_of_keystrokes(self):
        self.usecases.open_side_by_side(self.window)
        self.settle()
        before = len(self.executor.calls)
        for index in range(20):
            self.text = "# One" + "x" * index
            self.usecases.source_modified(self.source)
        self.settle()
        self.assertIn("x" * 19, self.bodies()[-1])
        # 20 keystrokes must not mean 20 renders.
        self.assertLessEqual(len(self.executor.calls) - before, 2)

    def test_delay_comes_from_the_setting(self):
        self.usecases.open_side_by_side(self.window)
        self.settle()
        session = self.manager.all_sessions()[0]
        session.settings = RenderSettings(update_delay_ms=1000, enable_toc=False)
        self.usecases.source_modified(self.source)
        self.assertEqual(self.clock.calls[-1]["delay"], 1000)

    def test_edit_while_a_render_is_in_flight_is_not_lost(self):
        self.usecases.open_side_by_side(self.window)
        self.settle()
        self.text = "# A\n"
        self.usecases.source_modified(self.source)
        self.clock.fire_all()                 # dispatch A, still in flight
        self.text = "# B\n"
        self.usecases.source_modified(self.source)
        self.clock.fire_all()                 # coalesced behind the in-flight A
        self.executor.run_all()
        self.settle()
        self.assertIn("# B", self.bodies()[-1])
        session = self.manager.all_sessions()[0]
        session.validate()


if __name__ == "__main__":
    unittest.main(verbosity=2)
