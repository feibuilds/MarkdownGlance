# An empty pane is left when the panel closes after the layout has moved

Status: open, found 2026-09-07 while merging the outline and the table of
contents into one panel. Reproduced by `run-markdownglance`'s `panel_toggle`
scenario, whose last phase asserts the pane is still there.

## What happens

1. Open a Markdown file, no preview. `Ctrl+Shift+B` opens the panel beside it:
   two groups, source and panel.
2. Open the preview. The window becomes source, preview, panel.
3. Toggle the panel off. The panel view closes, but its group stays behind as
   an empty pane on the right.

## Why

`LayoutOwner` records, for each group it makes, the layout that was in force
before the split (`previous_layout`) and a fingerprint of the layout it left
(`fingerprint`). `release` restores `previous_layout` only while the window
still matches that fingerprint -- the rule that keeps it from undoing a
divider the user dragged.

Step 2 splits a *different* cell, so by step 3 the panel's fingerprint no
longer matches and nothing is restored. Restoring the recorded layout would be
wrong anyway: it predates the preview and would take the preview's group with
it.

This is not new. The outline could always be opened before a preview, and the
same sequence left the same empty pane; the merged panel makes it a common
flow rather than a rare one, because a panel opened by hand is now the way to
get one at all when `enable_toc` is off.

## What a fix has to do

Remove the empty cell from the *current* layout instead of restoring an old
one: give its column span to a neighbour with the same row span, drop the
cell, compact the columns, and then put every view back in the group it was
in -- Sublime keeps views on their group index across `set_layout`, so every
group after the removed one has to be moved down by hand.

The cheaper half-measure -- keeping every owned group's `previous_layout` and
`fingerprint` in step whenever this owner splits or fits -- covers the split
above but not a `fit`, which moves a boundary the stored layouts cannot follow
without knowing which cell it was.
