import json
import os
import platform
import sys

import sublime
import sublime_plugin

from .container import container


def _active_view(window):
    sheet = window.active_sheet()
    return sheet.view() if sheet is not None else None


def _owned_outline(window):
    view = _active_view(window)
    return (
        container.outline.for_surface(view.id())
        if view is not None and container.outline
        else None
    )


def _owned_session(window):
    # Sheets and views have separate id spaces; surfaces are keyed by view id.
    view = _active_view(window)
    return (
        container.manager.for_surface(view.id())
        if view is not None and container.manager
        else None
    )


LIBRARIES_MESSAGE = (
    "MarkdownGlance needs the Package Control librar{plural} {names}, which "
    "{verb} not installed.\n\n"
    "Run \"Package Control: Satisfy Libraries\" from the Command Palette, then "
    "restart Sublime Text. Package Control installs them with the package; a "
    "manual install has to ask for them."
)


def libraries_missing(report=True):
    """True, after telling the user what to do, when the parser is absent.

    The libraries are looked up without being imported, so this is cheap and
    cannot itself fail.
    """
    from ..renderer.markdown_engine import missing_libraries

    names = missing_libraries()
    if names and report:
        sublime.error_message(
            LIBRARIES_MESSAGE.format(
                plural="ies" if len(names) > 1 else "y",
                names=" and ".join(names),
                verb="are" if len(names) > 1 else "is",
            )
        )
    return bool(names)


class MdglanceOpenSideBySideCommand(sublime_plugin.WindowCommand):
    def run(self):
        if libraries_missing():
            return
        container.reconcile(self.window)
        session = _owned_session(self.window)
        if session is not None:
            from ..domain.contracts import PreviewMode

            container.usecases.switch_mode(session, PreviewMode.SIDE_BY_SIDE)
            container.backend.focus(session.preview_surface)
        else:
            container.usecases.open_side_by_side(self.window)

    def is_enabled(self):
        if not container.loaded:
            return False
        view = self.window.active_view()
        return bool(_owned_session(self.window)) or bool(
            view and view.match_selector(0, "text.html.markdown")
        )


class MdglanceToggleFullScreenCommand(sublime_plugin.WindowCommand):
    def run(self):
        if libraries_missing():
            return
        container.usecases.toggle_full_screen(self.window)

    def is_enabled(self):
        if not container.loaded:
            return False
        view = self.window.active_view()
        return bool(_owned_session(self.window)) or bool(
            view and view.match_selector(0, "text.html.markdown")
        )


class MdglanceToggleOutlineCommand(sublime_plugin.WindowCommand):
    """Zed's outline panel, over the Markdown source rather than the preview."""

    def run(self):
        if not container.loaded:
            return
        container.reconcile(self.window)
        container.outline.toggle(self.window)

    def is_enabled(self):
        if not container.loaded:
            return False
        view = _active_view(self.window)
        return bool(_owned_outline(self.window)) or bool(
            view and view.match_selector(0, "text.html.markdown")
        )


class MdglanceOutlineNavigateCommand(sublime_plugin.WindowCommand):
    def run(self, token="", line=-1, event=None):
        if container.loaded:
            container.outline.navigate(self.window, token, line)


class MdglanceZoomCommand(sublime_plugin.WindowCommand):
    def run(self, delta=0.0, reset=False):
        if not container.loaded:
            return
        if container.outline.adjust_zoom(self.window, float(delta), bool(reset)):
            return
        container.usecases.adjust_zoom(self.window, float(delta), bool(reset))

    def is_enabled(self):
        return bool(
            container.loaded
            and (_owned_session(self.window) or _owned_outline(self.window))
        )


class MdglanceNavigateCommand(sublime_plugin.WindowCommand):
    def run(self, token="", slug="", event=None):
        container.usecases.navigate(self.window, token, slug)


class MdglanceOpenRelativeCommand(sublime_plugin.WindowCommand):
    def run(self, token="", path=-1, event=None):
        container.usecases.open_relative(self.window, token, path)


class MdglanceCopyDiagnosticsCommand(sublime_plugin.WindowCommand):
    def run(self):
        settings = container.settings.get()
        payload = {
            "package": "MarkdownGlance",
            "version": "0.4.1",
            "sublime_build": sublime.version(),
            "platform": sublime.platform(),
            "architecture": sublime.arch(),
            "python": platform.python_version(),
            "settings": {
                "update_delay_ms": settings.update_delay_ms,
                "enable_mermaid": settings.enable_mermaid,
                "enable_math": settings.enable_math,
                "allow_insecure_remote_images": settings.allow_insecure_remote_images,
                "remote_timeout_seconds": settings.remote_timeout_seconds,
                "remote_max_bytes": settings.remote_max_bytes,
                "remote_max_dimension": settings.remote_max_dimension,
                "toc_minimum_length": settings.toc_minimum_length,
                "toc_minimum_headings": settings.toc_minimum_headings,
                "debug_logging": settings.debug_logging,
            },
            "recent_stages": list(container.recent_stages),
            # Python render cost and Sublime paint cost for the last few
            # repaints. A `skipped` paint is one the backend dropped because
            # the HTML had not changed.
            "recent_renders": list(container.recent_renders),
            "recent_paints": list(container.recent_paints),
        }
        sublime.set_clipboard(json.dumps(payload, indent=2, sort_keys=True))
        sublime.status_message("MarkdownGlance diagnostics copied")


class MdglanceOpenInBrowserCommand(sublime_plugin.WindowCommand):
    """Write the document as a standalone page and hand it to the browser.

    The preview stays in the editor; this is for the moment a page has to be
    seen the way a browser lays it out, or sent to someone. The page is the
    parser's own output, unsanitised, since it is the user's file opened
    locally, and it goes under the temporary directory, one file per source
    path.
    """

    def run(self):
        import hashlib
        import pathlib
        import tempfile
        import webbrowser

        if libraries_missing():
            return
        from ..renderer.export import standalone_html

        view = self.window.active_view()
        if view is None:
            return
        source = view.substr(sublime.Region(0, view.size()))
        name = view.file_name() or ""
        title = os.path.basename(name) or "Untitled"
        page = standalone_html(source, title, os.path.dirname(name))
        # The page may hold an unsaved buffer, so the directory and the file
        # are private to the user on hosts that honour modes; the file is
        # created fresh each time rather than followed if something else has
        # put an entry under that name.
        directory = os.path.join(tempfile.gettempdir(), "MarkdownGlance")
        stem = os.path.splitext(title)[0]
        digest = hashlib.sha1((name or str(view.id())).encode("utf-8")).hexdigest()[:8]
        target = os.path.join(directory, "{}-{}.html".format(stem, digest))
        try:
            os.makedirs(directory, mode=0o700, exist_ok=True)
            if os.path.lexists(target):
                os.remove(target)
            descriptor = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as sink:
                sink.write(page)
        except OSError as error:
            sublime.error_message(
                "MarkdownGlance could not write the page for the browser.\n\n"
                "{}\n\n{}".format(target, error)
            )
            return
        if webbrowser.open(pathlib.Path(target).as_uri()):
            sublime.status_message(
                "MarkdownGlance: opened {} in the browser".format(title)
            )
        else:
            sublime.error_message(
                "MarkdownGlance wrote the page but no browser could be started. "
                "Open it yourself:\n\n{}".format(target)
            )

    def is_enabled(self):
        view = self.window.active_view()
        return bool(view and view.match_selector(0, "text.html.markdown"))


class MdglanceRunContractTestsCommand(sublime_plugin.WindowCommand):
    def run(self):
        from ..presentation.phantom_view import PhantomViewBackend

        backend = PhantomViewBackend()
        original_layout = self.window.layout()
        dummy = None
        handle = None
        results = []
        try:
            if self.window.num_groups() < 2:
                self.window.set_layout(
                    {
                        "cols": [0.0, 0.5, 1.0],
                        "rows": [0.0, 1.0],
                        "cells": [[0, 0, 1, 1], [1, 0, 2, 1]],
                    }
                )
            self.window.focus_group(1)
            dummy = self.window.new_file()
            dummy.set_scratch(True)
            dummy.set_name("MarkdownGlance contract user sheet")
            self.window.focus_group(0)
            handle = backend.create(self.window, 0, "Contract preview", "contract")
            backend.update(handle, '<h1 id="top">Top</h1><p>Body</p>')
            backend.set_heading_ratios(handle, {"top": 0.0})
            assert backend.is_alive(handle)
            assert (
                backend.owner_of(
                    next(
                        sheet
                        for sheet in self.window.sheets()
                        if sheet.view() is not None
                        and sheet.view().id() == handle.id
                    )
                )
                == "contract"
            )
            assert handle in backend.live_handles(self.window)
            assert backend.navigate(handle, "top")
            backend.move(handle, 1)
            assert backend.group_of(handle) == 1
            self.window.focus_group(0)
            backend.reveal(handle)
            assert self.window.active_group() == 0
            assert self.window.active_sheet_in_group(1).view().id() == handle.id
            backend.focus(handle)
            assert self.window.active_sheet().view().id() == handle.id
            backend.set_title(handle, "Contract renamed")
            results.append({"backend": "phantom_view", "result": "pass"})
        except Exception as error:
            results.append(
                {"backend": "phantom_view", "result": "fail", "error": repr(error)}
            )
        finally:
            if handle is not None and backend.is_alive(handle):
                backend.close(handle)
            if dummy is not None and dummy.window() is not None:
                dummy.close()
            self.window.set_layout(original_layout)
            path = os.path.join(
                sublime.packages_path(),
                "MarkdownGlance",
                "docs",
                "verification",
                "st{}-contract.json".format(sublime.version()),
            )
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as output:
                json.dump(results, output, indent=2, sort_keys=True)
                output.write("\n")
            sublime.status_message("MarkdownGlance contract results: {}".format(path))


class MdglanceRunBenchmarkCommand(sublime_plugin.WindowCommand):
    def run(self):
        from MarkdownGlance.tests.benchmark import run

        package_root = os.path.join(sublime.packages_path(), "MarkdownGlance")
        result = run(package_root)
        result["sublime_build"] = sublime.version()
        path = os.path.join(
            package_root,
            "docs",
            "verification",
            "st{}-benchmark.json".format(sublime.version()),
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as output:
            json.dump(result, output, indent=2, sort_keys=True)
            output.write("\n")
        sublime.status_message("MarkdownGlance benchmark: {}".format(path))
