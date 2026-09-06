from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet, Optional, Set, Tuple

from ..domain.contracts import (
    AssetKey,
    PreviewDocument,
    PreviewMode,
    RenderSettings,
    ThemeSnapshot,
)
from .ports import SurfaceHandle


class SessionState(Enum):
    OPENING = "opening"
    RENDERING = "rendering"
    VISIBLE = "visible"
    MOVING = "moving"
    ERROR = "error"
    CLOSING = "closing"


class CloseCause(Enum):
    SOURCE_CLOSED = "source_closed"
    PREVIEW_CLOSED_BY_USER = "preview_closed_by_user"
    WINDOW_CLOSED = "window_closed"
    UNLOAD = "unload"


@dataclass
class PreviewSession:
    id: str
    window_id: int
    source_buffer_id: int
    source_sheet_id: int
    preview_surface: Optional[SurfaceHandle]
    mode: PreviewMode
    state: SessionState
    source_group: int = 0
    source_name: str = "Untitled"
    base_path: Optional[str] = None
    zoom: float = 1.0
    requested_generation: int = 0
    completed_generation: int = 0
    successful_generation: int = 0
    last_document: Optional[PreviewDocument] = None
    pending_assets: FrozenSet[AssetKey] = frozenset()
    layout_groups: Set[int] = field(default_factory=set)
    action_token: str = ""
    settings: RenderSettings = field(default_factory=RenderSettings)
    theme: ThemeSnapshot = field(default_factory=ThemeSnapshot)
    table_budget: Optional[Tuple[int, int]] = None
    inflight_generation: Optional[int] = None
    inflight_future: object = None
    debounce_handle: object = None

    def validate(self) -> None:
        if not (
            self.successful_generation
            <= self.completed_generation
            <= self.requested_generation
        ):
            raise AssertionError("invalid generation ordering")
        if self.state == SessionState.VISIBLE:
            if self.last_document is None:
                raise AssertionError("visible session has no document")
            if self.successful_generation != self.requested_generation:
                raise AssertionError("visible session is not latest")
        if self.state == SessionState.ERROR:
            if not (
                self.completed_generation == self.requested_generation
                and self.completed_generation > self.successful_generation
            ):
                raise AssertionError("error session generation mismatch")
