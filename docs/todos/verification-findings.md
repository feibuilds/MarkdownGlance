# Verification findings

## 中文摘要

- 0.4.2 验证发现两项缺陷：Windows 图片绝对路径无法解析，以及 TOC 与 outline 同开时宽度不足；见 [VF-001](#vf-001-windows-absolute-local-image-paths) 与 [VF-002](#vf-002-toc-and-outline-width-allocation)。
- 两项已在工作区修复并在真机复验（Windows 与 Linux），新证据见 [windows-2026-09-06-after-fix](../verification/windows-2026-09-06-after-fix/)；尚未提交，故未关闭。见 [Closure](#closure)。
- VF-002 的报告口径已更正：长标题换行是 `share_for` 的 role share 上限，属预期行为；真正的缺陷是 short 文档要 161 / 186 px 却只拿到 95 / 30 px。

## VF-001: Windows absolute local image paths

Status: reproduced in `cfdaf25` (0.4.2). Fixed in the working tree and
verified on real Windows; not committed, so not closed. Tracked as
[issue #3](https://github.com/pandadolphin/MarkdownGlance/issues/3).

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
[issue #4](https://github.com/pandadolphin/MarkdownGlance/issues/4).

Evidence: [Windows Finding 2 and Linux confirmation](../verification/windows-2026-09-06.md#finding-2-the-outline-is-carved-out-of-the-table-of-contents-group).

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
- [ ] Check zoom, live heading changes and resize again on the fixed build.
  The pre-fix run could not: the panels were pinned by this defect, so those
  three measurements said nothing.
- [ ] Verify a real divider drag survives repaint and close/reopen restores
  automatic fitting; do not substitute unrestricted `window.set_layout` for
  the mouse interaction. Still outstanding — the recorded drag went through
  `set_layout`, which is not bounded the way the mouse is.
- [ ] Record the fix commit and link new verification evidence here.

## Closure

Implementation changes alone do not close these items. Add the fix commit,
new report link, verified environments and remaining limits before marking an
item resolved. Keep the original report and evidence as the pre-fix snapshot.
Its `KNOWN DEFECT` checks confirm failures existed; rerunning them on saved
JSON cannot establish that a fix works.
