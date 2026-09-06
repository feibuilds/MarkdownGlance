# Verification records

These are historical measurements of the revisions and environments named in
each report. A passing assertion count is not a claim that the whole product
or manual test plan passed. Later fixes need new evidence.

## Records

| Record | Revision | Environment and coverage | Outcome and limits |
| --- | --- | --- | --- |
| [Windows, 2026-09-06](windows-2026-09-06.md) | `cfdaf25`, 0.4.2 | Windows 11 / ST 4200; steps 6, 9, 10, 12 and math from step 7; Linux layout confirmation | Two defects found; 70 export/math checks pass; 58 expected-behaviour checks pass and six confirm defects. Browser anchor clicks unverified. |
| [Linux manual, 2026-09-06](manual-2026-09-06.md) | `4597f58`, 0.4.1 | Linux / ST 4200; steps 12–15 | Installation, library recovery and coexistence pass; synthetic HTTP browser checks pass; original `file://` navigation unverified. |
| [Release 0.4.2](release-0.4.2.md) | `d0f3181` plus release metadata | Linux / ST 4200; two Python/library pairs; Chrome export rendering | 295 tests per pair, native math and contract checks pass; full manual matrix not rerun. |
| [Math, 2026-09-06](math-2026-09-06.md) | `4597f58` plus the then-uncommitted math change | Linux / ST 4200; math from step 7 | Enable, scheme refresh, diagnostics and disable checks pass; see report for rendering observations. |
| [Initial implementation audit](implementation-audit.md) | Initial implementation; exact tested revision not recorded | Linux / ST 4200 and pure Python checks | Historical requirement audit, including deferred gates; its platform scope and parser details are not current release claims. |

The initial audit also uses [CPython benchmark data](cpython-benchmark.json)
and [ST 4200 contract data](st4200-contract.json). Test procedures live in the
[manual test plan](../manual-test-plan.md).

**Step numbers in these records are the plan's numbering on the day they were
written.** `c6f59c6` inserted a two-documents step at 10 and pushed the old
10 to 15 down by one, so a record dated 2026-09-06 or earlier that says step
*n* means step *n+1* from 10 upwards -- its "step 12: browser export" is the
plan's step 13. The records are not renumbered: a dated measurement says what
was run, and rewriting it to match a later plan would make it say something
else.

## Follow-up

Track the Windows absolute-image-path and TOC/outline layout defects in
[Verification findings](../todos/verification-findings.md). Close an item only
with the fix revision and a new verification record covering its acceptance
checks.

## Keeping evidence

- Keep a report beside its evidence directory, using the same dated or release
  name. Record the tested revision, local changes, environment, coverage,
  failures and unverified behaviour.
- Preserve captured JSON, HTML, screenshots, fixtures and run-specific scripts.
  Verify the supplied hash manifest before archiving. Do not overwrite an old
  run with results from a newer checkout.
- Correct report wording when needed, making clear that the underlying run is
  unchanged. Add a new report and directory for fix verification.
- Run historical checkers on a copy: some overwrite their result JSON.
  `KNOWN DEFECT` assertions describe broken behaviour and must not become CI
  success criteria. Extract reusable tooling into `tests/` when needed, with
  regression tests asserting the intended behaviour.
- Keep editor workspace files out of Git. `/docs` is excluded from release
  archives by `.gitattributes`; evidence still contributes to Git history size.
  Keep the current bundles together. Reconsider external storage if repeated
  captures make repository growth material, preserving durable links and hashes.
