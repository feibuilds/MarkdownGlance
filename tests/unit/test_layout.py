import copy
import unittest

from MarkdownGlance.preview.application.ports import GroupRole
from MarkdownGlance.preview.presentation.layout import (
    ROLE_MINIMUM,
    ROLE_SHARE,
    LayoutOwner,
    left_neighbour,
    refit_cell,
    share_for,
    split_cell,
)


class FakeView:
    """A view whose viewport is the group's share of a 1000 px window."""

    def __init__(self, width):
        self.width = width

    def viewport_extent(self):
        return (self.width, 800.0)


class FakeWindow:
    WIDTH = 1000.0

    def __init__(self, layout):
        self._layout = copy.deepcopy(layout)
        self._sheets = {}
        self.empty_groups = set()

    def id(self):
        return 1

    def layout(self):
        return copy.deepcopy(self._layout)

    def set_layout(self, layout):
        self._layout = copy.deepcopy(layout)

    def sheets_in_group(self, group):
        return self._sheets.get(group, [])

    def active_view_in_group(self, group):
        if group in self.empty_groups or group >= len(self._layout["cells"]):
            return None
        c0, _, c1, _ = self._layout["cells"][group]
        cols = self._layout["cols"]
        return FakeView((cols[c1] - cols[c0]) * self.WIDTH)


ONE = {"cols": [0.0, 1.0], "rows": [0.0, 1.0], "cells": [[0, 0, 1, 1]]}


def width_of(window, group):
    """A group's width in the fake window's pixels."""
    return window.active_view_in_group(group).viewport_extent()[0]


class LayoutTest(unittest.TestCase):
    def test_split_one_by_one(self):
        layout, group = split_cell(ONE, 0, 0.5)
        self.assertEqual(group, 1)
        self.assertEqual(layout["cols"], [0.0, 0.5, 1.0])
        self.assertEqual(layout["cells"], [[0, 0, 1, 1], [1, 0, 2, 1]])

    def test_split_nested_span_preserves_other_geometry(self):
        layout = {
            "cols": [0.0, 0.25, 0.5, 1.0],
            "rows": [0.0, 0.5, 1.0],
            "cells": [[0, 0, 3, 1], [0, 1, 1, 2], [1, 1, 2, 2], [2, 1, 3, 2]],
        }
        result, new_group = split_cell(layout, 0, 0.5)
        self.assertEqual(result["cells"][1:], layout["cells"][1:] + [[2, 0, 3, 1]])
        self.assertEqual(new_group, 4)

    def test_existing_coincident_boundary_is_reused(self):
        layout = {
            "cols": [0.0, 0.5, 1.0],
            "rows": [0.0, 0.5, 1.0],
            "cells": [[0, 0, 2, 1], [0, 1, 1, 2], [1, 1, 2, 2]],
        }
        result, _ = split_cell(layout, 0, 0.5)
        self.assertEqual(result["cols"], layout["cols"])

    def test_acquire_beside_never_shares_an_existing_group(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "preview")
        outline = owner.acquire_beside(window, 0, GroupRole.OUTLINE, "outline")
        self.assertNotEqual(outline, preview)
        self.assertTrue(owner.is_owned(window, outline))
        self.assertEqual(len(window.layout()["cells"]), 3)

    def test_a_panel_is_never_split_out_of_another_panel(self):
        """Issue #4: the outline used to be carved out of the table of contents.

        Walking right to the last group in the row landed on the table of
        contents whenever one was open, so both panels ended up measured
        against each other and neither could reach the width its entries
        needed. Every panel must border a group that is not itself a panel.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        toc = owner.acquire(window, preview, GroupRole.TOC, "session", 160.0)
        outline = owner.acquire_beside(window, 0, GroupRole.OUTLINE, "outline", 190.0)

        layout = window.layout()
        self.assertEqual(len({preview, toc, outline}), 3)
        # The outline borders the source, which no session owns.
        self.assertEqual(left_neighbour(layout, outline), 0)
        self.assertFalse(owner.is_owned(window, 0))
        # And the table of contents keeps the width it was given.
        self.assertAlmostEqual(width_of(window, toc), 160.0, places=6)

    def test_two_panels_both_reach_the_width_their_entries_need(self):
        """Each panel gets what it asks for, up to its own role share.

        Measured before the fix, on a 1920 px window: a table of contents that
        wanted 161 px got 95, and an outline that wanted 186 px got 30, because
        the second panel was carved out of the first. The widths here are the
        same shape against this fake window's 1000 px.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        toc = owner.acquire(window, preview, GroupRole.TOC, "session", 140.0)
        outline = owner.acquire_beside(window, 0, GroupRole.OUTLINE, "outline", 120.0)
        self.assertAlmostEqual(width_of(window, toc), 140.0, places=6)
        self.assertAlmostEqual(width_of(window, outline), 120.0, places=6)

    def test_a_panel_wider_than_its_role_share_is_still_capped(self):
        """The ceiling is deliberate: one long heading may not take the window.

        This is why a heading long enough to want 945 px still wraps, and why
        the manual plan's "no entry may wrap" holds only for entries that fit
        inside the share.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        outline = owner.acquire_beside(window, 0, GroupRole.OUTLINE, "outline", 900.0)
        self.assertAlmostEqual(
            width_of(window, outline), 500.0 * ROLE_SHARE[GroupRole.OUTLINE], places=6
        )

    def test_the_outline_still_never_lands_in_the_preview_group(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "preview")
        outline = owner.acquire_beside(window, 0, GroupRole.OUTLINE, "outline")
        self.assertNotEqual(outline, preview)
        self.assertTrue(owner.is_owned(window, outline))
        self.assertEqual(len(window.layout()["cells"]), 3)

    def test_owner_restores_only_exact_empty_layout(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        group = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        owner.release(window, group, "session", restore=True)
        self.assertEqual(window.layout(), ONE)

        group = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        changed = window.layout()
        changed["cols"][1] = 0.6
        window.set_layout(changed)
        owner.release(window, group, "session", restore=True)
        self.assertEqual(window.layout(), changed)


class ShareTest(unittest.TestCase):
    def test_a_measurement_narrows_but_never_widens(self):
        self.assertEqual(share_for(GroupRole.TOC, 200.0, 1000.0), 0.2)
        self.assertEqual(
            share_for(GroupRole.TOC, 900.0, 1000.0), ROLE_SHARE[GroupRole.TOC]
        )

    def test_a_short_list_still_leaves_a_usable_group(self):
        self.assertEqual(
            share_for(GroupRole.OUTLINE, 10.0, 1000.0), ROLE_MINIMUM[GroupRole.OUTLINE]
        )

    def test_nothing_measured_falls_back_to_the_role_share(self):
        for width, pair in ((0.0, 1000.0), (200.0, 0.0)):
            self.assertEqual(
                share_for(GroupRole.TOC, width, pair), ROLE_SHARE[GroupRole.TOC]
            )


class RefitTest(unittest.TestCase):
    TWO = {
        "cols": [0.0, 0.65, 1.0],
        "rows": [0.0, 1.0],
        "cells": [[0, 0, 1, 1], [1, 0, 2, 1]],
    }

    def test_only_the_shared_boundary_moves(self):
        result = refit_cell(self.TWO, 1, 0.2)
        self.assertEqual(result["cols"], [0.0, 0.8, 1.0])
        self.assertEqual(result["cells"], self.TWO["cells"])

    def test_the_leftmost_cell_has_nothing_to_take_from(self):
        self.assertIsNone(refit_cell(self.TWO, 0, 0.2))

    def test_a_move_too_small_to_see_is_not_made(self):
        self.assertIsNone(refit_cell(self.TWO, 1, 0.352))

    def test_a_column_another_cell_hangs_off_is_left_alone(self):
        layout = {
            "cols": [0.0, 0.65, 1.0],
            "rows": [0.0, 0.5, 1.0],
            "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [0, 1, 1, 2], [1, 1, 2, 2]],
        }
        self.assertIsNone(refit_cell(layout, 1, 0.2))

    def test_neither_cell_is_squeezed_out_of_existence(self):
        result = refit_cell(self.TWO, 1, 0.99)
        self.assertEqual(result["cols"][1], 0.05)


class FitTest(unittest.TestCase):
    def owner_with_toc(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        group = owner.acquire(window, 0, GroupRole.TOC, "session")
        # 0.35 of a 1000 px window, before anything has been measured.
        self.assertAlmostEqual(window.layout()["cols"][1], 0.65)
        return window, owner, group

    def test_fitting_narrows_the_group_to_the_width_asked_for(self):
        window, owner, group = self.owner_with_toc()
        owner.fit(window, group, GroupRole.TOC, 200.0)
        self.assertAlmostEqual(window.layout()["cols"][1], 0.8)

    def test_a_later_fit_can_widen_again_up_to_the_role_share(self):
        window, owner, group = self.owner_with_toc()
        owner.fit(window, group, GroupRole.TOC, 200.0)
        owner.fit(window, group, GroupRole.TOC, 900.0)
        self.assertAlmostEqual(window.layout()["cols"][1], 0.65)

    def test_a_group_the_user_has_dragged_is_never_moved_again(self):
        window, owner, group = self.owner_with_toc()
        dragged = window.layout()
        dragged["cols"][1] = 0.5
        window.set_layout(dragged)
        owner.fit(window, group, GroupRole.TOC, 200.0)
        self.assertEqual(window.layout(), dragged)

    def test_fitting_a_group_this_owner_did_not_make_does_nothing(self):
        window, owner, _ = self.owner_with_toc()
        owner.fit(window, 0, GroupRole.TOC, 200.0)
        self.assertAlmostEqual(window.layout()["cols"][1], 0.65)

    def test_an_empty_group_cannot_be_measured_so_is_left_alone(self):
        window, owner, group = self.owner_with_toc()
        window.empty_groups.add(group)
        owner.fit(window, group, GroupRole.TOC, 200.0)
        self.assertAlmostEqual(window.layout()["cols"][1], 0.65)

    def test_a_fitted_group_is_still_restored_when_it_is_released(self):
        window, owner, group = self.owner_with_toc()
        owner.fit(window, group, GroupRole.TOC, 200.0)
        owner.release(window, group, "session", restore=True)
        self.assertEqual(window.layout(), ONE)
