"""Unattended Windows checks of MarkdownGlance's GUI, run inside Sublime Text.

One suite per run, named in `Packages/WinProbe/suite.txt` by `w.ps1`:

    export   manual-test-plan step 12 and the Math half of step 7
    images   step 6, local and remote images
    outline  steps 9 and 10, the outline panel and auto_width

The flow is a generator on the UI thread. `yield WAIT` comes back on the next
tick; `yield post(name, payload)` hands the payload to the host collector at
`http://10.0.2.2:8099` over QEMU's user-mode NAT and resumes when it answers,
which is also when the collector has screendumped the guest. Nothing here is
part of the package.
"""

import json
import os
import re
import threading
import time

import sublime

HOST = "http://10.0.2.2:8099"
IMAGES = "http://10.0.2.2:8100"
TICK_MS = 400
WAIT = object()

DESKTOP = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
EXPORT_DIR = os.path.join(DESKTOP, "fixture space #hash")
IMAGE_DIR = os.path.join(DESKTOP, "images")
OUTLINE_DIR = os.path.join(DESKTOP, "outline")
MATH_MD = os.path.join(DESKTOP, "math.md")
SUITE_FILE = os.path.join(os.path.dirname(__file__), "suite.txt")

THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
MARKDOWN_SYNTAX = "Packages/Markdown/Markdown.sublime-syntax"


# --------------------------------------------------------------------------
# plumbing


def post(name, payload):
    return ("post", name, payload)


def _http(url, data=None, timeout=60):
    import urllib.request

    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return reply.read().decode("utf-8", "replace")


def _reachable(url, timeout=15):
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as reply:
            return {"url": url, "status": reply.status, "bytes": len(reply.read(2048))}
    except Exception as error:  # noqa: BLE001 - evidence, not control flow
        return {"url": url, "error": repr(error)}


def _close_browser():
    import subprocess

    try:
        return subprocess.run(
            ["taskkill", "/IM", "msedge.exe", "/F"],
            capture_output=True,
            timeout=30,
            creationflags=0x08000000,  # CREATE_NO_WINDOW; no console flash
        ).returncode
    except Exception as error:  # noqa: BLE001
        return repr(error)


def _temp_dir():
    import tempfile

    return os.path.join(tempfile.gettempdir(), "MarkdownGlance")


def _temp_listing():
    directory = _temp_dir()
    out = {"directory": directory, "exists": os.path.isdir(directory), "entries": []}
    if not out["exists"]:
        return out
    out["dir_mode"] = oct(os.stat(directory).st_mode)
    for entry in sorted(os.listdir(directory)):
        info = os.stat(os.path.join(directory, entry))
        out["entries"].append(
            {"name": entry, "bytes": info.st_size, "mode": oct(info.st_mode)}
        )
    return out


def _read_page(stem):
    directory = _temp_dir()
    if not os.path.isdir(directory):
        return None, None
    candidates = [
        os.path.join(directory, entry)
        for entry in os.listdir(directory)
        if entry.startswith(stem) and entry.endswith(".html")
    ]
    if not candidates:
        return None, None
    newest = max(candidates, key=lambda path: os.stat(path).st_mtime)
    with open(newest, "r", encoding="utf-8") as handle:
        return newest, handle.read()


def _app_theme():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_KEY) as key:
            return int(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except Exception as error:  # noqa: BLE001
        return repr(error)


def _set_app_theme(light):
    import winreg

    value = 1 if light else 0
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, THEME_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, value)
        winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, value)


def setting(name, value):
    sublime.load_settings("MarkdownGlance.sublime-settings").set(name, value)


def container():
    from MarkdownGlance.preview.adapter.container import container as built

    return built


def _redact(locator):
    colour = re.search(r"%5Ccolor%5BRGB%5D%7B([0-9%C]+)%7D", locator)
    return {
        "host": locator.split("?", 1)[0],
        "colour": colour.group(1).replace("%2C", ",") if colour else None,
        "display": "%5Cdisplaystyle" in locator,
    }


def preview_snapshot(session):
    document = session.last_document
    body = document.body_html if document else ""
    body = re.sub(r'src="data:[^"]*"', 'src="data:REDACTED"', body)
    return {
        "generation": document.generation if document else None,
        "pending": [key.safe_label for key in session.pending_assets],
        "assets": [
            dict(label=key.safe_label, **_redact(key.locator))
            for key in (document.asset_dependencies if document else ())
        ],
        "theme": {
            "background": session.theme.background,
            "foreground": session.theme.foreground,
            "is_dark": session.theme.is_dark,
        },
        "settings": {"enable_math": session.settings.enable_math},
        "images": len(re.findall(r"<img ", body)),
        "loading": body.count("Loading"),
        "unavailable": body.count("Unavailable"),
        "inline_placeholders": body.count("mdglance-asset-placeholder-inline"),
        "code_math": body.count('<code class="math">'),
        "body_html": body,
    }


# --------------------------------------------------------------------------
# layout reporting, for steps 9 and 10


def _sheet_name(sheet):
    view = sheet.view()
    if view is None:
        return "(not a view)"
    return view.name() or os.path.basename(view.file_name() or "") or "Untitled"


def layout_report(window):
    """Every group's cell, pixel width and what is in it."""
    layout = window.layout()
    groups = []
    for index in range(window.num_groups()):
        view = window.active_view_in_group(index)
        groups.append(
            {
                "group": index,
                "cell": list(layout["cells"][index]),
                "width_px": round(float(view.viewport_extent()[0]), 1) if view else 0.0,
                "sheets": len(window.sheets_in_group(index)),
                "names": [_sheet_name(sheet) for sheet in window.sheets_in_group(index)],
            }
        )
    return {
        "cols": [round(value, 6) for value in layout["cols"]],
        "rows": [round(value, 6) for value in layout["rows"]],
        "num_groups": window.num_groups(),
        "groups": groups,
    }


def outline_report(window, view):
    session = container().outline.for_source(window.id(), view.buffer_id())
    if session is None:
        return {"open": False}
    group = container().backend.group_of(session.surface)
    return {
        "open": True,
        "group": group,
        "zoom": round(session.zoom, 4),
        "active": session.active,
        "headings": [
            {"level": heading.level, "text": heading.text, "line": heading.line}
            for heading in session.headings
        ],
        "width_px": round(
            float(window.active_view_in_group(group).viewport_extent()[0]), 1
        )
        if group is not None and window.active_view_in_group(group)
        else 0.0,
    }


def toc_report(window, session):
    if session is None or session.toc_surface is None:
        return {"open": False}
    group = container().backend.group_of(session.toc_surface)
    view = window.active_view_in_group(group) if group is not None else None
    return {
        "open": True,
        "group": group,
        "width_px": round(float(view.viewport_extent()[0]), 1) if view else 0.0,
        "headings": [
            heading.text for heading in (session.last_document.headings if session.last_document else ())
        ],
    }


def resize_window(width, height, result):
    """Resize the editor's own OS window, which no Sublime API exposes.

    Run this on a worker thread and never on the plugin host's main thread.
    Measured: a synchronous `SetWindowPos` from there deadlocked the guest --
    the editor's UI thread was waiting on the plugin host's callback to
    return, and the callback was waiting on that UI thread to handle
    WM_WINDOWPOSCHANGING. SWP_ASYNCWINDOWPOS queues the change instead.
    """
    import ctypes

    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        flags = 0x0004 | 0x0010 | 0x4000  # NOZORDER | NOACTIVATE | ASYNCWINDOWPOS
        ok = bool(user32.SetWindowPos(hwnd, 0, 0, 0, int(width), int(height), flags))
        result.update({"hwnd": int(hwnd), "requested": [width, height], "ok": ok})
    except Exception as error:  # noqa: BLE001
        result.update({"error": repr(error)})
    result["done"] = True


# --------------------------------------------------------------------------
# the driver


class Probe:
    def __init__(self, suite, generation):
        self.suite = suite
        self.generation = generation
        self.window = None
        self.view = None
        self.busy = False
        self.done = False
        self.log = []
        self.started = time.time()
        self.flow = None

    def note(self, message):
        self.log.append("{:.1f}s {}".format(time.time() - self.started, message))
        print("WINPROBE", message)

    # -- generator helpers ------------------------------------------------

    def open_file(self, path):
        view = self.window.open_file(path)
        for _ in range(150):
            if not view.is_loading():
                break
            yield WAIT
        self.window.focus_view(view)
        self.view = view
        self.note("opened " + os.path.basename(path))
        return view

    def session_for(self, view):
        return container().usecases.manager.for_source(
            self.window.id(), view.buffer_id()
        )

    def settled_preview(self, view, want_images=None, limit=90):
        """Wait until the preview has a document with nothing in flight."""
        deadline = time.time() + limit
        session = None
        while time.time() < deadline:
            session = self.session_for(view)
            if session is not None:
                snapshot = preview_snapshot(session)
                done = (
                    snapshot["generation"] is not None
                    and not snapshot["pending"]
                    and snapshot["loading"] == 0
                )
                if done and (want_images is None or snapshot["images"] >= want_images):
                    return session
            yield WAIT
        self.note("preview did not settle within {}s".format(limit))
        return session

    def pause(self, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            yield WAIT

    # -- suites -----------------------------------------------------------

    def script(self):
        self.window = sublime.active_window()
        if self.suite == "images":
            yield from self.suite_images()
        elif self.suite == "outline":
            yield from self.suite_outline()
        elif self.suite == "widths":
            # Step 10 on its own, for re-running the measurements without
            # replaying all of step 9 first.
            yield from self.widths()
        else:
            yield from self.suite_export()

    # ---- step 6 ---------------------------------------------------------

    def image_cases(self):
        """One case per line of step 6, with this guest's real paths.

        Windows absolute paths are spelled three ways on purpose: with a drive
        letter, rooted without one, and as a `file:` URL. They do not all take
        the same route through `_asset_key`.
        """
        drive = os.path.join(IMAGE_DIR, "pixel.png").replace("\\", "/")
        rooted = drive[2:] if drive[1:2] == ":" else drive
        return (
            ("relative", "pixel.png"),
            ("absolute-drive", drive),
            ("absolute-rooted", rooted),
            ("absolute-file-url", "file:///" + drive),
            ("missing", "nope.png"),
            ("oversized-local", "huge-header.png"),
            ("extensionless", "pixel-noext"),
            ("remote-https", "https://latex.codecogs.com/png.latex?a"),
            ("remote-redirect", IMAGES + "/redirect.png"),
            ("remote-timeout", IMAGES + "/slow.png"),
            ("remote-invalid", IMAGES + "/notimage.png"),
            ("remote-oversized", IMAGES + "/huge.png"),
        )

    def write_images_fixture(self):
        """One list item per case, so each result can be read back by label."""
        lines = ["# Image checks", ""]
        for label, source in self.image_cases():
            lines.append("- {}: ![{}]({})".format(label, label, source))
        lines.append("")
        path = os.path.join(IMAGE_DIR, "images.md")
        with open(path, "w", encoding="utf-8") as sink:
            sink.write("\n".join(lines))
        return path

    @staticmethod
    def classify(body_html):
        """What each labelled list item ended up showing."""
        out = {}
        for item in re.findall(r"<li>(.*?)</li>", body_html, re.S):
            label = re.match(r"\s*([a-z-]+):", item)
            if label is None:
                continue
            if "<img " in item:
                size = re.search(r'width="(\d+)" height="(\d+)"', item)
                out[label.group(1)] = {
                    "result": "image",
                    "width": int(size.group(1)) if size else None,
                    "height": int(size.group(2)) if size else None,
                }
            else:
                status = re.search(r"<strong>([^<]+)</strong>", item)
                out[label.group(1)] = {
                    "result": status.group(1) if status else "unknown",
                }
        return out

    def suite_images(self):
        import platform
        import sys

        path = self.write_images_fixture()
        yield post(
            "i0-start",
            {
                "sublime_version": sublime.version(),
                "python": sys.version,
                "windows": platform.platform(),
                "fixture": path,
                "cases": [list(case) for case in self.image_cases()],
                "imgserver": _reachable(IMAGES + "/ping"),
                "https_probe": _reachable("https://latex.codecogs.com/png.latex?a"),
            },
        )

        view = yield from self.open_file(path)
        self.window.run_command("mdglance_open_side_by_side")
        session = yield from self.settled_preview(view)
        snapshot = preview_snapshot(session) if session else {}
        yield post(
            "i1-http-allowed",
            {
                "allow_insecure_remote_images": True,
                "results": self.classify(snapshot.get("body_html", "")),
                "preview": {k: v for k, v in snapshot.items() if k != "body_html"},
                "body_html": snapshot.get("body_html", ""),
            },
        )

        # The same document under the default policy: every http asset has to
        # come back blocked, and nothing else may change.
        setting("allow_insecure_remote_images", False)
        self.note("allow_insecure_remote_images off")
        deadline = time.time() + 60
        results = {}
        while time.time() < deadline:
            session = self.session_for(view)
            if session is not None:
                snapshot = preview_snapshot(session)
                results = self.classify(snapshot["body_html"])
                blocked = [
                    label
                    for label, value in results.items()
                    if value.get("result") == "Blocked by settings"
                ]
                if len(blocked) >= 4 and not snapshot["pending"]:
                    break
            yield WAIT
        yield post(
            "i2-http-blocked",
            {
                "allow_insecure_remote_images": False,
                "results": results,
                "preview": {k: v for k, v in snapshot.items() if k != "body_html"},
                "body_html": snapshot.get("body_html", ""),
            },
        )
        setting("allow_insecure_remote_images", True)

    # ---- steps 9 and 10 -------------------------------------------------

    def outline_of(self, view):
        return container().outline.for_source(self.window.id(), view.buffer_id())

    def close_outline(self, view):
        """The toggle closes only from the panel; from the source it focuses."""
        session = self.outline_of(view)
        if session is None:
            return
        container().backend.focus(session.surface)
        yield from self.pause(0.8)
        self.window.run_command("mdglance_toggle_outline")
        yield from self.pause(1.5)

    def wait_outline(self, view, predicate, limit=30):
        deadline = time.time() + limit
        while time.time() < deadline:
            session = self.outline_of(view)
            if session is not None and predicate(session):
                return session
            yield WAIT
        return self.outline_of(view)

    def suite_outline(self):
        import platform
        import sys

        yield post(
            "o0-start",
            {
                "sublime_version": sublime.version(),
                "python": sys.version,
                "windows": platform.platform(),
                "layout": layout_report(self.window),
                "fixtures": {
                    name: os.path.exists(os.path.join(OUTLINE_DIR, name))
                    for name in ("kinds.md", "none.md", "short.md", "long.md", "second.md")
                },
            },
        )

        # 9a: an outline over a file with no preview takes a group of its own.
        kinds = yield from self.open_file(os.path.join(OUTLINE_DIR, "kinds.md"))
        before = layout_report(self.window)
        self.window.run_command("mdglance_toggle_outline")
        session = yield from self.wait_outline(kinds, lambda s: s.headings)
        yield post(
            "o1-no-preview",
            {
                "layout_before": before,
                "layout_after": layout_report(self.window),
                "outline": outline_report(self.window, kinds),
                "source_group": self.window.get_view_index(kinds)[0],
            },
        )

        # 9b: with a preview open it must still get a group, never a tab in
        # the preview's. The toggle closes only when the outline itself has
        # focus -- from the source it just focuses the panel -- so the close
        # goes through the surface.
        container().backend.focus(session.surface)
        yield from self.pause(0.8)
        self.window.run_command("mdglance_toggle_outline")  # close
        yield from self.pause(1.5)
        self.window.focus_view(kinds)
        self.window.run_command("mdglance_open_side_by_side")
        preview_session = yield from self.settled_preview(kinds)
        self.window.focus_view(kinds)
        self.window.run_command("mdglance_toggle_outline")  # open beside both
        session = yield from self.wait_outline(kinds, lambda s: s.headings)
        outline_group = container().backend.group_of(session.surface) if session else None
        preview_group = (
            container().backend.group_of(preview_session.preview_surface)
            if preview_session
            else None
        )
        yield post(
            "o2-with-preview",
            {
                "layout": layout_report(self.window),
                "outline_group": outline_group,
                "preview_group": preview_group,
                "distinct_groups": outline_group != preview_group,
                "sheets_in_outline_group": len(self.window.sheets_in_group(outline_group))
                if outline_group is not None
                else None,
            },
        )

        # 9c: which lines count as headings.
        yield post(
            "o3-heading-kinds",
            {
                "outline": outline_report(self.window, kinds),
                "source": open(
                    os.path.join(OUTLINE_DIR, "kinds.md"), "r", encoding="utf-8"
                ).read(),
            },
        )

        # 9d: the caret across headings, and a heading typed live.
        moves = []
        for heading in list(session.headings):
            point = kinds.text_point(heading.line, 0)
            kinds.sel().clear()
            kinds.sel().add(sublime.Region(point, point))
            self.window.focus_view(kinds)
            yield from self.pause(0.8)
            current = self.outline_of(kinds)
            moves.append(
                {
                    "line": heading.line,
                    "text": heading.text,
                    "active": current.active if current else None,
                    "expected": heading.ordinal,
                }
            )
        kinds.run_command("append", {"characters": "\n\n## Typed while open\n"})
        typed = yield from self.wait_outline(
            kinds, lambda s: any(h.text == "Typed while open" for h in s.headings)
        )
        yield post(
            "o4-caret-and-typing",
            {
                "moves": moves,
                "after_typing": outline_report(self.window, kinds),
                "typed_present": any(
                    heading.text == "Typed while open" for heading in typed.headings
                )
                if typed
                else False,
            },
        )

        # 9e: clicking entries top, middle and bottom is the navigate command.
        headings = list(typed.headings)
        picks = [headings[0], headings[len(headings) // 2], headings[-1]]
        clicks = []
        for heading in picks:
            self.window.run_command(
                "mdglance_outline_navigate",
                {"token": typed.action_token, "line": heading.line},
            )
            yield from self.pause(0.8)
            row, _ = kinds.rowcol(kinds.sel()[0].begin())
            clicks.append(
                {"text": heading.text, "line": heading.line, "caret_row": row}
            )
        yield post("o5-clicks", {"clicks": clicks})

        # 9f: no headings at all, and two outlines at once.
        none_view = yield from self.open_file(os.path.join(OUTLINE_DIR, "none.md"))
        self.window.run_command("mdglance_toggle_outline")
        yield from self.pause(2.0)
        second = yield from self.open_file(os.path.join(OUTLINE_DIR, "second.md"))
        self.window.run_command("mdglance_toggle_outline")
        second_session = yield from self.wait_outline(second, lambda s: s.headings)
        self.window.focus_view(kinds)
        yield from self.pause(1.0)
        yield post(
            "o6-empty-and-two-files",
            {
                "none": outline_report(self.window, none_view),
                "second": outline_report(self.window, second),
                "kinds": outline_report(self.window, kinds),
                "sessions_in_window": len(
                    container().outline.sessions_in(self.window.id())
                ),
                "layout": layout_report(self.window),
            },
        )

        # 9g: zoom the outline, then close it and the source.
        if second_session is not None:
            container().backend.focus(second_session.surface)
        yield from self.pause(0.8)
        self.window.run_command("mdglance_zoom", {"delta": 0.25})
        yield from self.pause(1.2)
        zoomed = outline_report(self.window, second)
        self.window.run_command("mdglance_zoom", {"reset": True})
        yield from self.pause(1.2)
        reset = outline_report(self.window, second)
        yield from self.close_outline(second)
        yield post(
            "o7-zoom-and-close",
            {
                "zoomed": zoomed,
                "reset": reset,
                "after_close": outline_report(self.window, second),
                "layout": layout_report(self.window),
            },
        )

        yield from self.widths()

    # ---- step 10 --------------------------------------------------------

    def close_everything(self):
        for view in list(self.window.views()):
            view.set_scratch(True)
            view.close()
        yield from self.pause(1.5)
        self.window.set_layout({"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]})
        yield from self.pause(0.8)

    def panels_for(self, name, auto_width):
        """Open a preview (for its table of contents) and an outline."""
        setting("auto_width", auto_width)
        yield from self.close_everything()
        view = yield from self.open_file(os.path.join(OUTLINE_DIR, name))
        self.window.run_command("mdglance_open_side_by_side")
        session = yield from self.settled_preview(view)
        self.window.focus_view(view)
        self.window.run_command("mdglance_toggle_outline")
        yield from self.wait_outline(view, lambda s: s.headings)
        yield from self.pause(1.5)
        return view, session

    def widths(self):
        measurements = {}
        for auto_width in (True, False):
            for name in ("short.md", "long.md"):
                view, session = yield from self.panels_for(name, auto_width)
                key = "{}-auto_width-{}".format(name[:-3], auto_width)
                measurements[key] = {
                    "auto_width": auto_width,
                    "document": name,
                    "toc": toc_report(self.window, session),
                    "outline": outline_report(self.window, view),
                    "layout": layout_report(self.window),
                }
                yield post("w1-{}".format(key), measurements[key])

        # A hand-dragged divider must win, and keep winning across repaints.
        view, session = yield from self.panels_for("long.md", True)
        fitted = layout_report(self.window)
        outline_group = outline_report(self.window, view)["group"]
        layout = self.window.layout()
        cells = layout["cells"]
        cols = list(layout["cols"])
        left_column = cells[outline_group][0]
        dragged_to = max(0.05, cols[left_column] - 0.12)
        cols[left_column] = dragged_to
        self.window.set_layout(
            {"cols": cols, "rows": layout["rows"], "cells": layout["cells"]}
        )
        yield from self.pause(1.0)
        after_drag = layout_report(self.window)
        view.run_command(
            "append", {"characters": "\n\n## A heading typed after the drag\n"}
        )
        yield from self.wait_outline(
            view, lambda s: any("after the drag" in h.text for h in s.headings)
        )
        yield from self.pause(2.0)
        yield post(
            "w2-drag-wins",
            {
                "fitted": fitted,
                "dragged_to": dragged_to,
                "after_drag": after_drag,
                "after_repaint": layout_report(self.window),
                "outline": outline_report(self.window, view),
            },
        )

        # Closing and reopening the group hands the fit back.
        yield from self.close_outline(view)
        self.window.focus_view(view)
        self.window.run_command("mdglance_toggle_outline")
        yield from self.wait_outline(view, lambda s: s.headings)
        yield from self.pause(1.5)
        yield post(
            "w3-reopen-refits",
            {
                "layout": layout_report(self.window),
                "outline": outline_report(self.window, view),
            },
        )

        # Zoom, then a longer heading, then a smaller window: the group follows.
        view, session = yield from self.panels_for("short.md", True)
        base = outline_report(self.window, view)
        outline_session = self.outline_of(view)
        if outline_session is not None:
            container().backend.focus(outline_session.surface)
        yield from self.pause(0.8)
        self.window.run_command("mdglance_zoom", {"delta": 0.5})
        yield from self.pause(2.0)
        zoomed = outline_report(self.window, view)
        self.window.run_command("mdglance_zoom", {"reset": True})
        yield from self.pause(1.5)

        self.window.focus_view(view)
        view.run_command(
            "append",
            {
                "characters": "\n\n## "
                + "A heading long enough that the panel has to grow to fit it"
                + "\n"
            },
        )
        yield from self.wait_outline(
            view, lambda s: any("long enough" in h.text for h in s.headings)
        )
        yield from self.pause(2.0)
        longer = outline_report(self.window, view)

        resized = {"done": False}
        threading.Thread(
            target=resize_window, args=(1280, 860, resized), daemon=True
        ).start()
        deadline = time.time() + 15
        while not resized["done"] and time.time() < deadline:
            yield WAIT
        yield from self.pause(2.5)
        view.run_command("append", {"characters": "\n\n## After the resize\n"})
        yield from self.wait_outline(
            view, lambda s: any("After the resize" in h.text for h in s.headings)
        )
        yield from self.pause(2.0)
        yield post(
            "w4-zoom-longer-resize",
            {
                "base": base,
                "zoomed": zoomed,
                "longer_heading": longer,
                "resize": resized,
                "after_resize": outline_report(self.window, view),
                "layout": layout_report(self.window),
            },
        )
        setting("auto_width", True)

    # ---- step 12 and the math half of step 7 ----------------------------

    def export_and_read(self, stem, settle):
        self.window.run_command("mdglance_open_in_browser")
        yield from self.pause(1.0)
        target, page = _read_page(stem)
        yield from self.pause(settle)
        return {
            "target": target,
            "listing": _temp_listing(),
            "page": page,
            "app_theme_light": _app_theme(),
        }

    def suite_export(self):
        import platform
        import sys

        initial_theme = _app_theme()
        yield post(
            "p0-start",
            {
                "sublime_version": sublime.version(),
                "python": sys.version,
                "windows": platform.platform(),
                "app_theme_light": initial_theme,
                "network": [
                    _reachable("https://cdn.jsdelivr.net/npm/katex@0.16.22/dist/katex.min.css"),
                    _reachable("https://latex.codecogs.com/png.latex?a"),
                ],
            },
        )
        view = yield from self.open_file(os.path.join(EXPORT_DIR, "export-check.md"))
        payload = yield from self.export_and_read("export-check", 12.0)
        yield post("p1-export-saved", payload)

        _set_app_theme(not bool(initial_theme))
        yield from self.pause(2.0)
        self.window.focus_view(view)
        payload = yield from self.export_and_read("export-check", 12.0)
        yield post("p2-export-other-theme", payload)

        yield from self.open_file(os.path.join(EXPORT_DIR, "plain-export.md"))
        payload = yield from self.export_and_read("plain-export", 8.0)
        yield post("p3-export-plain", payload)

        with open(os.path.join(EXPORT_DIR, "export-check.md"), "r", encoding="utf-8") as handle:
            source = handle.read()
        fresh = self.window.new_file()
        fresh.set_syntax_file(MARKDOWN_SYNTAX)
        fresh.run_command("append", {"characters": source})
        fresh.set_scratch(True)
        self.window.focus_view(fresh)
        payload = yield from self.export_and_read("Untitled", 10.0)
        yield post("p4-export-unsaved", payload)

        plain = yield from self.open_file(os.path.join(EXPORT_DIR, "plain.txt"))
        from MarkdownGlance.preview.adapter.commands import MdglanceOpenInBrowserCommand

        yield post(
            "p5-non-markdown",
            {
                "file": plain.file_name(),
                "syntax": plain.settings().get("syntax"),
                "matches_markdown": plain.match_selector(0, "text.html.markdown"),
                "is_enabled": MdglanceOpenInBrowserCommand(self.window).is_enabled(),
            },
        )

        _close_browser()
        yield from self.pause(1.5)
        math = yield from self.open_file(MATH_MD)
        self.window.run_command("mdglance_open_side_by_side")
        session = yield from self.settled_preview(math, want_images=1)
        yield post("p6-math-preview", preview_snapshot(session) if session else {})

        sublime.set_clipboard("")
        self.window.run_command("mdglance_copy_diagnostics")
        clipboard = sublime.get_clipboard()
        yield post(
            "p7-diagnostics",
            {
                "clipboard": clipboard,
                "leaks": [
                    token
                    for token in ("a^2", "frac", "int_0", "alpha", "codecogs.com/png")
                    if token in clipboard
                ],
            },
        )
        yield post("p8-finish", {"temp": _temp_listing()})

    # -- the tick ---------------------------------------------------------

    def send(self, name, payload):
        self.busy = True
        data = dict(payload)
        data["log"] = list(self.log)
        data["phase"] = name

        def worker():
            try:
                reply = _http(
                    "{}/evidence/{}".format(HOST, name),
                    json.dumps(data, indent=2, sort_keys=True, default=str).encode(
                        "utf-8"
                    ),
                )
                self.note("posted {} -> {}".format(name, reply.strip()[:20]))
            except Exception as error:  # noqa: BLE001
                self.note("post failed for {}: {!r}".format(name, error))
            self.busy = False
            sublime.set_timeout(self.tick, TICK_MS)

        threading.Thread(target=worker, daemon=True).start()

    def tick(self):
        if self.generation != GENERATION[0]:
            return  # a newer plugin load owns the window now
        if self.busy:
            sublime.set_timeout(self.tick, TICK_MS)
            return
        if self.done:
            return
        try:
            request = next(self.flow)
        except StopIteration:
            # `send` reschedules the tick, so the flag is what stops the run;
            # without it StopIteration is raised again and the last phase is
            # posted for as long as the editor is open.
            self.done = True
            self.note("suite {} finished".format(self.suite))
            self.send("z-finished", {"suite": self.suite})
            return
        except Exception as error:  # noqa: BLE001 - evidence, not control flow
            import traceback

            self.note("error: {!r}".format(error))
            self.send(
                "error",
                {"suite": self.suite, "error": repr(error), "traceback": traceback.format_exc()},
            )
            return
        if isinstance(request, tuple) and request and request[0] == "post":
            self.send(request[1], request[2])
            return
        sublime.set_timeout(self.tick, TICK_MS)


# Sublime reloads a package's plugins when their files change on disk, and
# `w.ps1` rewrites this one on every run. The old Probe's `set_timeout` chain
# survives that reload, so without a generation to check against, two probes
# drive the same window at once -- measured: a finished run kept posting its
# last phase for as long as the editor stayed open.
GENERATION = [0]


def plugin_loaded():
    GENERATION[0] += 1
    suite = "export"
    if os.path.exists(SUITE_FILE):
        with open(SUITE_FILE, "r", encoding="utf-8") as handle:
            suite = handle.read().strip() or "export"
    probe = Probe(suite, GENERATION[0])
    probe.flow = probe.script()
    sublime.set_timeout(probe.tick, 4000)
