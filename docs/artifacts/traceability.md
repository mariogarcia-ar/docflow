# Traceability — `docflow` (PoC)

| Field | Value |
|---|---|
| Purpose | Answer "what asked for this, and what proves it?" for every requirement, pipeline and task |
| Lifecycle stage | **PoC** — close the end-to-end flow, happy path first |
| Companion docs | `prd.md` (the requirements), `sad.md` (the decisions), `wbs.md` (the work), `kernel-cli.md` (the Stage 1 harness), `../../my_prompt.md` (the origin) |
| Status | **Analysis artifact.** No code exists yet; every "Test" cell names a designed verification, not a passing one |

---

## 1. Why this document exists

Three requirements documents and four artifacts were written without a document that says *which* requirement produced *which* decision. That is tolerable while the set is small and becomes expensive the moment the set is large: 10 origin routes became 13 pipeline codes, and nothing recorded the three added or the one changed.

This document is the missing link. It has four jobs:

1. **Origin → requirement.** Every bullet in `my_prompt.md` traced to the FR that encodes it.
2. **Origin → deviation.** Every place the artifacts depart from `my_prompt.md`, with the reason. A silent departure is the failure mode; a recorded one is a design decision.
3. **Requirement → task → test.** FR/NFR → the WBS task that builds it → what proves it.
4. **Gap register.** Requirements with no task, and tasks with no requirement.

**The rule for reading it:** a `—` in the *Task* column is a gap, not a formatting artifact. §7 explains each one.

---

## 2. The origin — `my_prompt.md` → artifacts

`my_prompt.md` is 45 lines and states requirements as prose. This is the full mapping.

| `my_prompt.md` says | Artifact decision | Where |
|---|---|---|
| 11k documents in `documentos`, extract and expose to another system | The PoC target: one command over the corpus, per-field output a consumer integrates against | `prd.md` §1, `NFR-01`, `FR-33` |
| Solution name `docflow` | Product name, `docflow` | `FR-01`, `sad.md` ADR-008 |
| "librería que va a tener diferentes formas de ser consumida" — includes + CLI | **Library first**, CLI as one caller; identical names on both surfaces | `sad.md` ADR-008, `FR-12` |
| Invoke each component from the CLI (`docflow segmentador`, `docflow identificador`) | 10 per-component subcommands, each reading the previous artifact and writing its own | `FR-12`, `S2-T16` |
| Batch: one file, several files, or a folder | `run` accepts all three | `FR-28`, `S3-T06` |
| "respetar la estructura de salida" for a folder | Mirrored tree: `out/2024/enero/factura-001.json` | `FR-28`, `S3-T06` |
| `stop` with force | `stop <job> [--force]`; `stop` bare discovers instead of killing | `FR-02`, `S1-T18` |
| Pause and resume | `pause`, and resume via a plain `run` — there is no `resume` verb | `FR-01`, `FR-02`, `NFR-02` |
| Local models via Ollama, "los cuales necesitan un ajuste" | Ollama as the local engine; `warm`/`pull`/`ps` exist for exactly that adjustment; digest recorded at first use | `FR-27`, `S1-T15`, `S3-T11` |
| Frontier LLM as the validator and "guía de la solución" (deepseek / claude / openai) | `--validator <provider:model>` governs escalation; resolves by capability, never falls back | `FR-27`, `S1-T16`, `S1-T17` |
| "la idea es el golden para usarlos tanto como…" — sentence incomplete | Deferred whole: `--golden`, the labeller role, the comparator | `prd.md` §7, `wbs.md` §10 |
| OCR with Docling ("por debajo usa easy ocr para…") | Docling is the fixed and only engine; **the backend is not a setting** | `FR-16`, `sad.md` ADR-001 |
| The 10 explicit circuits (see §3) | 13 pipeline codes | `FR-25` |
| "imagen > aplicar ocr" as a standalone circuit | `M3` material — image in, OCR, then the extractor | `FR-25`, `S2-T05` |

---

## 3. The 13 codes — derivation and deviation

`my_prompt.md` lists **10 circuits**. The artifacts define **13 codes**. The count is not a mistake, but nothing recorded the delta until now.

### 3.1 The 10 origin routes, mapped

| # | `my_prompt.md` circuit | Code | V present? |
|---:|---|---|:---:|
| 1 | pdf texto > extraer texto > reglas / prompts > validar > reportar | `M1-ErpVR` | yes |
| 2 | pdf texto > extraer texto > reglas > **reportar** | `M1-ErVR` | **no → added** |
| 3 | pdf texto > extraer texto > prompts > validar > reportar | `M1-EpVR` | yes |
| 4 | pdf imagen > convertir > OCR > reglas / prompts > validar > reportar | `M2-ErpVR` | yes |
| 5 | pdf imagen > convertir > OCR > reglas > validar > reportar | `M2-ErVR` | yes |
| 6 | pdf imagen > convertir > OCR > prompts > validar > reportar | `M2-EpVR` | yes |
| 7 | imagen > OCR > reglas / prompts > validar > reportar | `M3-ErpVR` | yes |
| 8 | imagen > OCR > reglas > validar > reportar | `M3-ErVR` | yes |
| 9 | imagen > OCR > prompts > validar > reportar | `M3-EpVR` | yes |
| 10 | imagen > prompts > validar > reportar | `M4-EpVR` | yes |

### 3.2 The three added codes

| Code | Why it exists | Justification |
|---|---|---|
| `M0-ErVR` | Text arrives directly — no acquisition at all | `my_prompt.md` asks for a **library consumed as includes**. A caller already holding text (a form, a DB field, an upstream system) is that consumer, and it needs a pipeline with no file. `01-pipelines.md` §M0 develops it; `FR-31` fixes it accepts text, Markdown or `-`, and **errors** on a PDF |
| `M0-EpVR` | Same, prompt mode | as above |
| `M0-ErpVR` | Same, dual read | as above — and it is where contrast is **cheapest**, since no acquisition has to be repeated (`01-pipelines.md` §283) |

### 3.3 The one changed route

**Route 2 has no `V`, and the artifacts give it one.** `M1-ErVR` validates.

| | |
|---|---|
| **Origin** | `pdf texto > extraer texto > usar reglas > reportar` |
| **Artifact** | `FR-18` — no pipeline can skip validation; there is no `--no-validate`. `sad.md` ADR-002 records the decision |
| **Reason** | A regex match proves a value was **captured**, not that it is **correct**. The `V` is what makes the 13 codes substitutable rather than merely similar: the consumer reads the same verdict vector whatever route produced it (`FR-33`) |
| **Cost** | Route 2 as written is slightly cheaper than `M1-ErVR`. Accepted: a pipeline that can drop validation also can produce a field with no `shape`/`type`/`content` verdict, and the consumer's integration would need two shapes |
| **Where the origin is preserved** | `01-pipelines.md` §130 — "no pipeline skips validation, including the rules-only ones" |

**This is the only requirement-level override in the set.** The other nine routes are implemented as written.

### 3.4 Deviation register

| # | Deviation | Type | Recorded in |
|---:|---|---|---|
| D1 | Route 2 gains a `V` it did not have | **Override** | ADR-002, `FR-18` |
| D2 | Three `M0` codes added (10 → 13) | **Addition** | `FR-25`, `FR-31`, `01-pipelines.md` §M0 |
| D3 | `easyocr` named in `my_prompt.md` as Docling's internal backend is **not mentioned** in the artifacts | **Omission** | ADR-001 (Docling fixed; what it uses underneath is not a setting and not tracked in the cache key) |
| D4 | The golden-set sentence is incomplete in the origin | **Deferral** | `prd.md` §7, `wbs.md` §10 |
| D5 | Corpus thresholds moved from environment settings to registry policy | **Reversal** | ADR-009, `03-cli.md` marked superseded |
| D6 | A `--rebuild-index` **flag** is deferred while `rebuild_index()` is a Stage 1 library call | **Split** | `S1-T06`, `S3-T07` |
| D7 | `run.json` and its rebuild were claimed by two tasks (`S1-T06`, `S3-T07`/`S3-T10`) with no stated division | **Clarification** | `S1-T06` owns the **mechanism** (`rebuild_index()`); `S3-T07` owns the manifest's **shape and location**. K1 is the sole authority; K7's `rebuild_manifest()` delegates |

D5–D7 were ambiguities **inside** the artifacts rather than departures from the origin; each is now stated rather than implied. D1–D4 are genuine departures from `my_prompt.md` and are the ones worth arguing about.
---

## 4. Requirement → task

### 4.1 Functional requirements

| FR | Requirement (abridged) | Stage | Task(s) | Test / proof |
|---|---|:---:|---|---|
| FR-01 | `run` single, idempotent verb | 1 | `S1-T18` | `S1-T19` — repeat `run` skips; after a kill it continues |
| FR-02 | `pause` / `resume` / `stop [--force]` | 1 | `S1-T18` | `S1-T19`; AC *Resume after a forced kill* |
| FR-03 | 7 durable states, `running` before work | 1 | `S1-T07` | `S1-T22` row 1 |
| FR-04 | Never `done` about non-durable bytes | 1 | `S1-T03`, `S1-T07` | `S1-T22` row 2 |
| FR-05 | Verification mandatory, no flag | 1 | `S1-T10` | AC *Verification is not optional*; AC *Resume* |
| FR-06 | No third state at any boundary | 1 | `S1-T01` | unit test asserting `KernelResult` cannot express it |
| FR-07 | Typed slots, barriers, contained failure | 1 | `S1-T09` | synthetic graph, partial-barrier release |
| FR-08 | 7-term cache key | 1 | `S1-T05` | unit test per term; registry-hash term test |
| FR-09 | Determinism classes; sampled = evidence | 1 | `S1-T08` | AC *A sampled artifact is evidence, not a cache* |
| FR-10 | K8 as versioned data, fail fast | 1 | `S1-T04` | `S1-T22` row 17 |
| FR-11 | K7 content-addressed, atomic, `get` raises | 1 | `S1-T02` | `S1-T22` rows 16; store unit tests |
| FR-12 | 10 components standalone via CLI | 2 | `S2-T16` | each component runs from the previous artifact |
| FR-13 | Segmenter over-segments on doubt | 2 | `S2-T01` | ADR-007 test: a doubtful cut is not merged |
| FR-14 | Re-segmentation once only | 2 | `S2-T03` | second pass returning two types routes to review |
| FR-15 | Diagnosis: quality, not presence | 2 | `S2-T04` | stale invisible layer is not routed to conversion |
| FR-16 | Docling fixed; correction never digits | 2 | `S2-T05`, `S1-T14` | no `--engine` flag exists (contract test); raw tokens retained |
| FR-17 | Positioned tokens, no reading order | 2 | `S2-T05`, `S1-T14` | `kernel-cli.md` §11 row 10; tokens carry boxes |
| FR-18 | 4 independent checks; no `--no-validate` | 2 | `S2-T08` | a field passes shape+type, fails content |
| FR-19 | Validator owns "could not" and the ladder | 2 | `S2-T09` | invalid → region; missing → whole document |
| FR-20 | Normalize before comparing; tolerance by type | 2 | `S2-T10` | `1.540,00` == `1540.00`; identifiers exact |
| FR-21 | Contrast across extractors | 2 | `S2-T11` | AC *The 15400 vs 1540 contrast case* |
| FR-22 | Catalog: unavailability ≠ invalidity | 2 | `S2-T12` | non-responding source → `unverified`, never rejected |
| FR-23 | Verdict vector per field + trace | 2 | `S2-T13`, `S2-T14`, `S2-T12` | output matches the documented shape; `consistency: null` on single reads; `catalog` carries a reason |
| FR-24 | Partial failure | 2 | `S2-T13` | AC *Partial failure marks one page* |
| FR-25 | 13 codes reachable | 3 | `S3-T02` | all 13 resolve; unknown code is an error |
| FR-26 | `--extractor` alternative; both is an error | 3 | `S3-T05` | mixed-material folder routes per file |
| FR-27 | Ollama + frontier; resolve by capability | 1–3 | `S1-T15`, `S1-T16`, `S1-T17` | `S1-T22` row 13; unknown model exits 3 with `model_unknown` |
| FR-28 | Batch + mirrored tree | 3 | `S3-T06` | the tree is preserved; empty directories kept |
| FR-29 | Three artifacts beside each other + `run.json` | 3 | `S3-T07` | suffix rule is unambiguous |
| FR-30 | `--force` / `--stage` / `--only` + invalidation | 3 | `S3-T08` | forced `extract.p` re-pends downstream |
| FR-31 | M0 accepts text, errors on a PDF | 3 | `S3-T02` | `M0-*` at a PDF exits as an error |
| FR-32 | M2/M3 one implementation, switch at front | 2 | `S2-T06` | a test asserts the switch is the only difference |
| FR-33 | All 13 produce the same shape | 3 | `S3-T13` | contract test across 13 codes |

### 4.2 Non-functional requirements

| NFR | Requirement (abridged) | Stage | Task(s) | Test / proof |
|---|---|:---:|---|---|
| NFR-01 | 11k files, one command, survives interruption | 3 | `S3-T09`, `S3-T14` | the first full run |
| NFR-02 | At most one stage re-run per in-flight document | 1 | `S1-T07`, `S1-T19` | `S1-T19`'s closing assertion |
| NFR-03 | Restart cost bounded | 1 | `S1-T03`, `S1-T05` | ledger + verification test |
| NFR-04 | `--jobs` bounds CPU; GPU serialized | 1, 3 | `S1-T09`, `S3-T11` | slot tests; `keep_alive` check |
| NFR-05 | Secrets from the environment only | 1 | `S1-T16` | no `--api-key` flag exists (contract test) |
| NFR-06 | Precedence for **operational** settings | 1, 3 | `S1-T18`, `S3-T12` | precedence test; `--force` not settable |
| NFR-06a | Corpus policy is registry data, **not** configuration | 2, 3 | `S2-T04`, `S3-T12` | a test asserts no policy value can be set from the environment |
| NFR-07 | Trace points at the right pixels | 1 | `S1-T13` | `S1-T22` row 8 — inverse map |
| NFR-08 | Truncation is typed, never parsed | 1 | `S1-T15`, `S1-T16` | `S1-T22` row 12 |
| NFR-09 | Observability is the ledger and `run.json`, `jq`-able | 1, 3 | `S1-T06`, `S3-T07` | `S1-T22` row 16 |
| NFR-10 | `CallRecord` per document | 1 | `S1-T16` | `call_record` populated on K6 |
| NFR-11 | No latency targets in the PoC | 3 | `S3-T14` | the first run sets the baseline |
| NFR-12 | Local process, no HA | — | — | **out of scope**, `# TODO: [RELEASE]` |

---

## 5. Task → requirement (the reverse check)

Every task must trace back, or it is work nobody asked for.

| Tasks | Traces to |
|---|---|
| `S1-T01`–`S1-T10`, `S1-T19` | FR-03…FR-11, NFR-02, NFR-03 — the orchestrator/store/ledger spine |
| `S1-T11`–`S1-T17` | `my_prompt.md` (Docling, Ollama, frontier validator) → FR-16, FR-27, NFR-05, NFR-08 |
| `S1-T18` | FR-01, FR-02, FR-28, NFR-06 |
| `S1-T20`, `S1-T21`, `S1-T22` | The user requirement that kernels be testable independently before the domain layer is built on them; `S1-T22` is the 17-row matrix |
| `S2-T01`–`S2-T15` | FR-12…FR-24 — the 10 components |
| `S2-T16`, `S2-T17` | FR-12, FR-21, FR-24 — the per-component surface and the Stage 2 close |
| `S3-T01`–`S3-T13` | FR-25…FR-33 — the 13 codes |
| `S3-T14` | NFR-01, NFR-11 — the corpus close |

**No orphan task.** Every one of the 53 traces to an FR, an NFR, or a stated user requirement.

---

## 6. Test inventory

What exists today, by kind:

| Kind | Count | Where | Runs when |
|---|---:|---|---|
| Acceptance scenarios (Gherkin) | 6 | `prd.md` §8 | Stage 1 (3), Stage 2 (2), Stage 3 (1) |
| Silent-failure matrix rows | 17 | `kernel-cli.md` §11 | 16 in the Stage 1 gate; row 15 gated on `judge` |
| Stage closing flows | 3 | `S1-T19`, `S2-T17`, `S3-T14` | one per stage; a stage is not done without it |
| Flag/port contract tests | 2 | `S1-T21` (flag ↔ port), `S3-T13` (13 codes, one shape) | Stage 1, Stage 3 |
| Invariant tests | ≥6 | `FR-06`, ADR-002, ADR-005, ADR-006, ADR-007, ADR-009 | with the task that introduces the invariant |

**The AC-to-stage split matters more than the count.** Three of the six scenarios close at Stage 1 — the synthetic flow, which is where resume, `running`-before-work and mandatory verification are actually provable. If those three slip to Stage 2, the invariants they assert are being tested inside a domain component, which is exactly the misattribution `kernel-cli.md` §1 exists to prevent.

---

## 7. Gap register

### 7.1 Requirements with no task

| Item | Status | Why it is acceptable now |
|---|---|---|
| NFR-12 (deployment) | **No task, deliberately** | `# TODO: [RELEASE]`. A local process needs no task to build; it needs one to un-build. |
| FR-31's M0 text input | Covered by `S3-T02` only at Stage 3 | M0 cannot be exercised before the 13 descriptors exist. Accepted, and it is the reason `M0-*` is not on the critical path. |
| `prd.md` §4.2's object-storage exclusion | No task | An exclusion, not a requirement. It is in the register so it is not silently dropped. |
| Golden set / labeller | Deferred with markers | `prd.md` §7, `wbs.md` §10. Origin sentence is incomplete (D4). |

### 7.2 Open questions carried, not closed

These are unresolved in the artifacts **by design**, and each is an input to the design, not a defect:

| Question | Where | Impact if deferred past Stage 1 |
|---|---|---|
| Whether the kernel CLI may execute a descriptor with domain-component stages | `kernel-cli.md` §17 | Stage 1's flow stays synthetic — intended, but it means the same command cannot debug a real graph |
| Whether `--save` needs an explicit `--root` | `kernel-cli.md` §17 | A default temp root makes a hash real but the artifact disposable; a test can pass over bytes already gone |
| Whether the 17 rows run in CI at all stages | `kernel-cli.md` §17 | The K4–K6 rows need GPU, tokens and provider availability; unsplit, the suite becomes flaky and then ignored |
| Whether `registry hash` is per-asset | `kernel-cli.md` §17 | One hash means a prompt tweak invalidates a schema version — coarse but never wrong |
| What M0's targeted escalation means | `01-pipelines.md` §393 | No page and no image, so "render the region" is meaningless; M0 escalation is unresolved |
| Whether M0's trace carries a hash of the processed text | `01-pipelines.md` §395 | Without it, an offset into supplied text points at a string that may not exist in that form |
| **Whether `S2-T12` (Catalog) is a dependency of `S2-T17`** | `wbs.md` §6.2 | `FR-23` obliges the Contract to emit `catalog` with the reason `not_run` on every field, and that value is the Catalog's to define — yet the dependency diagram marks the Catalog unreachable. Either `S2-T17` gains the dependency (Catalog moves onto the path) or `not_run` is defined where the Contract can reach it without the Catalog existing. Unresolved; it changes the dependency table |

**One of these is load-bearing for the PoC and should be settled before Stage 2:** the M0 escalation question. `S2-T09` builds the escalation ladder and `M0-*` is three of the thirteen codes; discovering at `S3-T13` that M0 breaks an assumption the other ten materials share would invalidate the shape-identity test (`FR-33`) rather than one pipeline.

### 7.3 Defects closed in the analysis pass

Recorded so the reasoning survives the edit:

| # | Defect | Resolution |
|---|---|---|
| 1 | Stage 1 scope contradicted its own acceptance suite — `S1-T21`/`S1-T22` required every §9 command while `sad.md` §3 called some `MVP` | §9 gained a per-command `now`/`MVP` status; `S1-T21`/`S1-T22` scoped to `now`; row 15 declared and gated |
| 2 | `--rebuild-index` was deferred *and* a Stage 3 done-when criterion | Split: `rebuild_index()` is Stage 1 (`S1-T06`); the flag stays deferred. K1 is the sole authority; K7 delegates |
| 3 | Corpus thresholds lived in the environment (Stage 3) and in the registry (Stage 2) at once | ADR-009: registry, no override. `NFR-06a` added; `03-cli.md` marked superseded |
| 4 | The 13 codes had no derivation from `my_prompt.md`'s 10 routes | This document, §3 |
| 5 | `S1-T20` named both a module and a package at the same path | Package only: `docflow/kernel_cli/__init__.py` + `main.py` |
| 6 | `reason.code` was a closed set that omitted the codes its own rows assert on | Full table with codes *and* exits; `model_unknown`, `provider_unknown`, `role_conflict`, `asset_missing` added |
| 7 | Guardrail 2 forbade the words three matrix rows assert on | Restated as observation vs. decision; thresholds explicitly not the kernel's |
| 8 | `catalog: unverified` meant both "never attempted" and "source down" | The Contract records the reason (`not_run` / `source_unavailable` / `pending_retry`); FR-23 and `sad.md` §11 updated |
| 9 | Critical-path arithmetic omitted `S1-T04` from the chain it counted | Chain corrected to 9 links; the derivation is now stated so it can be re-checked |
| 10 | One operation had three names across K1, K7 and the CLI | Authority stated in `kernel-cli.md` §9 |
| 11 | DoR required "a single owner" with no way to check it | Ownership table by layer, `wbs.md` §8 |
| 12 | `README.md` linked a path that does not exist; `docs/artifacts/` was unlisted | Link fixed; artifacts index added |
| 13 | `.env.example` called nine settings "nine flags" | Rewritten; the policy section now states the reason it is empty |
| 14 | Row 15's assertion matched a prose message | `role_conflict` added; exit reconciled to `3` so the envelope rule holds |
| 15 | `--out` was used but not in the allowed flag vocabulary | Added, with the `--out` vs `--root` boundary stated |
| 16 | **The Segmenter/Identifier were listed as non-critical while `S2-T17` depended on `S2-T03`.** `wbs.md` §6 said `S2-T02`/`S2-T03` "are not on the canonical chain — no pipeline runs them", but the same section's dependency table made `S2-T17` — Stage 2's closing criterion — depend on `S2-T03`, and `sad.md` §9 draws `File → Segmenter → Identifier → …` as the chain the close walks. Root cause: two different claims collapsed into one — *no pipeline invokes the Segmenter over the corpus* (true, and the declared permanent limitation) versus *the Segmenter task does not gate Stage 2* (false). A planner reading §6 would have under-estimated the Stage 2 close, which is the class of error this document set exists to prevent. | Rebuilt §6 by **computing** the path from the `Depends on` column instead of hand-listing it. `S2-T01`/`S2-T02`/`S2-T03` are on the path; §6.2 now shows `S2-T17`'s five dependency branches and identifies the longest, so both the obligation and the schedule driver are visible. Two further instances of the same collapse were found and fixed while verifying: `S2-T07` (Reconstructor — Stage 2's criterion requires the reading order it produces) and `S2-T12` (Catalog — now recorded as an open decision, §7.2). |

---

## 8. How to keep this true

The matrix is only worth what its maintenance costs. Two rules:

1. **A requirement change edits three things:** the `my_prompt.md` mapping (§2), the deviation register (§3.4) if it departs, and the row in §4. A change that touches one and not the others is how this document becomes fiction.
2. **A new task without an FR is a finding.** §5 is checked at each stage close, alongside the Stage DoD in `wbs.md` §8 — an orphan task means either a missing requirement or work nobody asked for, and both are worth knowing before the task is started rather than after.

**Definition of Ready, extended.** A task is ready when its row in §4 exists. A task with a `—` in the *Task* column of §4 is a requirement nobody has planned; a task absent from §5 is work nobody has justified.
