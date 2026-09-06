from typing import Callable, Dict, List, Optional, Tuple

from ..domain.contracts import PreviewMode
from ..domain.ids import new_action_token, new_session_id
from .ports import PresentationBackend
from .session import CloseCause, PreviewSession, SessionState
from .stage import PreviewStage


class SessionManager:
    """Documents, and the one stage per window they are shown on."""

    def __init__(
        self,
        backend: PresentationBackend,
        layout_owner,
        resolver,
        window_for_id: Callable[[int], object],
        on_session_close: Callable[[PreviewSession], None] = lambda session: None,
        foreign_surface: Callable[[int], bool] = lambda surface_id: False,
        on_show: Callable[[PreviewStage, PreviewSession], None] = (
            lambda stage, session: None
        ),
    ) -> None:
        self.backend = backend
        self.layout_owner = layout_owner
        self.resolver = resolver
        self.window_for_id = window_for_id
        self.on_session_close = on_session_close
        # Panel surfaces carry the same owner marker but belong to another
        # controller, so they must survive this manager's orphan sweep.
        self.foreign_surface = foreign_surface
        # Called when a stage changes what it is showing, so the use cases can
        # paint it. Which document goes on the stage is the manager's business;
        # painting it is not.
        self.on_show = on_show
        self._by_id: Dict[str, PreviewSession] = {}
        self._by_source: Dict[Tuple[int, int], str] = {}
        self._stages: Dict[int, PreviewStage] = {}

    # -- documents --------------------------------------------------------

    def new_session(
        self,
        window_id: int,
        source_buffer_id: int,
        source_sheet_id: int,
        source_group: int,
        source_name: str,
    ) -> PreviewSession:
        session = PreviewSession(
            new_session_id(),
            window_id,
            source_buffer_id,
            source_sheet_id,
            SessionState.OPENING,
            source_group=source_group,
            source_name=source_name,
            action_token=new_action_token(),
        )
        self.add(session)
        return session

    def add(self, session: PreviewSession) -> None:
        key = (session.window_id, session.source_buffer_id)
        if session.id in self._by_id or key in self._by_source:
            raise ValueError("duplicate preview session")
        self._by_id[session.id] = session
        self._by_source[key] = session.id

    def get(self, session_id: str) -> Optional[PreviewSession]:
        return self._by_id.get(session_id)

    def for_source(
        self, window_id: int, source_buffer_id: int
    ) -> Optional[PreviewSession]:
        session_id = self._by_source.get((window_id, source_buffer_id))
        return self.get(session_id) if session_id else None

    def all_sessions(self) -> List[PreviewSession]:
        return list(self._by_id.values())

    def sessions_in(self, window_id: int) -> List[PreviewSession]:
        return [s for s in self._by_id.values() if s.window_id == window_id]

    # -- the stage --------------------------------------------------------

    def stage(self, window_id: int) -> Optional[PreviewStage]:
        return self._stages.get(window_id)

    def stages(self) -> List[PreviewStage]:
        return list(self._stages.values())

    def open_stage(self, window_id: int, mode: PreviewMode) -> PreviewStage:
        stage = self._stages.get(window_id)
        if stage is None:
            stage = PreviewStage(new_session_id(), window_id, mode=mode)
            self._stages[window_id] = stage
        return stage

    def stage_for_surface(self, surface_id: int) -> Optional[PreviewStage]:
        return next(
            (
                stage
                for stage in self._stages.values()
                if stage.surface is not None and stage.surface.id == surface_id
            ),
            None,
        )

    def for_surface(self, surface_id: int) -> Optional[PreviewSession]:
        """The document on that surface: only ever the one it is showing."""
        stage = self.stage_for_surface(surface_id)
        if stage is None or stage.showing is None:
            return None
        return self.get(stage.showing)

    def show(self, session: PreviewSession) -> None:
        stage = self._stages.get(session.window_id)
        if stage is None or stage.is_showing(session.id):
            return
        stage.showing = session.id
        self.on_show(stage, session)

    def _reshow(self, stage: PreviewStage, closing: PreviewSession) -> None:
        """Put another document on the stage, or take the stage down.

        Called when the document on screen is going away. A window with other
        Markdown files open keeps its preview; when the last goes, so does the
        preview, which is what closing the only file you were previewing means.
        """
        stage.scroll.pop(closing.id, None)
        replacement = next(
            (
                session
                for session in self.sessions_in(stage.window_id)
                if session.id != closing.id and session.state != SessionState.CLOSING
            ),
            None,
        )
        if replacement is None:
            self.close_stage(stage.window_id)
            return
        stage.showing = replacement.id
        self.on_show(stage, replacement)

    def close_stage(self, window_id: int, restore: bool = True) -> None:
        stage = self._stages.pop(window_id, None)
        if stage is None:
            return
        if stage.surface is not None and self.backend.is_alive(stage.surface):
            self.backend.close(stage.surface)
        window = self.window_for_id(window_id)
        if window is not None:
            self.layout_owner.release_all(window, stage.id, restore=restore)

    # -- closing ----------------------------------------------------------

    def close(self, session: PreviewSession, cause: CloseCause) -> None:
        if session.id not in self._by_id or session.state == SessionState.CLOSING:
            return
        session.state = SessionState.CLOSING
        session.requested_generation += 1
        session.debounce_handle = None
        self.on_session_close(session)
        self.resolver.forget_session(session.id)
        stage = self._stages.get(session.window_id)
        self._remove(session)
        if stage is None:
            return
        if not stage.is_showing(session.id):
            stage.scroll.pop(session.id, None)
            return
        if cause in (CloseCause.WINDOW_CLOSED, CloseCause.UNLOAD):
            self.close_stage(session.window_id, restore=False)
        else:
            self._reshow(stage, session)

    def _remove(self, session: PreviewSession) -> None:
        self._by_id.pop(session.id, None)
        self._by_source.pop((session.window_id, session.source_buffer_id), None)

    def surface_closed(self, surface_id: int) -> None:
        """The user closed the preview tab, so the window's preview is gone.

        One surface serves every document in the window, so this is not "close
        this document's preview" any more; it ends them all. The view is gone
        before this runs, so the handle is dropped rather than closed.
        """
        stage = self.stage_for_surface(surface_id)
        if stage is not None:
            stage.surface = None
            self._end(stage)

    def close_preview(self, window_id: int) -> None:
        """Close the window's preview ourselves, surface and all."""
        stage = self._stages.get(window_id)
        if stage is not None:
            self._end(stage)

    def _end(self, stage: PreviewStage) -> None:
        stage.showing = None
        for session in list(self.sessions_in(stage.window_id)):
            self.close(session, CloseCause.PREVIEW_CLOSED_BY_USER)
        self.close_stage(stage.window_id)

    def close_window(self, window_id: int) -> None:
        for session in list(self.sessions_in(window_id)):
            self.close(session, CloseCause.WINDOW_CLOSED)
        self.close_stage(window_id, restore=False)

    def close_all(self, cause: CloseCause = CloseCause.UNLOAD) -> None:
        for session in list(self._by_id.values()):
            self.close(session, cause)
        for window_id in list(self._stages):
            self.close_stage(window_id, restore=False)

    def reconcile(self, window) -> None:
        live_handles = self.backend.live_handles(window)
        live = {handle.id for handle in live_handles}
        stage = self._stages.get(window.id())
        if stage is not None and (
            stage.surface is None or stage.surface.id not in live
        ):
            stage.surface = None
            self._end(stage)
            stage = self._stages.get(window.id())
        keep = (
            {stage.surface.id}
            if stage is not None and stage.surface is not None
            else set()
        )
        for handle in live_handles:
            if handle.id not in keep and not self.foreign_surface(handle.id):
                self.backend.close(handle)
