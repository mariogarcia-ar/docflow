# Product Requirements Document — `docflow` (PoC)

| Field | Value |
|---|---|
| Product | `docflow` |
| Lifecycle stage | **PoC** (`.github/copilot-instructions.md` §5) — close the end-to-end flow, happy path first |
| Build model | **Stage 1 — arch-components** · **Stage 2 — components** · **Stage 3 — pipelines** |
| Delivery shape | One Python library, one CLI surface |
| Debt visibility | Every PoC shortcut carries `# TODO: [MVP]` or `# TODO: [RELEASE]` |

---

## 1. Problem statement

Eleven thousand documents must be read and made available to a consuming system.

**Extraction is not the problem. Knowing whether to trust the result is.** A wrong total produces no exception: it produces a number, in a field, that looks exactly like the right answer, and the consumer invoices against it.

Three failures are the antagonist, in increasing nastiness:

| Failure | Why internal validation cannot see it |
|---|---|
| **Plausible-but-false value** — a total of 15400 that was really 1540 | Passes shape, type and content; an amount has no check digit |
| **Bad anchor** — a real, well-typed value taken from the wrong place | Every check describes the value, none asks where it came from |
| **Merged document** — one file holding three documents read as one | The merge precedes every extractor; fields are real and mixed |

The first two are why a second, differently-failing reader exists. The third is the one gap no pipeline closes.

## 2. Product goal

Make every extracted field carry enough declared evidence that a consumer can decide, per field, whether to trust it — and make the system honest about what it does not know.

**Three product principles** (from `README.md` and `04-storytelling.md`):

1. **The silent error is the antagonist.** Only errors that produce output indistinguishable from correct output are architected for.
2. **Two disagreeing readers beat one confident reader.** Contrast, not a better validator, is what reaches the right-value-wrong-place class.
3. **Emission is a verdict vector, not a score.** The threshold belongs to the consumer, who knows the use case.

## 3. Target users and consumers

| Consumer | Needs |
|---|---|
| Another Python program (library include) | `Pipeline(...).run(...)` and per-component functions, same names as the CLI |
| An operator on a shell (CLI) | `docflow run --pipeline <CODE>` with batch, pause, resume, forced stop |
| A batch job over 11k files | Per-document resumability, mirrored output tree, `run.json` progress |
| The downstream consuming system | Shape-identical per-field JSON with `verdicts` and `trace`; chooses its own threshold |
| A reviewer / analyst | Per-document ledger, review queue, provenance that points at the right pixels |

## 4. Scope of the PoC

### 4.1 In scope — the three stages, bottom-up

| Stage | Layer | What it delivers | Flow it closes |
|---|---|---|---|
| **Stage 1 — arch-components** | Kernels + ports/adapters | K1–K8 with only the operations Stage 2 calls | **Synthetic**: a trivial stage driven through orchestrator + store + ledger, with pause / resume / `stop --force` |
| **Stage 2 — components** | Domain | The 10 domain components | **Real document**: canonical chain emitting a verdict vector + trace |
| **Stage 3 — pipelines** | Routes | The 13 pipeline codes as configuration over Stage 2 | **Corpus**: all 13 codes reachable, 11k files, batch + resume |

Rationale: contracts must be fixed before they are multiplied (10 components × 13 pipelines call the same 8 kernels), and the riskiest invariants live at the bottom — resume semantics, `running`-before-work, cache key, sampled-vs-deterministic artifacts, never writing `done` about non-durable bytes. The 13 pipelines are a matrix (4 materials × 3 modes + 1), not 13 designs, so Stage 3 is largely data.

**Stage 1 is intentionally thin.** `02-arch-components.md` describes a target architecture, not PoC scope. Stage 1 implements only the kernel operations Stage 2 actually calls.

### 4.2 Out of scope for the PoC

- Multi-tenant or hosted deployment; no service, no queue, no database.
- Object storage or remote artifact backends (`# TODO: [RELEASE]`) — filesystem only.
- Per-pipeline regression dashboards, golden-set scoring harnesses (`--golden` is deferred).
- Any OCR engine other than Docling; any per-corpus engine choice.
- Business rules beyond the 4 universal Validator checks (6 categories pending definition).
- Cross-document checks (debit requires a source voucher) — no pipeline runs the Catalog yet.
- Reconstructor beyond minimal layout + cross-page continuity (`# TODO: [MVP]`).
- Any notion of solved merged-document detection.

## 5. Functional requirements

### 5.1 Stage 1 — arch-components (kernels)

| ID | Requirement |
|---|---|
| FR-01 | `docflow run --pipeline <CODE> <input> --out <dir>` is the single execution verb. `run` is **idempotent**: a finished run skips, an interrupted run continues from its ledger, `--force` ignores the ledger's completion claims. There is no separate `resume` verb. |
| FR-02 | The system supports `pause <job>`, `resume` (via a plain `run` again) and `stop <job> [--force]`. `stop` with no arguments discovers and reports active runs instead of killing. |
| FR-03 | Every unit has a durable ledger recording the 7 stage states: `pending`, `running`, `done`, `failed`, `blocked`, `stale`, `skipped`. `running` is written **before** the stage's work starts. |
| FR-04 | The system **never writes `done` about work that did not produce a durable artifact**. The write order is write → flush → fsync → rename → `done`. |
| FR-05 | Verification is **mandatory on every ledger read** and has no flag. A stage is trusted only if it is `done` **and** its artifact verifies against the store. |
| FR-06 | Every kernel call returns either a value with evidence, or no value with a reason. There is **no third state**: never an empty string, `0`, `[]`, or a default model as a stand-in. |
| FR-07 | Concurrency is governed by **typed slots** — `cpu`, `gpu`, `remote` — not by a single `--jobs N`. Barriers are dependencies on a *set*; a partial set releases when every member is terminal. Failure is contained to the unit; one failure never aborts the run. |
| FR-08 | Every stage result is keyed by the full cache key (input hash, kernel id/version, adapter revision, params, **registry hash**, **model revision**). A registry change invalidates the affected stages precisely. |
| FR-09 | Kernels declare a determinism class: `deterministic`, `sampled`, or `external`. A **sampled artifact is evidence and is never regenerated**; if its evidence is missing the stage reports `failed`, not a fresh value. |
| FR-10 | K8 registry holds patterns, prompts, schemas, business rules, policies, pipelines and the model catalog as versioned data. A missing asset **fails the run fast**; nothing is defaulted. |
| FR-11 | K7 store is content-addressed (sha256), atomically written, and `get` raises on miss — it **never returns empty**. `run.json` is derived and rebuildable, never authoritative. |

### 5.2 Stage 2 — components (domain)

| ID | Requirement |
|---|---|
| FR-12 | Each of the 10 domain components is invocable standalone via the CLI (`docflow segmenter|identifier|diagnosis|reader|reconstructor|validator|consistency|catalog|contract|reviewer`) and from the library, reading the previous component's artifact and writing its own. |
| FR-13 | The Segmenter groups pages into logical documents, emits a confidence per cut, and **over-segments when in doubt**. A doubtful cut is never merged. |
| FR-14 | The re-segmentation loop runs **once only**. Pages already read are reused; a second pass returning two types routes to review. There is no third pass. |
| FR-15 | The Diagnosis gate is **quality, not presence**: character proportion/alphabetic ratio plus legibility. Three outcomes — route to conversion, adapt then route to OCR, or route aside with a reason. Passing an illegible input to OCR is not expressible. |
| FR-16 | The Reader has two paths: conversion for a usable text layer, OCR for pixels. **Docling is the fixed and only OCR engine**, and there is no engine setting and no flag to change it. An image PDF is rasterized before Docling sees it. Correction applies to the OCR path only and **never to digits**; raw tokens are retained for audit. |
| FR-17 | The Reader returns **positioned tokens**, not ordered text. Reading order belongs to the Reconstructor. |
| FR-18 | The Validator runs 4 **independent** checks (shape, type, content, check digit) over the same field, each issuing its own verdict; the most severe failure governs. No pipeline can skip validation: there is **no `--no-validate`**. |
| FR-19 | The Validator is the single place where "could not" is defined and it owns the escalation ladder. Invalid field → targeted region render. Missing field → whole-document re-read, with no saving. |
| FR-20 | Consistency **normalizes before comparing** (otherwise it measures format, not value), applies tolerance by field type (amounts: cents; identifiers and dates: exact), and uses arithmetic to break a tie before a human is involved. |
| FR-21 | Consistency compares across extractors. This is the **only** mechanism that detects a plausible-but-false value, and it is available only where two reads exist. |
| FR-22 | The Catalog validates identity fields against an external source. Unavailability is **not** invalidity: the field stays `unverified`, never rejected, and the Catalog owns its retry queue. |
| FR-23 | The Contract emits a **verdict vector per field**, never a single confidence score, with `consistency` set only where both reads ran and `null` elsewhere, plus a per-field `(page, extractor)` trace. |
| FR-24 | Failure is **partial**: an illegible page is marked as such and the rest of the document is still emitted, with the absence declared. |

### 5.3 Stage 3 — pipelines (routes)

| ID | Requirement |
|---|---|
| FR-25 | All **13 pipeline codes** are reachable as CLI entry points: `M0-ErVR`, `M0-EpVR`, `M0-ErpVR`, `M1-ErVR`, `M1-EpVR`, `M1-ErpVR`, `M2-ErVR`, `M2-EpVR`, `M2-ErpVR`, `M3-ErVR`, `M3-EpVR`, `M3-ErpVR`, `M4-EpVR`. |
| FR-26 | `--extractor r\|p\|rp` is the alternative to `--pipeline`, letting Diagnosis select the material per file. Passing both is an error. |
| FR-27 | Local models run through **Ollama** as the extraction engine (`--model ollama:<model>`); a frontier LLM (`--validator <provider:model>`) governs escalation. Both resolve by capability, never by name, and an unknown provider or model **fails fast** — never a fallback default. |
| FR-28 | Batch accepts **one file, several files, or a folder**. Folder input **mirrors its tree** in the output: `documentos/2024/enero/factura-001.pdf` → `out/2024/enero/factura-001.json`. |
| FR-29 | Every document writes three artifacts beside each other: `<name>.json` (result), `<name>.ledger.json` (progress), `<name>.work/` (intermediates). A single `run.json` at the output root reports batch progress. |
| FR-30 | `--force` is the single override and means "do not trust the ledger". `--stage` sets the floor for a forced reprocess; `--only failed` scopes a run. Reprocessing a stage **invalidates everything downstream**. |
| FR-31 | M0 accepts text directly (file, Markdown, or `-` for stdin). Pointing M0 at a PDF is an **error**, not a silent conversion. |
| FR-32 | M2 and M3 share **one implementation** with a switch at the front — the rasterization. Six of the thirteen are three designs with a prefix. |
| FR-33 | All 13 codes produce the **same output shape**; the consumer writes one integration. |

## 6. Non-functional requirements (PoC-realistic)

| ID | Requirement | PoC position |
|---|---|---|
| NFR-01 | A run over 11k files completes as **one command** and survives interruption at any point. | Primary PoC target; measured at Stage 3 |
| NFR-02 | Resume re-runs **at most one stage per in-flight document** after a forced kill. | Invariant, tested at Stage 1 |
| NFR-03 | Restart cost is bounded: a killed run must not repeat completed work. | Guaranteed by ledger + verification |
| NFR-04 | `--jobs`/`DOCFLOW_JOBS` bounds CPU work; GPU work is serialized to one in-flight generation per device. | Enforced by typed slots |
| NFR-05 | Secrets (`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `DOCFLOW_OLLAMA_HOST`) come from the environment only — never a flag. | Environment-only |
| NFR-06 | Configuration precedence is CLI flag → environment → `.env` → built-in default. `--force`, `--stage` and `--only` are **never settable** by environment. | Implemented at Stage 1 |
| NFR-07 | Every field's trace points at the right pixels: a crop's coordinates are mapped back to source page coordinates before leaving the image kernel. | Contract-level correctness |
| NFR-08 | Structured output is grammar-constrained where the provider supports it; truncation is detected and mapped to a typed error, never parsed as complete. | Local + frontier |
| NFR-09 | Observability is the ledger and `run.json`, readable with `jq` without the tool installed. | Metric dashboards and tracing are `# TODO: [RELEASE]` |
| NFR-10 | Per-document cost is recorded (`CallRecord`: provider, model revision, tokens, cost, latency, request id). | Recorded, not yet budgeted |
| NFR-11 | Latency, throughput and availability targets are not fixed for the PoC; the first full run sets the baseline. | `# TODO: [MVP]` |
| NFR-12 | Deployment is a local process; no HA, no horizontal scale, no multi-region. | `# TODO: [RELEASE]` |

## 7. Deferred with explicit markers

| Deferred item | Marker | Source |
|---|---|---|
| `--dry-run`, `--format`, `--schema`, `--golden`, `--isolate`, `--keep-artifacts`, `--show-evidence`, `--continuity-only`, `--source`, `--failed`, `--state`, `--retry-queue`, `--retry`, `--rebuild`, `--rebuild-index`, `--rule`, `--new-type`, `--value` | `# TODO: [MVP]` | `03-cli.md` deferred flags |
| 6 categories of Validator business rules: range, relations between fields, conditional, structural, domain-specific, cross-document | `# TODO: [MVP]` | `02-components.md` pending business rules |
| Golden-set comparator and its labeller role | `# TODO: [MVP]` | `--golden`, deferred |
| Object-storage / database artifact backends | `# TODO: [RELEASE]` | K7 reusability |
| Telemetry, caching layers, HA, strict security compliance | `# TODO: [RELEASE]` | Lifecycle §5 |

## 8. Acceptance criteria (PoC)

```gherkin
Scenario: Resume after a forced kill
  Given a batch run over a folder that is executing stage "extract.p"
  When the operator runs "docflow stop --force"
  Then every interrupted stage is recorded as "running" in its ledger
  And the next "docflow run --pipeline <CODE>" re-runs that stage at most
  And every stage recorded "done" whose artifact verifies is skipped

Scenario: The 15400 vs 1540 contrast case
  Given a document whose total is 1540 and an extraction that reads 15400
  And a pipeline that runs both reads over the same text
  When the run reaches Consistency
  Then "consistency" is set to a disagreement for that field
  And arithmetic is checked first: only the value that closes with subtotal + taxes resolves it
  And if neither closes, the field routes to review with its verdicts intact

Scenario: A sampled artifact is evidence, not a cache
  Given a stage produced by a sampled kernel whose artifact is missing
  When the ledger is read
  Then the stage is reported "failed" with the evidence-missing reason
  And the system does not silently produce a fresh sample in its place

Scenario: Partial failure marks one page
  Given a document with one illegible page and nine readable pages
  When the Contract emits the document
  Then the illegible page is marked as such
  And the remaining fields are emitted with their verdicts and traces

Scenario: The merged-document limitation is declared, not hidden
  Given a file containing three logical documents
  And a pipeline that runs no Segmenter
  When the run completes
  Then the output is shape-valid and every field carries its verdicts
  And the merged-document limitation remains declared and unsolved

Scenario: Verification is not optional
  Given a ledger claiming a stage "done" whose artifact was deleted
  When any run reads that ledger
  Then the stage is treated as incomplete
  And no flag was required to trigger the check
```

## 9. Domain glossary

| Term | Meaning |
|---|---|
| **File** | What enters the system |
| **Document** | A unit with meaning of its own inside the file |
| **Page** | The physical unit of processing |
| **Material** | How text is obtained — `M0` text arrives directly, `M1` text from a text PDF, `M2` OCR of an image PDF, `M3` OCR of an image, `M4` pixels only |
| **Extractor** | How values are read — `r` regex, `p` prompt, `rp` both |
| **`EVR`** | The primitive: **E**xtractor → **V**alidate → **R**eport |
| **`ErVR` / `EpVR` / `ErpVR`** | The primitive with its mode written inside; Rules is `ErVR`, Interpretation and Vision are both `EpVR` on text and pixels |
| **Pipeline** | A material prefix plus a primitive — code `<material>-<primitive>`, 13 in total |
| **Verdict** | One of the per-field signals: `shape`, `type`, `content`, `digit`, `consistency`, `catalog` |
| **Verdict vector** | A field's verdicts kept separate, never collapsed into a score |
| **Contrast** | Two independent reads of the same field compared; available only in `ErpVR` |
| **Escalation ladder** | conversion → `ErVR` → `EpVR` → pixels; governed by the Validator |
| **Kernel** | K1–K8: a reusable engine with no domain noun in its API |
| **Ledger** | `<name>.ledger.json` — the per-document durable record of stage states |
| **Manifest** | `run.json` — derived, rebuildable, never authoritative |
| **Barrier** | A dependency on a set: Segmenter waits for all pages read, Consistency across extractors waits for both reads, Contract waits for all pages resolved |
| **Critical field** | A field subject to contrast and to targeted escalation (amounts, identifiers) |

## 10. Known limitations — declared, not solved

Copied from `README.md`. No document may claim these are solved.

| Limitation | Why it is not solved inside | Mitigation owner |
|---|---|---|
| **Plausible but false value** | Needs contrast or an external source; no internal check sees it | Stage 2 — Consistency (`ErpVR`) / Catalog |
| **Bad anchor in either mode** | The value is real and correctly typed; only contrast detects it | Stage 2 — Consistency, requires an `ErpVR` pipeline |
| **Doubtful segmentation cut** | Over-segmentation mitigates, it does not eliminate | Stage 2 — Segmenter |
| **External source down** | It is retried, but meanwhile the field stays `unverified` | Stage 2 — Catalog retry queue |
| **Merged documents** | A merge error precedes every extractor, so contrast agrees with it | **No stage closes it** — declared permanently |
| **Missing field escalated** | With no prior location, the pixel read re-runs over the whole document: no saving | Stage 2 — Validator escalation policy |
