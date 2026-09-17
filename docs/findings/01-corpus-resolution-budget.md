# Finding — the corpus's real resolution budget

| Field | Value |
|---|---|
| Found | 2026-09-17, while verifying `E04-02` (`kernel.pdf`) against `tests/fixtures/` |
| Raised by | `tests/kernels/test_pdf.py`'s assertion that `render` never upscales, run against real documents |
| Status | **Open** — an observation with a measured basis, not yet acted on |
| Affects | Stage 2 (`Diagnosis`, `Reader`, escalation) · Stage 3 (`S3-T11` slots and resources) |
| Evidence | `python tests/fixtures/verify_k2.py` — pass 2 |

---

## What was measured

The five scans in `tests/fixtures/pdf_escaneados/`, measured by
`kernel.pdf.effective_dpi`, which divides the embedded image's own pixel dimensions
by the area of the page it is placed in:

| Fixture | Measured resolution | At `DPI_DEFAULT = 300` |
|---|---:|---|
| `3ac5a2ec-d129-47c0-947a-4680c7e25f06.pdf` | 120.0 DPI | below |
| `68623f4b-775d-44cc-8f9c-369d441ef315.pdf` | 100.07 DPI | below |
| `722106ec-ad35-4d09-879f-b2da6f8897ad.pdf` | 271.43 DPI | below |
| `9b7a423c-189c-4b9b-8ab1-23b38d4518b4.pdf` | 100.07 DPI | below |
| `bddb529d-11ef-4380-92c3-56bdecf2acc2.pdf` | 294.35 DPI | below |

**Four of the five scans hold less than 300 DPI of real pixels.** The numbers are
not round — 100.07, 271.43, 294.35 — which is what a measurement looks like rather
than a metadata field being echoed.

## Why it matters

The legacy PoC's render path was `zoom = max(2000 / lado_px, dpi / 72)` — it
*enlarged* a page to meet the resolution it was asked for and reported success
(`legacy/voucherflow/processing/orquestacion.py:214`). Its default was
`DPI_DEFAULT = 300` (`legacy/voucherflow/pdf/modelo.py:43`).

Put together: **on this corpus, the previous system upscaled four of every five
scans to 300 DPI on every run, and reported the request as satisfied.** The output
was larger and no more legible, and nothing in the pipeline could tell. That is row
4 of the silent-failure matrix (`kernel-cli.md` §11) — not a hypothetical failure,
but the behaviour this corpus actually received.

`docflow`'s `render` refuses instead: it measures the embedded pixels and returns
`insufficient_effective_resolution` with no file produced. `verify_k2.py` pass 2
confirms 5 of 5 refused, 0 files written.

## What it does *not* say

The finding is a **measurement of the corpus**, and the conclusion it supports is
narrow. It does not say:

- that these documents are unusable — 100 DPI is legible for some material;
- that 300 DPI is the wrong request — it may be exactly right for a *target*, and
  the point is that it is unreachable from these sources;
- anything about the other 17 PDFs in the fixture set, which carry text layers
  rather than scans and were not part of this pass.

## Why it is recorded rather than fixed

Nothing in Stage 1 needs to change. `E04-02` behaves correctly: refusing an
unreachable resolution is the specified behaviour, and the fixture set is what
surfaced the fact rather than a fault.

What needs a decision is **everywhere above it**, because four of five scans
under 300 DPI is a constraint on:

| Consumer | The question it raises |
|---|---|
| `Diagnosis` (`S2-T04`) | What resolution may a route *require* before a material is judged unfit for it? |
| `Reader` (`S2-T06`) | Is a 100 DPI scan read from pixels, or escalated? At what cost? |
| Escalation (`S2-T09`, `S2-T11`) | Does a low-resolution source trigger the ladder, and on which rung does it land? |
| Legibility thresholds (registry, `S3-T12`) | The threshold is policy in `registry/policies/`, and it has to be set against *these* numbers rather than a guess |
| `S3-T11` slots and resources | A source that cannot be rendered at 300 changes nothing about cost — which is itself worth confirming |

The value of recording it now is that the alternative is discovering it during the
Stage 3 corpus run, when the resolution has already been assumed by every stage
above.

## Where the numbers come from, so they can be re-derived

```bash
python tests/fixtures/verify_k2.py          # pass 2 prints every measured page
python tests/fixtures/verify_k2.py --json   # the same, machine-readable
```

The measurement is `embedded pixels / (placed area in points / 72)`, taking the
smaller of the horizontal and vertical ratios, and the worst placement on the page.
It is deliberately not read from the file's metadata: metadata describes what
someone intended, and the bytes describe what is there.

## What is still missing

The fixture set is a **sample**, not the corpus. It holds 5 scans; the corpus is
11k files. These five establish that the condition exists and is common enough to
matter — they cannot establish its prevalence. `NFR-11`'s first full run sets that
baseline, and this finding is an input to it rather than a substitute.
