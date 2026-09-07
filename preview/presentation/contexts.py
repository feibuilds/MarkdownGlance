import sublime


def context_result(actual, operator, operand):
    expected = bool(operand)
    if operator == sublime.OP_NOT_EQUAL:
        return actual != expected
    return actual == expected


def preview_focused(view, backend):
    """True when the view the event is about is one this package created.

    The *view* rather than the window's active sheet, because a mouse binding
    is asked about the view under the pointer: `Ctrl`-scrolling a preview you
    are reading should zoom it, and the wheel does not move the focus. For a
    key press the two are the same view.
    """
    return bool(view is not None and backend.owner_of(view))


def preview_open(window, has_stage):
    """True when this window has a preview, focused or not.

    Zoom keys pressed in the Markdown source are meant for it: the source has
    the focus because that is where you last typed, not because it is what you
    are looking at.
    """
    return bool(window is not None and has_stage(window.id()))


def panel_focused(window, owns_surface):
    sheet = window.active_sheet() if window else None
    view = sheet.view() if sheet is not None else None
    return bool(view is not None and owns_surface(view.id()))


def markdown_source(view):
    return bool(view and view.match_selector(0, "text.html.markdown"))
