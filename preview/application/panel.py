"""The one contents panel a window has.

It shows the *source outline* while a source has the focus and the rendered
*table of contents* while the preview has it, for whichever document the window
is on -- one group, one tab, one surface, switched by a repaint rather than by
moving anything on screen.

The split mirrors the preview's. A `PanelDocument` is what is known about one
Markdown buffer: the headings scanned out of it, the heading the caret sits
under, the headings its last render produced. A `PanelStage` is the pane those
are drawn in: the surface, which document is on it, which half, and the zoom.

The panel is deliberately not part of a `PreviewSession`: it needs no render,
no asset resolution and no generation bookkeeping, and it has to work for a
file that has never been previewed. Everything it needs from a view arrives as
an injected callable so that this layer stays free of the Sublime API, and the
preview pushes each rendered document in through `document_rendered`; nothing
here reaches back for one.
"""

import os.path
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Set, Tuple

from ..domain.contracts import Heading, SourceHeading, ThemeSnapshot
from ..domain.ids import new_action_token, new_session_id
from ..renderer.align import NOTHING, HeadingLinks, align
from ..renderer.measure import outline_width_px, toc_width_px
from ..renderer.outline import active_ordinal, build_outline, scan_outline
from ..renderer.stylesheet import represent, root_font_px
from ..renderer.toc import build_toc, toc_required
from .ports import GroupRole, SurfaceHandle


@dataclass
class PanelDocument:
    """What is known about one Markdown buffer, on screen or not."""

    window_id: int
    buffer_id: int
    source_name: str
    # The source scan, and the heading the caret sits under.
    headings: Tuple[SourceHeading, ...] = ()
    active: Optional[int] = None
    # The last render's headings, and the one last navigated to. Empty
    # whenever no preview is open for this buffer.
    document: Tuple[Heading, ...] = ()
    active_slug: Optional[str] = None
    # Which scanned heading is which rendered one, where the two agree. Kept
    # here rather than worked out per click: it is the same answer until one
    # of the two lists changes.
    links: HeadingLinks = NOTHING
    debounce_handle: object = None

    def realign(self) -> None:
        self.links = align(self.headings, self.document)


@dataclass
class PanelStage:
    id: str
    window_id: int
    surface: Optional[SurfaceHandle] = None
    # The buffer whose headings are on the surface.
    showing: Optional[int] = None
    # Which half. Only ever true while the showing document has a render.
    showing_preview: bool = False
    zoom: float = 1.0
    action_token: str = ""
    # True when a render opened the panel rather than the user asking for it.
    automatic: bool = False


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
        scroll_preview: Callable[[int, int, str], bool] = lambda *unused: False,
        record=None,
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
        # What the window leaves behind for the process after it. A window
        # whose only pane is the panel's has no preview to name the document,
        # so the panel names it. See ADR 0018.
        self.record = record
        self._stages: Dict[int, PanelStage] = {}
        self._documents: Dict[Tuple[int, int], PanelDocument] = {}
        # Windows whose panel the user closed. A render must not put it back;
        # only asking for one again clears it.
        self._dismissed: Set[int] = set()

    # -- lookup ---------------------------------------------------------

    def stage(self, window_id: int) -> Optional[PanelStage]:
        return self._stages.get(window_id)

    def owns_surface(self, surface_id: int) -> bool:
        return self._stage_for_surface(surface_id) is not None

    def _stage_for_surface(self, surface_id: int) -> Optional[PanelStage]:
        return next(
            (
                stage
                for stage in self._stages.values()
                if stage.surface is not None and stage.surface.id == surface_id
            ),
            None,
        )

    def document(self, window_id: int, buffer_id: int) -> Optional[PanelDocument]:
        return self._documents.get((window_id, buffer_id))

    def showing(self, stage: PanelStage) -> Optional[PanelDocument]:
        if stage.showing is None:
            return None
        return self._documents.get((stage.window_id, stage.showing))

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
        stage = self._stages.get(window.id())
        if stage is not None and active is not None and self.owns_surface(active.id()):
            back_to = self._source_for_buffer(window, stage.showing)
            self.close(window.id())
            self._dismissed.add(window.id())
            if back_to is not None:
                window.focus_view(back_to)
            return
        if stage is not None:
            self.backend.focus(stage.surface)
            return
        source = self._document_view(window, source or active)
        if not self._is_markdown(source):
            return
        stage = self._open(window, source, automatic=False)
        if stage is not None:
            self.backend.focus(stage.surface)

    def _document_view(self, window, view):
        """The Markdown source a view stands for: itself, or the document
        behind a preview surface."""
        if view is None:
            return None
        session = self.preview_for_surface(view.id())
        if session is not None:
            return self._source_for_buffer(window, session.source_buffer_id)
        return view

    def restore(self, window, source, group: int) -> bool:
        """Re-open the panel into the group a previous process left for it.

        Never automatic, whatever `enable_toc` says: a panel that was on screen
        when Sublime was closed is one the reader kept. See ADR 0018.
        """
        if self._stages.get(window.id()) is not None:
            return False
        return self._open(window, source, automatic=False, group=group) is not None

    def _open(
        self, window, source, automatic: bool, group: Optional[int] = None
    ) -> Optional[PanelStage]:
        source_group, _ = window.get_view_index(source)
        stage = PanelStage(
            new_session_id(),
            window.id(),
            action_token=new_action_token(),
            automatic=automatic,
        )
        self._dismissed.discard(window.id())
        record = self._record(window.id(), source)
        # Scanned before the split, so the group is the right width the moment
        # it appears rather than snapping narrower on the first repaint.
        record.headings = scan_outline(self.read_source(source))
        record.active = active_ordinal(record.headings, self.caret_row(source))
        record.realign()
        stage.showing = record.buffer_id
        stage.showing_preview = bool(record.document) and self._focus_is_preview(
            window, record.buffer_id
        )
        if group is None:
            group = self.layout_owner.acquire_panel(
                window, source_group, stage.id, self._width(stage, record)
            )
        else:
            # A group that is already in the window: adopted, not split off.
            self.layout_owner.adopt(window, group, GroupRole.PANEL, stage.id)
        # `new_file` focuses the view it makes. Only `toggle` wants that, and
        # it focuses the panel itself afterwards.
        was_focused = self._active_view(window)
        stage.surface = self.backend.create(
            window, group, self._title(record.source_name), stage.id
        )
        # Before the first paint, so the empty surface never shows in a scheme
        # the source does not use.
        self.backend.apply_theme(stage.surface, self.theme_provider(source))
        self.backend.set_role(stage.surface, "panel")
        self._stages[window.id()] = stage
        self._present(stage, source)
        if was_focused is not None:
            window.focus_view(was_focused)
        return stage

    def _record(self, window_id: int, source) -> PanelDocument:
        key = (window_id, source.buffer_id())
        record = self._documents.get(key)
        if record is None:
            record = PanelDocument(
                window_id, source.buffer_id(), self._source_name(source)
            )
            self._documents[key] = record
        return record

    def _title(self, name: str) -> str:
        return "Contents: {}".format(name)

    def close(self, window_id: int, restore: bool = True) -> None:
        stage = self._stages.pop(window_id, None)
        if stage is None:
            return
        for record in self._documents.values():
            if record.window_id == window_id:
                self.clock.cancel(record.debounce_handle)
                record.debounce_handle = None
        if stage.surface is not None and self.backend.is_alive(stage.surface):
            self.backend.close(stage.surface)
        window = self.window_for_id(window_id)
        if window is not None:
            self.layout_owner.release_all(window, stage.id, restore=restore)

    def surface_closed(self, surface_id: int) -> bool:
        """True when the closed view was the panel this controller owned."""
        stage = self._stage_for_surface(surface_id)
        if stage is None:
            return False
        stage.surface = None
        self._dismissed.add(stage.window_id)
        self.close(stage.window_id)
        return True

    def source_closed(self, view) -> None:
        window = view.window()
        if window is None:
            return
        record = self._documents.pop((window.id(), view.buffer_id()), None)
        if record is not None:
            self.clock.cancel(record.debounce_handle)
        stage = self._stages.get(window.id())
        if stage is None or stage.showing != view.buffer_id():
            return
        remaining = next(
            (
                item
                for item in self._documents.values()
                if item.window_id == window.id()
            ),
            None,
        )
        if remaining is None:
            self.close(window.id())
            return
        stage.showing = remaining.buffer_id
        stage.showing_preview = False
        source = self._source_for_buffer(window, remaining.buffer_id)
        self.backend.set_title(stage.surface, self._title(remaining.source_name))
        self._present(stage, source)

    def close_window(self, window_id: int) -> None:
        self.close(window_id, restore=False)
        self._forget_window(window_id)

    def close_all(self) -> None:
        for window_id in list(self._stages):
            self.close(window_id, restore=False)
        self._documents.clear()
        self._dismissed.clear()

    def _forget_window(self, window_id: int) -> None:
        for key in [key for key in self._documents if key[0] == window_id]:
            self._documents.pop(key, None)
        self._dismissed.discard(window_id)

    def reconcile(self, window) -> None:
        """Drop the panel whose surface the user closed behind our back."""
        stage = self._stages.get(window.id())
        if stage is None:
            return
        live = {handle.id for handle in self.backend.live_handles(window)}
        if stage.surface is None or stage.surface.id not in live:
            stage.surface = None
            self._dismissed.add(window.id())
            self.close(window.id())

    def settings_changed(self) -> None:
        """Repaint every panel, which is also what re-fits its group."""
        wanted = self.settings_provider().enable_toc
        for window_id, stage in list(self._stages.items()):
            if stage.automatic and not wanted:
                self.close(window_id)
                continue
            window = self.window_for_id(window_id)
            self._present(stage, self._source_for_buffer(window, stage.showing))

    # -- what the preview tells us ---------------------------------------

    def document_rendered(self, window_id: int, buffer_id: int, document) -> None:
        """A render finished: keep its headings, and open a panel if asked to.

        `enable_toc` and the two thresholds decide only whether a panel opens
        *by itself*. One the user opened by hand shows the table of contents
        whichever way those are set, because a panel that emptied half of
        itself on a focus change would be stranger than one that does not.
        """
        headings = tuple(document.headings) if document is not None else ()
        window = self.window_for_id(window_id)
        source = self._source_for_buffer(window, buffer_id)
        if source is None:
            return
        record = self._record(window_id, source)
        had_document = bool(record.document)
        record.document = headings
        record.realign()
        stage = self._stages.get(window_id)
        if stage is None:
            if self._wants_automatic(window_id, source, headings):
                self._open(window, source, automatic=True)
            return
        if stage.showing != buffer_id:
            # A document nobody is looking at: keep its headings, paint nothing.
            return
        if not headings:
            stage.showing_preview = False
        elif not had_document:
            # This document has a table of contents for the first time -- it or
            # its preview has just been opened. Which half to show is the
            # focus's answer, and the focus is wherever opening it left it.
            stage.showing_preview = self._focus_is_preview(window, buffer_id)
        self._present(stage, source)

    def _focus_is_preview(self, window, buffer_id: int) -> bool:
        """True when the window's focus is on this document's own preview."""
        active = self._active_view(window)
        if active is None:
            return False
        session = self.preview_for_surface(active.id())
        return session is not None and session.source_buffer_id == buffer_id

    def document_closed(self, window_id: int, buffer_id: int) -> None:
        """The preview went away: that document loses its contents half."""
        record = self._documents.get((window_id, buffer_id))
        if record is not None:
            record.document = ()
            record.active_slug = None
            record.realign()
        stage = self._stages.get(window_id)
        if stage is None or stage.showing != buffer_id:
            return
        stage.showing_preview = False
        window = self.window_for_id(window_id)
        self._present(stage, self._source_for_buffer(window, buffer_id))

    def heading_shown(self, window_id: int, buffer_id: int, slug: str) -> None:
        """A `#slug` link was clicked in the preview body.

        The preview has already scrolled; the caret follows, for the same
        reason a panel click moves both panes.
        """
        record = self._documents.get((window_id, buffer_id))
        if record is None:
            return
        window = self.window_for_id(window_id)
        source = self._source_for_buffer(window, buffer_id)
        line = record.links.line_for(slug)
        if record.active_slug == slug and line is None:
            return
        record.active_slug = slug
        if isinstance(line, int) and source is not None:
            self.reveal_line(source, line)
            heading = next(
                (item for item in record.headings if item.line == line), None
            )
            if heading is not None:
                record.active = heading.ordinal
        stage = self._stages.get(window_id)
        if stage is not None and stage.showing == buffer_id:
            self._present(stage, source)

    def _wants_automatic(self, window_id: int, source, headings) -> bool:
        settings = self.settings_provider()
        if not settings.enable_toc or window_id in self._dismissed:
            return False
        return toc_required(
            len(self.read_source(source)),
            headings,
            settings.toc_minimum_length,
            settings.toc_minimum_headings,
        )

    # -- content ---------------------------------------------------------

    def refresh(self, record: PanelDocument, source) -> None:
        if source is None:
            return
        record.headings = scan_outline(self.read_source(source))
        record.active = active_ordinal(record.headings, self.caret_row(source))
        record.realign()
        stage = self._stages.get(record.window_id)
        if stage is not None and stage.showing == record.buffer_id:
            self._present(stage, source)

    def refresh_source(self, view) -> None:
        """Repaint now: the source was activated, so its theme may have moved."""
        window = view.window()
        record = self.document(window.id(), view.buffer_id()) if window else None
        if record is not None:
            self.refresh(record, view)

    def refresh_for_source(self, view) -> None:
        """An edit landed; rescan after the configured settle delay."""
        window = view.window()
        record = self.document(window.id(), view.buffer_id()) if window else None
        if record is None:
            return
        self.clock.cancel(record.debounce_handle)
        delay = max(1, self.settings_provider().update_delay_ms)
        record.debounce_handle = self.clock.call_later(
            delay, lambda: self.refresh(record, view)
        )

    def sync_caret(self, view) -> None:
        window = view.window()
        record = self.document(window.id(), view.buffer_id()) if window else None
        if record is None:
            return
        active = active_ordinal(record.headings, self.caret_row(view))
        if active == record.active:
            return
        record.active = active
        # Keep the other half's highlight in step, so switching to it does not
        # show the heading you were at three sections ago.
        if active is not None:
            paired = record.links.slug_for(active)
            if paired is not None:
                record.active_slug = paired
        stage = self._stages.get(window.id())
        # The caret's heading is the outline's highlight; while the table of
        # contents is on screen, or another document is, there is nothing to
        # repaint for.
        if (
            stage is not None
            and stage.showing == record.buffer_id
            and not stage.showing_preview
        ):
            self._present(stage, view)

    def source_renamed(self, view) -> None:
        window = view.window()
        record = self.document(window.id(), view.buffer_id()) if window else None
        if record is None:
            return
        name = self._source_name(view)
        if name == record.source_name:
            return
        record.source_name = name
        stage = self._stages.get(window.id())
        if stage is not None and stage.showing == record.buffer_id:
            self.backend.set_title(stage.surface, self._title(name))

    def focus_changed(self, view) -> None:
        """Show the half, and the document, the window has settled on.

        The source's outline while a source has the focus, the rendered table
        of contents while the preview has it, and neither switched by anything
        the panel itself does.
        """
        window = view.window()
        if window is None:
            return
        stage = self._stages.get(window.id())
        if stage is None:
            return
        # Sublime activates views on the way past whenever the focus is moved
        # about -- restoring a scroll position, putting a focus back. Only the
        # view the window has come to rest on decides what the panel shows.
        active = window.active_view()
        if active is None or active.id() != view.id():
            return
        if self.owns_surface(view.id()):
            return
        session = self.preview_for_surface(view.id())
        if session is not None:
            buffer_id = session.source_buffer_id
            showing_preview = True
        elif self._is_markdown(view):
            buffer_id = view.buffer_id()
            showing_preview = False
        else:
            return
        source = self._source_for_buffer(window, buffer_id)
        if source is None:
            return
        record = self._record(window.id(), source)
        if not record.headings:
            record.headings = scan_outline(self.read_source(source))
            record.active = active_ordinal(record.headings, self.caret_row(source))
            record.realign()
        showing_preview = showing_preview and bool(record.document)
        if stage.showing == buffer_id and stage.showing_preview == showing_preview:
            return
        if stage.showing != buffer_id:
            self.backend.set_title(stage.surface, self._title(record.source_name))
        stage.showing = buffer_id
        stage.showing_preview = showing_preview
        self._present(stage, source)

    def adjust_zoom(self, window, delta: float = 0.0, reset: bool = False) -> bool:
        active = self._active_view(window)
        stage = self._stages.get(window.id())
        if stage is None or active is None or not self.owns_surface(active.id()):
            return False
        stage.zoom = 1.0 if reset else max(0.5, min(3.0, stage.zoom + delta))
        self._present(stage, self._source_for_buffer(window, stage.showing))
        return True

    def navigate(self, window, token: str, line=None, slug=None) -> None:
        """Take the reader to a section, in both panes where that is possible.

        An entry is a place in the document, not a place in one pane. Clicking
        one moves the caret to its line *and* scrolls the preview to it, so it
        does not matter which half is on screen or which view has the focus --
        the reason it used to matter is that a preview is read by scrolling,
        which leaves the focus behind on the source.

        Only the halves the alignment could pair move; see `renderer/align.py`.
        Neither move takes the focus: `reveal_line` sets a selection and
        centres it, and scrolling the preview is a viewport move.
        """
        stage = self._stages.get(window.id())
        if stage is None or stage.action_token != token:
            return
        record = self.showing(stage)
        source = self._source_for_buffer(window, stage.showing)
        if record is None or source is None:
            return
        if slug:
            if not any(item.slug == slug for item in record.document):
                return
            paired = record.links.line_for(slug)
        elif isinstance(line, int):
            heading = next(
                (item for item in record.headings if item.line == line), None
            )
            if heading is None:
                return
            slug = record.links.slug_for(heading.ordinal)
            paired = line
        else:
            return
        self._go_to(stage, record, source, slug, paired)
        self._present(stage, source)

    def _go_to(self, stage, record, source, slug, line) -> None:
        """Move both panes as far as the alignment allows, and remember where."""
        if slug and self.scroll_preview(stage.window_id, record.buffer_id, slug):
            record.active_slug = slug
        if isinstance(line, int):
            self.reveal_line(source, line)
            heading = next(
                (item for item in record.headings if item.line == line), None
            )
            if heading is not None:
                record.active = heading.ordinal

    def _source_for_buffer(self, window, buffer_id):
        if window is None or buffer_id is None:
            return None
        return next(
            (view for view in window.views() if view.buffer_id() == buffer_id),
            None,
        )

    def _showing_preview(self, stage: PanelStage, record: PanelDocument) -> bool:
        return stage.showing_preview and bool(record.document)

    def _width(self, stage: PanelStage, record: PanelDocument) -> float:
        """Pixels the panel wants, or 0.0 for the role's default share.

        Measured against whichever half is on screen: the two are different
        typefaces -- the outline is monospace and carries its `#` markers --
        so the group would be the wrong width for one of them otherwise.
        """
        if not self.settings_provider().auto_width:
            return 0.0
        rem_px = root_font_px(stage.zoom)
        if self._showing_preview(stage, record):
            return toc_width_px(record.document, rem_px)
        return outline_width_px(record.headings, rem_px)

    def _fit(self, stage: PanelStage, record: PanelDocument) -> None:
        """Give the panel's group the width its entries need.

        `LayoutOwner.fit` decides whether the move is allowed, so a divider the
        user has dragged is never moved back.
        """
        window = self.window_for_id(stage.window_id)
        if window is None or stage.surface is None:
            return
        group = self.backend.group_of(stage.surface)
        if group is not None:
            self.layout_owner.fit(
                window, group, GroupRole.PANEL, self._width(stage, record)
            )

    def _present(self, stage: PanelStage, source) -> None:
        record = self.showing(stage)
        if record is None or stage.surface is None:
            return
        if not self.backend.is_alive(stage.surface):
            return
        if self._showing_preview(stage, record):
            html = build_toc(record.document, stage.action_token, record.active_slug)
        else:
            html = build_outline(record.headings, stage.action_token, record.active)
        theme = (
            self.theme_provider(source) if source is not None else ThemeSnapshot()
        )
        # The scheme goes on before the paint: minihtml resolves the phantom's
        # colour variables against the surface's own scheme, not the source's.
        self.backend.apply_theme(stage.surface, theme)
        self.backend.update(
            stage.surface,
            represent(html, theme, stage.zoom, self.base_css, panel=True),
        )
        self._fit(stage, record)
        self._remember(stage, source)

    def _remember(self, stage: PanelStage, source) -> None:
        """Name the document this panel is on, for a restart to find.

        The preview does the same from its own side; either alone is enough,
        and a window can have a panel without ever having had a preview.
        """
        window = self.window_for_id(stage.window_id)
        if window is None or self.record is None or source is None:
            return
        self.record.remember_document(window, source.file_name() or None)
