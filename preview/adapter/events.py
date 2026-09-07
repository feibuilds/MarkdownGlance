import os.path

import sublime
import sublime_plugin

from ..presentation.phantom_view import OWNER_KEY
from ..presentation.contexts import (
    context_result,
    markdown_source,
    panel_focused,
    preview_focused,
    preview_open,
)
from .container import container

CLOSE_COMMANDS = frozenset(
    (
        "close",
        "close_by_index",
        "close_file",
        "close_pane",
        "close_others",
        "close_all",
        "close_workspace",
    )
)
LAYOUT_COMMANDS = frozenset(
    ("set_layout", "new_pane", "close_pane", "move_to_group", "clone_file")
)


def _ui(callback):
    sublime.set_timeout(callback, 0)


class SourceAndSurfaceListener(sublime_plugin.ViewEventListener):
    @classmethod
    def is_applicable(cls, settings):
        return True

    def on_modified_async(self):
        def modified():
            if not container.loaded:
                return
            container.usecases.source_modified(self.view)
            container.panel.refresh_for_source(self.view)

        _ui(modified)

    def on_selection_modified_async(self):
        _ui(lambda: container.loaded and container.panel.sync_caret(self.view))

    def on_post_save_async(self):
        def saved():
            if not container.loaded:
                return
            container.usecases.source_saved(self.view)
            container.panel.source_renamed(self.view)

        _ui(saved)

    def on_pre_close(self):
        if not container.loaded:
            return
        if self.view.settings().has(OWNER_KEY):
            surface_id = self.view.id()

            def closed():
                if not container.loaded:
                    return
                if not container.panel.surface_closed(surface_id):
                    container.manager.surface_closed(surface_id)

            _ui(closed)
        else:
            container.panel.source_closed(self.view)
            container.usecases.source_closed(self.view)

    def on_activated(self):
        _ui(self._settled)

    def on_load_async(self):
        """A file opened from the sidebar or Goto Anything is activated while
        it is still loading, before Sublime has given it a syntax, so the
        activation above sees a view that is not Markdown yet and leaves it
        alone. No second activation follows -- the view is already active --
        so the load is the only other chance to notice."""
        _ui(self._settled)

    def _settled(self):
        if not container.loaded or self.view.window() is None:
            return
        window = self.view.window()
        container.reconcile(window)
        container.panel.source_renamed(self.view)
        container.panel.refresh_source(self.view)
        container.usecases.follow_focus(self.view)
        container.panel.focus_changed(self.view)
        session = container.manager.for_source(window.id(), self.view.buffer_id())
        if session is None:
            return
        name = (
            self.view.name()
            or os.path.basename(self.view.file_name() or "")
            or "Untitled"
        )
        base = (
            os.path.dirname(self.view.file_name())
            if self.view.file_name()
            else None
        )
        if name != session.source_name or base != session.base_path:
            container.usecases.source_saved(self.view)
        else:
            container.usecases.theme_changed(self.view)


class MarkdownGlanceEventListener(sublime_plugin.EventListener):
    def on_query_context(self, view, key, operator, operand, match_all):
        if not container.loaded:
            return None
        window = view.window() if view else sublime.active_window()
        if key == "mdglance.preview_focused":
            return context_result(
                preview_focused(view, container.backend), operator, operand
            )
        if key == "mdglance.preview_open":
            return context_result(
                preview_open(
                    window, lambda window_id: container.manager.stage(window_id)
                ),
                operator,
                operand,
            )
        if key == "mdglance.panel_focused":
            return context_result(
                panel_focused(window, container.panel.owns_surface),
                operator,
                operand,
            )
        if key == "mdglance.markdown_source":
            return context_result(markdown_source(view), operator, operand)
        return None

    def on_init(self, views):
        """The views Sublime restored before the plugin API was ready.

        The one signal that a window has come back from a session rather than
        been opened: its groups are already filled, so a group that looks empty
        here really is empty, and `reconcile` can take back the ones a previous
        process left behind. `plugin_loaded` sweeps every window too; this
        covers the order where the session arrives after the container is up.
        """
        if not container.loaded:
            return
        windows = {}
        for view in views:
            window = view.window()
            if window is not None:
                windows[window.id()] = window
        for window in windows.values():
            container.reconcile(window)

    def on_new_window(self, window):
        """A window opened after startup carries a restored session too, when
        it comes from a project or a workspace."""
        if container.loaded:
            _ui(lambda: container.loaded and container.reconcile(window))

    def on_post_window_command(self, window, command_name, args):
        if not container.loaded:
            return
        if command_name in LAYOUT_COMMANDS:
            container.layout.invalidate(window)
        if command_name in CLOSE_COMMANDS:
            container.clock.once_per_tick(
                ("reconcile", window.id()), lambda: container.reconcile(window)
            )

    def on_pre_close_window(self, window):
        if container.loaded:
            container.panel.close_window(window.id())
            container.usecases.window_closed(window)
