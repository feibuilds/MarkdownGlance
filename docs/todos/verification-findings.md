# Verification findings

## 中文摘要

- 0.4.2 验证发现两项缺陷：Windows 图片绝对路径无法解析，以及 TOC 与 outline 同开时宽度不足；见 [VF-001](#vf-001-windows-absolute-local-image-paths) 与 [VF-002](#vf-002-toc-and-outline-width-allocation)。
- 两项已修复并在真机复验（Windows 与 Linux），新证据见 [windows-2026-09-06-after-fix](../verification/windows-2026-09-06-after-fix/)。VF-001 只差记录 fix commit；VF-002 还差两项：真实拖拽后的关闭重开，以及 Windows 上的真实拖拽（QEMU 无可用指针）。见 [Closure](#closure)。
- VF-002 的报告口径已更正：长标题换行是 `share_for` 的 role share 上限，属预期行为；真正的缺陷是 short 文档要 161 / 186 px 却只拿到 95 / 30 px。

## VF-001: Windows absolute local image paths

Status: reproduced in `cfdaf25` (0.4.2). Fixed in the working tree and
verified on real Windows; not committed, so not closed. Tracked as
[issue #3](https://github.com/feibuilds/MarkdownGlance/issues/3).

Evidence: [Windows Finding 1](../verification/windows-2026-09-06.md#finding-1-absolute-local-image-paths-do-not-resolve-on-windows),
and the post-fix run in
[windows-2026-09-06-after-fix](../verification/windows-2026-09-06-after-fix/i1-http-allowed.json).

`C:/Users/…/pixel.png` and `file:///C:/Users/…/pixel.png` render as
`Unavailable`. At the tested revision, `preview/renderer/structure.py`
(`_asset_key`) treats the drive letter as a URL scheme or passes the URL's
leading slash to Windows path normalization. Inspect this boundary together
with `preview/domain/paths.py` when fixing it.

- [x] Add regression coverage for drive-absolute and local `file:` image paths,
  including encoded spaces and `#`, while preserving relative-image behaviour
  and remote-host restrictions. `test_paths.py` covers all three spellings
  against the Windows flavour and asserts the POSIX one is unchanged; a UNC
  root is explicitly not a drive; `test_export.py` covers the same for the
  browser page. `splitdrive` joined the path-seam guard.
- [x] Verify both spellings render the intended local image in real Windows
  ST 4200; retain checks for relative, rooted and missing files. Both now
  render 160x64; the other ten cases in the suite are unchanged.
- [ ] Record the fix commit and link new verification evidence here.

## VF-002: TOC and outline width allocation

Status: reproduced in `cfdaf25` (0.4.2) on Windows and Linux. Fixed in the
working tree and verified on both; not committed, so not closed. macOS was not
tested. Tracked as
[issue #4](https://github.com/feibuilds/MarkdownGlance/issues/4).

Evidence: [Windows Finding 2 and Linux confirmation](../verification/windows-2026-09-06.md#finding-2-the-outline-is-carved-out-of-the-table-of-contents-group).

Overtaken by ADR 0014 (2026-09-07), which leaves one panel where there were
two: there is no second panel to carve a group out of, `acquire_beside` is
gone, and `acquire_panel` walks right past groups this owner made and stops at
the first it did not. The regression tests below moved with it and still hold.

With source, preview and TOC open, opening the outline splits the TOC group.
At the tested revision, `preview/presentation/layout.py`
(`LayoutOwner.acquire_beside` and `share_for`) then sizes both panels against
that narrow pair. The Windows fixture gives TOC / outline widths of 192 / 72 px;
Linux reproduces the same column fractions. Disabling TOC increases the Linux
outline from 59 to 203 px.

- [x] Add regression coverage ensuring the outline has its own group without
  carving space from the TOC. `test_layout.py` asserts that no panel is split
  out of another, that two panels each reach the width their entries ask for,
  and that a panel wanting more than its role share is still capped, so the
  deliberate ceiling cannot be removed by accident.
- [x] Repeat the short/long-heading fixture with TOC on and off in real Windows
  and Linux ST 4200, distinguishing the recorded fixture from arbitrarily long
  headings. `short.md` wants 161 / 186 px and now gets 146 / 183 (Windows) and
  163 / 185 (Linux), every entry on one line. `long.md` wants 722 / 945 px and
  gets 283 / 239 (Windows) and 240 / 202 (Linux): both at the role-share
  ceiling, and its one long entry still wraps, which is the ceiling working.
- [x] Check zoom, live heading changes and resize again on the fixed build.
  Measured on Linux ST 4200 with a fixture sized to leave room under the role
  share ([followups.json](../verification/windows-2026-09-06-after-fix/linux/followups.json)):
  152 px at zoom 1.0, 202 at zoom 1.25, back to 151 on reset, 202 again after
  a longer heading is typed, and 225 after the window goes from 1700 to 1280 px
  wide. The two 202s are the ceiling rather than a coincidence: both changes
  ask for more than `ROLE_SHARE` allows, so the group grows to the cap and
  stops. What the pre-fix run could not show is that it moves at all.
- [x] Verify a real divider drag survives repaint; do not substitute
  unrestricted `window.set_layout` for the mouse interaction. Driven with real
  X11 pointer events through `xdotool` on Linux: the boundary went from
  `cols[1] = 0.35` to `0.2772` and the outline from 202 px to 309 — past the
  role share, which is what a hand drag is for — and a heading typed afterwards
  left the columns exactly where the drag put them.
- [ ] Close and reopen the group after a *real* drag and confirm automatic
  fitting comes back. Only the `set_layout` version of this has been run.
- [ ] Repeat the drag on Windows. The QEMU harness has no usable pointer —
  HMP `mouse_move` sends relative deltas even with a usb-tablet attached — so
  this needs a VNC client or another way into the guest.
- [ ] Record the fix commit and link new verification evidence here.

## Closure

Implementation changes alone do not close these items. Add the fix commit,
new report link, verified environments and remaining limits before marking an
item resolved. Keep the original report and evidence as the pre-fix snapshot.
Its `KNOWN DEFECT` checks confirm failures existed; rerunning them on saved
JSON cannot establish that a fix works.
