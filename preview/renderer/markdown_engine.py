import threading
from typing import Protocol

# Both are Package Control libraries, declared in `dependencies.json` and
# installed beside the package rather than vendored with it. See ADR 0012.
import markdown

from .lists import ListExtension

MARKDOWN_EXTENSIONS = (
    "pymdownx.superfences",
    "tables",
)


class MarkdownEngine(Protocol):
    def convert(self, source: str) -> str: ...


class PythonMarkdownEngine:
    version = markdown.__version__
    extensions = MARKDOWN_EXTENSIONS

    def __init__(self) -> None:
        self._engine = markdown.Markdown(
            extensions=[*self.extensions, ListExtension()]
        )
        # A Markdown instance keeps parse state between calls, and two render
        # workers may convert at once.
        self._lock = threading.Lock()

    def convert(self, source: str) -> str:
        with self._lock:
            self._engine.reset()
            return str(self._engine.convert(source))


DEFAULT_ENGINE = PythonMarkdownEngine()
