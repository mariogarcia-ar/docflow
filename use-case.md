# Pipeline invocations

How each of the thirteen pipelines is called from the CLI.

**The CLI surface below is proposed, not specified.** No document in this workspace defines the command names, flags or job model — `my_prompt.md` states the requirements (library + CLI, per-component invocation, batch, stop with force, pause/resume) without fixing syntax. The examples are consistent with those requirements and with the pipeline codes in `workflow.md`, and should be treated as a design proposal to adjust.

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

## Single components

`my_prompt.md` requires each component to be invocable on its own, so a stage can be re-run without repeating the ones before it:

```bash
docflow segmenter documentos/escaneo.pdf
docflow identifier documentos/escaneo.pdf
docflow diagnosis  documentos/escaneo.pdf
docflow reader     documentos/escaneo.pdf
docflow validator  out/factura-001.json
```

**This is what makes partial re-runs cheap.** If a document is misclassified, re-running `identifier` should not mean re-parsing the file — which matters at eleven thousand files, and matters more when the extraction model is the expensive step.

The same components are available as a library:

```python
from docflow import Pipeline

result = Pipeline("M1-ErpVR", model="ollama:qwen2.5").run("documentos/factura.pdf")
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