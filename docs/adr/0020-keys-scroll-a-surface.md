# 20. The navigation keys scroll a surface

Date: 2026-10-16

## Status

Accepted. Adds bindings under the rule of
[ADR 0009](0009-full-screen-toggle-returns-to-ctrl-shift-v.md): a binding that
fires only inside a view this package created takes no key from anyone.

## Context

[#6](https://github.com/feibuilds/MarkdownGlance/issues/6): the preview can be
scrolled with the wheel and not with the keyboard. A surface is an empty,
read-only buffer under one `LAYOUT_BLOCK` phantom
([ADR 0001](0001-presentation-backend.md)), and Sublime Text's own bindings
for these keys move the caret -- `move` by lines and by pages, `move_to` the
line or the file's ends -- through text the surface does not have.

Measured in build 4215 with the preview focused and real key presses, on
`toc-long.md` (a 519 px viewport over a 4688 px document):

| key | Sublime Text's command | viewport moves |
| --- | --- | --- |
| `Down` ×3 | `move` by lines | 0 px |
| `PageDown` | `move` by pages | 0 px |
| `Ctrl+End` | `move_to` eof | 0 px |
| `Ctrl+Down` | `scroll_lines` | 17 px a press |

`scroll_lines` works because it moves the viewport, but by the *editor's* line
height, which has nothing to do with the preview's text or its zoom.

## Decision

A new `mdglance_scroll` command moves the viewport of the focused surface, and
the keymaps bind it under `mdglance.preview_focused`, which holds in the
preview and in the contents panel:

| keys | moves |
| --- | --- |
| `Up`, `Down` | one line of body text at the surface's zoom, not animated |
| `PageUp`, `PageDown` | the viewport less one line, animated |
| `Home`, `End`, `Ctrl+Home`, `Ctrl+End` | to the top or the bottom, animated |
| macOS: `Cmd+Up`, `Cmd+Down` | to the top or the bottom, animated |

There is no line in a phantom for `Home` and `End` to go to the start of, so
they do what they do in a browser and on macOS. `Cmd+Up` and `Cmd+Down` are
how macOS goes to the ends of a document and have no Linux or Windows key to be
spelled from, so they are the one place the OSX keymap is more than a
respelling of the Linux one. A line is `1.55rem`, the `line-height` of `body`
in `resources/preview.css`, at the zoom of the surface it is pressed in.

## Consequences

- An arrow moves a little over one line. Measured on 4215, minihtml lays a row
  out at about `0.59 × font-size + line-height / 2`: 21.9 px for body text at
  zoom 1, against the stylesheet's 24.8. Pixels are otherwise one to one with
  layout units, at `ui_scale` 2 as at 1, so the step needs no scale of its own.
  Matching 21.9 would mean copying that rule into the package, and a step
  that is a tenth too long costs nothing.
- Sublime keeps the viewport on whole pixels, so a press lands within a pixel
  of its target; nothing accumulates, since each press starts from where the
  last one landed.
- `viewport_position` reports the target of an animated move straight away, so
  a held `PageDown` keeps going rather than restarting from mid-animation.
- In the source the keys are Sublime Text's, as before.
- Left and Right do nothing: the phantom wraps to the width of the pane.
- Automated as `run-markdownglance`'s `keyboard_scroll` scenario, on both
  builds. The macOS keys are covered by the keymap tests only.
