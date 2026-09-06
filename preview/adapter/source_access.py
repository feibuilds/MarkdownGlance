"""The three things the panel needs from a source view.

They are injected into `PanelController` rather than reached for, so the
application layer never imports the Sublime API.
"""

import sublime


def read_source(view) -> str:
    return view.substr(sublime.Region(0, view.size()))


def caret_row(view) -> int:
    selection = view.sel()
    point = selection[0].begin() if len(selection) else 0
    return view.rowcol(point)[0]


def reveal_line(view, line: int) -> None:
    point = view.text_point(line, 0)
    view.sel().clear()
    view.sel().add(sublime.Region(point))
    view.show_at_center(point)
