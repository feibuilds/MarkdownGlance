"""The one panel beside a Markdown document.

It shows the *source outline* while the source has the focus and the rendered
*table of contents* while the preview has it: one group, one tab, one surface,
switched by a repaint rather than by moving anything on screen. They used to be
two surfaces in two groups, which cost a document four editor groups and left
whichever list you were not using in front of you.

The panel is deliberately not part of `PreviewSession`: it needs no render, no
asset resolution and no generation bookkeeping, and it has to work for a file
that has never been previewed. It owns its own surfaces, keyed by source
buffer, and everything it needs from a view arrives as an injected callable so
that this layer stays free of the Sublime API. The preview pushes each rendered
document in through `document_rendered`; nothing here reaches back for one.
"""

import os.path
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

from ..domain.contracts import Heading, SourceHeading, ThemeSnapshot
from ..domain.ids import new_action_token, new_session_id
from ..renderer.measure import outline_width_px, toc_width_px
from ..renderer.outline import active_ordinal, build_outline, scan_outline
from ..renderer.stylesheet import represent, root_font_px
from ..renderer.toc import build_toc, toc_required
from .ports import GroupRole, SurfaceHandle


@dataclass
class PanelSession:
    id: str
    window_id: int
    source_buffer_id: int
    surface: SurfaceHandle
    source_name: str
    action_token: str
    # The source scan, and the heading the caret sits under.
    headings: Tuple[SourceHeading, ...] = ()
    active: Optional[int] = None
    # The last rendered document's headings, and the one last navigated to.
    # Empty whenever no preview is open for this buffer.
    document: Tuple[Heading, ...] = ()
    active_slug: Optional[str] = None
    # Which half is on screen. Only ever true while `document` has entries.
    showing_preview: bool = False
    # True when a render opened the panel rather than the user asking for it.
    # Such a panel closes again when the document stops asking for one; a panel
    # the user opened by hand stays until they close it.
    automatic: bool = False
    zoom: float = 1.0
    layout_groups: Set[int] = field(default_factory=set)
    debounce_handle: object = None


class PanelController:
    def __init__(
        self,
        backend,
        layout_owner,
        clock,
        window_for_id: Callable[[int], object],
        settings_provider,
        theme_provider,
        read_source: Callable[[object], str],
        caret_row: Callable[[object], int],
        reveal_line: Callable[[object, int], None],
        base_css: str,
        preview_for_surface: Callable[[int], object] = lambda surface_id: None,
        scroll_preview: Callable[[int, int, str], None] = lambda *unused: None,
    ) -> None:
        self.backend = backend
        self.layout_owner = layout_owner
        self.clock = clock
        self.window_for_id = window_for_id
        self.settings_provider = settings_provider
        self.theme_provider = theme_provider
        self.read_source = read_source
        self.caret_row = caret_row
        self.reveal_line = reveal_line
        self.base_css = base_css
        self.preview_for_surface = preview_for_surface
        self.scroll_preview = scroll_preview
        self._by_source: Dict[Tuple[int, int], PanelSession] = {}
        self._by_surface: Dict[int, PanelSession] = {}
        # Buffers whose panel the user closed. A render must not put it back;
        # only the preview closing, or the user asking again, clears one.
        self._dismissed: Set[Tuple[int, int]] = set()

    # -- lookup ---------------------------------------------------------

    def for_source(self, window_id: int, buffer_id: int) -> Optional[PanelSession]:
        return self._by_source.get((window_id, buffer_id))

    def for_surface(self, surface_id: int) -> Optional[PanelSession]:
        return self._by_surface.get(surface_id)

    def owns_surface(self, surface_id: int) -> bool:
        return surface_id in self._by_surface

    def sessions_in(self, window_id: int) -> List[PanelSession]:
        return [
            panel
            for panel in self._by_source.values()
            if panel.window_id == window_id
        ]

    # -- opening and closing --------------------------------------------

    def _is_markdown(self, view) -> bool:
        return bool(view and view.match_selector(0, "text.html.markdown"))

    def _source_name(self, view) -> str:
        return view.name() or os.path.basename(view.file_name() or "") or "Untitled"

    def _active_view(self, window):
        sheet = window.active_sheet() if window is not None else None
        return sheet.view() if sheet is not None else None

    def toggle(self, window, source=None) -> None:
        """Zed's toggle: open and focus, focus, then close on the third press."""
        active = self._active_view(window)
        focused = self.for_surface(active.id()) if active is not None else None
        if focused is not None:
            source = self._source_view(focused, window)
            self.close(focused, window)
            self._dismissed.add((focused.window_id, focused.source_buffer_id))
            if source is not None:
                window.focus_view(source)
            return
        source = source or active
        if source is None:
            return
        # Asked for from the preview: the panel belongs to the document behind
        # it, not to the surface.
        session = self.preview_for_surface(source.id())
        if session is not None:
            existing = self.for_source(window.id(), session.source_buffer_id)
            if existing is not None:
                self.backend.focus(existing.surface)
                return
            source = self._source_for_buffer(window, session.source_buffer_id)
            if source is None:
                return
        existing = self.for_source(window.id(), source.buffer_id())
        if existing is not None:
            self.backend.focus(existing.surface)
            return
        if not self._is_markdown(source):
            return
        panel = self._open(window, source, automatic=False)
        if panel is not None:
            self.backend.focus(panel.surface)

    def _open(self, window, source, automatic: bool) -> Optional[PanelSession]:
        source_group, _ = window.get_view_index(source)
        session_id = new_session_id()
        key = (window.id(), source.buffer_id())
        self._dismissed.discard(key)
        # Scanned before the split, so the group is the right width the moment
        # it appears rather than snapping narrower on the first repaint.
        headings = scan_outline(self.read_source(source))
        group = self.layout_owner.acquire_panel(
            window,
            source_group,
            session_id,
            self._width(headings, (), False, 1.0),
        )
        surface = self.backend.create(
            window, group, self._title(self._source_name(source)), session_id
        )
        # Before the first paint, so the empty surface never shows in a scheme
        # the source does not use.
        self.backend.apply_theme(surface, self.theme_provider(source))
        self.backend.set_role(surface, "panel")
        panel = PanelSession(
            session_id,
            window.id(),
            source.buffer_id(),
            surface,
            self._source_name(source),
            new_action_token(),
            automatic=automatic,
        )
        if self.layout_owner.is_owned(window, group):
            panel.layout_groups.add(group)
        self._by_source[key] = panel
        self._by_surface[surface.id] = panel
        self.refresh(panel, source)
        return panel

    def _title(self, name: str) -> str:
        return "Contents: {}".format(name)

    def close(self, panel: PanelSession, window=None) -> None:
        self._forget(panel)
        if self.backend.is_alive(panel.surface):
            self.backend.close(panel.surface)
        self._release(panel, window)

    def _forget(self, panel: PanelSession) -> None:
        self.clock.cancel(panel.debounce_handle)
        panel.debounce_handle = None
        self._by_source.pop((panel.window_id, panel.source_buffer_id), None)
        self._by_surface.pop(panel.surface.id, None)

    def _release(self, panel: PanelSession, window=None, restore=True) -> None:
        window = window or self.window_for_id(panel.window_id)
        if window is None:
            return
        for group in sorted(panel.layout_groups, reverse=True):
            self.layout_owner.release(window, group, panel.id, restore=restore)
        panel.layout_groups.clear()

    def surface_closed(self, surface_id: int) -> bool:
        """True when the closed view was a panel this controller owned."""
        panel = self.for_surface(surface_id)
        if panel is None:
            return False
        self._forget(panel)
        self._dismissed.add((panel.window_id, panel.source_buffer_id))
        self._release(panel)
        return True

    def source_closed(self, view) -> None:
        window = view.window()
        panel = self.for_source(window.id(), view.buffer_id()) if window else None
        if panel is not None:
            self.close(panel, window)
        if window is not None:
            self._dismissed.discard((window.id(), view.buffer_id()))

    def close_window(self, window_id: int) -> None:
        for panel in self.sessions_in(window_id):
            self._forget(panel)
            if self.backend.is_alive(panel.surface):
                self.backend.close(panel.surface)

    def close_all(self) -> None:
        for panel in list(self._by_source.values()):
            self._forget(panel)
            if self.backend.is_alive(panel.surface):
                self.backend.close(panel.surface)

    def reconcile(self, window) -> None:
        """Drop panels whose surface the user closed behind our back."""
        live = {handle.id for handle in self.backend.live_handles(window)}
        for panel in self.sessions_in(window.id()):
            if panel.surface.id not in live:
                self._forget(panel)
                self._dismissed.add((panel.window_id, panel.source_buffer_id))
                self._release(panel, window)

    def settings_changed(self) -> None:
        """Repaint every panel, which is also what re-fits its group."""
        for panel in list(self._by_source.values()):
            source = self._source_view(panel)
            if not self._still_wanted(panel, source):
                self.close(panel)
                continue
            self._present(panel, source)

    # -- what the preview tells us ---------------------------------------

    def document_rendered(self, window_id: int, buffer_id: int, document) -> None:
        """A render finished: keep its headings, and open a panel if asked to.

        `enable_toc` and the two thresholds decide only whether a panel opens
        *by itself*. One the user opened by hand shows the table of contents
        whichever way those are set, because a panel that emptied half of
        itself on a focus change would be stranger than one that does not.
        """
        panel = self.for_source(window_id, buffer_id)
        headings = tuple(document.headings) if document is not None else ()
        window = self.window_for_id(window_id)
        # Read before anything is created: `new_file` focuses the view it
        # makes, so by the time a panel exists the window is looking at the
        # panel rather than at whatever asked for it.
        focused_preview = self._focus_is_preview(window, buffer_id)
        if panel is None:
            if not self._wants_automatic(window_id, buffer_id, headings):
                return
            source = (
                self._source_for_buffer(window, buffer_id)
                if window is not None
                else None
            )
            if source is None:
                return
            was_focused = self._active_view(window)
            panel = self._open(window, source, automatic=True)
            if panel is None:
                return
            # A panel nobody asked for must not take the caret with it.
            if was_focused is not None:
                window.focus_view(was_focused)
        had_document = bool(panel.document)
        panel.document = headings
        if panel.automatic and not self._still_wanted(panel, None, headings):
            self.close(panel)
            return
        if not headings:
            panel.showing_preview = False
        elif not had_document:
            # The panel has a table of contents for the first time -- it was
            # just opened, or the preview behind it was. Which half to show is
            # the focus's answer, and the focus is wherever opening the preview
            # left it, which is usually the preview itself.
            panel.showing_preview = focused_preview
        self._present(panel, self._source_view(panel))

    def _focus_is_preview(self, window, buffer_id: int) -> bool:
        """True when the window's focus is on this document's own preview."""
        active = self._active_view(window)
        if active is None:
            return False
        session = self.preview_for_surface(active.id())
        return session is not None and session.source_buffer_id == buffer_id

    def document_closed(self, window_id: int, buffer_id: int) -> None:
        """The preview went away: an automatic panel goes with it."""
        self._dismissed.discard((window_id, buffer_id))
        panel = self.for_source(window_id, buffer_id)
        if panel is None:
            return
        panel.document = ()
        panel.active_slug = None
        panel.showing_preview = False
        if panel.automatic:
            self.close(panel)
            return
        self._present(panel, self._source_view(panel))

    def _wants_automatic(self, window_id, buffer_id, headings) -> bool:
        settings = self.settings_provider()
        if not settings.enable_toc or (window_id, buffer_id) in self._dismissed:
            return False
        window = self.window_for_id(window_id)
        source = self._source_for_buffer(window, buffer_id) if window else None
        if source is None:
            return False
        return toc_required(
            len(self.read_source(source)),
            headings,
            settings.toc_minimum_length,
            settings.toc_minimum_headings,
        )

    def _still_wanted(self, panel: PanelSession, source, headings=None) -> bool:
        """False when a panel that opened by itself should close again."""
        if not panel.automatic:
            return True
        settings = self.settings_provider()
        if not settings.enable_toc:
            return False
        document = panel.document if headings is None else headings
        source = source or self._source_view(panel)
        if source is None:
            return True
        return toc_required(
            len(self.read_source(source)),
            document,
            settings.toc_minimum_length,
            settings.toc_minimum_headings,
        )

    # -- content ---------------------------------------------------------

    def refresh(self, panel: PanelSession, source) -> None:
        if source is None or not self.backend.is_alive(panel.surface):
            return
        panel.headings = scan_outline(self.read_source(source))
        panel.active = active_ordinal(panel.headings, self.caret_row(source))
        self._present(panel, source)

    def refresh_source(self, view) -> None:
        """Repaint now: the source was activated, so its theme may have moved."""
        window = view.window()
        panel = self.for_source(window.id(), view.buffer_id()) if window else None
        if panel is None:
            return
        self.refresh(panel, view)

    def refresh_for_source(self, view) -> None:
        """An edit landed; repaint after the configured settle delay."""
        window = view.window()
        panel = self.for_source(window.id(), view.buffer_id()) if window else None
        if panel is None:
            return
        self.clock.cancel(panel.debounce_handle)
        delay = max(1, self.settings_provider().update_delay_ms)
        panel.debounce_handle = self.clock.call_later(
            delay, lambda: self.refresh(panel, view)
        )

    def sync_caret(self, view) -> None:
        window = view.window()
        panel = self.for_source(window.id(), view.buffer_id()) if window else None
        if panel is None or not self.backend.is_alive(panel.surface):
            return
        active = active_ordinal(panel.headings, self.caret_row(view))
        if active == panel.active:
            return
        panel.active = active
        # The caret's heading is the outline's highlight; while the table of
        # contents is on screen there is nothing to repaint for.
        if not self._showing_preview(panel):
            self._present(panel, view)

    def source_renamed(self, view) -> None:
        window = view.window()
        panel = self.for_source(window.id(), view.buffer_id()) if window else None
        if panel is None:
            return
        name = self._source_name(view)
        if name != panel.source_name:
            panel.source_name = name
            self.backend.set_title(panel.surface, self._title(name))

    def focus_changed(self, view) -> None:
        """Show the half that belongs to the tab the window has settled on.

        The source's outline while the source has the focus, the rendered
        table of contents while the preview has it, and neither switched by
        anything the panel itself does.
        """
        window = view.window()
        if window is None:
            return
        # `reveal` focuses a group, a view and the previous group back, and
        # each of those activates a view the user never chose. Those arrive
        # here a tick later; acting on them makes two documents take turns
        # pulling their tabs forward. Only the settled view counts.
        active = window.active_view()
        if active is None or active.id() != view.id():
            return
        if self.owns_surface(view.id()):
            return
        session = self.preview_for_surface(view.id())
        if session is not None:
            panel = self.for_source(window.id(), session.source_buffer_id)
            showing = True
        else:
            panel = self.for_source(window.id(), view.buffer_id())
            showing = False
        if panel is None:
            return
        showing = showing and bool(panel.document)
        if showing != panel.showing_preview:
            panel.showing_preview = showing
            self._present(panel, self._source_view(panel, window))
        self.backend.reveal(panel.surface)

    def adjust_zoom(self, window, delta: float = 0.0, reset: bool = False) -> bool:
        active = self._active_view(window)
        panel = self.for_surface(active.id()) if active is not None else None
        if panel is None:
            return False
        panel.zoom = 1.0 if reset else max(0.5, min(3.0, panel.zoom + delta))
        self._present(panel, self._source_view(panel, window))
        return True

    def navigate(self, window, token: str, line=None, slug=None) -> None:
        panel = next(
            (
                candidate
                for candidate in self.sessions_in(window.id())
                if candidate.action_token == token
            ),
            None,
        )
        if panel is None:
            return
        if slug:
            heading = next(
                (item for item in panel.document if item.slug == slug), None
            )
            if heading is None:
                return
            self.scroll_preview(panel.window_id, panel.source_buffer_id, slug)
            panel.active_slug = slug
            self._present(panel, self._source_view(panel, window))
            return
        if not isinstance(line, int):
            return
        heading = next((item for item in panel.headings if item.line == line), None)
        if heading is None:
            return
        source = self._source_view(panel, window)
        if source is None:
            return
        self.reveal_line(source, line)
        panel.active = heading.ordinal
        self._present(panel, source)

    def _source_for_buffer(self, window, buffer_id: int):
        if window is None:
            return None
        return next(
            (view for view in window.views() if view.buffer_id() == buffer_id),
            None,
        )

    def _source_view(self, panel: PanelSession, window=None):
        window = window or self.window_for_id(panel.window_id)
        return self._source_for_buffer(window, panel.source_buffer_id)

    def _showing_preview(self, panel: PanelSession) -> bool:
        return panel.showing_preview and bool(panel.document)

    def _width(
        self,
        headings: Sequence[SourceHeading],
        document: Sequence[Heading],
        showing_preview: bool,
        zoom: float,
    ) -> float:
        """Pixels the panel wants, or 0.0 for the role's default share.

        Measured against whichever half is on screen: the two are different
        typefaces -- the outline is monospace and carries its `#` markers --
        so the group would be the wrong width for one of them otherwise.
        """
        if not self.settings_provider().auto_width:
            return 0.0
        rem_px = root_font_px(zoom)
        if showing_preview:
            return toc_width_px(document, rem_px)
        return outline_width_px(headings, rem_px)

    def _fit(self, panel: PanelSession) -> None:
        """Give the panel's group the width its entries need.

        `LayoutOwner.fit` decides whether the move is allowed, so a divider the
        user has dragged is never moved back.
        """
        window = self.window_for_id(panel.window_id)
        if window is None:
            return
        group = self.backend.group_of(panel.surface)
        if group is not None:
            self.layout_owner.fit(
                window,
                group,
                GroupRole.PANEL,
                self._width(
                    panel.headings,
                    panel.document,
                    self._showing_preview(panel),
                    panel.zoom,
                ),
            )

    def _present(self, panel: PanelSession, source) -> None:
        if not self.backend.is_alive(panel.surface):
            return
        if self._showing_preview(panel):
            html = build_toc(panel.document, panel.action_token, panel.active_slug)
        else:
            html = build_outline(panel.headings, panel.action_token, panel.active)
        theme = (
            self.theme_provider(source) if source is not None else ThemeSnapshot()
        )
        # The scheme goes on before the paint: minihtml resolves the phantom's
        # colour variables against the surface's own scheme, not the source's.
        self.backend.apply_theme(panel.surface, theme)
        self.backend.update(
            panel.surface,
            represent(html, theme, panel.zoom, self.base_css, panel=True),
        )
        self._fit(panel)
