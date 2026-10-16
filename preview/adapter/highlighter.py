import threading
import traceback
from collections import OrderedDict
from typing import Dict, List, Optional, Sequence, Tuple

import sublime

from ..application.errors import describe
from ..domain.contracts import ThemeSnapshot
from ..renderer.highlight import CodeBlock, CodeStyle, Run, fenced

PANEL = "mdglance-highlight"
# Marks the panel for this package's own listeners, which skip it.
HIGHLIGHTER_KEY = "mdglance.highlighter"
# Only for a source whose syntax could not be read.
MARKDOWN = "Packages/Markdown/Markdown.sublime-syntax"
# Blocks, not bytes: a block is rarely more than a few kilobytes, and a cache
# of this many covers every fence in any document anyone previews at once.
CACHE_BLOCKS = 512

CacheKey = Tuple[ThemeSnapshot, str, str]
Runs = Optional[Tuple[Run, ...]]


class SyntaxHighlighter:
    """Tokenise fenced code with Sublime Text's own syntaxes (ADR 0021).

    The blocks a render has not seen before are written into one hidden output
    panel as Markdown fences, and the panel is given the source's Markdown
    syntax and colour scheme. Each fence's language is then recognised by the
    same rule that colours it in the source -- `py` and `python` alike, every
    syntax the user has installed, nothing for a language the editor does not
    know either -- and each token's style is the one the scheme gives it
    there. The panel is destroyed again before the call returns, so that no
    Markdown buffer is left behind for another package to act on.

    It runs on a render worker. The Sublime API may be called from any thread;
    the lock is so that two renders do not write into one panel at once.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: "OrderedDict[CacheKey, Runs]" = OrderedDict()
        # The last failure, for the diagnostics: a block that cannot be
        # coloured is shown plain, so the console and this are all there is.
        self.last_error: Optional[Dict[str, object]] = None

    def __call__(
        self, blocks: Sequence[CodeBlock], theme: ThemeSnapshot
    ) -> List[Runs]:
        with self._lock:
            found: Dict[CacheKey, Runs] = {}
            missing: List[CodeBlock] = []
            for language, code in dict.fromkeys(blocks):
                key = (theme, language, code)
                if key in self._cache:
                    self._cache.move_to_end(key)
                    found[key] = self._cache[key]
                else:
                    missing.append((language, code))
            if missing:
                try:
                    tokenised = self._tokenise(missing, theme)
                except Exception as error:
                    # Not cached: a window that was closing may be back.
                    self._failed(error)
                    tokenised = None
                for (language, code), runs in zip(missing, tokenised or ()):
                    key = (theme, language, code)
                    found[key] = self._cache[key] = runs
                while len(self._cache) > CACHE_BLOCKS:
                    self._cache.popitem(last=False)
            return [found.get((theme, language, code)) for language, code in blocks]

    def _failed(self, error: BaseException) -> None:
        frames = traceback.format_exception(type(error), error, error.__traceback__)
        message = describe(error)
        if self.last_error is None or self.last_error.get("message") != message:
            print(
                "MarkdownGlance: code highlighting failed; fences are shown "
                "plain\n{}".format("".join(frames).rstrip())
            )
        self.last_error = {
            "message": message,
            "traceback": "".join(frames).rstrip().splitlines(),
        }

    def _tokenise(
        self, blocks: Sequence[CodeBlock], theme: ThemeSnapshot
    ) -> List[Runs]:
        window = sublime.active_window()
        if window is None:
            raise RuntimeError("no window to tokenise code in")
        pieces: List[str] = []
        spans: List[Tuple[int, int]] = []
        offset = 0
        for language, code in blocks:
            fence, begin, end = fenced(language, code)
            spans.append((offset + begin, offset + end))
            # A blank line between fences, as the source would have them.
            pieces.append(fence + "\n")
            offset += len(fence) + 1
        text = "".join(pieces)
        panel = window.create_output_panel(PANEL, unlisted=True)
        try:
            settings = panel.settings()
            settings.set(HIGHLIGHTER_KEY, True)
            settings.set("is_widget", True)
            for key, value in theme.scheme:
                settings.set(key, value)
            panel.assign_syntax(theme.syntax or MARKDOWN)
            panel.run_command(
                "append", {"characters": text, "force": True, "scroll_to_end": False}
            )
            if panel.size() != len(text):
                raise RuntimeError(
                    "the panel holds {} characters, not {}".format(
                        panel.size(), len(text)
                    )
                )
            styles: Dict[str, CodeStyle] = {}
            return [
                _runs(panel, code, begin, end, styles)
                for (_, code), (begin, end) in zip(blocks, spans)
            ]
        finally:
            window.destroy_output_panel(PANEL)


def _style(panel, scope: str, styles: Dict[str, CodeStyle]) -> CodeStyle:
    style = styles.get(scope)
    if style is None:
        found = panel.style_for_scope(scope)
        style = styles[scope] = CodeStyle(
            str(found.get("foreground", "")),
            bool(found.get("bold")),
            bool(found.get("italic")),
        )
    return style


def _runs(
    panel, code: str, begin: int, end: int, styles: Dict[str, CodeStyle]
) -> Runs:
    """The code cut where its tokens are, or None if they do not tile it."""
    runs: List[Run] = []
    position = begin
    for region, scope in panel.extract_tokens_with_scopes(sublime.Region(begin, end)):
        start, stop = max(region.begin(), begin), min(region.end(), end)
        if start != position or stop < start:
            return None
        runs.append((code[start - begin : stop - begin], _style(panel, scope, styles)))
        position = stop
    return tuple(runs) if position == end else None
