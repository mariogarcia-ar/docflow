# docflow

## Problem

11k files in `documentos/`. Extract information from them and expose it so another system can consume it.

The volume rules out one-off scripts: the tool has to run unattended over the whole corpus, survive interruption, and be callable again without starting over.

## Product

A library with two consumption modes:

- **As includes** in other programs
- **As a CLI**

Every component is invocable from the CLI, so a single stage can be run in isolation:

```bash
docflow segmenter <input>
docflow identifier <input>
```

This matters for debugging and for partial re-runs: when a document is misclassified, re-running just `identifier` should not mean re-parsing the file.

Component list and responsibilities: see `components.md`.

## Batch mode (critical)

Input: **one file, several files, or a folder.**

| Requirement | Notes |
|---|---|
| Folder input mirrors the input tree | Output layout must reflect the source layout |
| Forced stop | Kill in-flight work, no graceful drain |
| Pause and resume | Requires durable per-file state; a resumed run picks up where it stopped |

Resume is the constraint that shapes the rest: it forces each unit of work to have a committed state, so progress survives a process restart.

## Models

| Role | What it is |
|---|---|
| **Extraction** | Local models (e.g. via Ollama). They need tuning — prompt/calibration work is expected, not optional |
| **Validator** | A frontier LLM (DeepSeek, Claude, OpenAI, or other). It is the guide of the solution and governs escalation: "could not" is defined here, nowhere else |
| **Golden set** | The ground-truth corpus |

**The golden set has two jobs:**

1. **Tune the local models** — it is the reference they are fitted against.
2. **Compare the three flows** — all three are validated against the same schema and the same golden set, which is what makes the architectures comparable on equal terms.

## Flows

Three cascading flows, each more expensive and more accurate than the last. Two independent flows over the same critical field is what produces the contrast that catches a plausible-but-false value.

| Flow | Receives | Design note |
|---|---|---|
| **Rules** | Nothing | Text + anchors + regex. Cheap, deterministic |
| **Interpretation** | Text | An LLM over reconstructed text |
| **Vision** | Pixels | A VLM reads the image directly. Last resort |

Per-flow designs: `a.md` (text-only), `b.md` (visual-only), `c.md` (multimodal fusion). The invariant across all three: escalation is governed by the Validator, and emission is a **verdict vector per field, not a score** — the threshold is set by the consumer.

## Fast paths (direct circuits)

Three direct circuits, **complementary to the general cascade**. They skip most components to cut cost and latency, and are sound only under narrower input assumptions. Not to be confused with the three general flows above.

| Circuit | Input | Steps |
|---|---|---|
| **Text PDF** | PDF with a usable text layer | `pdftotext` → extraction prompt → validate → emit |
| **Image-only PDF** | PDF with no usable text layer | rasterize → image treatment → OCR → OCR correction → extraction prompt → validate → emit |
| **Image** | A photo or scan | image treatment → MoE (direct) → validate → emit |

The general cascade segments, identifies, reconstructs, contrasts flows and queries external sources. These circuits do none of that — they are cheaper precisely because they assume away what those components exist to handle.

**Full detail — component mapping, escalation and output equivalence — is in `workflow.md`.** What follows is the summary.

### What they trade away

| Component skipped | Consequence |
|---|---|
| **Segmenter** | Assumes one file = one document. A text PDF holding three invoices mixes fields across them, and that error is silent: `components.md` calls it unrecoverable downstream |
| **Identifier** | The type must be known or asserted, or there is no routing to templates |
| **Reconstructor** | No cross-page continuity: a table spanning a page break loses its header association |
| **Cross-flow contrast** | No second flow over critical fields, so a plausible-but-false value goes undetected |
| **Catalog** | Identity fields are never checked against an external source |

The text-PDF circuit is the most exposed: it skips the Segmenter *and* keeps no secondary read, so a merged document has neither a detector nor a contrasting flow to catch it.

### What they keep

All three still **validate**. The Validator does not care how a value was obtained, so schema, type and arithmetic checks apply unchanged.

### Gating condition

The circuits hold only while their input assumption holds. What selects one is unresolved:

- **Declared** — the caller asserts it (`--circuit text-pdf`). Cheap, and the caller owns the error when the assumption is wrong.
- **Inferred** — the system decides. This requires the same evidence the Diagnosis gathers (usable text layer, single logical document), so the cheap path pays for part of the expensive one before starting.

Either way, the `components.md` rule applies: **a fast-path failure escalates into the general cascade, not straight to review.** A fast path that sends its doubts to a human queue has simply made the expensive path mandatory for everything it could not handle.

### Note on the MoE

The image circuit sends the treated image **directly to a Mixture-of-Experts model** with no separate OCR step — one pass reads and extracts, the same shape as the Vision flow in `README.md`. Whether this is the same model the general cascade uses, or a cheaper specialist, is unresolved.

## Validation model

`d.md` covers the implementation rules that follow from the above:

- **Auditing is not normalizing.** Two separate steps, no shared model.
- The observation model carries **no defaults** — a default fabricates data (`total = 0` turns "the model did not return it" into a zero).
- Keep it **lax at the boundary**, `Field(strict=True)` only where coercion would hide a real error.

## References

- `README.md` — architecture overview, the three flows, invariants, known limitations
- `components.md` — the ten components in depth
- `workflow.md` — the direct circuits and how they map onto those components
- `a.md` / `b.md` / `c.md` — the three flow designs
- `d.md` — validation with Pydantic
- `analisis.md` — analysis notes

## Open questions

- The source notes ended mid-sentence on the golden set ("the golden to use them both as…"). The reading above is an inferred completion, not a transcription.
- CLI subcommand naming is aligned to `README.md` English terms (`segmenter`, `identifier`, not `segmentador`, `identificador`).
- Implementation language is undecided.
- Deployment target for the local models (GPU availability, concurrency at 11k scale) is undecided.
- **Circuit selection is undecided**: declared vs. inferred (see Fast paths). This decides whether the cheap path can be trusted to self-select.
- **Whether the MoE in the image circuit is the same model as the general cascade's Vision flow**, or a cheaper specialist. It affects whether tuning carries over between them.
- **Whether the three general flows should be reconciled with the three circuits**: they look like two different decompositions of the same space (by input type vs. by extraction method), and having both unsynthesized invites drift.
- **Fast paths are not in `README.md`**, which describes only the general cascade; they live in `workflow.md`. Whether `README.md` should link to them, or they stay a separate layer beneath it, is unresolved.