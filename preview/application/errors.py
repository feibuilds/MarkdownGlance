from typing import Optional

from ..domain.contracts import DiagnosticStage


def describe(error: BaseException) -> str:
    """The exception as one line a reader can act on: its class and message.

    `ModuleNotFoundError: No module named 'pymdownx.superfences'` says which
    library is broken; "Render failed" said nothing, and that was all the
    preview and the diagnostics carried for issue #5.
    """
    text = str(error).strip()
    name = type(error).__name__
    return "{}: {}".format(name, text) if text else name


class RenderFailure(Exception):
    """A stage of the render pipeline failed.

    `cause` is the exception the stage raised, kept so that the adapter can
    print its traceback to the console and record it in the diagnostics.
    """

    def __init__(
        self, stage: DiagnosticStage, message: str, cause: Optional[BaseException] = None
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.safe_message = message
        self.cause = cause

    @classmethod
    def wrap(cls, stage: DiagnosticStage, error: BaseException) -> "RenderFailure":
        failure = cls(stage, describe(error), error)
        failure.__cause__ = error
        return failure
