# Verification findings

## 中文摘要

- 0.4.2 验证发现两项缺陷：Windows 图片绝对路径无法解析，以及 TOC 与 outline 同开时宽度不足；见 [VF-001](#vf-001-windows-absolute-local-image-paths) 与 [VF-002](#vf-002-toc-and-outline-width-allocation)。
- 两项均已复现，修复验证待补；关闭条件是记录修复 commit 并提供新验证证据，历史快照保持不变。见 [Closure](#closure)。

## VF-001: Windows absolute local image paths

Status: reproduced in `cfdaf25` (0.4.2); fix verification pending.

Evidence: [Windows Finding 1](../verification/windows-2026-09-06.md#finding-1-absolute-local-image-paths-do-not-resolve-on-windows).

`C:/Users/…/pixel.png` and `file:///C:/Users/…/pixel.png` render as
`Unavailable`. At the tested revision, `preview/renderer/structure.py`
(`_asset_key`) treats the drive letter as a URL scheme or passes the URL's
leading slash to Windows path normalization. Inspect this boundary together
with `preview/domain/paths.py` when fixing it.

- [ ] Add regression coverage for drive-absolute and local `file:` image paths,
  including encoded spaces and `#`, while preserving relative-image behaviour
  and remote-host restrictions.
- [ ] Verify both spellings render the intended local image in real Windows
  ST 4200; retain checks for relative, rooted and missing files.
- [ ] Record the fix commit and link new verification evidence here.

## VF-002: TOC and outline width allocation

Status: reproduced in `cfdaf25` (0.4.2) on Windows and Linux;
fix verification pending. macOS was not tested.

Evidence: [Windows Finding 2 and Linux confirmation](../verification/windows-2026-09-06.md#finding-2-the-outline-is-carved-out-of-the-table-of-contents-group).

With source, preview and TOC open, opening the outline splits the TOC group.
At the tested revision, `preview/presentation/layout.py`
(`LayoutOwner.acquire_beside` and `share_for`) then sizes both panels against
that narrow pair. The Windows fixture gives TOC / outline widths of 192 / 72 px;
Linux reproduces the same column fractions. Disabling TOC increases the Linux
outline from 59 to 203 px.

- [ ] Add regression coverage ensuring the outline has its own group without
  carving space from the TOC, and closing panels preserves the other views.
- [ ] Repeat the short/long-heading fixture with TOC on and off in real Windows
  and Linux ST 4200. Check usable widths, zoom, live heading changes and resize;
  distinguish the recorded fixture from arbitrarily long headings.
- [ ] Verify a real divider drag survives repaint and close/reopen restores
  automatic fitting; do not substitute unrestricted `window.set_layout` for
  the mouse interaction.
- [ ] Record the fix commit and link new verification evidence here.

## Closure

Implementation changes alone do not close these items. Add the fix commit,
new report link, verified environments and remaining limits before marking an
item resolved. Keep the original report and evidence as the pre-fix snapshot.
Its `KNOWN DEFECT` checks confirm failures existed; rerunning them on saved
JSON cannot establish that a fix works.
