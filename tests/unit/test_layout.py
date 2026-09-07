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
from MarkdownGlance.preview.presentation import window_record
from MarkdownGlance.preview.presentation.window_record import KEY as RECORD_KEY


class FakeView:
    """A view whose viewport is the group's share of a 1000 px window."""

    def __init__(self, width):
        self.width = width

    def viewport_extent(self):
        return (self.width, 800.0)


class FakeSettings:
    """A window's settings, which Sublime writes into the session."""

    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def erase(self, key):
        self.values.pop(key, None)


class FakeWindow:
    WIDTH = 1000.0

    def __init__(self, layout, settings=None):
        self._layout = copy.deepcopy(layout)
        self._sheets = {}
        self._views = {}
        self._settings = FakeSettings(settings)
        self.empty_groups = set()

    def id(self):
        return 1

    def settings(self):
        return self._settings

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


class RecordTest(unittest.TestCase):
    """What one process leaves behind for the next one to sweep up.

    A layout survives a restart; the scratch surfaces in it do not. See
    ADR 0018.
    """

    def test_a_split_names_its_group_in_the_window_settings(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]]},
        )

    def test_a_panel_beside_a_preview_is_recorded_too(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        owner.acquire_panel(window, 0, "session")

        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 3, "groups": [[1, "preview"], [2, "panel"]]},
        )

    def test_giving_the_last_group_back_erases_the_record(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        owner.release_all(window, "session", restore=True)

        self.assertIsNone(window.settings().get(RECORD_KEY))

    def test_a_collapse_records_the_group_that_is_left(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        panel = owner.acquire_panel(window, 0, "session")
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        owner.release(window, panel, "session", restore=True)

        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]]},
        )

    def test_unloading_without_giving_the_group_back_keeps_the_record(self):
        """What `plugin_unloaded` does, and the case the record exists for.

        The surfaces go and the cell stays, so the record has to stay with it:
        erasing here is what leaves the next process a pane it cannot account
        for.
        """
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        owner.release_all(window, "session", restore=False)

        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]]},
        )

    def test_a_group_the_user_has_filled_stays_recorded(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        group = owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        window._sheets[group] = ["a file the user dragged in"]

        owner.release(window, group, "session", restore=True)

        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]]},
        )

    def test_a_layout_command_of_the_users_drops_the_record(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        owner.invalidate(window)

        self.assertIsNone(window.settings().get(RECORD_KEY))


class ReclaimTest(unittest.TestCase):
    """The sweep a restart, a crash or a package reload arrives at."""

    def restarted(self, layout, record, sheets=None):
        """A window as Sublime restores it: the layout back, the surfaces not."""
        window = FakeWindow(layout, {RECORD_KEY: record})
        window._sheets = dict(sheets or {0: ["source"]})
        return window, LayoutOwner()

    def test_an_empty_group_a_previous_process_left_is_taken_back(self):
        window, owner = self.restarted(
            {"cols": [0.0, 0.5, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]},
            {"cells": 2, "groups": [[1, "preview"]]},
        )

        self.assertTrue(owner.reclaim(window))

        self.assertEqual(window.layout(), ONE)
        self.assertIsNone(window.settings().get(RECORD_KEY))

    def test_a_preview_and_a_panel_both_go(self):
        window, owner = self.restarted(
            {"cols": [0.0, 0.4, 0.8, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [2, 0, 3, 1]]},
            {"cells": 3, "groups": [[1, "preview"], [2, "panel"]]},
        )

        owner.reclaim(window)

        self.assertEqual(window.layout(), ONE)

    def test_a_group_with_a_sheet_in_it_is_never_removed(self):
        window, owner = self.restarted(
            {"cols": [0.0, 0.5, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]},
            {"cells": 2, "groups": [[1, "preview"]]},
            sheets={0: ["source"], 1: ["a file the user dragged in"]},
        )
        before = window.layout()

        self.assertFalse(owner.reclaim(window))

        self.assertEqual(window.layout(), before)

    def test_a_group_still_holding_a_restored_sheet_waits_for_the_next_sweep(self):
        """Measured on build 4200: a restored window keeps the preview's and
        the panel's scratch sheets for a moment and drops them once the session
        has settled, so the first sweep -- at `plugin_loaded` -- sees groups
        that are about to be empty and are not yet."""
        window, owner = self.restarted(
            {"cols": [0.0, 0.5, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]},
            {"cells": 2, "groups": [[1, "preview"]]},
            sheets={0: ["source"], 1: ["a sheet still settling"]},
        )

        self.assertFalse(owner.reclaim(window))
        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]]},
        )

        window._sheets[1] = []
        self.assertTrue(owner.reclaim(window))
        self.assertEqual(window.layout(), ONE)
        self.assertIsNone(window.settings().get(RECORD_KEY))

    def test_a_window_the_user_has_restructured_keeps_its_record(self):
        window, owner = self.restarted(
            {"cols": [0.0, 0.3, 0.6, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [2, 0, 3, 1]]},
            {"cells": 2, "groups": [[1, "preview"]]},
        )
        before = window.layout()

        self.assertFalse(owner.reclaim(window))

        self.assertEqual(window.layout(), before)
        # Kept, not dropped: the window may simply not be restored yet.
        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]]},
        )

    def test_a_dragged_divider_does_not_defeat_it(self):
        """The record holds a cell count, not the fingerprint `fit` uses: a
        moved boundary is what a user does to a pane they mean to keep."""
        window, owner = self.restarted(
            {"cols": [0.0, 0.83, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]},
            {"cells": 2, "groups": [[1, "preview"]]},
        )

        self.assertTrue(owner.reclaim(window))

        self.assertEqual(window.layout(), ONE)

    def test_the_views_after_a_reclaimed_group_come_with_it(self):
        window, owner = self.restarted(
            {"cols": [0.0, 0.3, 0.6, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [2, 0, 3, 1]]},
            {"cells": 3, "groups": [[1, "preview"]]},
            sheets={0: ["source"], 2: ["another file"]},
        )
        window._views = {0: ["source"], 2: ["another file"]}

        owner.reclaim(window)

        self.assertEqual(len(window.layout()["cells"]), 2)
        self.assertEqual(window.views_in_group(1), ["another file"])

    def test_a_window_this_process_already_owns_is_not_swept(self):
        """The record would be our own live state, and the group is about to
        have a surface put in it."""
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        before = window.layout()

        self.assertFalse(owner.reclaim(window))

        self.assertEqual(window.layout(), before)
        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]]},
        )

    def test_a_window_with_no_record_is_not_touched(self):
        window = FakeWindow(
            {"cols": [0.0, 0.5, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]}
        )
        before = window.layout()

        self.assertFalse(LayoutOwner().reclaim(window))

        self.assertEqual(window.layout(), before)


class FreeGroupsTest(unittest.TestCase):
    """What both halves of ADR 0018 are decided on: which recorded groups are
    still standing, and empty, in the window this process has just found."""

    def restarted(self, record, sheets=None):
        window = FakeWindow(
            {"cols": [0.0, 0.4, 0.8, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [2, 0, 3, 1]]},
            {RECORD_KEY: record},
        )
        window._sheets = dict(sheets or {0: ["source"]})
        return window, LayoutOwner()

    def test_the_groups_come_back_under_their_roles(self):
        window, owner = self.restarted(
            {"cells": 3, "groups": [[1, "preview"], [2, "panel"]]}
        )

        self.assertEqual(
            owner.free_groups(window),
            {GroupRole.PREVIEW: 1, GroupRole.PANEL: 2},
        )

    def test_a_group_that_is_not_empty_is_not_free(self):
        window, owner = self.restarted(
            {"cells": 3, "groups": [[1, "preview"], [2, "panel"]]},
            sheets={0: ["source"], 1: ["a sheet still settling"]},
        )

        self.assertEqual(owner.free_groups(window), {GroupRole.PANEL: 2})

    def test_a_role_this_version_does_not_know_is_skipped(self):
        window, owner = self.restarted(
            {"cells": 3, "groups": [[1, "sidebar"], [2, "panel"]]}
        )

        self.assertEqual(owner.free_groups(window), {GroupRole.PANEL: 2})

    def test_nothing_is_free_while_this_process_owns_the_window(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        self.assertEqual(owner.free_groups(window), {})


class AdoptTest(unittest.TestCase):
    def test_an_adopted_group_is_owned_and_released_like_any_other(self):
        window = FakeWindow(
            {"cols": [0.0, 0.5, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1]]},
            {RECORD_KEY: {"cells": 2, "groups": [[1, "preview"]]}},
        )
        window._sheets = {0: ["source"]}
        owner = LayoutOwner()

        owner.adopt(window, 1, GroupRole.PREVIEW, "session")

        self.assertTrue(owner.is_owned(window, 1))
        self.assertEqual(owner.groups_of(window, "session"), [1])
        # And it is recorded again, for the process after this one.
        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]]},
        )

        owner.release_all(window, "session", restore=True)

        self.assertEqual(window.layout(), ONE)
        self.assertIsNone(window.settings().get(RECORD_KEY))

    def test_a_panel_adopted_beside_a_preview_keeps_both_roles(self):
        window = FakeWindow(
            {"cols": [0.0, 0.4, 0.8, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [2, 0, 3, 1]]},
            {RECORD_KEY: {"cells": 3, "groups": [[1, "preview"], [2, "panel"]]}},
        )
        owner = LayoutOwner()

        owner.adopt(window, 1, GroupRole.PREVIEW, "preview-stage")
        owner.adopt(window, 2, GroupRole.PANEL, "panel-stage")

        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 3, "groups": [[1, "preview"], [2, "panel"]]},
        )
        # The panel group is found again rather than split a second time.
        self.assertEqual(owner.acquire_panel(window, 0, "another"), 2)
        self.assertEqual(len(window.layout()["cells"]), 3)


class DocumentHalfTest(unittest.TestCase):
    """The record has two writers -- the layout owner and the use cases -- so
    a write of one half must leave the other alone."""

    def test_a_split_does_not_lose_the_document(self):
        window = FakeWindow(ONE)
        window.settings().set(RECORD_KEY, {"document": "/docs/a.md", "zoom": 1.5})
        owner = LayoutOwner()

        owner.acquire(window, 0, GroupRole.PREVIEW, "session")

        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {
                "document": "/docs/a.md",
                "zoom": 1.5,
                "cells": 2,
                "groups": [[1, "preview"]],
            },
        )

    def test_the_document_goes_with_the_last_group(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PREVIEW, "session")
        window_record.update(window, document="/docs/a.md")

        owner.release_all(window, "session", restore=True)

        self.assertIsNone(window.settings().get(RECORD_KEY))

    def test_a_document_alone_never_starts_a_record(self):
        """A full-screen preview owns no group, so it leaves no pane to
        restore into and must not write one."""
        window = FakeWindow(ONE)

        window_record.update_existing(window, document="/docs/a.md")

        self.assertIsNone(window.settings().get(RECORD_KEY))

    def test_the_panel_names_the_document_without_overwriting_the_rest(self):
        window = FakeWindow(ONE)
        owner = LayoutOwner()
        owner.acquire(window, 0, GroupRole.PANEL, "session")
        window_record.update(window, zoom=1.4)

        window_record.remember_document(window, "/docs/a.md")

        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {
                "cells": 2,
                "groups": [[1, "panel"]],
                "zoom": 1.4,
                "document": "/docs/a.md",
            },
        )

    def test_naming_the_document_a_second_time_writes_nothing(self):
        window = FakeWindow(ONE)
        LayoutOwner().acquire(window, 0, GroupRole.PANEL, "session")
        window_record.remember_document(window, "/docs/a.md")
        written = window.settings().get(RECORD_KEY)

        window_record.remember_document(window, "/docs/a.md")

        self.assertIs(window.settings().get(RECORD_KEY), written)


class PartialSweepTest(unittest.TestCase):
    """One pane empty, the other still occupied: the sweep takes what it can
    and keeps the rest of the record, renumbered, for the next one."""

    def test_the_group_left_behind_stays_recorded_at_its_new_index(self):
        window = FakeWindow(
            {"cols": [0.0, 0.4, 0.8, 1.0], "rows": [0.0, 1.0],
             "cells": [[0, 0, 1, 1], [1, 0, 2, 1], [2, 0, 3, 1]]},
            {
                RECORD_KEY: {
                    "cells": 3,
                    "groups": [[1, "preview"], [2, "panel"]],
                    "document": "/docs/a.md",
                }
            },
        )
        # The preview's pane holds a file the user dragged into it; only the
        # panel's is empty.
        window._sheets = {0: ["source"], 1: ["a file the user dragged in"]}
        window._views = {0: ["source"], 1: ["a file the user dragged in"]}
        owner = LayoutOwner()

        self.assertTrue(owner.reclaim(window))

        self.assertEqual(len(window.layout()["cells"]), 2)
        self.assertEqual(
            window.settings().get(RECORD_KEY),
            {"cells": 2, "groups": [[1, "preview"]], "document": "/docs/a.md"},
        )

        # And when that file is closed, the next sweep takes the pane too.
        window._sheets[1] = []
        window._views[1] = []
        self.assertTrue(owner.reclaim(window))
        self.assertEqual(window.layout(), ONE)
        self.assertIsNone(window.settings().get(RECORD_KEY))
