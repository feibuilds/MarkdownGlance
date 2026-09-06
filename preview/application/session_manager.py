from typing import Callable, Dict, Iterable, List, Optional, Tuple

from ..domain.contracts import PreviewMode
from ..domain.ids import new_action_token, new_session_id
from .ports import PresentationBackend, SurfaceHandle
from .session import CloseCause, PreviewSession, SessionState


class SessionManager:
    def __init__(
        self,
        backend: PresentationBackend,
        layout_owner,
        resolver,
        window_for_id: Callable[[int], object],
        on_session_close: Callable[[PreviewSession], None] = lambda session: None,
        foreign_surface: Callable[[int], bool] = lambda surface_id: False,
    ) -> None:
        self.backend = backend
        self.layout_owner = layout_owner
        self.resolver = resolver
        self.window_for_id = window_for_id
        self.on_session_close = on_session_close
        # Panel surfaces carry the same owner marker but belong to another
        # controller, so they must survive this manager's orphan sweep.
        self.foreign_surface = foreign_surface
        self._by_id: Dict[str, PreviewSession] = {}
        self._by_source: Dict[Tuple[int, int], str] = {}
        self._by_surface: Dict[int, str] = {}

    def new_session(
        self,
        window_id: int,
        source_buffer_id: int,
        source_sheet_id: int,
        source_group: int,
        source_name: str,
        mode: PreviewMode,
    ) -> PreviewSession:
        session = PreviewSession(
            new_session_id(),
            window_id,
            source_buffer_id,
            source_sheet_id,
            None,
            mode,
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
        self.bind_surfaces(session)

    def bind_surfaces(self, session: PreviewSession) -> None:
        if session.preview_surface is not None:
            self._by_surface[session.preview_surface.id] = session.id

    def get(self, session_id: str) -> Optional[PreviewSession]:
        return self._by_id.get(session_id)

    def for_source(
        self, window_id: int, source_buffer_id: int
    ) -> Optional[PreviewSession]:
        session_id = self._by_source.get((window_id, source_buffer_id))
        return self.get(session_id) if session_id else None

    def for_surface(self, surface_id: int) -> Optional[PreviewSession]:
        session_id = self._by_surface.get(surface_id)
        return self.get(session_id) if session_id else None

    def all_sessions(self) -> List[PreviewSession]:
        return list(self._by_id.values())

    def sessions_in(self, window_id: int) -> List[PreviewSession]:
        return [s for s in self._by_id.values() if s.window_id == window_id]

    def close(self, session: PreviewSession, cause: CloseCause) -> None:
        if session.id not in self._by_id or session.state == SessionState.CLOSING:
            return
        session.state = SessionState.CLOSING
        session.requested_generation += 1
        session.debounce_handle = None
        self.on_session_close(session)
        self.resolver.forget_session(session.id)
        window = self.window_for_id(session.window_id)
        restore = cause not in (CloseCause.WINDOW_CLOSED, CloseCause.UNLOAD)

        if (
            cause != CloseCause.PREVIEW_CLOSED_BY_USER
            and session.preview_surface is not None
            and self.backend.is_alive(session.preview_surface)
        ):
            self.backend.close(session.preview_surface)

        if window is not None:
            for group in sorted(session.layout_groups, reverse=True):
                self.layout_owner.release(window, group, session.id, restore=restore)
        self._remove(session)

    def _remove(self, session: PreviewSession) -> None:
        self._by_id.pop(session.id, None)
        self._by_source.pop((session.window_id, session.source_buffer_id), None)
        if session.preview_surface is not None:
            self._by_surface.pop(session.preview_surface.id, None)

    def surface_closed(self, surface_id: int) -> None:
        session = self.for_surface(surface_id)
        if session is not None:
            self.close(session, CloseCause.PREVIEW_CLOSED_BY_USER)

    def close_window(self, window_id: int) -> None:
        for session in list(self.sessions_in(window_id)):
            self.close(session, CloseCause.WINDOW_CLOSED)

    def close_all(self, cause: CloseCause = CloseCause.UNLOAD) -> None:
        for session in list(self._by_id.values()):
            self.close(session, cause)

    def reconcile(self, window) -> None:
        live_handles = self.backend.live_handles(window)
        live = {handle.id for handle in live_handles}
        for session in list(self.sessions_in(window.id())):
            if (
                session.preview_surface is not None
                and session.preview_surface.id not in live
            ):
                self.close(session, CloseCause.PREVIEW_CLOSED_BY_USER)
        registered = set(self._by_surface)
        for handle in live_handles:
            if handle.id not in registered and not self.foreign_surface(handle.id):
                self.backend.close(handle)
