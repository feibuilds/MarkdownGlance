"""Unattended check of LaTeX math in the preview, run inside Sublime Text.

A state machine on the UI thread. Each phase writes `<phase>.json` to the
evidence directory and touches `<phase>.done`; the outside driver takes a
screenshot and touches `go<N>` to release the next phase. Nothing here is
part of the package.
"""

import json
import os
import re
import time

import sublime

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
EVIDENCE = os.path.join(ROOT, "evidence")
FIXTURE = os.path.join(ROOT, "fixtures", "math.md")
LIGHT_SCHEME = "Breakers.sublime-color-scheme"
PHASE_TIMEOUT_S = 90


def _path(name):
    return os.path.join(EVIDENCE, name)


def _write(name, data):
    with open(_path(name), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)


def _touch(name):
    open(_path(name), "w").close()


def _redact(locator):
    # The query string is the formula; keep the host and the colour only.
    colour = re.search(r"%5Ccolor%5BRGB%5D%7B([0-9%C]+)%7D", locator)
    return {
        "host": locator.split("?", 1)[0],
        "colour": colour.group(1).replace("%2C", ",") if colour else None,
        "display": "%5Cdisplaystyle" in locator,
    }


def _snapshot(session):
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
        "privacy_captions": body.count("ormula source is sent to"),
        "code_math": body.count('<code class="math">'),
        "body_html": body,
    }


class Probe:
    def __init__(self):
        self.phase = "open"
        self.started = time.time()
        self.window = None
        self.view = None
        self.session = None
        self.previous_assets = None
        self.log = []

    def note(self, message):
        self.log.append("{:.1f}s {}".format(time.time() - self.started, message))
        print("MATHPROBE", message)

    def container(self):
        from MarkdownGlance.preview.adapter.container import container

        return container

    def find_session(self):
        manager = self.container().usecases.manager
        return manager.for_source(self.window.id(), self.view.buffer_id())

    def settled(self, snapshot):
        return (
            snapshot["generation"] is not None
            and not snapshot["pending"]
            and snapshot["loading"] == 0
        )

    def finish(self, name, snapshot, extra=None):
        data = dict(snapshot)
        data.update(extra or {})
        data["log"] = list(self.log)
        _write(name + ".json", data)
        _touch(name + ".done")
        self.note("wrote " + name)
        self.started = time.time()

    def timed_out(self):
        return time.time() - self.started > PHASE_TIMEOUT_S

    def tick(self):
        try:
            self.step()
        except Exception as error:  # noqa: BLE001 - evidence, not control flow
            self.note("error in {}: {!r}".format(self.phase, error))
            _write("error.json", {"phase": self.phase, "error": repr(error), "log": self.log})
            self.phase = "done"
        if self.phase != "done":
            sublime.set_timeout(self.tick, 500)

    def step(self):
        phase = self.phase
        if phase == "open":
            self.window = sublime.active_window()
            self.view = self.window.open_file(FIXTURE)
            self.phase = "loading"
        elif phase == "loading":
            if not self.view.is_loading():
                self.window.focus_view(self.view)
                self.window.run_command("mdglance_open_side_by_side")
                self.note("preview opened")
                self.phase = "render1"
        elif phase == "render1":
            self.session = self.find_session()
            if self.session is None:
                if self.timed_out():
                    _write("error.json", {"phase": phase, "error": "no session"})
                    self.phase = "done"
                return
            snapshot = _snapshot(self.session)
            if self.settled(snapshot) and snapshot["images"] > 0:
                self.previous_assets = snapshot["assets"]
                self.finish("phase1-math-on", snapshot)
                self.phase = "go2"
            elif self.timed_out():
                self.finish("phase1-math-on", snapshot, {"timed_out": True})
                self.phase = "go2"
        elif phase == "go2":
            if os.path.exists(_path("go2")):
                self.started = time.time()
                sublime.load_settings("Preferences.sublime-settings").set(
                    "color_scheme", LIGHT_SCHEME
                )
                self.note("switched to " + LIGHT_SCHEME)
                self.phase = "render2"
        elif phase == "render2":
            snapshot = _snapshot(self.session)
            changed = snapshot["assets"] != self.previous_assets
            if changed and self.settled(snapshot):
                self.finish("phase2-light-scheme", snapshot, {"assets_changed": True})
                self.phase = "go3"
            elif self.timed_out():
                self.finish(
                    "phase2-light-scheme",
                    snapshot,
                    {"assets_changed": changed, "timed_out": True},
                )
                self.phase = "go3"
        elif phase == "go3":
            if os.path.exists(_path("go3")):
                sublime.set_clipboard("")
                self.window.run_command("mdglance_copy_diagnostics")
                clipboard = sublime.get_clipboard()
                leaks = [
                    token
                    for token in ("a^2", "frac", "int_0", "alpha", "codecogs.com/png")
                    if token in clipboard
                ]
                _write(
                    "phase3-diagnostics.json",
                    {"clipboard": clipboard, "leaks": leaks, "log": list(self.log)},
                )
                _touch("phase3-diagnostics.done")
                self.note("diagnostics copied, leaks={}".format(leaks))
                self.started = time.time()
                self.phase = "go4"
        elif phase == "go4":
            if os.path.exists(_path("go4")):
                self.started = time.time()
                sublime.load_settings("MarkdownGlance.sublime-settings").set(
                    "enable_math", False
                )
                self.note("enable_math off")
                self.phase = "render4"
        elif phase == "render4":
            snapshot = _snapshot(self.session)
            if snapshot["code_math"] > 0 and snapshot["images"] == 0:
                self.finish("phase4-math-off", snapshot)
                self.phase = "go5"
            elif self.timed_out():
                self.finish("phase4-math-off", snapshot, {"timed_out": True})
                self.phase = "go5"
        elif phase == "go5":
            if os.path.exists(_path("go5")):
                self.note("exiting")
                self.phase = "done"
                sublime.run_command("exit")


def plugin_loaded():
    os.makedirs(EVIDENCE, exist_ok=True)
    probe = Probe()
    sublime.set_timeout(probe.tick, 2000)
