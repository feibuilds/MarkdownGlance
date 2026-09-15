"""A render failure names its cause.

Issue #5: a user on macOS saw "Serialise / Render failed" for a two-line
document, and the diagnostics they pasted said the same and nothing more.
Every exception on the render pool was folded into that one card, which is
not enough to act on. This scenario breaks the Markdown engine the way a
library that fails to import does, opens a document, and reads the card and
the diagnostics record that the failure leaves behind.
"""

from mdglance_probe import phase


class BrokenEngine:
    def convert(self, source):
        raise ModuleNotFoundError("No module named 'pymdownx.superfences'")


def break_engine(ctx):
    from MarkdownGlance.preview.renderer import markdown_engine

    markdown_engine._default = BrokenEngine()
    ctx.open_fixture("preview.md")


def failed(ctx, snap):
    return any(
        stage.startswith("error:") for stage in ctx.container().recent_stages
    )


def _painted(ctx):
    container = ctx.container()
    stage = container.manager.stage(ctx.window.id())
    if stage is None or stage.surface is None:
        return ""
    return container.backend._html.get(stage.surface.id, "")


def check(ctx, snap):
    import json

    html = _painted(ctx)
    ctx.note("card: " + " ".join(html.split("mdglance-error", 1)[-1][:200].split()))
    ctx.run("mdglance_copy_diagnostics")
    diagnostics = json.loads(ctx.clipboard())
    last_error = diagnostics.get("last_error") or {}
    libraries = diagnostics.get("libraries") or {}
    ctx.note("last_error: " + json.dumps(last_error)[:300])
    ctx.note("libraries: " + json.dumps(libraries))
    return {
        "error card painted": "mdglance-error" in html,
        "card names the stage": "<strong>Parse</strong>" in html,
        "card names the exception": "ModuleNotFoundError" in html,
        "card names the library": "pymdownx.superfences" in html,
        "card says where the traceback is": "Show Console" in html,
        "diagnostics carry the traceback": "ModuleNotFoundError" in "".join(
            last_error.get("traceback", ())
        ),
        "diagnostics name the stage": last_error.get("stage") == "parse",
        "diagnostics report both libraries": all(
            "version" in libraries.get(name, {})
            for name in ("Markdown", "pymdown-extensions")
        ),
    }


PHASES = [phase("broken-engine", action=break_engine, done=failed, check=check)]
