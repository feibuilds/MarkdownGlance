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
        self._views = {}
        self.empty_groups = set()

    def id(self):
        return 1

    def layout(self):
        return copy.deepcopy(self._layout)

    def set_layout(self, layout):
        self._layout = copy.deepcopy(layout)

    def sheets_in_group(self, group):
        return self._sheets.get(group, [])

    def views_in_group(self, group):
        return list(self._views.get(group, []))

    def set_view_index(self, view, group, index):
        for views in self._views.values():
            if view in views:
                views.remove(view)
        self._views.setdefault(group, []).insert(index, view)

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

    def test_the_panel_never_lands_in_the_preview_group(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        panel = owner.acquire_panel(window, 0, "session")
        self.assertNotEqual(panel, preview)
        self.assertTrue(owner.is_owned(window, panel))
        self.assertEqual(len(window.layout()["cells"]), 3)

    def test_the_panel_is_split_out_of_the_preview_not_the_source(self):
        """Issue #4: the outline used to be carved out of the table of contents.

        There were two panels then, and walking right to the last group in the
        row landed on the table of contents whenever one was open, so each was
        measured against the other and neither could reach the width its
        entries needed -- 161 px wanted and 95 given, 186 wanted and 30 given,
        measured on a 1920 px window. There is one panel now, and the walk
        stops at the first group this owner did not make.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        panel = owner.acquire_panel(window, 0, "session", 160.0)

        layout = window.layout()
        self.assertEqual(left_neighbour(layout, panel), preview)
        self.assertFalse(owner.is_owned(window, 0))
        self.assertAlmostEqual(width_of(window, panel), 160.0, places=6)

    def test_a_second_document_joins_the_one_panel_group(self):
        """One panel group per window, however many documents are open in it."""
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "first")
        first = owner.acquire_panel(window, 0, "first", 140.0)
        cells = len(window.layout()["cells"])

        second = owner.acquire_panel(window, 0, "second", 140.0)

        self.assertEqual(second, first)
        self.assertEqual(len(window.layout()["cells"]), cells)
        # Held by both, so one closing does not take the group away.
        owner.release(window, first, "first")
        self.assertTrue(owner.is_owned(window, first))

    def test_the_panel_never_lands_in_a_pane_the_user_opened(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        # A second cell this owner did not make: the user's own split.
        theirs, _ = split_cell(window.layout(), 0, 0.5)
        window.set_layout(theirs)

        panel = owner.acquire_panel(window, 0, "session")

        self.assertNotEqual(panel, 1)
        self.assertEqual(len(window.layout()["cells"]), 3)

    def test_a_preview_is_never_opened_inside_the_panel_group(self):
        """The panel opens beside the source before any preview exists.

        Reusing the group to the right of the source would then put the
        preview into the panel's own group, where it takes the panel's place
        rather than appearing beside it -- and the command looks like it did
        nothing at all.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        panel = owner.acquire_panel(window, 0, "session")

        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        self.assertNotEqual(preview, panel)
        self.assertEqual(len(window.layout()["cells"]), 3)
        # Source, preview, panel, in that order.
        layout = window.layout()
        self.assertEqual(left_neighbour(layout, preview), 0)
        self.assertEqual(left_neighbour(layout, panel), preview)

    def test_a_second_preview_still_joins_the_first_ones_group(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        first = owner.acquire(window, 0, GroupRole.PREVIEW, "first")

        second = owner.acquire(window, 0, GroupRole.PREVIEW, "second")

        self.assertEqual(second, first)
        owner.release(window, first, "first")
        self.assertTrue(owner.is_owned(window, first))

    def test_a_pane_the_user_opened_is_still_reused(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        theirs, _ = split_cell(window.layout(), 0, 0.5)
        window.set_layout(theirs)

        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        self.assertEqual(preview, 1)
        self.assertEqual(len(window.layout()["cells"]), 2)

    def test_a_panel_wider_than_its_role_share_is_still_capped(self):
        """The ceiling is deliberate: one long heading may not take the window.

        This is why a heading long enough to want 945 px still wraps, and why
        the manual plan's "no entry may wrap" holds only for entries that fit
        inside the share.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        panel = owner.acquire_panel(window, 0, "session", 900.0)
        self.assertAlmostEqual(
            width_of(window, panel), 500.0 * ROLE_SHARE[GroupRole.PANEL], places=6
        )

    def test_an_untouched_layout_is_put_back_exactly(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        group = owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        owner.release(window, group, "session", restore=True)

        self.assertEqual(window.layout(), ONE)

    def test_a_layout_that_has_moved_loses_the_empty_cell_instead(self):
        """Restoring what was recorded would undo the drag as well."""
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        group = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        changed = window.layout()
        changed["cols"][1] = 0.6
        window.set_layout(changed)

        owner.release(window, group, "session", restore=True)

        # One group again, and the boundary the user dragged is simply gone
        # with the cell it belonged to.
        self.assertEqual(window.layout(), ONE)

    def test_one_panel_fitting_does_not_freeze_the_other_group(self):
        """A fingerprint asks whether the *user* moved a divider.

        Every group of this owner's shares one, so a change this owner made
        itself -- a fit, a split, a collapse -- has to be taken as read, or the
        first fit would look like a drag to every other group and freeze it.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        panel = owner.acquire_panel(window, 0, "session", 200.0)

        owner.fit(window, preview, GroupRole.PREVIEW, 300.0)
        owner.fit(window, panel, GroupRole.PANEL, 150.0)

        self.assertAlmostEqual(width_of(window, panel), 150.0, places=6)

    def test_a_group_that_is_not_empty_is_left_alone(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        group = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        window._sheets[group] = ["a sheet"]
        before = window.layout()

        owner.release(window, group, "session", restore=True)

        self.assertEqual(window.layout(), before)

    def test_closing_a_panel_between_two_groups_moves_the_views_down(self):
        """Sublime keeps a view on its group index across `set_layout`.

        The panel can be opened before the preview, which makes it cell 1 and
        the preview cell 2. Dropping cell 1 renumbers the preview to 1, and
        its views have to be carried across or they stay in a group that is
        now the panel's old space.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        panel = owner.acquire_panel(window, 0, "session")
        preview = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        self.assertEqual((panel, preview), (1, 2))
        window._views = {0: ["source"], 2: ["preview view"]}

        owner.release(window, panel, "session", restore=True)

        self.assertEqual(len(window.layout()["cells"]), 2)
        self.assertEqual(window.views_in_group(0), ["source"])
        self.assertEqual(window.views_in_group(1), ["preview view"])
        # And the owner still knows where the preview group went.
        self.assertTrue(owner.is_owned(window, 1))
        self.assertEqual(owner.groups_of(window, "session"), [1])

    def test_releasing_the_renumbered_group_still_gives_it_back(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        panel = owner.acquire_panel(window, 0, "session")
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        owner.release(window, panel, "session", restore=True)

        owner.release_all(window, "session", restore=True)

        self.assertEqual(window.layout(), ONE)
        self.assertFalse(owner.is_owned(window, 1))


class ShareTest(unittest.TestCase):
    def test_a_measurement_narrows_but_never_widens(self):
        self.assertEqual(share_for(GroupRole.PANEL, 200.0, 1000.0), 0.2)
        self.assertEqual(
            share_for(GroupRole.PANEL, 900.0, 1000.0), ROLE_SHARE[GroupRole.PANEL]
        )

    def test_a_short_list_still_leaves_a_usable_group(self):
        self.assertEqual(
            share_for(GroupRole.PANEL, 10.0, 1000.0), ROLE_MINIMUM[GroupRole.PANEL]
        )

    def test_nothing_measured_falls_back_to_the_role_share(self):
        for width, pair in ((0.0, 1000.0), (200.0, 0.0)):
            self.assertEqual(
                share_for(GroupRole.PANEL, width, pair), ROLE_SHARE[GroupRole.PANEL]
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
        group = owner.acquire(window, 0, GroupRole.PANEL, "session")
        # 0.35 of a 1000 px window, before anything has been measured.
        self.assertAlmostEqual(window.layout()["cols"][1], 0.65)
        return window, owner, group

    def test_fitting_narrows_the_group_to_the_width_asked_for(self):
        window, owner, group = self.owner_with_toc()
        owner.fit(window, group, GroupRole.PANEL, 200.0)
        self.assertAlmostEqual(window.layout()["cols"][1], 0.8)

    def test_a_later_fit_can_widen_again_up_to_the_role_share(self):
        window, owner, group = self.owner_with_toc()
        owner.fit(window, group, GroupRole.PANEL, 200.0)
        owner.fit(window, group, GroupRole.PANEL, 900.0)
        self.assertAlmostEqual(window.layout()["cols"][1], 0.65)

    def test_a_group_the_user_has_dragged_is_never_moved_again(self):
        window, owner, group = self.owner_with_toc()
        dragged = window.layout()
        dragged["cols"][1] = 0.5
        window.set_layout(dragged)
        owner.fit(window, group, GroupRole.PANEL, 200.0)
        self.assertEqual(window.layout(), dragged)

    def test_fitting_a_group_this_owner_did_not_make_does_nothing(self):
        window, owner, _ = self.owner_with_toc()
        owner.fit(window, 0, GroupRole.PANEL, 200.0)
        self.assertAlmostEqual(window.layout()["cols"][1], 0.65)

    def test_an_empty_group_cannot_be_measured_so_is_left_alone(self):
        window, owner, group = self.owner_with_toc()
        window.empty_groups.add(group)
        owner.fit(window, group, GroupRole.PANEL, 200.0)
        self.assertAlmostEqual(window.layout()["cols"][1], 0.65)

    def test_a_fitted_group_is_still_restored_when_it_is_released(self):
        window, owner, group = self.owner_with_toc()
        owner.fit(window, group, GroupRole.PANEL, 200.0)
        owner.release(window, group, "session", restore=True)
        self.assertEqual(window.layout(), ONE)
