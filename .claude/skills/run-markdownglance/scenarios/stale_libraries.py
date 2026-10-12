"""Libraries another Python left behind are named, not shown as a traceback.

Sublime Text 4213 replaced the Python 3.8 plugin host with 3.14 and kept
`Lib/python38` on `sys.path`. Until Package Control has installed the
libraries for 3.14, the Markdown that is found is the one installed for 3.8,
and it fails inside its own import: the preview used to open on a card
reading "Parse / AttributeError: 'EntryPoints' object has no attribute
'get'". This scenario puts such a library ahead of the real one inside the
running host, asks for a preview and reads the dialog; then takes the library
away again and asks once more. The last phase puts it back under the open
preview and edits the document, which is what a preview restored at startup
meets: a render that no command checked first. The card must carry the fix.

The dialog is `sublime.error_message`, which is modal and would stop the
probe, so it is replaced for the run and its text is kept instead.
"""

import importlib
import os
import sys

import sublime

from mdglance_probe import phase

LISTS = "MarkdownGlance.preview.renderer.lists"


class Stale:
    directory = ""
    messages = []
    error_message = None


def _forget_libraries():
    from MarkdownGlance.preview.renderer import markdown_engine

    for name in list(sys.modules):
        if name.split(".")[0] in ("markdown", "pymdownx") or name == LISTS:
            del sys.modules[name]
    markdown_engine._default = None
    importlib.invalidate_caches()


def plant(ctx):
    # `python33` is another host's directory on every build this runs on.
    Stale.directory = os.path.join(ctx.evidence, "Lib", "python33")
    package = os.path.join(Stale.directory, "markdown")
    os.makedirs(package)
    with open(os.path.join(package, "__init__.py"), "w", encoding="utf-8") as out:
        out.write(
            "raise AttributeError(\"'EntryPoints' object has no attribute 'get'\")\n"
        )
    sys.path.insert(0, Stale.directory)
    _forget_libraries()
    Stale.error_message = sublime.error_message
    sublime.error_message = Stale.messages.append
    ctx.open_fixture("preview.md")


def told(ctx, snap):
    return bool(Stale.messages)


def check_told(ctx, snap):
    message = Stale.messages[0] if Stale.messages else ""
    ctx.note("dialog: " + " | ".join(message.split("\n")))
    python = "{}.{}".format(*sys.version_info[:2])
    return {
        "one dialog": len(Stale.messages) == 1,
        "it names this python": "under Python {}.".format(python) in message,
        "it carries the exception": "AttributeError: 'EntryPoints' object" in message,
        "it says where the library was found": os.path.join(Stale.directory, "markdown")
        in message,
        "and which python that was for": "(installed for Python 3.3)" in message,
        "it names the fix": "Package Control: Satisfy Libraries" in message,
        "no preview was opened": not snap["session"]
        and ctx.container().manager.stage(ctx.window.id()) is None,
        "no group was added": ctx.window.num_groups() == 1,
    }


def remove_and_retry(ctx):
    sys.path.remove(Stale.directory)
    _forget_libraries()
    ctx.open_preview()


def check_recovered(ctx, snap):
    return {
        "the preview rendered": snap["headings"] == 3 and snap["images"] == 1,
        "no error card": snap["error_cards"] == 0,
        "no second dialog": len(Stale.messages) == 1,
    }


def _painted(ctx):
    container = ctx.container()
    stage = container.manager.stage(ctx.window.id())
    if stage is None or stage.surface is None:
        return ""
    return container.backend._html.get(stage.surface.id, "")


def plant_under_the_preview(ctx):
    sys.path.insert(0, Stale.directory)
    _forget_libraries()
    # Scratch, so the edited fixture does not ask to be saved at exit.
    ctx.view.set_scratch(True)
    ctx.view.run_command("append", {"characters": "\nOne more line.\n"})


def carded(ctx, snap):
    return "mdglance-error" in _painted(ctx)


def check_card(ctx, snap):
    sublime.error_message = Stale.error_message
    html = _painted(ctx)
    ctx.note("card: " + " ".join(html.split("mdglance-error", 1)[-1][:300].split()))
    return {
        "the card carries the exception": "AttributeError" in html
        and "EntryPoints" in html,
        "it names the fix": "Package Control: Satisfy Libraries" in html,
        "and not the console": "Show Console" not in html,
        "the document is still under it": "Preview check" in html,
        "still no second dialog": len(Stale.messages) == 1,
    }


PHASES = [
    phase("stale", action=plant, done=told, check=check_told, screenshot=False),
    phase(
        "recovered",
        action=remove_and_retry,
        done=lambda ctx, snap: ctx.settled(snap),
        check=check_recovered,
    ),
    phase(
        "stale-under-the-preview",
        action=plant_under_the_preview,
        done=carded,
        check=check_card,
    ),
]
