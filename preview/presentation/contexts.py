import sublime


def context_result(actual, operator, operand):
    expected = bool(operand)
    if operator == sublime.OP_NOT_EQUAL:
        return actual != expected
    return actual == expected


def preview_focused(window, backend):
    sheet = window.active_sheet() if window else None
    return bool(sheet and backend.owner_of(sheet))


def panel_focused(window, owns_surface):
    sheet = window.active_sheet() if window else None
    view = sheet.view() if sheet is not None else None
    return bool(view is not None and owns_surface(view.id()))


def markdown_source(view):
    return bool(view and view.match_selector(0, "text.html.markdown"))
