"""What one process leaves in a window for the next one to read.

Sublime persists `window.settings()` into the session and hands it back to the
window when the session is restored -- measured on build 4200 -- and persists
nothing else this package could use. A preview surface is a scratch buffer,
which is not written to the session at all; the marks that identify one are
view settings, and only a fixed handful of those survive a restart. So one key
holds everything a restart needs to know: which groups this package split off,
how many cells the window had when it did, and which document was on the
preview. See ADR 0018.

The two halves are written by two owners -- `LayoutOwner` keeps `cells` and
`groups`, the use cases keep `document` and `zoom` -- so every write merges
rather than replaces, and the record goes away as a whole when the last group
does: a document with no pane to put it in describes nothing.
"""

KEY = "mdglance.window"


def read(window) -> dict:
    """The record, or an empty one. Never raises on a value someone else set."""
    record = window.settings().get(KEY)
    return dict(record) if isinstance(record, dict) else {}


def update(window, **fields) -> None:
    """Merge fields into the record, leaving the rest of it as it was."""
    record = read(window)
    record.update(fields)
    window.settings().set(KEY, record)


def update_existing(window, **fields) -> None:
    """Merge, but only into a record that is already there.

    Which groups are ours is what makes a record worth keeping. A window whose
    preview is in full screen owns no group, so it has no record, and the
    document on that preview must not create one: there would be no pane to
    restore it into.
    """
    if read(window):
        update(window, **fields)


def remember_document(window, path) -> None:
    """Put the document on an existing record, if it is not already there.

    The panel repaints far more often than the document under it changes -- a
    caret move is a repaint -- so this compares before it writes.
    """
    record = read(window)
    if record and record.get("document") != path:
        record["document"] = path
        window.settings().set(KEY, record)


def clear(window) -> None:
    window.settings().erase(KEY)
