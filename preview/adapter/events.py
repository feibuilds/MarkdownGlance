import os.path

import sublime
import sublime_plugin

from ..presentation.phantom_view import OWNER_KEY
from ..presentation.contexts import (
    context_result,
    markdown_source,
    outline_focused,
    preview_focused,
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
            container.outline.refresh_for_source(self.view)

        _ui(modified)

    def on_selection_modified_async(self):
        _ui(lambda: container.loaded and container.outline.sync_caret(self.view))

    def on_post_save_async(self):
        def saved():
            if not container.loaded:
                return
            container.usecases.source_saved(self.view)
            container.outline.source_renamed(self.view)

        _ui(saved)

    def on_pre_close(self):
        if not container.loaded:
            return
        if self.view.settings().has(OWNER_KEY):
            surface_id = self.view.id()

            def closed():
                if not container.loaded:
                    return
                if not container.outline.surface_closed(surface_id):
                    container.manager.surface_closed(surface_id)

            _ui(closed)
        else:
            container.outline.source_closed(self.view)
            container.usecases.source_closed(self.view)

    def on_activated(self):
        def activated():
            if not container.loaded or self.view.window() is None:
                return
            window = self.view.window()
            container.reconcile(window)
            container.outline.source_renamed(self.view)
            container.outline.refresh_source(self.view)
            container.usecases.reveal_surfaces(self.view)
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

        _ui(activated)


class MarkdownGlanceEventListener(sublime_plugin.EventListener):
    def on_query_context(self, view, key, operator, operand, match_all):
        if not container.loaded:
            return None
        window = view.window() if view else sublime.active_window()
        if key == "mdglance.preview_focused":
            return context_result(
                preview_focused(window, container.backend), operator, operand
            )
        if key == "mdglance.outline_focused":
            return context_result(
                outline_focused(window, container.outline.owns_surface),
                operator,
                operand,
            )
        if key == "mdglance.markdown_source":
            return context_result(markdown_source(view), operator, operand)
        return None

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
            container.outline.close_window(window.id())
            container.usecases.window_closed(window)
