import unittest
from concurrent.futures import Future

from MarkdownGlance.preview.application.errors import RenderFailure
from MarkdownGlance.preview.application.scheduler import GenerationScheduler
from MarkdownGlance.preview.application.session import PreviewSession, SessionState
from MarkdownGlance.preview.domain.contracts import (
    DiagnosticStage,
    PreviewDocument,
    PreviewMode,
    RenderRequest,
    RenderSettings,
    ThemeSnapshot,
)


class ManualExecutor:
    def __init__(self):
        self.calls = []

    def submit(self, fn, request):
        future = Future()
        self.calls.append((fn, request, future))
        return future

    def complete(self, index, result=None, error=None):
        future = self.calls[index][2]
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)


class FakeClock:
    def __init__(self):
        self.calls = []

    def call_later(self, delay, callback):
        handle = {"active": True, "callback": callback}
        self.calls.append(handle)
        return handle

    def cancel(self, handle):
        handle["active"] = False

    def fire_latest(self):
        handle = self.calls[-1]
        if handle["active"]:
            handle["active"] = False
            handle["callback"]()


def document(generation):
    return PreviewDocument(generation, "body-{}".format(generation), (), (), (), ())


class SchedulerTest(unittest.TestCase):
    def setUp(self):
        self.session = PreviewSession("s", 1, 2, 3, SessionState.OPENING)
        self.clock = FakeClock()
        self.executor = ManualExecutor()
        self.presented = []
        self.errors = []
        self.scheduler = GenerationScheduler(
            lambda session_id: self.session if session_id == "s" else None,
            lambda session, generation: RenderRequest(
                session.id,
                generation,
                "source-{}".format(generation),
                None,
                1.0,
                session.settings,
                ThemeSnapshot(),
            ),
            lambda request: document(request.generation),
            lambda session, doc: self.presented.append(doc.generation),
            lambda session, stage, message: self.errors.append((stage, message)),
            self.executor,
            self.clock,
            lambda callback: callback(),
        )

    def test_latest_wins_and_only_one_render_is_in_flight(self):
        self.scheduler.request_render("s", "edit")
        self.clock.fire_latest()
        self.scheduler.request_render("s", "edit")
        self.scheduler.request_render("s", "edit")
        self.clock.fire_latest()
        self.assertEqual(len(self.executor.calls), 1)
        self.executor.complete(0, document(1))
        self.assertEqual(self.presented, [])
        self.assertEqual(len(self.executor.calls), 2)
        self.assertEqual(self.executor.calls[1][1].generation, 3)
        self.executor.complete(1, document(3))
        self.assertEqual(self.presented, [3])
        self.assertEqual(self.session.successful_generation, 3)
        self.session.validate()

    def test_close_during_flight_discards_completion(self):
        self.scheduler.request_render("s")
        self.clock.fire_latest()
        self.session.state = SessionState.CLOSING
        self.executor.complete(0, document(1))
        self.assertEqual(self.presented, [])

    def test_latest_failure_advances_completed_without_retry_loop(self):
        self.scheduler.request_render("s")
        self.clock.fire_latest()
        self.executor.complete(
            0, error=RenderFailure(DiagnosticStage.PARSE, "fixed safe message")
        )
        self.assertEqual(self.session.completed_generation, 1)
        self.assertEqual(self.session.successful_generation, 0)
        self.assertEqual(self.session.state, SessionState.ERROR)
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual(self.errors, [(DiagnosticStage.PARSE, "fixed safe message")])
        self.session.validate()

    def test_edit_arriving_during_inflight_is_never_lost(self):
        self.scheduler.request_render("s")
        self.clock.fire_latest()
        self.scheduler.request_render("s")
        self.clock.fire_latest()
        self.executor.complete(0, document(1))
        self.assertEqual(self.executor.calls[1][1].generation, 2)
        self.executor.complete(1, document(2))
        self.assertEqual(self.presented, [2])
