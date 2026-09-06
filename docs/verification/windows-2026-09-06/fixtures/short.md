# Short

This document clears both table-of-contents thresholds: more than three
headings, and more than 1200 characters of source. Every heading in it is
short, so the fitted table of contents and the fitted outline should both be
narrow -- narrower than the share either group would take with `auto_width`
switched off.

## Alpha

Body text so the section has some height in the preview, and so that the
document as a whole is comfortably over the length threshold that the table of
contents needs before it will appear at all. Nothing here is interesting; it is
padding with a purpose.

## Beta

More padding. The point of this section is only that the heading above it is
four characters long, which is the case the width estimate has to get right at
the narrow end: the group must not collapse to nothing, because the floor in
`ROLE_MINIMUM` keeps it wide enough to read and to grab.

### Gamma

A third level, to give the outline an indent to render and the table of
contents a nested entry. The indent counts towards the width, so a deep
heading with a short text can still be wider than a shallow one.

### Delta

The last section. Between them these five headings give the outline five
entries and the table of contents four, which is enough for both panels to
have a longest entry worth measuring.

Closing paragraph, so the file ends on prose rather than on a heading.
