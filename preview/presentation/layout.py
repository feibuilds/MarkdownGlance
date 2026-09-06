import bisect
import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from ..application.ports import GroupRole

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


class LayoutOwner:
    def __init__(self) -> None:
        self._owned: Dict[int, Dict[int, OwnedGroup]] = {}

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

    def invalidate(self, window) -> None:
        self._owned.pop(window.id(), None)
