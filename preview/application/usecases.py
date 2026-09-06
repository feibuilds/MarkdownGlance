import os.path
from typing import Callable, Optional

from ..assets.math import formula_appearance
from ..assets.mermaid import diagram_appearance
from ..domain.contracts import (
    AssetKind,
    DiagnosticStage,
    PreviewDocument,
    PreviewMode,
    RenderSettings,
    ThemeSnapshot,
)
from ..domain.paths import HOST
from ..renderer.errors import error_card
from ..renderer.stylesheet import represent
from .ports import GroupRole
from .session import CloseCause, PreviewSession, SessionState


def _has_asset(document: Optional[PreviewDocument], kind: AssetKind) -> bool:
    return document is not None and any(
        key.kind == kind for key in document.asset_dependencies
    )


def _baked_assets_stale(
    document: Optional[PreviewDocument], old: ThemeSnapshot, new: ThemeSnapshot
) -> bool:
    """Whether a theme change reaches an image the server coloured.

    A Mermaid diagram is baked for one background and a formula in one
    foreground; each is stale only when the part of the theme it can see has
    moved, and only when the document has one.
    """
    return (
        diagram_appearance(new) != diagram_appearance(old)
        and _has_asset(document, AssetKind.MERMAID)
    ) or (
        formula_appearance(new) != formula_appearance(old)
        and _has_asset(document, AssetKind.MATH)
    )


class UseCases:
    def __init__(
        self,
        manager,
        scheduler,
        backend,
        layout_owner,
        source_snapshot: Callable[[PreviewSession, int], object],
        settings_provider: Callable[[], RenderSettings],
        theme_provider: Callable[[object], ThemeSnapshot],
        theme_observer: Callable[[object, str], None],
        base_css: str,
        panel=None,
    ) -> None:
        self.manager = manager
        self.scheduler = scheduler
        self.backend = backend
        self.layout_owner = layout_owner
        self.source_snapshot = source_snapshot
        self.settings_provider = settings_provider
        self.theme_provider = theme_provider
        self.theme_observer = theme_observer
        self.base_css = base_css
        # The panel beside the preview. It owns its own surface and its own
        # lifetime; a render only hands it the headings it produced.
        self.panel = panel

    def _is_markdown(self, view) -> bool:
        return bool(view and view.match_selector(0, "text.html.markdown"))

    def _source_name(self, view) -> str:
        return view.name() or os.path.basename(view.file_name() or "") or "Untitled"

    def _base_path(self, view, window) -> Optional[str]:
        if view.file_name():
            return os.path.dirname(view.file_name())
        folders = window.folders() if window is not None else []
        return HOST.normalise(folders[0]) if folders else None

    def _active_view_id(self, sheet) -> Optional[int]:
        # A sheet carries its own id, distinct from the id of the view inside
        # it. Surfaces are keyed by view id, so always take the sheet's view.
        view = sheet.view() if sheet is not None else None
        return view.id() if view is not None else None

    def _session_for_active(self, window) -> Optional[PreviewSession]:
        sheet = window.active_sheet()
        if sheet is not None:
            view = sheet.view()
            if view is not None:
                session = self.manager.for_surface(view.id())
                if session is not None:
                    return session
                return self.manager.for_source(window.id(), view.buffer_id())
        return None

    def _session_for_action_token(self, window, token: str) -> Optional[PreviewSession]:
        if not token:
            return None
        return next(
            (
                session
                for session in self.manager.sessions_in(window.id())
                if session.action_token == token
            ),
            None,
        )

    def _create(self, window, source, mode: PreviewMode) -> PreviewSession:
        source_group, _ = window.get_view_index(source)
        session = self.manager.new_session(
            window.id(),
            source.buffer_id(),
            source.sheet().id(),
            source_group,
            self._source_name(source),
            mode,
        )
        session.settings = self.settings_provider()
        session.theme = self.theme_provider(source)
        self.theme_observer(source, session.id)
        session.base_path = self._base_path(source, window)
        group = source_group
        if mode == PreviewMode.SIDE_BY_SIDE:
            group = self.layout_owner.acquire(
                window, source_group, GroupRole.PREVIEW, session.id
            )
        session.preview_surface = self.backend.create(
            window, group, "Preview: {}".format(session.source_name), session.id
        )
        # Before anything is painted, so the empty surface never shows in the
        # global scheme while the first render is still on the pool.
        self.backend.apply_theme(session.preview_surface, session.theme)
        self.backend.set_role(session.preview_surface, "preview")
        self.manager.bind_surfaces(session)
        session.state = SessionState.RENDERING
        self.backend.focus(session.preview_surface)
        self.scheduler.request_render(session.id, "open")
        return session

    def open_side_by_side(self, window, source=None) -> None:
        self.reconcile(window)
        source = source or window.active_view()
        if not self._is_markdown(source):
            return
        existing = self.manager.for_source(window.id(), source.buffer_id())
        if existing is not None:
            if existing.mode != PreviewMode.SIDE_BY_SIDE:
                self.switch_mode(existing, PreviewMode.SIDE_BY_SIDE)
            elif existing.preview_surface is not None:
                self.backend.focus(existing.preview_surface)
            return
        self._create(window, source, PreviewMode.SIDE_BY_SIDE)

    def toggle_full_screen(self, window) -> None:
        self.reconcile(window)
        session = self._session_for_active(window)
        if session is None:
            source = window.active_view()
            if self._is_markdown(source):
                self._create(window, source, PreviewMode.FULL_SCREEN)
            return
        active = window.active_sheet()
        if session.mode == PreviewMode.SIDE_BY_SIDE:
            self.switch_mode(session, PreviewMode.FULL_SCREEN)
        elif (
            session.preview_surface is not None
            and self._active_view_id(active) == session.preview_surface.id
        ):
            source = self._find_source(session)
            self.backend.close(session.preview_surface)
            self.manager.close(session, CloseCause.PREVIEW_CLOSED_BY_USER)
            if source is not None:
                window.focus_view(source)
        elif session.preview_surface is not None:
            self.backend.focus(session.preview_surface)

    def switch_mode(self, session: PreviewSession, mode: PreviewMode) -> None:
        if session.mode == mode or session.preview_surface is None:
            return
        window = self.manager.window_for_id(session.window_id)
        if window is None:
            return
        session.state = SessionState.MOVING
        self.backend.move(session.preview_surface, session.source_group)
        self.layout_owner.release_all(window, session.id, restore=True)

        if mode == PreviewMode.SIDE_BY_SIDE:
            preview_group = self.layout_owner.acquire(
                window, session.source_group, GroupRole.PREVIEW, session.id
            )
            self.backend.move(session.preview_surface, preview_group)
        session.mode = mode
        self.backend.focus(session.preview_surface)
        session.state = (
            SessionState.VISIBLE if session.last_document else SessionState.RENDERING
        )
        self.represent(session)

    def _paint(self, session: PreviewSession, surface, html: str) -> None:
        """Repaint a surface, reasserting the source's colour scheme first.

        The scheme has to travel with every paint rather than being set once at
        creation: `markdownediting: select color scheme` moves it under a
        preview that is already open.
        """
        self.backend.apply_theme(surface, session.theme)
        self.backend.update(surface, html)

    def present(self, session: PreviewSession, document: PreviewDocument) -> None:
        if session.preview_surface is None or not self.backend.is_alive(
            session.preview_surface
        ):
            return
        ratios = {heading.slug: heading.position_ratio for heading in document.headings}
        self.backend.set_heading_ratios(session.preview_surface, ratios)
        self._paint(
            session,
            session.preview_surface,
            represent(document.body_html, session.theme, session.zoom, self.base_css),
        )
        if self.panel is not None:
            self.panel.document_rendered(
                session.window_id, session.source_buffer_id, document
            )

    def present_error(
        self, session: PreviewSession, stage: DiagnosticStage, message: str
    ) -> None:
        if session.preview_surface is None:
            return
        previous = session.last_document.body_html if session.last_document else ""
        body = "{}{}".format(error_card(stage, message), previous)
        self._paint(
            session,
            session.preview_surface,
            represent(body, session.theme, session.zoom, self.base_css),
        )

    def represent(self, session: PreviewSession) -> None:
        if session.last_document is not None:
            self._paint(
                session,
                session.preview_surface,
                represent(
                    session.last_document.body_html,
                    session.theme,
                    session.zoom,
                    self.base_css,
                ),
            )

    def adjust_zoom(self, window, delta: float = 0.0, reset: bool = False) -> None:
        session = self._session_for_active(window)
        if session is None:
            return
        session.zoom = 1.0 if reset else max(0.5, min(3.0, session.zoom + delta))
        self.represent(session)

    def scroll_preview(self, window_id: int, buffer_id: int, slug: str) -> bool:
        """Scroll a document's preview to one heading. The panel's click path."""
        return self._scroll(self.manager.for_source(window_id, buffer_id), slug)

    def navigate_for_surface(self, surface_id: int, slug: str) -> None:
        """A `#slug` link clicked inside the preview body."""
        session = self.manager.for_surface(surface_id)
        if self._scroll(session, slug) and self.panel is not None:
            self.panel.heading_shown(
                session.window_id, session.source_buffer_id, slug
            )

    def _scroll(self, session: Optional[PreviewSession], slug: str) -> bool:
        if (
            session is None
            or session.preview_surface is None
            or session.last_document is None
            or not any(
                heading.slug == slug for heading in session.last_document.headings
            )
        ):
            return False
        return self.backend.navigate(session.preview_surface, slug)

    def open_relative(self, window, token: str, path: int) -> None:
        session = self._session_for_action_token(window, token)
        if (
            session is None
            or session.last_document is None
            or not isinstance(path, int)
            or path < 0
            or path >= len(session.last_document.links)
        ):
            return
        target = HOST.expand(session.last_document.links[path])
        if session.base_path is None or HOST.is_absolute(target):
            return
        window.open_file(HOST.resolve(session.base_path, target))

    def source_modified(self, view) -> None:
        window = view.window()
        session = (
            self.manager.for_source(window.id(), view.buffer_id()) if window else None
        )
        if session is not None:
            self.scheduler.request_render(session.id, "edit")

    def source_saved(self, view) -> None:
        window = view.window()
        session = (
            self.manager.for_source(window.id(), view.buffer_id()) if window else None
        )
        if session is not None:
            session.base_path = self._base_path(view, window)
            session.source_name = self._source_name(view)
            if session.preview_surface:
                self.backend.set_title(
                    session.preview_surface, "Preview: {}".format(session.source_name)
                )
            self.scheduler.request_render(session.id, "save")

    def source_closed(self, view) -> None:
        window = view.window()
        session = (
            self.manager.for_source(window.id(), view.buffer_id()) if window else None
        )
        if session is not None:
            self.manager.close(session, CloseCause.SOURCE_CLOSED)

    def surface_closed(self, view) -> None:
        self.manager.surface_closed(view.id())

    def window_closed(self, window) -> None:
        self.manager.close_window(window.id())

    def reconcile(self, window) -> None:
        self.manager.reconcile(window)

    def _find_source(self, session: PreviewSession):
        window = self.manager.window_for_id(session.window_id)
        if window is None:
            return None
        return next(
            (
                view
                for view in window.views()
                if view.buffer_id() == session.source_buffer_id
            ),
            None,
        )

    def settings_changed(self, render_required: bool, policy_changed: bool) -> None:
        settings = self.settings_provider()
        for session in list(self.manager._by_id.values()):
            session.settings = settings
            if render_required or policy_changed:
                self.scheduler.request_render(session.id, "settings")

    def reveal_preview(self, view) -> None:
        """Bring the focused document's preview to the front.

        Every document previewed in a window stacks its preview in one group,
        so without this the tab left in front is whichever was opened last, and
        it stays there while the user reads a different file. The panel beside
        it follows the focus on its own; see `PanelController.focus_changed`.
        """
        window = view.window()
        if window is None:
            return
        # `reveal` focuses a group, a view, and the previous group back, and
        # each of those makes Sublime activate a view the user never chose --
        # starting with whatever was already at the front of the group being
        # focused. Those activations arrive here a tick later, and each would
        # reveal a *different* document's preview, which reveals more: the two
        # documents take turns pulling their tabs forward and the window never
        # settles. Only the view the window has come to rest on moves a tab.
        active = window.active_view()
        if active is None or active.id() != view.id():
            return
        session = self.manager.for_surface(view.id()) or self.manager.for_source(
            window.id(), view.buffer_id()
        )
        if session is None or session.preview_surface is None:
            return
        if session.preview_surface.id == view.id():
            return
        # In Full Screen the preview is a tab in the source's own group.
        # Bringing it forward there would hide the file the user has just
        # clicked, and the two would take turns hiding each other.
        group, _ = window.get_view_index(view)
        if self.backend.group_of(session.preview_surface) == group:
            return
        self.backend.reveal(session.preview_surface)

    def theme_changed(self, view) -> None:
        window = view.window()
        session = (
            self.manager.for_source(window.id(), view.buffer_id()) if window else None
        )
        if session is not None:
            theme = self.theme_provider(view)
            if theme == session.theme:
                # `on_activated` asks on every focus change, and the answer is
                # almost always the same one. Repainting anyway costs a full
                # minihtml layout of the whole document.
                return
            stale_images = _baked_assets_stale(
                session.last_document, session.theme, theme
            )
            session.theme = theme
            self.represent(session)
            if stale_images:
                # A repaint recolours the document, but not a Mermaid diagram
                # or a formula: those are images the server baked for one
                # palette, and their URLs are fixed when the Markdown is
                # parsed. Without a render the document would come back in the
                # new palette carrying images in the old one.
                self.scheduler.request_render(session.id, "theme")
