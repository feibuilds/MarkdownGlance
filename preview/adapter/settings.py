from dataclasses import asdict
from typing import Callable

import sublime

from ..domain.contracts import RenderSettings
from ..domain.settings import parse_settings

SETTING_KEYS = tuple(asdict(RenderSettings()).keys())
RENDER_KEYS = frozenset(
    (
        "enable_mermaid",
        "mermaid_server",
        "enable_math",
        "math_server",
        "table_max_columns",
        "enable_toc",
        "toc_minimum_length",
        "toc_minimum_headings",
        "auto_width",
    )
)
POLICY_KEYS = frozenset(
    (
        "allow_insecure_remote_images",
        "remote_timeout_seconds",
        "remote_max_bytes",
        "remote_max_dimension",
    )
)


class SettingsAdapter:
    def __init__(self, changed: Callable[[bool, bool], None]) -> None:
        self._settings = sublime.load_settings("MarkdownGlance.sublime-settings")
        self._changed_callback = changed
        self._current = self._load()
        self._settings.add_on_change("mdglance", self._changed)

    def _load(self) -> RenderSettings:
        defaults = asdict(RenderSettings())
        values = {key: self._settings.get(key, defaults[key]) for key in SETTING_KEYS}
        return parse_settings(
            values, lambda message: print("MarkdownGlance: " + message)
        )

    def _changed(self) -> None:
        previous = self._current
        current = self._load()
        self._current = current
        changed = {
            key
            for key in SETTING_KEYS
            if getattr(previous, key) != getattr(current, key)
        }
        self._changed_callback(bool(changed & RENDER_KEYS), bool(changed & POLICY_KEYS))

    def get(self) -> RenderSettings:
        return self._current

    def detach(self) -> None:
        self._settings.clear_on_change("mdglance")
