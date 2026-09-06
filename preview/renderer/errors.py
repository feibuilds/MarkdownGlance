from html import escape
from typing import Optional

from ..domain.contracts import AssetStatus, DiagnosticStage

STATUS_LABELS = {
    AssetStatus.LOADING: "Loading",
    AssetStatus.UNAVAILABLE: "Unavailable",
    AssetStatus.BLOCKED: "Blocked by settings",
    AssetStatus.TOO_LARGE: "Too large",
    AssetStatus.TIMEOUT: "Timed out",
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
    if inline:
        if privacy:
            detail += " ({})".format(escape(privacy[0].lower() + privacy[1:]))
        return '<span class="mdglance-asset-placeholder-inline">{}</span>'.format(
            detail
        )
    if privacy:
        detail += "<br /><span>{}</span>".format(escape(privacy))
    return '<div class="mdglance-asset-placeholder">{}</div>'.format(detail)


def error_card(stage: DiagnosticStage, message: str) -> str:
    return '<div class="mdglance-error"><strong>{}</strong><br />{}</div>'.format(
        escape(stage.value.title()), escape(message)
    )
