# CLI invocations

How each of the thirteen pipelines is called from the CLI, and how each of the ten components is invoked on its own.

**The CLI surface below is proposed, not specified.** No document in this workspace defines the command names, flags or job model — `my_prompt.md` states the requirements (library + CLI, per-component invocation, batch, stop with force, pause/resume) without fixing syntax. The examples are consistent with those requirements, with the pipeline codes in `workflow.md`, and with the component names in `components.md`. Treat them as a design proposal to adjust.

**Contents**

- [Common shape](#common-shape) — the options every invocation shares
- [Pipeline invocations](#m0--text-arrives-directly) — the thirteen, `M0-ErVR` through `M4-EpVR`
- [Choosing without declaring](#choosing-without-declaring)
- [Batch](#batch) — one file, several, a folder
- [Control](#control) — pause, resume, forced stop
- [Component invocations](#component-invocations) — the ten, runnable in isolation
- [What every invocation returns](#what-every-invocation-returns)
- [Quick reference](#quick-reference) — the thirteen pipelines
- [Quick reference — components](#quick-reference--components) — the ten components

---

## Common shape

Every invocation is the same command with a different `--pipeline` code:

```bash
docflow run --pipeline <CODE> <input> [options]
```

| Part | Meaning |
|---|---|
| `run` | Execute a pipeline end to end. Sibling subcommands exist for single components (see below) |
| `--pipeline` | One of the thirteen codes from `workflow.md` |
| `<input>` | A file, several files, a folder, or `-` for stdin |
| `--out` | Output directory |

**There is no flag to skip validation.** The `V` in every primitive is invariant (`workflow.md`), so no `--no-validate` exists and no example below passes one.

### Options used in these examples

| Flag | Meaning |
|---|---|
| `--model` | Local extraction model, e.g. `ollama:qwen2.5`. Used by `EpVR` and `ErpVR` |
| `--validator` | Frontier LLM that governs escalation, e.g. `claude`, `deepseek`, `openai` |
| `--golden` | Golden set for comparison and tuning |
| `--jobs` | Concurrency for batch runs |
| `--out` | Output directory. Folder input mirrors its tree here |
| `--report` | Output format: `json` (default), `md`, `html` |

---

## M0 — text arrives directly

No acquisition step. The caller supplies the text, so the pipeline begins at the extractor. `workflow.md` calls this "the primitive with an empty prefix".

### M0-ErVR — text, regex

```bash
docflow run --pipeline M0-ErVR --text-file cuerpo.txt --out out/
```

```bash
# same, from stdin
cat cuerpo.txt | docflow run --pipeline M0-ErVR - --out out/
```

Deterministic read, invents nothing. **Blind spot:** a bad anchor is invisible to it — the value is real, with correct shape and type.

### M0-EpVR — text, prompt

```bash
docflow run --pipeline M0-EpVR --text-file cuerpo.txt \
  --model ollama:qwen2.5 --out out/
```

Use when the wording varies and a pattern per variant is impractical. **Blind spot:** can invent a value and can misattribute one.

### M0-ErpVR — text, both

```bash
docflow run --pipeline M0-ErpVR --text-file cuerpo.txt \
  --model ollama:qwen2.5 --out out/
```

Both reads over the same text, compared by Consistency. **The cheapest contrast in the system** — nothing was spent acquiring the text, so a second read costs only one call on critical fields.

---

## M1 — text PDF

`pdftotext` produces a linear stream. One step more than M0, and that step is the only liability: reading order is heuristic, so table continuity across pages is lost and the failure is quiet.

### M1-ErVR — text PDF, regex

```bash
docflow run --pipeline M1-ErVR documentos/factura.pdf --out out/
```

### M1-EpVR — text PDF, prompt

```bash
docflow run --pipeline M1-EpVR documentos/factura.pdf \
  --model ollama:qwen2.5 --out out/
```

### M1-ErpVR — text PDF, both

```bash
docflow run --pipeline M1-ErpVR documentos/factura.pdf \
  --model ollama:qwen2.5 --out out/
```

---

## M2 — image PDF

Rasterize, then OCR. Identical to M3 once the image exists, so the two share one implementation with a switch at the front.

### M2-ErVR — image PDF, regex

```bash
docflow run --pipeline M2-ErVR documentos/escaneo.pdf --out out/
```

Patterns must tolerate the misreads OCR actually produces — an `O` for a `0` in a known position, for instance.

### M2-EpVR — image PDF, prompt

```bash
docflow run --pipeline M2-EpVR documentos/escaneo.pdf \
  --model ollama:qwen2.5 --out out/
```

### M2-ErpVR — image PDF, both

```bash
docflow run --pipeline M2-ErpVR documentos/escaneo.pdf \
  --model ollama:qwen2.5 --out out/
```

---

## M3 — image via OCR

Page becomes a string first. Loses everything visual — layout, signatures, seals, checkboxes, logos.

### M3-ErVR — image, regex

```bash
docflow run --pipeline M3-ErVR documentos/foto.jpg --out out/
```

### M3-EpVR — image, prompt

```bash
docflow run --pipeline M3-EpVR documentos/foto.jpg \
  --model ollama:qwen2.5 --out out/
```

### M3-ErpVR — image, both

```bash
docflow run --pipeline M3-ErpVR documentos/foto.jpg \
  --model ollama:qwen2.5 --out out/
```

**The M3-versus-M4 fork is a real trade.** M3 can verify itself cheaply, because the text it produces admits a second read. M4 cannot. If contrast on critical fields is required, that requirement is what pushes an image to M3.

---

## M4 — image, direct to the model

The one material with a **single primitive**. No text intermediate exists, so there is no string for a regex to run on and no `ErVR` or `ErpVR` variant.

### M4-EpVR — image, prompt on pixels

```bash
docflow run --pipeline M4-EpVR documentos/foto.jpg \
  --model ollama:llava --out out/
```

**Sees what no other route can:** signatures, seals, checkboxes and logos are available to the extractor rather than lost in conversion.

**At the cost of two things:** a single fused read with no second opinion, and no character offset — the trace is a bounding region.

---

## Choosing without declaring

The codes above declare the pipeline explicitly. Since Diagnosis is the component that decides the material, the same run can be left to select:

```bash
# let Diagnosis pick the material, then choose the extractor mode
docflow run --extractor rp documentos/ --model ollama:qwen2.5 --out out/
```

```bash
# inspect what would be chosen, without running
docflow run --extractor rp documentos/ --dry-run
```

**Whether this is allowed is an open question in `workflow.md`** — nothing yet says whether the caller declares the pipeline or the system infers it. It is sharpest in two places: M0 is a caller *assertion* with no artifact to diagnose, and for an image both M3 and M4 are valid.

---

## Batch

The batch requirement from `my_prompt.md`: one file, several files, or a folder. Folder input **mirrors its tree** in the output.

### One file

```bash
docflow run --pipeline M1-ErpVR documentos/factura.pdf --out out/
```

### Several files

```bash
docflow run --pipeline M1-ErpVR \
  documentos/enero/factura-001.pdf \
  documentos/enero/factura-002.pdf \
  documentos/febrero/nota-014.pdf \
  --out out/
```

### A folder

```bash
docflow run --pipeline M1-ErpVR documentos/ --out out/ --jobs 8
```

The tree is preserved:

```
documentos/                          out/
  2024/enero/factura-001.pdf    →      2024/enero/factura-001.json
  2024/enero/factura-002.pdf    →      2024/enero/factura-002.json
  2024/febrero/nota-014.pdf     →      2024/febrero/nota-014.json
```

### Mixed materials in one folder

For a corpus of eleven thousand files, the materials will not be uniform. Since a folder run can select per file, one pass handles the mixture:

```bash
docflow run --extractor rp documentos/ --out out/ --jobs 8
```

### With a golden set

`my_prompt.md` describes the golden set as serving two jobs: tuning the local models, and comparing the pipelines against each other on equal terms. The second is why the flag exists at run time:

```bash
docflow run --pipeline M1-ErpVR documentos/ \
  --model ollama:qwen2.5 --validator claude \
  --golden golden/facturas.jsonl --out out/
```

---

## Control

A folder run over eleven thousand files will be interrupted. `my_prompt.md` requires a forced stop, plus pause and resume.

Every run reports a job id:

```bash
docflow run --pipeline M1-ErpVR documentos/ --out out/ --jobs 8
# job 7f3a91c2 started — 11034 files queued
```

### Pause and resume

```bash
docflow pause 7f3a91c2        # finish in-flight files, then hold
docflow resume 7f3a91c2       # continue where it stopped
```

Resume is what makes durable per-file state necessary: the process can end and the run picks up without reprocessing what already completed.

### Forced stop

```bash
docflow stop 7f3a91c2         # graceful: drain in-flight work
docflow stop 7f3a91c2 --force # kill now, no drain
```

### Inspect

```bash
docflow status 7f3a91c2
docflow status 7f3a91c2 --failed      # what escalated, and why
docflow jobs                          # all runs
```

---

## Component invocations

`my_prompt.md` requires each component to be invocable on its own, so a stage can be re-run without repeating the ones before it.

Each component reads the previous one's artifact and writes its own, mirroring the chain in `components.md`:

```mermaid
graph LR
    A["File"] --> B["segmenter"] --> C["identifier"] --> D["diagnosis"]
    D --> E["reader"] --> F["reconstructor"] --> G["validator"]
    G --> H["consistency"] --> I["catalog"] --> J["contract"]
    J --> K["reviewer"]
```

### Artifacts

Every component takes an input and writes an artifact to `--out`. Passing artifacts between stages is what makes a single stage re-runnable:

| Component | Reads | Writes |
|---|---|---|
| `segmenter` | `<name>.pdf` / `.jpg` / … | `<name>.segments.json` |
| `identifier` | `<name>.segments.json` | `<name>.identity.json` |
| `diagnosis` | `<name>.identity.json` | `<name>.diagnosis.json` |
| `reader` | `<name>.diagnosis.json` | `<name>.tokens.json` |
| `reconstructor` | `<name>.tokens.json` | `<name>.document.json` |
| `validator` | `<name>.document.json` | `<name>.validated.json` |
| `consistency` | `<name>.validated.json` | `<name>.consistency.json` |
| `catalog` | `<name>.consistency.json` | `<name>.catalog.json` |
| `contract` | `<name>.catalog.json` | the final output |
| `reviewer` | routed cases | corrections |

This is the shape the examples below follow: each stage names the artifact it consumes, so a run can be resumed at any point in the chain.

---

### segmenter

Groups pages into logical documents. **The only component with no escape hatch** — its error is unrecoverable downstream, which is why it over-segments on a doubtful cut.

```bash
docflow segmenter documentos/escaneo.pdf --out work/
```

```bash
# a folder, preserving the tree
docflow segmenter documentos/ --out work/ --jobs 8
```

```bash
# raise the bar for accepting a cut; doubtful ones split
docflow segmenter documentos/escaneo.pdf --cut-confidence 0.7 --out work/
```

Over-splitting is on by default and there is no flag to disable it. Splitting too much is recoverable noise; merging too much is silent corruption.

### identifier

Determines the document type and the routing.

```bash
docflow identifier work/escaneo.segments.json --out work/
```

```bash
# print which words or shapes triggered each decision
docflow identifier work/escaneo.segments.json --show-evidence --out work/
```

Low confidence routes to review rather than guessing the most likely type. If the evidence shows **two types in one segment**, it returns the cut and forces re-segmentation — **once only**, and pages already read are reused.

### diagnosis

Detects what is there, measures whether it is processable, and adapts the input. Runs before reading.

```bash
docflow diagnosis work/escaneo.identity.json --out work/
```

```bash
# tighten the quality gate
docflow diagnosis work/escaneo.identity.json \
  --min-chars 100 --min-dpi 200 --out work/
```

The gate is **quality, not presence** — a layer with 40 characters on an A4 sheet is not a text layer. Three outcomes: route to conversion, adapt then route to OCR, or route aside with a reason.

### reader

Extracts tokens by conversion or OCR, routed **per page**.

```bash
docflow reader work/escaneo.diagnosis.json --out work/
```

```bash
# force an OCR engine, and enable OCR-text correction
docflow reader work/escaneo.diagnosis.json \
  --ocr tesseract --correct --out work/
```

Correction exists **only in the OCR path** — a converter does not read badly, it transcribes what is there. Output is **positioned tokens**, not ordered text: reading order is the Reconstructor's job.

### reconstructor

Layout, tables and reading order across pages.

```bash
docflow reconstructor work/escaneo.tokens.json --out work/
```

```bash
# cross-page continuity only, for documents where each page stands alone
docflow reconstructor work/escaneo.tokens.json \
  --continuity-only --out work/
```

Receives **several pages**, not one: layout is local, continuity is not. A table whose header is on one page and whose rows continue on the next loses the association if pages are processed in isolation.

### validator

The four independent checks — shape, type, content, check digit — and the policy that governs escalation.

```bash
docflow validator work/escaneo.document.json --out work/
```

```bash
# validate against a document-type schema
docflow validator work/escaneo.document.json \
  --schema schemas/factura.json --out work/
```

```bash
# validate an existing output without re-running anything upstream
docflow validator out/factura-001.json --schema schemas/factura.json
```

There is **no flag to skip validation** — the `V` is invariant across all thirteen pipelines. The four checks are independent, and the most severe failure governs the outcome.

### consistency

Cross-checks fields against each other, and compares extractors.

```bash
docflow consistency work/escaneo.validated.json --out work/
```

```bash
# override the default tolerance for amounts, in cents
docflow consistency work/escaneo.validated.json --tolerance-amounts 1 --out work/
```

Two levels: **between fields** (subtotal + taxes = total; issue ≤ due) and **across extractors** (the same field read by `r` and by `p`). Values are normalized before comparison — otherwise it measures format, not value. Where the two reads disagree, arithmetic arbitrates before a human is involved.

### catalog

Validates identity fields against something outside the document.

```bash
docflow catalog work/escaneo.consistency.json \
  --source padron --out work/
```

```bash
# inspect the retry queue for fields that could not be verified
docflow catalog --retry-queue work/
```

```bash
# retry with backoff
docflow catalog --retry-queue work/ --retry --out work/
```

**Unavailability is not invalidity.** If the external source does not answer, the field is `unverified`, not rejected — and the Catalog owns the retry queue, so the state does not become a hole.

### contract

Assembles the output. A **barrier**: it waits for every page to resolve.

```bash
docflow contract work/escaneo.catalog.json --out out/
```

```bash
# other report formats
docflow contract work/escaneo.catalog.json --format md --out out/
```

Emits each field with its **verdict vector**, not a collapsed score, plus its `(page, extractor)` trace. Failure is partial: an illegible page is marked as such and the rest of the document is emitted.

### reviewer

Closes the loop. Takes what the other components routed out.

```bash
# what is waiting, grouped by case pattern
docflow reviewer queue --out work/
```

```bash
# fix a one-off
docflow reviewer correct <case-id> --value 1540.00
```

```bash
# a case that repeats becomes a rule and stops reaching review
docflow reviewer promote <case-id> --rule reglas/cuit-proveedor.yaml
```

```bash
# the "other" category accumulated cases: define a type and its route
docflow reviewer promote <case-id> --new-type nota-de-credito
```

Three outputs — corrected datum, new rule, new type. **Without it the system does not improve**: corrections pile up in logs nobody reads and the same error returns in every batch.

---

### Re-running a single stage

This is the practical payoff of invocability. A document misclassified does not need re-parsing:

```bash
docflow identifier work/escaneo.segments.json --out work/

# the extraction model changed; re-run from the reader on
docflow reader     work/escaneo.diagnosis.json --out work/ --correct
docflow reconstructor work/escaneo.tokens.json --out work/
docflow validator  work/escaneo.document.json --schema schemas/factura.json --out work/
```

At eleven thousand files this matters most when the expensive step is the model call, not the parse.

### Library equivalent

Every component is reachable from code with the same names:

```python
from docflow import Pipeline, components

result = Pipeline("M1-ErpVR", model="ollama:qwen2.5").run("documentos/factura.pdf")

segments = components.segmenter("documentos/escaneo.pdf")
identity = components.identifier(segments)
tokens   = components.reader(components.diagnosis(identity))

for field, verdicts in result.verdicts.items():
    print(field, verdicts)
```

---

## What every invocation returns

The output shape does not vary by pipeline — that is what makes the thirteen substitutable (`workflow.md`). Every field carries its verdicts separately rather than a collapsed score:

```json
{
  "total": {
    "value": "15400.00",
    "extractor": "r",
    "trace": { "page": 3, "offset": [412, 424] },
    "verdicts": {
      "shape": "ok",
      "type": "ok",
      "content": "ok",
      "digit": null,
      "consistency": "ok",
      "catalog": "unverified"
    }
  }
}
```

`consistency` is `null` unless the pipeline ran both reads — so a consumer can require it on critical fields and accept `null` elsewhere, which is the information needed to pick a pipeline per document type.

---

## Quick reference

| Pipeline | Command |
|---|---|
| `M0-ErVR` | `docflow run --pipeline M0-ErVR --text-file cuerpo.txt` |
| `M0-EpVR` | `docflow run --pipeline M0-EpVR --text-file cuerpo.txt --model ollama:qwen2.5` |
| `M0-ErpVR` | `docflow run --pipeline M0-ErpVR --text-file cuerpo.txt --model ollama:qwen2.5` |
| `M1-ErVR` | `docflow run --pipeline M1-ErVR documentos/factura.pdf` |
| `M1-EpVR` | `docflow run --pipeline M1-EpVR documentos/factura.pdf --model ollama:qwen2.5` |
| `M1-ErpVR` | `docflow run --pipeline M1-ErpVR documentos/factura.pdf --model ollama:qwen2.5` |
| `M2-ErVR` | `docflow run --pipeline M2-ErVR documentos/escaneo.pdf` |
| `M2-EpVR` | `docflow run --pipeline M2-EpVR documentos/escaneo.pdf --model ollama:qwen2.5` |
| `M2-ErpVR` | `docflow run --pipeline M2-ErpVR documentos/escaneo.pdf --model ollama:qwen2.5` |
| `M3-ErVR` | `docflow run --pipeline M3-ErVR documentos/foto.jpg` |
| `M3-EpVR` | `docflow run --pipeline M3-EpVR documentos/foto.jpg --model ollama:qwen2.5` |
| `M3-ErpVR` | `docflow run --pipeline M3-ErpVR documentos/foto.jpg --model ollama:qwen2.5` |
| `M4-EpVR` | `docflow run --pipeline M4-EpVR documentos/foto.jpg --model ollama:llava` |

Add `--out out/` to any of them. Add `--jobs N` for a folder.

---

## Quick reference — components

| Component | Command |
|---|---|
| `segmenter` | `docflow segmenter <file> --out work/` |
| `identifier` | `docflow identifier work/<name>.segments.json --out work/` |
| `diagnosis` | `docflow diagnosis work/<name>.identity.json --out work/` |
| `reader` | `docflow reader work/<name>.diagnosis.json --out work/` |
| `reconstructor` | `docflow reconstructor work/<name>.tokens.json --out work/` |
| `validator` | `docflow validator work/<name>.document.json --out work/` |
| `consistency` | `docflow consistency work/<name>.validated.json --out work/` |
| `catalog` | `docflow catalog work/<name>.consistency.json --source padron` |
| `contract` | `docflow contract work/<name>.catalog.json --out out/` |
| `reviewer` | `docflow reviewer queue --out work/` |

**No component can be invoked with validation disabled.** The `V` in every primitive is invariant, so there is no flag that would let a pipeline skip it.