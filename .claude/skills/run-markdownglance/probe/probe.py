"""Scenario runner that lives inside a portable Sublime Text as a package.

Not part of MarkdownGlance. `setup.sh` links this directory in as
`Data/Packages/MdglanceProbe`; `drive.sh` writes `probe.json` beside `Data`
naming a scenario file and an evidence directory, then launches Sublime Text.
At `plugin_loaded` the scenario's phases run one after another on the UI
thread. Each phase performs an action, polls until its `done` predicate holds
(or its timeout passes), writes `<phase>.json`, touches `<phase>.done`, and,
if it wants a screenshot, waits for `go-<phase>` from the driver before the
next phase starts. The last thing it does is exit Sublime Text.

A scenario is a Python file with a `PHASES` list built from `phase(...)`:

    from mdglance_probe import phase

    def start(ctx):
        ctx.set_setting("MarkdownGlance.sublime-settings", "enable_math", True)
        ctx.open_fixture("math.md")

    PHASES = [
        phase("math-on", action=start,
              done=lambda ctx, snap: ctx.settled(snap) and snap["images"] > 0,
              check=lambda ctx, snap: {"three images": snap["images"] == 3}),
    ]

`ctx.open_fixture` also opens the preview once the file has loaded. `snap` is
`ctx.snapshot()`: what the live session holds, with data URIs and formula
locators redacted, so the JSON is safe to keep as evidence.
"""

import importlib.util
import json
import os
import re
import sys
import time
import traceback
from collections import namedtuple

import sublime

# Data/Packages/MdglanceProbe/probe.py -> the profile root beside Data.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
CONTROL = os.path.join(ROOT, "probe.json")
TICK_MS = 500

Phase = namedtuple("Phase", "name action done check screenshot timeout")


def phase(name, action=None, done=None, check=None, screenshot=True, timeout=90):
    """One step of a scenario. See the module docstring."""
    return Phase(name, action, done, check, screenshot, timeout)


def _redact_locator(locator):
    # A Mermaid or math locator carries document text; keep host and colour.
    colour = re.search(r"%5Ccolor%5BRGB%5D%7B([0-9%C]+)%7D", locator)
    background = re.search(r"bgColor=([0-9a-f]+)", locator)
    return {
        "host": locator.split("?", 1)[0].split("/img/", 1)[0],
        "colour": colour.group(1).replace("%2C", ",") if colour else None,
        "background": background.group(1) if background else None,
        "display": "%5Cdisplaystyle" in locator,
    }


class Context:
    def __init__(self, control):
        self.control = control
        self.evidence = control["evidence"]
        self.fixtures = control["fixtures"]
        self.window = sublime.active_window()
        self.view = None
        self.started = time.time()
        self.log = []
        self._preview_pending = False

    # -- helpers a scenario calls -------------------------------------------

    def note(self, message):
        self.log.append("{:.1f}s {}".format(time.time() - self.started, message))
        print("MDGLANCE-PROBE", message)

    def open_fixture(self, name):
        """Open a fixture file and, once it has loaded, its preview."""
        self.view = self.window.open_file(os.path.join(self.fixtures, name))
        self._preview_pending = True

    def open_preview(self):
        self.window.focus_view(self.view)
        self.window.run_command("mdglance_open_side_by_side")
        self.note("preview opened")

    def run(self, command, args=None):
        self.window.run_command(command, args or {})

    def set_setting(self, file, key, value):
        sublime.load_settings(file).set(key, value)
        self.note("{}: {} = {!r}".format(file, key, value))

    def clipboard(self):
        return sublime.get_clipboard()

    def container(self):
        from MarkdownGlance.preview.adapter.container import container

        return container

    def session(self):
        if self.view is None:
            return None
        manager = self.container().usecases.manager
        return manager.for_source(self.window.id(), self.view.buffer_id())

    def snapshot(self):
        session = self.session()
        if session is None:
            return {"session": False, "generation": None, "pending": [], "loading": 0}
        document = session.last_document
        body = document.body_html if document else ""
        body = re.sub(r'src="data:[^"]*"', 'src="data:REDACTED"', body)
        return {
            "session": True,
            "generation": document.generation if document else None,
            "pending": [key.safe_label for key in session.pending_assets],
            "assets": [
                dict(label=key.safe_label, **_redact_locator(key.locator))
                for key in (document.asset_dependencies if document else ())
            ],
            "theme": {
                "background": session.theme.background,
                "foreground": session.theme.foreground,
                "is_dark": session.theme.is_dark,
            },
            "settings": {
                "enable_math": session.settings.enable_math,
                "enable_mermaid": session.settings.enable_mermaid,
            },
            "images": len(re.findall(r"<img ", body)),
            "loading": body.count("Loading"),
            "unavailable": body.count("Unavailable"),
            "block_placeholders": body.count('class="mdglance-asset-placeholder"'),
            "inline_placeholders": body.count("mdglance-asset-placeholder-inline"),
            "privacy_captions": body.count("source is sent to"),
            "error_cards": body.count("mdglance-error"),
            "code_math": body.count('<code class="math">'),
            "headings": len(document.headings) if document else 0,
            "body_html": body,
        }

    def settled(self, snap):
        """The session has rendered and nothing is still loading."""
        return (
            snap.get("session")
            and snap["generation"] is not None
            and not snap["pending"]
            and snap["loading"] == 0
        )

    # -- internals ------------------------------------------------------------

    def _path(self, name):
        return os.path.join(self.evidence, name)

    def write(self, name, data):
        with open(self._path(name), "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)

    def touch(self, name):
        open(self._path(name), "w").close()

    def exists(self, name):
        return os.path.exists(self._path(name))


class Runner:
    def __init__(self, ctx, phases):
        self.ctx = ctx
        self.phases = list(phases)
        self.index = -1
        self.state = "next"
        self.phase_started = time.time()

    def start(self):
        self.ctx.write(
            "phases.json",
            [
                {"name": p.name, "screenshot": p.screenshot, "timeout": p.timeout}
                for p in self.phases
            ],
        )
        sublime.set_timeout(self.tick, TICK_MS)

    def tick(self):
        try:
            self.step()
        except Exception:  # noqa: BLE001 - recorded, then the run ends cleanly
            self.ctx.note("error: " + traceback.format_exc().strip().splitlines()[-1])
            self.ctx.write(
                "error.json",
                {
                    "phase": self.current.name if self.index >= 0 else None,
                    "traceback": traceback.format_exc(),
                    "log": self.ctx.log,
                },
            )
            self.state = "exit"
        if self.state == "exit":
            self.ctx.note("exiting")
            self.ctx.touch("exit.done")
            if not self.ctx.control.get("keep_open"):
                sublime.run_command("exit")
            return
        sublime.set_timeout(self.tick, TICK_MS)

    @property
    def current(self):
        return self.phases[self.index]

    def step(self):
        ctx = self.ctx
        # The preview opens once the fixture has loaded, whichever phase asked.
        if ctx._preview_pending and ctx.view is not None and not ctx.view.is_loading():
            ctx._preview_pending = False
            ctx.open_preview()
            return
        if self.state == "next":
            self.index += 1
            if self.index >= len(self.phases):
                self.state = "exit"
                return
            self.phase_started = time.time()
            if self.current.action is not None:
                self.current.action(ctx)
            self.state = "wait"
        elif self.state == "wait":
            if ctx._preview_pending:
                return
            snap = ctx.snapshot()
            done = self.current.done
            finished = done(ctx, snap) if done is not None else True
            timed_out = time.time() - self.phase_started > self.current.timeout
            if finished or timed_out:
                data = dict(snap)
                data["timed_out"] = bool(timed_out and not finished)
                checks = self.current.check(ctx, snap) if self.current.check else {}
                data["checks"] = {name: bool(value) for name, value in checks.items()}
                data["log"] = list(ctx.log)
                ctx.write(self.current.name + ".json", data)
                ctx.touch(self.current.name + ".done")
                ctx.note(
                    "phase {} {}".format(
                        self.current.name, "timed out" if data["timed_out"] else "done"
                    )
                )
                self.state = "go" if self.current.screenshot else "next"
        elif self.state == "go":
            if ctx.exists("go-" + self.current.name):
                self.state = "next"


def _load_scenario(path):
    sys.modules["mdglance_probe"] = sys.modules[__name__]
    spec = importlib.util.spec_from_file_location("mdglance_scenario", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PHASES


def plugin_loaded():
    if not os.path.exists(CONTROL):
        print("MDGLANCE-PROBE no probe.json at", CONTROL)
        return
    with open(CONTROL, encoding="utf-8") as handle:
        control = json.load(handle)
    os.makedirs(control["evidence"], exist_ok=True)
    ctx = Context(control)
    try:
        phases = _load_scenario(control["scenario"])
    except Exception:  # noqa: BLE001
        ctx.write("error.json", {"phase": None, "traceback": traceback.format_exc()})
        ctx.touch("exit.done")
        sublime.run_command("exit")
        return
    # Give the package's own plugin_loaded and the window a moment first.
    sublime.set_timeout(Runner(ctx, phases).start, 1500)
