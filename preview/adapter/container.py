import json
import os.path
import time
import traceback
from typing import Optional

import sublime

from ..application.errors import describe
from ..application.panel import PanelController
from ..application.render_pipeline import render
from ..application.scheduler import GenerationScheduler
from ..application.session import CloseCause, PreviewSession
from ..application.session_manager import SessionManager
from ..application.usecases import UseCases
from ..assets import (
    AssetCache,
    AssetResolver,
    ImageFetcher,
    NetworkPolicy,
    SvgRasteriser,
)
from ..domain.contracts import RenderRequest
from ..domain.paths import HOST
from ..presentation import window_record
from ..presentation.layout import LayoutOwner
from ..presentation.phantom_view import PhantomViewBackend
from ..renderer.stylesheet import root_font_px
from ..renderer.tables import budgets
from .clock import SublimeClock
from .executors import OwnedExecutors
from .settings import SettingsAdapter
from .source_access import caret_row, read_source, reveal_line
from .theme import theme_snapshot

# ST reports no view-resize event, so a maximised or dragged window is noticed
# by polling. Only a change in the table budget triggers a re-render.
VIEWPORT_POLL_MS = 500

# How many of each timing to keep for `mdglance_copy_diagnostics`.
TIMING_HISTORY = 20


def _window(window_id: int):
    return next(
        (window for window in sublime.windows() if window.id() == window_id), None
    )


class Container:
    def __init__(self) -> None:
        self.loaded = False
        self.backend = None
        self.layout = None
        self.manager = None
        self.panel = None
        self.scheduler = None
        self.usecases = None
        self.settings = None
        self.executors = None
        self.resolver = None
        self.rasteriser = None
        self.clock = None
        self.policy_revision = 0
        self.recent_stages = []
        # Rolling windows of what each half of a repaint cost. `recent_renders`
        # is Python -- parse, table rewrite, serialise -- on the render pool.
        # `recent_paints` is what Sublime charged for the minihtml layout, and
        # it is the only view of that cost there is from here.
        self.recent_renders = []
        self.recent_paints = []
        # The last failure's stage, one-line description and traceback, for
        # `mdglance_copy_diagnostics`: the card in the preview shows the line,
        # an issue needs the frames.
        self.last_error = None
        self._theme_callbacks = {}

    def build(self) -> None:
        if self.loaded:
            return
        self.clock = SublimeClock()
        self.executors = OwnedExecutors()
        self.backend = PhantomViewBackend(self.handle_link, self.record_paint)
        self.layout = LayoutOwner()
        self.settings = SettingsAdapter(self._settings_changed)
        cache = AssetCache()
        # One rasteriser for both halves, so that the renderer is looked up
        # once and a local drawing and a remote badge are drawn the same way.
        self.rasteriser = SvgRasteriser()
        self.resolver = AssetResolver(
            cache,
            ImageFetcher(self.rasteriser),
            self.policy,
            self.executors.network,
            lambda callback: sublime.set_timeout(callback, 0),
            lambda key, waiters: self.scheduler.asset_available(key, waiters),
            self.rasteriser,
        )
        self.manager = SessionManager(
            self.backend,
            self.layout,
            self.resolver,
            _window,
            self.session_closed,
            lambda surface_id: self.panel is not None
            and self.panel.owns_surface(surface_id),
            lambda stage, session: self.usecases.show(stage, session),
        )
        self.scheduler = GenerationScheduler(
            self.manager.get,
            self.snapshot,
            self.render,
            self.present,
            self.present_error,
            self.executors.render,
            self.clock,
            lambda callback: sublime.set_timeout(callback, 0),
            self.report_failure,
        )
        base_css = sublime.load_resource(
            "Packages/MarkdownGlance/resources/preview.css"
        )
        self.panel = PanelController(
            self.backend,
            self.layout,
            self.clock,
            _window,
            self.settings.get,
            theme_snapshot,
            read_source,
            caret_row,
            reveal_line,
            base_css,
            lambda surface_id: self.manager.for_surface(surface_id),
            lambda window_id, buffer_id, slug: self.usecases.scroll_preview(
                window_id, buffer_id, slug
            ),
            window_record,
        )
        self.usecases = UseCases(
            self.manager,
            self.scheduler,
            self.backend,
            self.layout,
            self.snapshot,
            self.settings.get,
            theme_snapshot,
            self.observe_theme,
            base_css,
            self.panel,
            window_record,
        )
        self.loaded = True
        for window in sublime.windows():
            self.reconcile(window)
        self._watch_viewports()

    def reconcile(self, window) -> None:
        """Both registries sweep the same window; the panel's must run first
        so that its surfaces are still claimed when the preview sweep looks.

        The restore runs before either, and is about a window rather than a
        surface: it fills the panes a *previous* process left behind, or takes
        them away, neither of which the two registries can see -- nothing in
        the window is theirs to find.
        """
        self.usecases.restore(window)
        self.panel.reconcile(window)
        self.usecases.reconcile(window)

    def svg_renderer_found(self) -> bool:
        """Whether an SVG in a document would be drawn, for diagnostics."""
        if self.rasteriser is None or self.settings is None:
            return False
        return self.rasteriser.backend(self.settings.get()) is not None

    def policy(self) -> NetworkPolicy:
        return NetworkPolicy(self.settings.get(), self.policy_revision)

    def snapshot(self, session: PreviewSession, generation: int) -> RenderRequest:
        self.record_stage("snapshot")
        window = _window(session.window_id)
        if window is None:
            raise RuntimeError("source window is gone")
        source = next(
            (
                view
                for view in window.views()
                if view.buffer_id() == session.source_buffer_id
            ),
            None,
        )
        if source is None:
            raise RuntimeError("source view is gone")
        folders = window.folders()
        session.base_path = (
            os.path.dirname(source.file_name())
            if source.file_name()
            else HOST.normalise(folders[0]) if folders else None
        )
        session.theme = theme_snapshot(source)
        session.settings = self.settings.get()
        # Zoom and the table budget belong to the pane the document is shown
        # in, not to the document, so they come off the stage.
        stage = self.manager.stage(session.window_id)
        zoom = stage.zoom if stage is not None else 1.0
        viewport_width = self._viewport_width(stage)
        if stage is not None:
            stage.table_budget = self._table_budget(stage, viewport_width)
        return RenderRequest(
            session.id,
            generation,
            source.substr(sublime.Region(0, source.size())),
            session.base_path,
            zoom,
            session.settings,
            session.theme,
            session.action_token,
            viewport_width,
        )

    def _viewport_width(self, stage) -> float:
        handle = stage.surface if stage is not None else None
        if handle is None or not self.backend.is_alive(handle):
            return 0.0
        return self.backend.viewport_width(handle)

    def _table_budget(self, stage, viewport_width: float):
        return budgets(
            viewport_width,
            root_font_px(stage.zoom if stage is not None else 1.0),
            self.settings.get().table_max_columns,
        )

    def _watch_viewports(self) -> None:
        """Re-render the preview whose pane has been resized under it.

        One pane per window, so this is one measurement per window rather than
        one per document, and only the document on screen can be affected.
        """
        if not self.loaded:
            return
        for stage in self.manager.stages():
            if stage.table_budget is None or stage.showing is None:
                continue
            budget = self._table_budget(stage, self._viewport_width(stage))
            if budget != stage.table_budget:
                stage.table_budget = budget
                self.scheduler.request_render(stage.showing, "resize")
        sublime.set_timeout(self._watch_viewports, VIEWPORT_POLL_MS)

    def present(self, session, document) -> None:
        self.record_stage("present")
        self.usecases.present(session, document)

    def present_error(self, session, stage, message) -> None:
        self.record_stage("error:{}".format(stage.value))
        self.usecases.present_error(session, stage, message)

    def report_failure(self, session, stage, error) -> None:
        """Put the traceback where a reader can find it.

        The console always gets it, `debug_logging` or not: a preview that
        shows an error card and a console that says nothing about it was what
        issue #5 had to work with. The frames also go into the diagnostics,
        which is what an issue report carries.
        """
        frames = traceback.format_exception(type(error), error, error.__traceback__)
        self.last_error = {
            "stage": stage.value,
            "message": describe(error),
            "traceback": "".join(frames).rstrip().splitlines(),
        }
        print(
            "MarkdownGlance: {} failed for {}\n{}".format(
                stage.value, session.id, "".join(frames).rstrip()
            )
        )

    def _settings_changed(self, render_required: bool, policy_changed: bool) -> None:
        if policy_changed:
            self.policy_revision += 1
        if self.usecases is not None:
            self.usecases.settings_changed(render_required, policy_changed)
        if self.panel is not None:
            self.panel.settings_changed()

    def record_stage(self, stage: str) -> None:
        self.recent_stages.append(stage)
        del self.recent_stages[:-TIMING_HISTORY]

    def render(self, request: RenderRequest):
        """Render on the pool, timing the Python half of a repaint."""
        started = time.perf_counter()
        document = render(request, resolver=self.resolver)
        self.recent_renders.append(
            {
                "source_bytes": len(request.markdown),
                "html_bytes": len(document.body_html),
                "ms": round((time.perf_counter() - started) * 1000.0, 1),
            }
        )
        del self.recent_renders[:-TIMING_HISTORY]
        return document

    def record_paint(
        self, handle, size: int, elapsed_ms: float, skipped: bool
    ) -> None:
        """Record what `PhantomSet.update` cost for one surface.

        This is wall clock around the Sublime call, so it measures the layout
        only to the extent Sublime does that work synchronously; if minihtml
        defers any of it to the next paint, that part lands outside the timer
        and the number here is a floor, not the whole cost.
        """
        self.recent_paints.append(
            {
                "role": self.backend.role_of(self._surface_view(handle)) or "unknown",
                "html_bytes": size,
                "ms": round(elapsed_ms, 1),
                "skipped": skipped,
            }
        )
        del self.recent_paints[:-TIMING_HISTORY]
        if self.settings is not None and self.settings.get().debug_logging:
            print(
                "MarkdownGlance: paint {} bytes in {:.1f} ms{}".format(
                    size, elapsed_ms, " (skipped, unchanged)" if skipped else ""
                )
            )

    def _surface_view(self, handle):
        window = _window(handle.window_id)
        if window is None:
            return None
        return next(
            (view for view in window.views() if view.id() == handle.id), None
        )

    def observe_theme(self, view, session_id: str) -> None:
        key = "mdglance.theme.{}".format(session_id)

        def changed() -> None:
            sublime.set_timeout(
                lambda: self.loaded and self.usecases.theme_changed(view), 0
            )

        view.settings().add_on_change(key, changed)
        self._theme_callbacks[session_id] = (view, key)

    def session_closed(self, session: PreviewSession) -> None:
        """Every path that ends a preview arrives here, so the panel learns
        that its table-of-contents half has nothing behind it any more."""
        callback = self._theme_callbacks.pop(session.id, None)
        if callback is not None:
            view, key = callback
            view.settings().clear_on_change(key)
        if self.panel is not None:
            self.panel.document_closed(session.window_id, session.source_buffer_id)

    def handle_link(self, handle, href: str) -> None:
        window = _window(handle.window_id)
        if window is None or self.usecases is None:
            return
        if href.startswith("subl:"):
            command_and_args = href[len("subl:") :].split(" ", 1)
            command = command_and_args[0]
            try:
                args = (
                    json.loads(command_and_args[1])
                    if len(command_and_args) == 2
                    else {}
                )
            except (TypeError, ValueError):
                return
            # Both halves of the panel navigate through the same controller:
            # the table of contents by slug, the outline by source line.
            if command == "mdglance_navigate":
                self.panel.navigate(
                    window, args.get("token", ""), slug=args.get("slug", "")
                )
            elif command == "mdglance_outline_navigate":
                self.panel.navigate(
                    window, args.get("token", ""), line=args.get("line", -1)
                )
            elif command == "mdglance_open_relative":
                self.usecases.open_relative(
                    window, args.get("token", ""), args.get("path", -1)
                )
            return
        if href.startswith("#"):
            self.usecases.navigate_for_surface(handle.id, href[1:])
            return
        if href.startswith(("http://", "https://")):
            sublime.run_command("open_url", {"url": href})

    def unload(self) -> None:
        if not self.loaded:
            return
        self.settings.detach()
        self.panel.close_all()
        self.manager.close_all(CloseCause.UNLOAD)
        self.executors.shutdown()
        self.loaded = False


container = Container()
