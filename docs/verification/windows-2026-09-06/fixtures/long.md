# Long

The same shape as `short.md`, except that one heading is far longer than the
rest. That heading is what both panels have to be wide enough for: no entry may
wrap onto a second line, and the group still must not be wider than the share
it would take with `auto_width` switched off.

## Alpha

Body text so the section has some height in the preview, and so that the
document as a whole is comfortably over the length threshold that the table of
contents needs before it will appear at all.

## A deliberately long heading that the panel has to be wide enough to show on one line

The heading above is the measurement case. On Windows the estimate targets
Arial or Segoe UI rather than the Ubuntu stack it targets on Linux, so this is
not the same test as the Linux one even though the fixture is.

### Gamma

A third level, to give the outline an indent to render and the table of
contents a nested entry.

### Delta

The last section, so the file ends on prose rather than on a heading.

## Padding

The table of contents appears only once the source is over
`toc_minimum_length`, which is 1200 characters, and this document would
otherwise be a few hundred short of it. This section is here to clear that
threshold without adding another long heading, so that the measurement case
above stays the only one. It carries no other meaning, and nothing in it is
checked; it exists so that both panels are open at the same time, which is
what step 10 asks for.
