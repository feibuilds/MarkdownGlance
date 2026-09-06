import importlib.util
import threading
from typing import Dict, List, Optional, Protocol

# The parser and its fence extension are Package Control libraries, declared
# in `dependencies.json` and installed beside the package rather than vendored
# with it (ADR 0012). Nothing here imports them at module level: a package
# whose import fails never loads at all, and a user whose libraries are not
# installed yet would get a traceback where a message belongs. See
# `missing_libraries`.

MARKDOWN_EXTENSIONS = (
    "pymdownx.superfences",
    "pymdownx.highlight",
    "pymdownx.arithmatex",
    "tables",
    "sane_lists",
)

# superfences hands a fenced block to Pygments whenever Pygments can be
# imported, and Pygments is itself a Package Control library that other
# packages install. Highlighted, a block is `<div class="highlight"><pre>`
# with no `code` element and no language class, which is not a fenced block
# to the structural pass and not a Mermaid diagram at all. Off, always.
#
# arithmatex finds `$...$`, `$$...$$`, `\(...\)` and `\[...\]` and, in
# generic mode, wraps each in `<span class="arithmatex">` or a `div` for
# something else to typeset -- MathJax on a web page, the structural pass
# here. Its default `smart_dollar` leaves `$5 and $6` alone.
EXTENSION_CONFIGS: Dict[str, Dict[str, object]] = {
    "pymdownx.highlight": {"use_pygments": False},
    "pymdownx.arithmatex": {"generic": True},
}

LIBRARIES = (("markdown", "Markdown"), ("pymdownx", "pymdown-extensions"))


def missing_libraries() -> List[str]:
    """The Package Control library names that are not importable.

    `find_spec` looks the module up without importing it, so this is safe to
    call at plugin load and costs nothing when everything is in place.
    """
    return [
        library
        for module, library in LIBRARIES
        if importlib.util.find_spec(module) is None
    ]


class MarkdownEngine(Protocol):
    def convert(self, source: str) -> str: ...


def build_markdown(extra_extensions: Optional[list] = None):
    """A configured `markdown.Markdown`, with our list preprocessor attached."""
    import markdown

    from .lists import ListExtension

    return markdown.Markdown(
        extensions=[*MARKDOWN_EXTENSIONS, ListExtension(), *(extra_extensions or [])],
        extension_configs=EXTENSION_CONFIGS,
    )


class PythonMarkdownEngine:
    extensions = MARKDOWN_EXTENSIONS

    def __init__(self) -> None:
        self._engine = build_markdown()
        # A Markdown instance keeps parse state between calls, and two render
        # workers may convert at once.
        self._lock = threading.Lock()

    @property
    def version(self) -> str:
        import markdown

        return str(markdown.__version__)

    def convert(self, source: str) -> str:
        with self._lock:
            self._engine.reset()
            return str(self._engine.convert(source))


_default: Optional[PythonMarkdownEngine] = None
_default_lock = threading.Lock()


def default_engine() -> MarkdownEngine:
    """The shared engine, built on first use rather than at import."""
    global _default
    with _default_lock:
        if _default is None:
            _default = PythonMarkdownEngine()
        return _default
