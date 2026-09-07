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
        record=None,
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
        # What this window leaves behind for the process after it: the groups
        # (written by the layout owner) and the document on them. See ADR 0018.
        self.record = record

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

    def _create(self, window, source) -> PreviewSession:
        """A document the window can show. It has no surface of its own."""
        source_group, _ = window.get_view_index(source)
        session = self.manager.new_session(
            window.id(),
            source.buffer_id(),
            source.sheet().id(),
            source_group,
            self._source_name(source),
        )
        session.settings = self.settings_provider()
        session.theme = self.theme_provider(source)
        self.theme_observer(source, session.id)
        session.base_path = self._base_path(source, window)
        session.state = SessionState.RENDERING
        self.scheduler.request_render(session.id, "open")
        return session

    def _open_surface(
        self, window, stage, source_group: int, focus: bool, group: Optional[int] = None
    ) -> None:
        """Make the window's one preview surface, in the group its mode wants.

        `group` names a pane that is already there -- the one a previous
        process left behind, on the restore path -- and is adopted rather than
        split off, so that it is released and collapsed like any other.
        """
        if group is not None:
            self.layout_owner.adopt(window, group, GroupRole.PREVIEW, stage.id)
        elif stage.mode == PreviewMode.SIDE_BY_SIDE:
            group = self.layout_owner.acquire(
                window, source_group, GroupRole.PREVIEW, stage.id
            )
        else:
            group = source_group
        # `new_file` focuses the view it makes, so a surface the user did not
        # ask for has to put the focus back where it found it.
        was_focused = None if focus else window.active_view()
        stage.surface = self.backend.create(window, group, "Preview", stage.id)
        self.backend.set_role(stage.surface, "preview")
        if focus:
            self.backend.focus(stage.surface)
        elif was_focused is not None:
            window.focus_view(was_focused)

    def show(self, stage, session: PreviewSession) -> None:
        """Put a document on the stage.

        The manager decides which document; this paints it. Everything the
        surface carries belongs to the document going on it -- the title, the
        heading ratios navigation uses, the colour scheme -- so all of it is
        reasserted here rather than at creation.
        """
        outgoing = self.manager.get(stage.showing) if stage.showing else None
        if outgoing is not None and stage.surface is not None:
            stage.scroll[outgoing.id] = self.backend.scroll_ratio(stage.surface)
        stage.showing = session.id
        if stage.surface is None or not self.backend.is_alive(stage.surface):
            return
        self.backend.set_title(
            stage.surface, "Preview: {}".format(session.source_name)
        )
        document = session.last_document
        self.backend.set_heading_ratios(
            stage.surface,
            {head.slug: head.position_ratio for head in document.headings}
            if document is not None
            else {},
        )
        self._paint(stage, session, document.body_html if document else "")
        self.backend.restore_scroll(stage.surface, stage.scroll.get(session.id, 0.0))
        self._remember(stage, session)

    def _stage_focused(self, window, stage) -> bool:
        """True when the active view is the stage's own surface."""
        if stage is None or stage.surface is None:
            return False
        return self._active_view_id(window.active_sheet()) == stage.surface.id

    def open_side_by_side(self, window, source=None) -> None:
        self.reconcile(window)
        stage = self.manager.stage(window.id())
        if source is None and self._stage_focused(window, stage):
            # Asked for from inside the preview, and with no document named:
            # the one on it is the one that was meant.
            if stage.mode != PreviewMode.SIDE_BY_SIDE:
                self.switch_mode(stage, PreviewMode.SIDE_BY_SIDE)
            else:
                self.backend.focus(stage.surface)
            return
        source = source or window.active_view()
        if not self._is_markdown(source):
            return
        session = self.manager.for_source(
            window.id(), source.buffer_id()
        ) or self._create(window, source)
        if stage is None:
            stage = self.manager.open_stage(window.id(), PreviewMode.SIDE_BY_SIDE)
            source_group, _ = window.get_view_index(source)
            self._open_surface(window, stage, source_group, focus=True)
            self.show(stage, session)
            return
        if stage.mode != PreviewMode.SIDE_BY_SIDE:
            self.switch_mode(stage, PreviewMode.SIDE_BY_SIDE)
        self.show(stage, session)
        self.backend.focus(stage.surface)

    def toggle_full_screen(self, window) -> None:
        self.reconcile(window)
        stage = self.manager.stage(window.id())
        source = window.active_view()
        if stage is None:
            if not self._is_markdown(source):
                return
            stage = self.manager.open_stage(window.id(), PreviewMode.FULL_SCREEN)
            session = self.manager.for_source(
                window.id(), source.buffer_id()
            ) or self._create(window, source)
            source_group, _ = window.get_view_index(source)
            self._open_surface(window, stage, source_group, focus=True)
            self.show(stage, session)
            return
        if stage.mode == PreviewMode.SIDE_BY_SIDE:
            self.switch_mode(stage, PreviewMode.FULL_SCREEN)
            return
        if self._stage_focused(window, stage):
            # The preview stands in for the source in this mode, so the second
            # press from inside it is how the user gets their file back.
            session = self.manager.get(stage.showing) if stage.showing else None
            back_to = self._find_source(session) if session else None
            self.manager.close_preview(window.id())
            if back_to is not None:
                window.focus_view(back_to)
        elif stage.surface is not None:
            self.backend.focus(stage.surface)

    def switch_mode(self, stage, mode: PreviewMode) -> None:
        if stage.mode == mode or stage.surface is None:
            return
        window = self.manager.window_for_id(stage.window_id)
        if window is None:
            return
        session = self.manager.get(stage.showing) if stage.showing else None
        source_group = self._source_group(window, session, stage)
        self.backend.move(stage.surface, source_group)
        self.layout_owner.release_all(window, stage.id, restore=True)
        if mode == PreviewMode.SIDE_BY_SIDE:
            group = self.layout_owner.acquire(
                window, source_group, GroupRole.PREVIEW, stage.id
            )
            self.backend.move(stage.surface, group)
        stage.mode = mode
        self.backend.focus(stage.surface)
        if session is not None:
            self.represent(session)

    def _source_group(self, window, session, stage) -> int:
        """Where the showing document's own view is, read live.

        The number recorded when the session opened goes stale the moment the
        user drags the source tab to another group.
        """
        source = self._find_source(session) if session is not None else None
        if source is not None:
            group, _ = window.get_view_index(source)
            return group
        return session.source_group if session is not None else 0

    def _paint(self, stage, session: PreviewSession, body_html: str) -> None:
        """Repaint the stage, reasserting the source's colour scheme first.

        The scheme has to travel with every paint rather than being set once at
        creation: `markdownediting: select color scheme` moves it under a
        preview that is already open.
        """
        if stage.surface is None:
            return
        self.backend.apply_theme(stage.surface, session.theme)
        self.backend.update(
            stage.surface,
            represent(body_html, session.theme, stage.zoom, self.base_css),
        )

    def _showing_stage(self, session: PreviewSession):
        """The stage this document is on, or None while it is not on one.

        Everything that paints goes through here. A hidden document still
        renders -- an edit from Find in Files, a reload from disk, a settings
        change -- and its result must not land on a surface showing something
        else.
        """
        stage = self.manager.stage(session.window_id)
        return stage if stage is not None and stage.is_showing(session.id) else None

    def present(self, session: PreviewSession, document: PreviewDocument) -> None:
        stage = self._showing_stage(session)
        if stage is not None and self.backend.is_alive(stage.surface):
            self.backend.set_heading_ratios(
                stage.surface,
                {head.slug: head.position_ratio for head in document.headings},
            )
            self._paint(stage, session, document.body_html)
        if self.panel is not None:
            self.panel.document_rendered(
                session.window_id, session.source_buffer_id, document
            )

    def present_error(
        self, session: PreviewSession, diagnostic: DiagnosticStage, message: str
    ) -> None:
        stage = self._showing_stage(session)
        if stage is None:
            return
        previous = session.last_document.body_html if session.last_document else ""
        self._paint(stage, session, "{}{}".format(
            error_card(diagnostic, message), previous
        ))

    def represent(self, session: PreviewSession) -> None:
        stage = self._showing_stage(session)
        if stage is not None and session.last_document is not None:
            self._paint(stage, session, session.last_document.body_html)

    def adjust_zoom(self, window, delta: float = 0.0, reset: bool = False) -> None:
        stage = self.manager.stage(window.id())
        if stage is None or self._session_for_active(window) is None:
            return
        # Zoom belongs to the pane, not to the document. With a surface each it
        # was per document and jumped every time you switched files.
        stage.zoom = 1.0 if reset else max(0.5, min(3.0, stage.zoom + delta))
        session = self.manager.get(stage.showing) if stage.showing else None
        if session is not None:
            self.represent(session)
            self._remember(stage, session)

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
        if session is None or session.last_document is None:
            return False
        stage = self._showing_stage(session)
        if stage is None or not any(
            heading.slug == slug for heading in session.last_document.headings
        ):
            return False
        return self.backend.navigate(stage.surface, slug)

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
            stage = self._showing_stage(session)
            if stage is not None:
                self.backend.set_title(
                    stage.surface, "Preview: {}".format(session.source_name)
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

    def _remember(self, stage, session: PreviewSession) -> None:
        """Keep the record's half of the story current: what is on the stage.

        Only into a record that already has groups in it. A full-screen
        preview owns no group, so it leaves nothing behind and must not start
        a record of its own -- there would be no pane to restore into. A
        document with no file of its own records `None`, which is honest: an
        unsaved buffer cannot be found again by name after a restart, and the
        pane it was in is tidied away instead.
        """
        window = self.manager.window_for_id(stage.window_id)
        if window is None or self.record is None:
            return
        source = self._find_source(session)
        self.record.update_existing(
            window,
            document=source.file_name() if source is not None else None,
            zoom=stage.zoom,
        )

    def restore(self, window) -> bool:
        """Put the preview back into the pane a previous process left for it.

        The other half of ADR 0018. The layout of a window outlives the process
        that made it and the preview in it does not, so a restart used to leave
        blank panes; this fills them again with what was in them -- the same
        document, in the same pane, at the same zoom -- and falls back to
        `reclaim`, which takes the panes away, whenever it cannot.

        It cannot when the document is not open in the window any more, when it
        was an unsaved buffer with no name to find it by, or when only a panel
        was recorded and the document to outline is gone. Doing nothing at all
        is the answer while a group still holds a sheet: a restored window has
        not settled yet, and the sweep runs again on the next activation.
        """
        if self.manager.stage(window.id()) is not None or self.record is None:
            return False
        free = self.layout_owner.free_groups(window)
        if not free:
            return False
        source = self._recorded_source(window, self.record.read(window).get("document"))
        if source is not None and source.is_loading():
            # Sublime has the file but not its syntax yet, so there is no
            # telling whether it is Markdown. Come back on the next sweep.
            return False
        if source is None or not self._is_markdown(source):
            return self.layout_owner.reclaim(window)
        source_group, _ = window.get_view_index(source)
        preview_group = free.get(GroupRole.PREVIEW)
        panel_group = free.get(GroupRole.PANEL)
        restored = False
        if preview_group is not None:
            stage = self.manager.open_stage(window.id(), PreviewMode.SIDE_BY_SIDE)
            # Before the render: the zoom is part of what the surface is
            # measured and laid out for, not something applied to it after.
            stage.zoom = self._recorded_zoom(window)
            session = self.manager.for_source(
                window.id(), source.buffer_id()
            ) or self._create(window, source)
            # The focus stays on whatever Sublime restored it to. A preview
            # that steals it on startup would be worse than the blank pane.
            self._open_surface(
                window, stage, source_group, focus=False, group=preview_group
            )
            self.show(stage, session)
            restored = True
        if panel_group is not None and self.panel is not None:
            restored = self.panel.restore(window, source, panel_group) or restored
        return restored or self.layout_owner.reclaim(window)

    def _recorded_source(self, window, path):
        """The view the record names, if the window still has it open."""
        if not isinstance(path, str) or not path:
            return None
        return next(
            (view for view in window.views() if view.file_name() == path), None
        )

    def _recorded_zoom(self, window) -> float:
        zoom = self.record.read(window).get("zoom")
        if not isinstance(zoom, (int, float)) or isinstance(zoom, bool):
            return 1.0
        return max(0.5, min(3.0, float(zoom)))

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

    def follow_focus(self, view) -> None:
        """Put the focused document on the window's preview.

        One surface, so this is the whole of "which document am I previewing".
        A document the window has never rendered gets a session here; one it
        has is simply shown again, which costs a repaint and no render.
        """
        window = view.window()
        if window is None or not self._is_markdown(view):
            return
        stage = self.manager.stage(window.id())
        if stage is None:
            return
        # `restore_scroll` and `focus` both move the focus about, and Sublime
        # activates views on the way past. Only the view the window has come
        # to rest on decides what the preview shows.
        active = window.active_view()
        if active is None or active.id() != view.id():
            return
        session = self.manager.for_source(window.id(), view.buffer_id())
        if session is None:
            session = self._create(window, view)
        self.manager.show(session)

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
