"""The one preview surface a window has.

A `PreviewSession` is a *document*: its render generations, its parsed
document, its assets, its theme. A stage is the *pane* those documents are
shown in -- one per window, holding the surface, which document is on it, and
everything that belongs to the viewport rather than to any document: the mode,
the zoom, the table budget measured from its width, and where each document
was scrolled to when it was last on screen.

Keeping them apart is what lets a window hold ten Markdown files and one
preview tab. It also puts the fields that were always per-pane in the right
place: with a surface each, zoom was per document and jumped when you switched,
and a window resize asked every session to re-render for a width only one of
them was being measured at.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from ..domain.contracts import PreviewMode
from .ports import SurfaceHandle


@dataclass
class PreviewStage:
    id: str
    window_id: int
    surface: Optional[SurfaceHandle] = None
    # The session whose document is painted on the surface right now.
    showing: Optional[str] = None
    mode: PreviewMode = PreviewMode.SIDE_BY_SIDE
    zoom: float = 1.0
    table_budget: Optional[Tuple[int, int]] = None
    # Where each document was scrolled to, as a fraction of its own height:
    # the surface is one viewport, and a document put back at the pixel it
    # left would be in the wrong place after a divider drag or a zoom.
    scroll: Dict[str, float] = field(default_factory=dict)

    def is_showing(self, session_id: str) -> bool:
        return self.showing is not None and self.showing == session_id
