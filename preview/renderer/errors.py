from html import escape
from typing import Optional

from ..domain.contracts import AssetStatus, DiagnosticStage

STATUS_LABELS = {
    AssetStatus.LOADING: "Loading",
    AssetStatus.UNAVAILABLE: "Unavailable",
    AssetStatus.UNSUPPORTED_FORMAT: "Not a PNG, JPEG or GIF",
    AssetStatus.SVG_RENDERER_MISSING: "No SVG renderer",
    AssetStatus.RENDER_FAILED: "Could not be drawn",
    AssetStatus.BLOCKED: "Blocked by settings",
    AssetStatus.TOO_LARGE: "Too large",
    AssetStatus.TIMEOUT: "Timed out",
}

# What the reader can do about it, where there is something to do. An SVG is
# the case that brought this in: minihtml cannot draw one, `Open in Browser`
# hands the parser's own output to a browser, which can.
STATUS_NOTES = {
    AssetStatus.UNSUPPORTED_FORMAT: "The preview cannot draw it; Open in Browser can.",
    AssetStatus.SVG_RENDERER_MISSING: (
        "Install resvg, or set svg_renderer_path to one."
    ),
    AssetStatus.RENDER_FAILED: "The SVG renderer could not draw it.",
}


def asset_placeholder(
    status: AssetStatus, privacy: Optional[str] = None, inline: bool = False
) -> str:
    """A stand-in for an image that is not here yet, or not coming.

    Block by default. Inline, for a formula in the middle of a sentence, it is
    a `span` so that the line around it keeps its shape.
    """
    caption = STATUS_LABELS[status]
    detail = "<strong>{}</strong>".format(escape(caption))
    notes = [note for note in (STATUS_NOTES.get(status), privacy) if note]
    if inline:
        for note in notes:
            detail += " ({})".format(escape(note[0].lower() + note[1:]))
        return '<span class="mdglance-asset-placeholder-inline">{}</span>'.format(
            detail
        )
    for note in notes:
        detail += "<br /><span>{}</span>".format(escape(note))
    return '<div class="mdglance-asset-placeholder">{}</div>'.format(detail)


# Where the rest of a failure went. The card carries one line of it.
ERROR_NOTE = "Traceback: View > Show Console, or MarkdownGlance: Copy Diagnostics."


def error_card(stage: DiagnosticStage, message: str) -> str:
    return (
        '<div class="mdglance-error"><strong>{}</strong><br />{}'
        "<br /><span>{}</span></div>"
    ).format(escape(stage.value.title()), escape(message), escape(ERROR_NOTE))
