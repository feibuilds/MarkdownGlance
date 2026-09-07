# 18. The groups a preview made outlive the process that made them

Date: 2026-09-07

## Status

Accepted. Both halves are implemented: the panes a dead process left are
either **filled again** with what was in them or **taken away**, and one
record in the window decides which.

## Context

A user reopened Sublime Text on a window that had a preview and a contents
panel in it, and got a three-column window with a Markdown source in the left
column and two blank panes beside it. Nothing in the package knew they were
there.

The session file says exactly why. In
`~/.config/sublime-text/Local/Auto Save Session.sublime_session`, the window
holding this repository was recorded as:

```json
"layout": {"cells": [[0,0,1,1],[2,0,3,1],[1,0,2,1]], "cols": [0.0, 0.428, 0.860, 1.0]}
"groups": [{"sheets": [SECURITY.md, README.md, 0017-...md]}, {"sheets": []}, {"sheets": []}]
"buffers": [SECURITY.md, README.md, 0017-...md]
```

Sublime persists **the layout** and drops **the surfaces**. A preview surface
is `window.new_file()` with `set_scratch(True)`, and a scratch buffer is not
written to the session; the three cells are, because a layout belongs to the
window rather than to any view. The two groups this package split off come
back with nothing in them.

The marks that would identify them are gone too. `mdglance.session` is set on
the surface's `view.settings()`, and only a fixed handful of view settings
survive a restart -- the sheets above carry `syntax`, `tab_size` and
`translate_tabs_to_spaces`, and nothing else. `SessionManager.reconcile` asks
`live_handles` for the views bearing that mark, gets an empty list, and cannot
tell an empty group of ours from one the user made.

Cleaning up on the way out is not an answer either. `close_all` deliberately
passes `restore=False` (`application/session_manager.py:216`), and even if it
did not, `plugin_unloaded` does not run when the process is killed or crashes,
which is the case that leaves the worst mess.

## Decision

**Write down which groups are ours, in the one place Sublime persists per
window: `window.settings()`.** Measured on build 4200: a value set there is
written into the session under the window's `settings` key and read back by
the next process, with `hot_exit` either way. It is per window, so no key has
to be invented to identify a window across a restart -- the problem a file
under `cache_path()` would have had.

The key is `mdglance.window`, and it has two writers:

```json
{"cells": 3, "groups": [[1, "preview"], [2, "panel"]],
 "document": "/home/p/dev/MarkdownGlance/README.md", "zoom": 1.2}
```

`LayoutOwner` keeps `cells` and `groups` -- which groups it holds, under which
role, and how many cells the window had when it last touched the layout. The
use cases keep `document` and `zoom`, the pane's half of what is on screen;
the panel writes the document too, because a window can have a contents panel
and no preview, and then only the panel knows which document the pane is for.
Every write merges, so neither writer can lose the other's half, and the
record goes away as a whole with the last group: a document with no pane to
put it in describes nothing. `presentation/window_record.py` is the one place
that touches the key.

Nothing records the scroll position. There is no scroll event to hang it on
and polling for one would write the session on a timer; a restored preview
opens at the top.

On the way in, the sweep runs from `Container.reconcile`, and therefore at
`plugin_loaded` for every window, at `on_init` for the windows Sublime
restored before the plugin API was ready, on every activation, and before
every command. `LayoutOwner.free_groups(window)` is the one test both halves
are decided on -- which recorded groups are still standing, and empty, keyed
by role. It answers with nothing at all unless all of these hold:

- this process owns no group in the window -- the record is a previous
  process's, not our own live state;
- the window still has the number of cells the record was written for -- the
  user has not restructured the layout since;
- the group is **empty**.

A group with a sheet in it is never in the answer, whoever made it: a user who
dragged their own file into the preview's pane keeps both.

What the two halves then do with a free group is fill it (below) or, failing
that, remove it. The removal is `_collapse`, the same code path as closing a
preview, highest group index first, so the cell's width goes back to the
neighbour it came from and the groups after it are renumbered with their
views.

**A sweep that gives nothing back leaves the record alone**, and only one
that collapsed a group erases it. This is not tidiness; it is what makes the
sweep work at all. Two moments, both measured on build 4200, look exactly
like a group that is not ours:

- At `plugin_loaded` the restored window is not settled. Sublime writes the
  preview's and the panel's scratch sheets into the session -- the window's
  `groups` came back `[1, 1, 1]` in the file -- restores them, and drops them
  a moment later, so the first sweep sees three occupied groups and the
  second sees one occupied and two empty. Erasing on the first would spend
  the record before the panes appear, which is the bug this change was
  written for and which the first version of it reproduced exactly.
- A record written by a process that was killed before the layout settled
  names a window that may not be restored yet.

The cost is a record that outlives its usefulness in the window a user has
restructured. It is a few bytes in the session, and the next preview opened
in that window overwrites it.

`plugin_unloaded` must not erase it either, and this is why `release` no
longer records: `close_all` gives up ownership with `restore=False`, which
leaves the cell in the window. Only `_collapse` -- the path that actually
takes a group out -- writes the record again.

**Filling the panes comes first, taking them away is the fallback.**
`UseCases.restore` runs from the same sweep, ahead of `reclaim`, and hot exit
is why: a user who quit with a preview open asked for it to be open, and what
was on screen coming back is the whole promise of the setting. It adopts the
free groups rather than splitting new ones -- `LayoutOwner.adopt` registers a
group that is already in the window, after which it is released and collapsed
like any other -- puts the recorded document on the preview at the recorded
zoom, and re-opens the panel in its own group. The focus stays wherever
Sublime restored it: a preview that took the focus on startup would be worse
than the blank pane it replaces.

It falls through to `reclaim` when the document is not open in the window any
more, when it was an unsaved buffer with no name to be found by, or when the
file at that path is no longer Markdown. It waits, and looks again on the next
sweep, while the view is still loading -- a file Sublime has opened but not
yet given a syntax cannot be judged either way.

A full-screen preview leaves nothing to restore, and nothing to tidy: it
stands in the source's own group and splits none, so the window has no record
and comes back as the source alone.

A restored panel is never *automatic*, whatever `enable_toc` says. One that
was on screen when Sublime closed is one the reader kept.

## Consequences

- A restart, a crash and a package reload end with the window the user left:
  the same document, in the same pane, at the same zoom, with the contents
  panel beside it if it was there -- or, when none of that can be put back,
  with the window the user would have had if the preview had never been
  opened. No blank panes either way.
- A restored preview renders on startup, which is one parse and one minihtml
  layout for one document; the render is the same one any preview pays and it
  happens off the UI thread. A document with Mermaid or math in it fetches its
  images then rather than later, but only with those settings already on.
- One `window.settings()` write per layout change this package makes: on
  opening a preview or a panel, on closing one, on a re-fit. Sublime writes
  the session itself, at its own cadence.
- Dragging the divider does not defeat it. The record holds a cell *count*,
  not the layout fingerprint `fit` compares against: a moved boundary is
  exactly what a user does to a preview pane they intend to keep, and it must
  not turn into a pane nobody can account for.
- Verified end to end against the portable build 4200 profile, with
  `hot_exit` on and two runs of the real binary each time. Preview and panel
  open, zoomed to 1.2: the session file holds
  `"settings": {"mdglance.window": {"cells": 3, "groups": [[1, "preview"], [2, "panel"]], "document": ".../README.md", "zoom": 1.2}}`,
  and the second run comes up with the preview and the panel in their panes,
  the same document on the stage, `zoom` 1.2, and the focus on the source.
  With the record's `document` edited to a path the window does not have, the
  second run comes up as one group and no record. With only a contents panel
  open, it comes back on its own.
- Splitting a pane by hand does, and deliberately. `new_pane` changes the cell
  count, `on_post_window_command` already calls `LayoutOwner.invalidate` for
  it, and the record goes with the ownership it describes.
- The record is not erased by `plugin_unloaded`. It has to survive the exit it
  describes, and a package reload wants the same sweep a restart does.
- A window from a Sublime older than this change, or one killed mid-write, has
  no record. Its empty panes stay until the user closes them -- this cleans up
  after the process, it does not go looking for panes to remove.
