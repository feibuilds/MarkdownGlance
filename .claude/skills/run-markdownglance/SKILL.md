---
name: run-markdownglance
description: Run, drive and screenshot MarkdownGlance inside a real portable Sublime Text 4200 on Linux, unattended. Use when asked to run the plugin, verify a preview change in the real app, take a screenshot of the preview, or run a manual-test-plan step automatically (math, mermaid, images, tables). Also covers the pure-Python unit tests.
---

MarkdownGlance is a Sublime Text 4 package; the app is Sublime Text itself.
It is driven by a probe package that runs *inside* Sublime Text
(`.claude/skills/run-markdownglance/probe/probe.py`), executing a scenario
file phase by phase against the live render session, while
`.claude/skills/run-markdownglance/drive.sh` launches the portable binary,
screenshots the window between phases and prints a pass/fail table. A
portable profile under `/tmp/mdglance-st` keeps the user's own Sublime Text
untouched. All paths below are relative to the repository root.

## Prerequisites

Linux x86_64 with an X11 display, or none plus `xvfb-run`. Tools the driver
checks for: `xdotool`, `wmctrl`, `import` (ImageMagick), and `xvfb-run` for
headless runs. On Ubuntu they are the packages `xdotool wmctrl imagemagick
xvfb`. Also `python3` with `pip`, `curl` and `tar` with xz. This host had
all of them already:

```bash
for t in xdotool wmctrl import xvfb-run python3 curl; do command -v $t; done
```

Network access to `download.sublimetext.com` (once, 16 MB, cached under
`~/.cache/markdownglance/`) and, for the math and Mermaid scenarios, to the
rendering servers the package uses.

## Setup

Builds the portable profile: extracts Sublime Text 4200, links this checkout
in as `Data/Packages/MarkdownGlance` and the probe as
`Data/Packages/MdglanceProbe`, pip-installs the two Package Control
libraries into `Data/Lib/python38`, and writes conservative preferences
(`hot_exit` off, software rendering). Idempotent; rerun after a clone.

```bash
.claude/skills/run-markdownglance/setup.sh            # -> /tmp/mdglance-st
```

`MDGLANCE_ST_ROOT=/some/dir` or a positional argument chooses another root.
Nothing is written to `~/.config/sublime-text`.

## Run (agent path)

One scenario per invocation. Exit code 0 only when every phase finished and
every check passed. Evidence goes to `/tmp/mdglance-st/evidence/<scenario>-<timestamp>/`.

```bash
.claude/skills/run-markdownglance/drive.sh math          # LaTeX math, 4 phases, ~25 s
.claude/skills/run-markdownglance/drive.sh preview       # smallest scenario, 1 phase
.claude/skills/run-markdownglance/drive.sh follow_focus  # two documents, front tabs follow focus
.claude/skills/run-markdownglance/drive.sh panel_toggle  # Ctrl+Shift+B with no preview open
.claude/skills/run-markdownglance/drive.sh preview_switch # scroll, switch document, switch back
.claude/skills/run-markdownglance/drive.sh panel_navigation # a panel click moves both panes
.claude/skills/run-markdownglance/drive.sh zoom_reach     # zoom keys and wheel, real input
.claude/skills/run-markdownglance/drive.sh svg_render      # local SVG, badge and WebP, needs network and resvg
.claude/skills/run-markdownglance/drive.sh math --xvfb   # same, on a private X server
```

Output ends with a table like:

```text
math-on          done      generation=5 math-on.png
    [ok] three formulas are images
    ...
RESULT: PASS - /tmp/mdglance-st/evidence/math-20260906-155014
```

Per phase the evidence directory holds `<phase>.json` (what the live session
held: image count, placeholders, asset labels and the colour baked into each
locator, the theme, the body HTML with data URIs redacted) and, unless the
phase opts out, `<phase>.png`, a capture of the whole window. **Look at the
PNG**: the JSON proves what was rendered, the picture proves how it looks.
`console.log` is Sublime Text's stdout, which does not carry plugin prints
on this build. `--keep` leaves the window open for a human to poke at;
`--root DIR` selects another profile.

### Writing a scenario

Copy `.claude/skills/run-markdownglance/scenarios/preview.py`. A scenario
is a `PHASES` list; each phase has an `action(ctx)` run once, a
`done(ctx, snap)` predicate polled every 500 ms until true or the timeout,
and a `check(ctx, snap)` returning `{label: bool}`. `ctx` offers
`open_fixture(name)` (opens the preview too), `set_setting(file, key, value)`
(in memory, triggers the package's own settings watcher), `run(command)`,
`clipboard()`, `snapshot()` and `settled(snap)`. Fixtures live in
`.claude/skills/run-markdownglance/fixtures/`; `checker.png` there is made by
`fixtures/make_checker.py`. `scenarios/math.py` shows a settings change, a
colour-scheme switch and a diagnostics check; `scenarios/follow_focus.py` shows
two documents open at once and a check that reads the window's groups rather
than the snapshot; `scenarios/panel_toggle.py` shows a file opened without a
preview, which means `window.open_file` rather than `ctx.open_fixture` and a
`done` predicate of its own, since `ctx.settled` never holds without a session;
`scenarios/preview_switch.py` reads a view's viewport straight off the Sublime
API, and puts each `check` in the phase that observes the state rather than the
one that changes it; `scenarios/zoom_reach.py` presses real keys and turns
the real wheel with `xdotool`, which is the only way to test a keymap context
or a mousemap -- both are invisible to `window.run_command`. A path to a `.py` outside the skill also works as the
scenario argument.

## Direct invocation

Most changes touch the renderer, which needs no Sublime Text at all. With the
libraries installed for the current Python:

```bash
cd .. && python3 -m unittest discover -s MarkdownGlance/tests -t . -p 'test_*.py'
```

The checkout directory must be named `MarkdownGlance` and the tests run from
its parent; CONTRIBUTING.md lists the library pair per Python version.

## Run (human path)

`/tmp/mdglance-st/sublime_text --multiinstance` opens the portable instance
by hand; open a Markdown file and run **MarkdownGlance: Open Preview to the
Side** from the palette. Without `probe.json` beside `Data` the probe does
nothing.

## Gotchas

- **`xdotool search` ORs its conditions.** `--pid X --name Y` matches any
  Sublime Text window on the desktop; the first run of this driver resized
  and captured someone else's instance. `--all` is required and is in
  `drive.sh`.
- **A plugin that imports the package must run in the 3.8 host.** Packages
  default to Python 3.3, where `MarkdownGlance.preview` does not exist. The
  probe directory carries `.python-version` = `3.8` for that reason; a
  scenario file is imported by the probe, so it needs nothing.
- **Sublime Text follows symlinked packages.** Both the checkout and the
  probe are symlinks under `Data/Packages`, so an edit is live at the next
  launch with no copy step.
- **Settings are changed in memory.** `ctx.set_setting` calls
  `Settings.set` without `save_settings`, which is enough to fire the
  package's `add_on_change` watcher and re-render; nothing is written to
  `Data/Packages/User` by a scenario.
- **A colour-scheme change alone triggers a render** when the document has
  a Mermaid or math asset; the `light-scheme` phase relies on that and on
  `Breakers.sublime-color-scheme`, which ships with Sublime Text.
- **`import -window` needs the window on top.** `drive.sh` raises it with
  `wmctrl` first. Under Xvfb there is no window manager: `wmctrl` no-ops,
  the window is undecorated and full-size, and the capture is fine.
- **The invalid-formula phase talks to the network.** `codecogs` answers
  400 for bad LaTeX, which the preview shows as `Unavailable`; offline, every
  formula shows it and the `math-on` checks fail.
- **The preview's privacy caption appears once per render**, on the first
  formula that is not ready. A document whose formulas all render never
  shows it, so `privacy_captions == 1` depends on the fixture's bad formula.
- **The profile remembers its window layout.** `hot_exit` is off, so no files
  come back, but the splits do: a scenario that measures group widths inherits
  the previous run's groups and measures a window nobody would have. Start
  such a scenario by closing every view and setting a one-cell layout.
- **A scenario can drive the mouse**, which is the only way to test something
  a user does with the pointer -- dragging a group divider, say. `xdotool
  mousemove --sync`, `mousedown 1`, a few moves, `mouseup 1`, all of it on a
  worker thread: a synchronous call that makes the window manager talk back to
  the editor can deadlock the editor against its own plugin host. Compute the
  divider from the *live* `window.layout()` and the window geometry, and try a
  few pixels either side -- the hot spot is narrow, and a press that misses
  lands on the minimap, where a drag scrolls the file and looks like nothing
  happened.

## Troubleshooting

- `no phases.json: the probe never started` — `probe.json` was not beside
  `Data` when Sublime Text loaded, or the probe package is not linked. Run
  `setup.sh` again and check `ls -la /tmp/mdglance-st/Data/Packages`.
- `sublime_text exited before <phase>.done` — the probe hit an exception and
  exited; read `error.json` in the evidence directory.
- `MISSING (never reached)` in the table — an earlier phase timed out and the
  driver moved on; its JSON carries `"timed_out": true` and the snapshot at
  that moment.
- `Gtk-WARNING ... Could not load a pixbuf from icon theme` in `console.log`
  is normal for the portable build and harmless.
- A `(UNREGISTERED)` title is expected; the portable copy has no licence and
  needs none for this.
