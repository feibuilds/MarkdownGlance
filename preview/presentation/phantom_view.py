import time
from typing import Callable, Dict, Optional

import sublime

from ..application.ports import NavigationCapability, SurfaceHandle
from ..domain.contracts import ThemeSnapshot

OWNER_KEY = "mdglance.session"
ROLE_KEY = "mdglance.role"
CHROME_SUPPRESSION = {
    "gutter": False,
    "line_numbers": False,
    "fold_buttons": False,
    "draw_indent_guides": False,
    "highlight_line": False,
    "caret_extra_width": 0,
    "caret_style": "solid",
    "scroll_past_end": False,
    "word_wrap": True,
    "rulers": [],
    "draw_white_space": "none",
    "is_widget": True,
}


class PhantomViewBackend:
    name = "phantom_view"
    navigation = NavigationCapability.PROGRAMMATIC

    def __init__(
        self,
        on_link: Optional[Callable[[SurfaceHandle, str], None]] = None,
        on_paint: Optional[Callable[[SurfaceHandle, int, float, bool], None]] = None,
    ):
        self._phantoms: Dict[int, object] = {}
        self._ratios: Dict[int, Dict[str, float]] = {}
        # One navigate callback per surface, held for the life of the surface.
        # `PhantomSet.update` keys a phantom on (region, content, layout,
        # on_navigate), so a callback built fresh on each repaint never
        # compares equal: the set erases the phantom and adds it back, and
        # minihtml lays the whole document out again even when not a byte of
        # it changed. A stable callback makes an unchanged repaint free.
        self._navigators: Dict[int, Callable[[str], None]] = {}
        self._html: Dict[int, str] = {}
        self._on_link_callback = on_link or (lambda handle, href: None)
        # Told about every repaint: the surface, the size of the HTML, how long
        # the phantom set took, and whether the paint was skipped as unchanged.
        # This is the only place the cost of a minihtml layout is visible from
        # Python, and it is the number to look at before optimising further.
        self._on_paint = on_paint or (
            lambda handle, size, elapsed_ms, skipped: None
        )

    def set_link_handler(self, callback: Callable[[SurfaceHandle, str], None]) -> None:
        self._on_link_callback = callback

    def create(self, window, group: int, title: str, session_id: str) -> SurfaceHandle:
        view = window.new_file()
        window.set_view_index(view, group, len(window.views_in_group(group)))
        view.set_scratch(True)
        view.set_read_only(True)
        view.set_name(title)
        settings = view.settings()
        settings.set(OWNER_KEY, session_id)
        settings.set(ROLE_KEY, "preview")
        for key, value in CHROME_SUPPRESSION.items():
            settings.set(key, value)
        self._phantoms[view.id()] = sublime.PhantomSet(view, "mdglance")
        return SurfaceHandle(self.name, view.id(), window.id())

    def viewport_width(self, handle: SurfaceHandle) -> float:
        view = self._view(handle)
        return float(view.viewport_extent()[0]) if view is not None else 0.0

    def apply_theme(self, handle: SurfaceHandle, theme: ThemeSnapshot) -> None:
        """Put the source's colour scheme on the surface.

        A phantom resolves `var(--background)`, `var(--bluish)` and the rest
        against the colour scheme of the view it sits in, and so does the strip
        of view around it. A surface is a plain scratch file, so it inherits
        the global scheme -- which is the wrong one for a Markdown source that
        MarkdownEditing has given a scheme of its own.
        """
        view = self._view(handle)
        if view is None:
            return
        settings = view.settings()
        for key, value in theme.scheme:
            # Setting a value Sublime already holds still costs a re-resolve of
            # the scheme, and this runs on every repaint.
            if settings.get(key) != value:
                settings.set(key, value)

    def set_role(self, handle: SurfaceHandle, role: str) -> None:
        view = self._view(handle)
        if view is not None:
            view.settings().set(ROLE_KEY, role)

    def update(self, handle: SurfaceHandle, html: str) -> None:
        view = self._view(handle)
        if view is None:
            return
        if self._html.get(handle.id) == html:
            # Nothing changed. Repaints arrive from the viewport poll, from a
            # theme re-read on focus and from every table-of-contents render,
            # and each one would otherwise cost a full minihtml layout.
            self._on_paint(handle, len(html), 0.0, True)
            return
        phantom_set = self._phantoms.get(handle.id)
        if phantom_set is None:
            phantom_set = sublime.PhantomSet(view, "mdglance")
            self._phantoms[handle.id] = phantom_set
        started = time.perf_counter()
        phantom_set.update(
            [
                sublime.Phantom(
                    sublime.Region(0),
                    html,
                    sublime.LAYOUT_BLOCK,
                    self._navigator(handle),
                )
            ]
        )
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._html[handle.id] = html
        self._on_paint(handle, len(html), elapsed_ms, False)

    def _navigator(self, handle: SurfaceHandle) -> Callable[[str], None]:
        callback = self._navigators.get(handle.id)
        if callback is None:
            def callback(href: str, handle: SurfaceHandle = handle) -> None:
                self._on_link_callback(handle, href)

            self._navigators[handle.id] = callback
        return callback

    def set_heading_ratios(
        self, handle: SurfaceHandle, ratios: Dict[str, float]
    ) -> None:
        self._ratios[handle.id] = dict(ratios)

    def navigate(self, handle: SurfaceHandle, slug: str) -> bool:
        view = self._view(handle)
        ratio = self._ratios.get(handle.id, {}).get(slug)
        if view is None or ratio is None:
            return False
        document_height = view.layout_extent()[1]
        viewport_height = view.viewport_extent()[1]
        y = max(0.0, document_height * ratio - viewport_height * 0.1)
        view.set_viewport_position((0.0, y), True)
        return True

    def scroll_ratio(self, handle: SurfaceHandle) -> float:
        """Where the surface is scrolled to, as a fraction of its own height.

        A fraction rather than a pixel because the document that comes back to
        this surface will have been laid out again at whatever width and zoom
        the pane has by then; the pixel would put it somewhere else. It is the
        same reason `navigate` works in ratios.
        """
        view = self._view(handle)
        if view is None:
            return 0.0
        height = view.layout_extent()[1]
        return view.viewport_position()[1] / height if height else 0.0

    def restore_scroll(self, handle: SurfaceHandle, ratio: float) -> None:
        """Put a document back where it was, once minihtml has laid it out.

        There is no "layout finished" event, and `layout_extent` straight after
        `PhantomSet.update` can still describe the phantom that was there
        before, so the read has to happen on a later tick. The document appears
        at the top for that one frame.
        """
        if ratio <= 0.0:
            return

        def restore() -> None:
            view = self._view(handle)
            if view is None:
                return
            height = view.layout_extent()[1]
            if height:
                view.set_viewport_position((0.0, height * ratio), False)

        sublime.set_timeout(restore, 0)

    def move(self, handle: SurfaceHandle, group: int) -> None:
        window, view = self._window_view(handle)
        if view is not None:
            window.set_view_index(view, group, len(window.views_in_group(group)))

    def focus(self, handle: SurfaceHandle) -> None:
        _, view = self._window_view(handle)
        if view is not None:
            view.window().focus_view(view)

    def close(self, handle: SurfaceHandle) -> None:
        view = self._view(handle)
        self._phantoms.pop(handle.id, None)
        self._ratios.pop(handle.id, None)
        self._navigators.pop(handle.id, None)
        self._html.pop(handle.id, None)
        if view is not None:
            view.settings().erase(OWNER_KEY)
            view.settings().erase(ROLE_KEY)
            view.close()

    def is_alive(self, handle: SurfaceHandle) -> bool:
        return self._view(handle) is not None

    def group_of(self, handle: SurfaceHandle):
        window, view = self._window_view(handle)
        return window.get_view_index(view)[0] if view is not None else None

    def set_title(self, handle: SurfaceHandle, title: str) -> None:
        view = self._view(handle)
        if view is not None:
            view.set_name(title)

    def live_handles(self, window):
        return [
            SurfaceHandle(self.name, view.id(), window.id())
            for view in window.views()
            if view.settings().has(OWNER_KEY)
        ]

    def owner_of(self, sheet_or_view):
        if sheet_or_view is None:
            return None
        view = sheet_or_view.view() if hasattr(sheet_or_view, "view") else sheet_or_view
        return view.settings().get(OWNER_KEY) if view is not None else None

    def role_of(self, sheet_or_view):
        if sheet_or_view is None:
            return None
        view = sheet_or_view.view() if hasattr(sheet_or_view, "view") else sheet_or_view
        return view.settings().get(ROLE_KEY) if view is not None else None

    def _window(self, window_id: int):
        return next(
            (window for window in sublime.windows() if window.id() == window_id), None
        )

    def _view(self, handle: SurfaceHandle):
        window = self._window(handle.window_id)
        return (
            next((view for view in window.views() if view.id() == handle.id), None)
            if window is not None
            else None
        )

    def _window_view(self, handle: SurfaceHandle):
        window = self._window(handle.window_id)
        return window, self._view(handle)
