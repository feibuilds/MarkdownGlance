import bisect
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ..application.ports import GroupRole
from . import window_record

EPSILON = 1e-6


# The share of the group being split that a new group takes when its content
# cannot be measured. With a measurement it is the ceiling instead: fitting the
# content may make the group narrower than this, never wider.
ROLE_SHARE = {
    GroupRole.PREVIEW: 0.5,
    GroupRole.PANEL: 0.35,
}
# A floor, so that a document whose headings are all one word still leaves a
# group wide enough to read and to grab with the mouse.
ROLE_MINIMUM = {
    GroupRole.PREVIEW: 0.5,
    GroupRole.PANEL: 0.12,
}
# A refit moves the boundary only when it would move it visibly: the width is
# an estimate, and a group that creeps by a pixel on every keystroke is worse
# than one a few pixels wider than it needs to be.
FIT_THRESHOLD = 0.01
# No cell in a pair may be squeezed below this share of the window.
MIN_CELL = 0.05


@dataclass
class OwnedGroup:
    group: int
    # The layout this owner left when it made the group. `fit` compares it to
    # decide whether the user has dragged the divider since; releasing does
    # not, because it takes the cell out of whatever the layout is now.
    fingerprint: str
    holders: Set[str]
    role: GroupRole = GroupRole.PREVIEW


def fingerprint(layout: dict) -> str:
    return json.dumps(layout, sort_keys=True, separators=(",", ":"))


def right_neighbour(layout: dict, group: int) -> Optional[int]:
    """The group sharing this one's right edge and exact row span, if any."""
    _, r0, c1, r1 = layout["cells"][group]
    return next(
        (
            index
            for index, cell in enumerate(layout["cells"])
            if cell[0] == c1 and cell[1] == r0 and cell[3] == r1
        ),
        None,
    )


def left_neighbour(layout: dict, group: int) -> Optional[int]:
    """The group sharing this one's left edge and exact row span, if any."""
    c0, r0, _, r1 = layout["cells"][group]
    return next(
        (
            index
            for index, cell in enumerate(layout["cells"])
            if cell[2] == c0 and cell[1] == r0 and cell[3] == r1
        ),
        None,
    )


def split_cell(layout: dict, cell_index: int, new_share: float) -> Tuple[dict, int]:
    cols = list(layout["cols"])
    rows = list(layout["rows"])
    cells = [list(cell) for cell in layout["cells"]]
    c0, r0, c1, r1 = cells[cell_index]
    x0, x1 = cols[c0], cols[c1]
    x_new = x1 - (x1 - x0) * new_share
    insertion = bisect.bisect_left(cols, x_new)
    existing = insertion < len(cols) and abs(cols[insertion] - x_new) < EPSILON
    if not existing:
        cols.insert(insertion, x_new)
        for cell in cells:
            for position in (0, 2):
                if cell[position] >= insertion:
                    cell[position] += 1
    c0_after, r0_after, c1_after, r1_after = cells[cell_index]
    if not c0_after < insertion < c1_after:
        raise ValueError("split boundary does not fall inside anchor cell")
    cells[cell_index] = [c0_after, r0_after, insertion, r1_after]
    cells.append([insertion, r0_after, c1_after, r1_after])
    return {"cols": cols, "rows": rows, "cells": cells}, len(cells) - 1


def compact(layout: dict, cells: list) -> dict:
    """Rebuild a layout around a new cell list, dropping unused boundaries."""
    used_cols = sorted({index for cell in cells for index in (cell[0], cell[2])})
    used_rows = sorted({index for cell in cells for index in (cell[1], cell[3])})
    columns = {old: new for new, old in enumerate(used_cols)}
    rows = {old: new for new, old in enumerate(used_rows)}
    return {
        "cols": [layout["cols"][index] for index in used_cols],
        "rows": [layout["rows"][index] for index in used_rows],
        "cells": [
            [columns[c0], rows[r0], columns[c1], rows[r1]]
            for c0, r0, c1, r1 in cells
        ],
    }


def remove_cell(layout: dict, index: int) -> Optional[dict]:
    """The layout without one cell, its span given to a neighbour.

    The inverse of `split_cell`, except that it works on a layout that has
    moved on since: the span goes to whichever neighbour shares the cell's
    exact row span, left for preference, so every other boundary in the window
    stays where the user left it.

    Returns None when neither neighbour does -- in a grid, removing a cell
    would leave a hole no single neighbour can fill -- and when the cell is the
    only one, since a window must have a group.
    """
    cells = [list(cell) for cell in layout["cells"]]
    if not 0 <= index < len(cells) or len(cells) < 2:
        return None
    c0, _, c1, _ = cells[index]
    left = left_neighbour(layout, index)
    right = right_neighbour(layout, index)
    if left is not None:
        cells[left][2] = c1
    elif right is not None:
        cells[right][0] = c0
    else:
        return None
    del cells[index]
    return compact(layout, cells)


def group_width_px(window, group: int) -> float:
    """Measured width of a group, or 0.0 when it holds no view to measure."""
    view = window.active_view_in_group(group)
    return float(view.viewport_extent()[0]) if view is not None else 0.0


def share_for(role: GroupRole, width_px: float, pair_px: float) -> float:
    """The fraction of a cell pair a role wants, given the width of its content.

    Falls back to the role's default share whenever there is nothing to measure
    -- a group with no view in it yet, or a caller that passed no width.
    """
    default = ROLE_SHARE[role]
    if width_px <= 0.0 or pair_px <= 0.0:
        return default
    return max(ROLE_MINIMUM[role], min(default, width_px / pair_px))


def refit_cell(layout: dict, cell_index: int, share: float) -> Optional[dict]:
    """Move a cell's left edge so it takes `share` of it and its left neighbour.

    Returns None when the edge cannot be moved on its own: with no left
    neighbour, with another cell hanging off the same column -- a row split
    somewhere else in the window would be dragged along with it -- or when the
    move is too small to be worth a relayout.
    """
    left = left_neighbour(layout, cell_index)
    if left is None:
        return None
    cells = [list(cell) for cell in layout["cells"]]
    cols = list(layout["cols"])
    c0, _, c1, _ = cells[cell_index]
    if any(
        c0 in (cell[0], cell[2])
        for index, cell in enumerate(cells)
        if index not in (cell_index, left)
    ):
        return None
    x_left, x_right = cols[cells[left][0]], cols[c1]
    lower = max(cols[c0 - 1], x_left) + MIN_CELL
    upper = cols[c0 + 1] - MIN_CELL
    if lower >= upper:
        return None
    x_new = min(max(x_right - (x_right - x_left) * share, lower), upper)
    if abs(x_new - cols[c0]) < FIT_THRESHOLD:
        return None
    cols[c0] = x_new
    return {"cols": cols, "rows": list(layout["rows"]), "cells": cells}


def recorded_groups(record: dict) -> List[Tuple[int, GroupRole]]:
    """The `[group, role]` pairs in a record, dropping anything unreadable.

    A record is read back out of a session file that any version of this
    package -- or anything else -- may have written, so nothing in it is
    trusted: an entry of the wrong shape, a negative index or a role this
    version does not have is skipped rather than raising.
    """
    groups = []
    for entry in record.get("groups") or []:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            continue
        group, role = entry
        if not isinstance(group, int) or isinstance(group, bool) or group < 0:
            continue
        try:
            groups.append((group, GroupRole(role)))
        except ValueError:
            continue
    return groups


class LayoutOwner:
    def __init__(self, record=window_record) -> None:
        self._owned: Dict[int, Dict[int, OwnedGroup]] = {}
        # Where the groups this owner makes are written down, so that the
        # process after this one can find them again. See ADR 0018.
        self.record = record

    def acquire(
        self,
        window,
        anchor_group: int,
        role: GroupRole,
        session_id: str,
        width_px: float = 0.0,
    ) -> int:
        layout = window.layout()
        right_group = right_neighbour(layout, anchor_group)
        owned = self._owned.setdefault(window.id(), {})
        if right_group is not None:
            held = owned.get(right_group)
            # A pane the user opened is reused rather than split again, and so
            # is a group this owner made for the same role -- that is how a
            # second document's preview joins the first one's group. A group
            # made for a *different* role is not: the panel sits beside the
            # source until a preview exists, and a preview put inside it would
            # take the panel's place instead of appearing at all.
            if held is None or held.role == role:
                if held is not None:
                    held.holders.add(session_id)
                return right_group
        share = share_for(role, width_px, group_width_px(window, anchor_group))
        updated, new_group = split_cell(layout, anchor_group, share)
        window.set_layout(updated)
        owned[new_group] = OwnedGroup(
            new_group, fingerprint(updated), {session_id}, role
        )
        self._restamp(window, updated)
        self._record(window, updated)
        return new_group

    def acquire_panel(
        self, window, anchor_group: int, session_id: str, width_px: float = 0.0
    ) -> int:
        """The one group every panel in the window shares.

        Walks right from the document's own group, past groups this owner made
        for previews, and stops at the first group it did not make: a panel
        must never land as a tab in a pane the user opened. If the group it
        stops before is the panel group, the caller joins it as another tab;
        otherwise the walk's last group is split.

        The walk is what an earlier version got wrong, expensively. The outline
        used to walk right to the last group in the row -- the table of
        contents, whenever one was open -- and carve itself out of the
        narrowest group in the window; `fit` then measured each panel against
        the other, and a pair of headings that wanted 186 and 161 pixels ended
        up with 30 and 95. One panel group, bounded by a group that is not
        itself a panel, is what stops that happening.
        """
        layout = window.layout()
        owned = self._owned.setdefault(window.id(), {})
        group = anchor_group
        while True:
            right = right_neighbour(layout, group)
            held = owned.get(right) if right is not None else None
            if held is None:
                break
            if held.role == GroupRole.PANEL:
                held.holders.add(session_id)
                return right
            group = right
        share = share_for(GroupRole.PANEL, width_px, group_width_px(window, group))
        updated, new_group = split_cell(layout, group, share)
        window.set_layout(updated)
        owned[new_group] = OwnedGroup(
            new_group, fingerprint(updated), {session_id}, GroupRole.PANEL
        )
        self._restamp(window, updated)
        self._record(window, updated)
        return new_group

    def fit(self, window, group: int, role: GroupRole, width_px: float) -> None:
        """Re-fit an owned group to its content.

        A width of 0.0 asks for the role's default share, which is how the
        setting is turned back off. Nothing happens once the layout has stopped
        matching the one this owner set: the user has dragged the divider, and
        where they put it wins from then on.
        """
        owned = self._owned.get(window.id(), {}).get(group)
        layout = window.layout()
        if owned is None or fingerprint(layout) != owned.fingerprint:
            return
        cols, cells = layout["cols"], layout["cells"]
        left = left_neighbour(layout, group) if group < len(cells) else None
        if left is None:
            return
        c0, _, c1, _ = cells[group]
        span = cols[c1] - cols[c0]
        measured = group_width_px(window, group)
        if span <= 0.0 or measured <= 0.0:
            return
        # The window's own width is not exposed, so it comes from the group:
        # its measured pixels divided by the share of the window it holds.
        pair_px = measured / span * (cols[c1] - cols[cells[left][0]])
        updated = refit_cell(layout, group, share_for(role, width_px, pair_px))
        if updated is None:
            return
        window.set_layout(updated)
        self._restamp(window, updated)

    def is_owned(self, window, group: int) -> bool:
        return group in self._owned.get(window.id(), {})

    def release_all(self, window, session_id: str, restore: bool = True) -> None:
        """Give back every group this session holds.

        Highest group first, because releasing one can renumber the groups
        after it and a lower index never moves.
        """
        groups = self._owned.get(window.id(), {})
        held = sorted(
            (group for group, owned in groups.items() if session_id in owned.holders),
            reverse=True,
        )
        for group in held:
            self.release(window, group, session_id, restore=restore)

    def groups_of(self, window, session_id: str) -> List[int]:
        """The groups this owner is holding on one session's behalf."""
        groups = self._owned.get(window.id(), {})
        return sorted(
            group for group, owned in groups.items() if session_id in owned.holders
        )

    def release(
        self, window, group: int, session_id: str, restore: bool = True
    ) -> None:
        groups = self._owned.get(window.id(), {})
        owned = groups.get(group)
        if owned is None:
            return
        owned.holders.discard(session_id)
        if owned.holders:
            return
        empty = restore and not window.sheets_in_group(group)
        groups.pop(group, None)
        # Only `_collapse` re-records. Losing the group without giving it back
        # -- `restore=False` on unload, or a group the user has since put a
        # file in -- leaves the cell in the window, and the record has to keep
        # naming it or the next process will not know it is there.
        if empty:
            # Out of the layout the window has *now*, never out of one recorded
            # when the group was made: another group of this owner's may have
            # been added since, or the user may have dragged a divider, and
            # putting back the old layout would undo both.
            self._collapse(window, group)
        if not groups:
            self._owned.pop(window.id(), None)

    def _collapse(self, window, group: int) -> bool:
        """Take one empty group out of the window, and renumber what follows.

        Sublime keeps a view on its group *index* across `set_layout`, so
        removing a cell in the middle would leave every group after it holding
        the views of its neighbour. The views are read before the change and
        put back afterwards, and this owner's own registry is renumbered the
        same way.
        """
        layout = window.layout()
        updated = remove_cell(layout, group)
        if updated is None:
            return False
        contents = [
            list(window.views_in_group(index))
            for index in range(len(layout["cells"]))
        ]
        window.set_layout(updated)
        for index, views in enumerate(contents):
            if index == group:
                continue
            target = index - 1 if index > group else index
            for position, view in enumerate(views):
                window.set_view_index(view, target, position)
        groups = self._owned.get(window.id(), {})
        moved = {}
        for owned_group, owned in groups.items():
            if owned_group == group:
                continue
            owned.group = owned_group - 1 if owned_group > group else owned_group
            moved[owned.group] = owned
        self._owned[window.id()] = moved
        self._restamp(window, updated)
        self._record(window, updated)
        return True

    def _restamp(self, window, layout: dict) -> None:
        """Take this owner's own layout change as read.

        A fingerprint answers one question -- has the *user* moved a divider
        since we last set the layout -- so a change this owner made itself must
        not be mistaken for one, or `fit` would stop moving a group the moment
        another one was opened or closed beside it.
        """
        stamp = fingerprint(layout)
        for owned in self._owned.get(window.id(), {}).values():
            owned.fingerprint = stamp

    def _record(self, window, layout: Optional[dict] = None) -> None:
        """Name this owner's groups for whatever process reads the window next.

        Each group goes down with its role, so that a restore can put the
        preview back in the preview's pane and the panel in the panel's. The
        cell count goes with them, as the one check that the window is still
        the shape the record was written for -- not the fingerprint `fit`
        compares against: a dragged divider is what a user does to a pane they
        mean to keep, and it must not turn the pane into one nobody can
        account for.

        Losing the last group clears the whole record, document and all: there
        is nothing left to restore into.
        """
        owned = self._owned.get(window.id())
        if not owned:
            self.record.clear(window)
            return
        cells = layout if layout is not None else window.layout()
        self.record.update(
            window,
            cells=len(cells["cells"]),
            groups=[[group, owned[group].role.value] for group in sorted(owned)],
        )

    def free_groups(self, window) -> Dict[GroupRole, int]:
        """The recorded groups still standing empty in this window, by role.

        Empty is the whole test, and it is made once here for both callers:
        `reclaim` collapses what this returns, a restore fills it. A group with
        a sheet in it -- a file the user dragged in, or a scratch sheet the
        restored session has not finished dropping -- is not in it, and neither
        is anything at all while this process holds groups of its own or the
        window has stopped being the shape the record describes.
        """
        if self._owned.get(window.id()):
            return {}
        record = self.record.read(window)
        cells = len(window.layout()["cells"])
        if record.get("cells") != cells:
            return {}
        return {
            role: group
            for group, role in recorded_groups(record)
            if group < cells and not window.sheets_in_group(group)
        }

    def adopt(self, window, group: int, role: GroupRole, session_id: str) -> None:
        """Take a group a previous process made as this owner's own.

        The group is already in the window -- the layout outlived the process
        that split it -- so there is nothing to lay out, only a registry to
        fill in, and from here on the group is released and collapsed like any
        other.
        """
        owned = self._owned.setdefault(window.id(), {})
        owned[group] = OwnedGroup(
            group, fingerprint(window.layout()), {session_id}, role
        )
        self._record(window)

    def reclaim(self, window) -> bool:
        """Take back the groups a previous process left empty in this window.

        The layout a preview split off outlives the process that made it --
        across a restart, a crash, or a package reload -- and the surface that
        justified it does not, so the user is left with a blank pane nothing
        owns. This is the sweep for that, and the record written by `_record`
        is the only thing that says which groups they are.

        It acts on a window this process holds nothing in, and only on a group
        that is genuinely empty in a layout still the shape the record
        describes. A group with a sheet in it is never removed, whoever put it
        there. The record survives a sweep that gave nothing back, because at
        `plugin_loaded` a restored window has not finished settling and a
        group that is about to be empty still looks occupied; only a sweep
        that actually collapsed a group ends it.
        """
        record = self.record.read(window)
        if not record:
            # Nothing recorded, or something that is not a record at all.
            self.record.clear(window)
            return False
        free = self.free_groups(window)
        if not free:
            return False
        # What the sweep cannot take now -- a group still holding a sheet --
        # stays recorded, renumbered as each cell above it goes, or the pane it
        # is in would be left with nothing to account for it when it does empty.
        remaining = [
            [group, role.value]
            for group, role in recorded_groups(record)
            if group not in free.values()
        ]
        collapsed = False
        for group in sorted(free.values(), reverse=True):
            if not self._collapse(window, group):
                continue
            collapsed = True
            remaining = [
                [index - 1 if index > group else index, role]
                for index, role in remaining
            ]
        if not collapsed:
            return False
        if remaining:
            # `_collapse` cleared the record on the way past, this owner having
            # nothing of its own in the window; the rest of it goes back.
            record["cells"] = len(window.layout()["cells"])
            record["groups"] = remaining
            self.record.update(window, **record)
        else:
            self.record.clear(window)
        return True

    def invalidate(self, window) -> None:
        self._owned.pop(window.id(), None)
        self._record(window)
