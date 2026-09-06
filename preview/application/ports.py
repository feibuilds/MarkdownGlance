from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Protocol, Sequence, Set

from ..domain.contracts import AssetKey, AssetResult, ThemeSnapshot


class NavigationCapability(Enum):
    PROGRAMMATIC = "programmatic"
    FRAGMENT_ONLY = "fragment_only"
    NONE = "none"


class GroupRole(Enum):
    PREVIEW = "preview"
    # One role for the panel beside the preview: it shows the source outline or
    # the rendered table of contents depending on which tab has the focus, and
    # a window holds one such group however many documents are open in it.
    PANEL = "panel"


@dataclass(frozen=True)
class SurfaceHandle:
    kind: str
    id: int
    window_id: int


class PresentationBackend(Protocol):
    navigation: NavigationCapability

    def create(
        self, window, group: int, title: str, session_id: str
    ) -> SurfaceHandle: ...

    def update(self, handle: SurfaceHandle, html: str) -> None: ...

    def apply_theme(self, handle: SurfaceHandle, theme: ThemeSnapshot) -> None: ...

    def viewport_width(self, handle: SurfaceHandle) -> float: ...

    def navigate(self, handle: SurfaceHandle, slug: str) -> bool: ...

    def set_heading_ratios(
        self, handle: SurfaceHandle, ratios: Dict[str, float]
    ) -> None: ...

    def scroll_ratio(self, handle: SurfaceHandle) -> float: ...

    def restore_scroll(self, handle: SurfaceHandle, ratio: float) -> None: ...

    def move(self, handle: SurfaceHandle, group: int) -> None: ...

    def focus(self, handle: SurfaceHandle) -> None: ...

    def close(self, handle: SurfaceHandle) -> None: ...

    def is_alive(self, handle: SurfaceHandle) -> bool: ...

    def group_of(self, handle: SurfaceHandle) -> Optional[int]: ...

    def set_title(self, handle: SurfaceHandle, title: str) -> None: ...

    def live_handles(self, window) -> List[SurfaceHandle]: ...

    def owner_of(self, sheet_or_view) -> Optional[str]: ...


class AssetResolverPort(Protocol):
    def resolve(
        self, keys: Sequence[AssetKey], session_id: str
    ) -> Dict[AssetKey, AssetResult]: ...

    def forget_session(self, session_id: str) -> None: ...


class Clock(Protocol):
    def call_later(self, delay_ms: int, callback: Callable[[], None]): ...

    def cancel(self, handle) -> None: ...


RunOnUi = Callable[[Callable[[], None]], None]
