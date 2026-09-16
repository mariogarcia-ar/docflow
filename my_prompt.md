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

Component list and responsibilities: see the table in `README.md`.

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

## Validation model

`d.md` covers the implementation rules that follow from the above:

- **Auditing is not normalizing.** Two separate steps, no shared model.
- The observation model carries **no defaults** — a default fabricates data (`total = 0` turns "the model did not return it" into a zero).
- Keep it **lax at the boundary**, `Field(strict=True)` only where coercion would hide a real error.

## References

- `README.md` — engine architecture, components, invariants, known limitations
- `a.md` / `b.md` / `c.md` — the three flow designs
- `d.md` — validation with Pydantic
- `analisis.md` — analysis notes

## Open questions

- The source notes ended mid-sentence on the golden set ("the golden to use them both as…"). The reading above is an inferred completion, not a transcription.
- CLI subcommand naming is aligned to `README.md` English terms (`segmenter`, `identifier`, not `segmentador`, `identificador`).
- Implementation language is undecided.
- Deployment target for the local models (GPU availability, concurrency at 11k scale) is undecided.