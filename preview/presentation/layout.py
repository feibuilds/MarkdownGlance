import bisect
import json
from dataclasses import dataclass
from typing import Dict, Optional, Set, Tuple

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
    previous_layout: dict
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
        previous = layout
        share = share_for(role, width_px, group_width_px(window, anchor_group))
        updated, new_group = split_cell(layout, anchor_group, share)
        window.set_layout(updated)
        owned[new_group] = OwnedGroup(
            new_group, previous, fingerprint(updated), {session_id}, role
        )
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
            new_group, layout, fingerprint(updated), {session_id}, GroupRole.PANEL
        )
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
        owned.fingerprint = fingerprint(updated)

    def is_owned(self, window, group: int) -> bool:
        return group in self._owned.get(window.id(), {})

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
        may_restore = (
            restore
            and not window.sheets_in_group(group)
            and fingerprint(window.layout()) == owned.fingerprint
        )
        groups.pop(group, None)
        if may_restore:
            window.set_layout(owned.previous_layout)
        if not groups:
            self._owned.pop(window.id(), None)

    def invalidate(self, window) -> None:
        self._owned.pop(window.id(), None)
