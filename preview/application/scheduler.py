from concurrent.futures import Executor
from typing import Callable, Dict, Optional

from ..domain.contracts import AssetKey, DiagnosticStage, PreviewDocument, RenderRequest
from .errors import RenderFailure, describe
from .ports import Clock, RunOnUi
from .session import PreviewSession, SessionState


class GenerationScheduler:
    def __init__(
        self,
        sessions: Callable[[str], Optional[PreviewSession]],
        snapshot: Callable[[PreviewSession, int], RenderRequest],
        render: Callable[[RenderRequest], PreviewDocument],
        present: Callable[[PreviewSession, PreviewDocument], None],
        present_error: Callable[[PreviewSession, DiagnosticStage, str], None],
        executor: Executor,
        clock: Clock,
        run_on_ui: RunOnUi,
        report_failure: Optional[
            Callable[[PreviewSession, DiagnosticStage, BaseException], None]
        ] = None,
    ) -> None:
        self._session = sessions
        self._snapshot = snapshot
        self._render = render
        self._present = present
        self._present_error = present_error
        # The exception behind a failure, for the console and the diagnostics.
        # The card gets one line of it; this gets the traceback.
        self._report_failure = report_failure
        self._executor = executor
        self._clock = clock
        self._run_on_ui = run_on_ui

    def request_render(self, session_id: str, reason: str = "unknown") -> None:
        self._run_on_ui(lambda: self._request(session_id, reason))

    def _request(self, session_id: str, reason: str) -> None:
        session = self._session(session_id)
        if session is None or session.state == SessionState.CLOSING:
            return
        session.requested_generation += 1
        session.state = SessionState.RENDERING
        if session.debounce_handle is not None:
            self._clock.cancel(session.debounce_handle)
        generation = session.requested_generation
        session.debounce_handle = self._clock.call_later(
            session.settings.update_delay_ms,
            lambda: self._dispatch(session_id, generation),
        )

    def _dispatch(self, session_id: str, generation: int) -> None:
        session = self._session(session_id)
        if session is None or session.state == SessionState.CLOSING:
            return
        session.debounce_handle = None
        if session.inflight_future is not None:
            return
        generation = session.requested_generation
        try:
            request = self._snapshot(session, generation)
        except Exception as error:
            session.completed_generation = generation
            self._apply_failure(
                session, DiagnosticStage.PARSE, describe(error), error
            )
            return
        future = self._executor.submit(self._render, request)
        session.inflight_generation = generation
        session.inflight_future = future
        future.add_done_callback(
            lambda completed, sid=session_id, gen=generation: self._run_on_ui(
                lambda: self._complete(sid, gen, completed)
            )
        )

    def _complete(self, session_id: str, generation: int, future) -> None:
        session = self._session(session_id)
        if session is None or session.state == SessionState.CLOSING:
            return
        if session.inflight_generation != generation:
            return
        session.inflight_generation = None
        session.inflight_future = None
        session.completed_generation = max(session.completed_generation, generation)
        try:
            document = future.result()
        except RenderFailure as error:
            if generation == session.requested_generation:
                self._apply_failure(
                    session, error.stage, error.safe_message, error.cause or error
                )
        except Exception as error:
            # The pipeline names its stage; anything else that reaches here
            # was raised outside it, and is still worth a traceback.
            if generation == session.requested_generation:
                self._apply_failure(
                    session, DiagnosticStage.SERIALISE, describe(error), error
                )
        else:
            if generation == session.requested_generation:
                session.last_document = document
                session.pending_assets = frozenset(document.pending_assets)
                session.successful_generation = generation
                session.state = SessionState.VISIBLE
                self._present(session, document)
        if (
            session.requested_generation > session.completed_generation
            and session.debounce_handle is None
            and session.inflight_future is None
        ):
            self._dispatch(session_id, session.requested_generation)

    def _apply_failure(
        self,
        session: PreviewSession,
        stage: DiagnosticStage,
        message: str,
        error: Optional[BaseException] = None,
    ) -> None:
        if error is not None and self._report_failure is not None:
            self._report_failure(session, stage, error)
        self._present_error(session, stage, message)
        session.state = SessionState.ERROR

    def asset_available(self, key: AssetKey, waiter_ids=None) -> None:
        candidates = waiter_ids or ()
        for session_id in candidates:
            session = self._session(session_id)
            if session is not None and key in session.pending_assets:
                self.request_render(session_id, "asset")
