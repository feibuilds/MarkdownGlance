# 22. The preview font is a setting, not a user stylesheet

Date: 2026-11-01

## Status

Accepted. Answers [#11](https://github.com/feibuilds/MarkdownGlance/issues/11).

## Context

Body text in the preview is set in the stack `resources/preview.css` names --
Ubuntu, DejaVu Sans, Open Sans, sans-serif -- and nothing changed it. #11
asked for a setting for the font family, or for a stylesheet of the user's own
loaded after the package's.

A user stylesheet would answer more than this request, but two parts of the
preview depend on the stylesheet being the one the package ships:

- **Tables** are typeset by the renderer in monospace columns, with a budget
  worked out from the advance of the fonts `.md-table` names
  ([ADR 0007](0007-table-rendering-under-minihtml.md)). A rule that changed a
  table's font, size or padding would leave its columns too wide or too
  narrow, and minihtml would re-wrap the rows that overflow.
- **The contents panel** sizes its group from an estimate of its longest
  heading in the body fonts, with the padding mirrored in `measure.py`
  ([ADR 0011](0011-panel-width-fits-its-content.md)).

And every class in `preview.css` would become an interface that someone's
stylesheet depends on and a release could break without knowing.

## Decision

**One setting, `font_family`, for body text.** It takes what CSS
`font-family` takes -- a name, or names separated by commas -- and is empty by
default, which keeps the package's stack.

**Validated into CSS, not passed through.** `domain/settings.py` splits the
value on commas and strips quotes, and accepts a name only if it is letters,
digits, spaces, hyphens, underscores and dots. Anything else -- a `;`, a
brace, a `<` -- makes the setting invalid, with the usual "Invalid setting"
message, and the default applies. Names are quoted; the generic families are
not, or they would name a font called `sans-serif`.

**After the stylesheet, ahead of its fonts.** `stylesheet()` writes
`body { font-family: <setting>, <the package's stack> }` after `preview.css`,
so it wins over the same selector by coming later, and a name the host does
not have falls back to the package's fonts rather than to minihtml's.
`BODY_FONTS` mirrors the stack, and a test keeps the two equal.

**Body text in the preview and the contents panel, and nothing else.**
Whatever inherits from `body` follows the setting. Code and tables name
monospace fonts of their own, which their alignment depends on, so they do
not. **Open in Browser** writes a page with its own stylesheet and is
unchanged.

**A change re-renders.** `font_family` is a render key, as `auto_width` is: a
change re-renders every document and repaints every panel, and the stylesheet
each paint carries has the new font. A repaint would be enough; a render is
what the settings path already does, and a font is not changed often.

## Consequences

- The panel's width is still estimated for the package's fonts. A face much
  wider than Arial can wrap the panel's longest heading onto a second line;
  dragging the divider, or turning `auto_width` off, takes care of it. The
  settings file says so.
- There is no user stylesheet. Colours follow the colour scheme and size
  follows zoom; a request a stylesheet would have answered next becomes a
  setting of its own, with its own reason, or a reason it cannot be one.
