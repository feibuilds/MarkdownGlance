import importlib.util
import os
import re
import sys
import threading
from typing import Dict, List, Optional, Protocol

# The parser and its fence extension are Package Control libraries, declared
# in `dependencies.json` and installed beside the package rather than vendored
# with it (ADR 0012). Nothing here imports them at module level: a package
# whose import fails never loads at all, and a user whose libraries are not
# installed yet would get a traceback where a message belongs. See
# `missing_libraries` and `library_failure`.

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


def library_failure() -> Optional[BaseException]:
    """What building the engine raises, or None when the libraries work.

    `missing_libraries` says a module can be found, and a module that is found
    is not always one that imports. Sublime Text 4213 and later run plugins
    under Python 3.14 and keep `Lib/python38` on `sys.path`, so until the
    libraries for 3.14 are installed the Markdown that was installed for 3.8
    is the one found, and it fails inside its own import. Building the engine
    is what a render does, so that is the test; once it succeeds it is the
    engine every render shares, and asking again costs a lock.
    """
    try:
        default_engine()
    except Exception as error:  # an import can fail with anything
        return error
    return None


def library_locations() -> Dict[str, str]:
    """Where each library would be imported from, without importing it."""
    locations = {}
    for module, library in LIBRARIES:
        try:
            spec = importlib.util.find_spec(module)
        except Exception:  # a half-imported module has no usable spec
            spec = None
        if spec is not None and spec.origin:
            locations[library] = os.path.dirname(spec.origin)
    return locations


_HOST_DIRECTORY = re.compile(r"python(\d)(\d+)")


def other_python(location: str) -> Optional[str]:
    """The Python a library directory was filled for, when it is not this one.

    Sublime Text keeps one library directory per plugin host, `python38` or
    `python314`, and Package Control installs into the one for the host that
    is running. `None` for that one, and for a path that is not such a
    directory at all.
    """
    for part in reversed(os.path.normpath(location).split(os.sep)):
        match = _HOST_DIRECTORY.fullmatch(part)
        if match:
            version = (int(match.group(1)), int(match.group(2)))
            if version == tuple(sys.version_info[:2]):
                return None
            return "{}.{}".format(*version)
    return None
