# E05 — Batch input & material routing

| Field | Value |
|---|---|
| Epic ID | **E05** |
| Capability | Batch input & material routing — one file, several files or one folder as input; each file's material chosen by Diagnosis under `--extractor`; and the input tree mirrored in the output, empty directories included |
| Issues | `E05-01` (`S3-T05`) — status `todo` · `E05-02` (`S3-T06`) — status `todo` |
| Issue count | **2** |
| Owner layer | **Surface** (`wbs.md` §8) — `docflow/cli.py`, `docflow/batch.py` |
| Wave span | **W3** |
| Effort total | **2 × M** |
| Source plan | [`../../plan-03-pipelines.md`](../../plan-03-pipelines.md) §2, §5 (`S3-T05`, `S3-T06`), §3 (the mirrored-tree evidence row and the `--extractor` error command), §6 step 10, §7b rows 2–3, §8, §12 #10, §13 Track 4 and Track 1 rung 2 |
| Depends on other epics | **E01** (`S3-T02` → both issues, two edges); entered from `S1-T18` and `S2-T04` (external) |

---

## §1 Objective

E05 delivers the two things that make a run *over a corpus* rather than over a file: **the selector** (`--extractor r|p|rp`, where the material is chosen **per file** by Diagnosis rather than declared once for the whole input) and **the batch shape** (one file, several files, one folder — with the folder's tree mirrored exactly in the output). Its capability is that a mixed-material folder routes each file correctly, that passing both `--extractor` and `--pipeline` is an **error and never a precedence rule**, and that `documentos/2024/enero/factura-001.pdf` comes out as `out/2024/enero/factura-001.json` with **empty directories preserved**.

The mirroring is not cosmetic. `plan-03-pipelines.md` §6 step 10 calls it *"the one thing `my_prompt.md` asks for by name"*, and `plan-03-pipelines.md` §13 Track 2 lists it among the claims whose golden artefact is *"a nested folder with empty directories"*. A flattened tree breaks the consumer's ability to map a result back to its input, which is the same failure class as a result indistinguishable from a ledger.

It is a separate deliverable because it is the **input side of the surface**: E04 owns what sits beside a result, E05 owns where results come from and where they go. It is also the epic with the plan's **two `S3-T02` edges** — both issues need the codes resolved before either can route anything, which is why E01 → E05 is drawn twice (index README §3, rows 2–3).

**What E05 is not.** It is not the codes themselves (E01), not the output layout (E04), not the invalidation flags (E06), and not the tree *contents* — `S3-T06` walks the tree and reproduces its structure; what is written inside each directory is E04's. It is also not a scheduler: a folder is a unit set, and how the units are dispatched is K1's (`S1-T06`).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E05-01` | `S3-T05` | `--extractor r\|p\|rp` with per-file material selection by Diagnosis | W3 | `S3-T02` → **E01** (inter) · `S2-T04` (external — the Diagnosis quality gate) | M | `# TODO: [MVP]`: `--dry-run` to inspect the selection without running |
| `E05-02` | `S3-T06` | Batch input: one file, several files, one folder; mirrored output tree | W3 | `S3-T02` → **E01** (inter) · `S1-T18` (external — the product CLI shell) | M | `# TODO: [MVP]`: symlink and permission edge cases |

No intra-epic edges exist: E05's two issues are independent inside the epic. `E05-01` needs the codes and the Diagnosis gate; `E05-02` needs the codes and the CLI shell. Neither waits on the other — the selector chooses a material *per file*, and batch is the thing that produces the *files*. They share an epic because both are the input surface over the same 13 codes, not because one follows the other.

---

## §3 Issue detail

### `E05-01` — implements `S3-T05`

**Title**
`--extractor r|p|rp` with per-file material selection by Diagnosis.

**Context**
Declaring `--pipeline M1-ErpVR` over a folder asserts that every file in it is M1. When the folder holds mixed materials, that assertion is wrong for some files and the run has no way to say so — unless the caller can delegate the decision. `FR-26` provides exactly one alternative: `--extractor r|p|rp`, where the material is chosen **per file by Diagnosis**, whose whole purpose is *quality, not presence* (`FR-15`). The design discipline is in the same requirement: passing both `--extractor` and `--pipeline` is an **error**, never a precedence rule — because a caller who passes both believes they declared a pipeline and would receive a diagnosis, which is a silent substitution of intent.

**Deliverable**
CLI + Diagnosis selector — `docflow run --extractor r|p|rp <input> --out <dir>`.

**Depends on**
- `S3-T02` — **inter-epic** (E01 → E05): the selector's alternative is the 13 codes, and the material axis it selects over is the axis those codes are prefixed by.
- `S2-T04` — **external entry edge**: the Diagnosis gate is what performs the per-file material selection; this issue exposes it on the batch surface rather than reimplementing it.

**Acceptance criteria**
- [ ] `docflow run --extractor r|p|rp <input> --out <dir>` is accepted, and `r` / `p` / `rp` map to the extractor axis of the primitive (`ErVR` / `EpVR` / `ErpVR`).
- [ ] **Per-file material selection by Diagnosis**: in **one pass** over a mixed-material folder, each file is routed according to its own material — text PDFs to M1, image PDFs to M2, images to M3 — and the routing decision is recorded rather than implied.
- [ ] A mixed-material folder is routed correctly **in a single invocation**; the test is one pass, not three filtered ones.
- [ ] **Passing both `--extractor` and `--pipeline` is an error** — a usage error naming the conflict, never a precedence rule and never a silent win for either flag (`FR-26`).
- [ ] The selection is a **quality** decision, not a presence check: a text PDF with an invisible or unusable text layer is not routed to conversion on the ground that characters exist (`FR-15`, `S2-T04`).
- [ ] The chosen material for each file is **observable in the output** — the result and the ledger record which code ran, so the caller can audit the selection.
- [ ] No default material is substituted when Diagnosis cannot classify a file: the file's outcome is a typed result, not a fallback route. **Never** a default model, engine or threshold (`prd.md` §10).
- [ ] **`--model <provider:model>` is the batch surface's model selector, and it resolves through the same chain as the rest of the operational settings** — `--model` / `DOCFLOW_MODEL` / `.env` / default, CLI first (`S3-T12`). The `plan-03-pipelines.md` §3 acceptance commands carry it (`docflow run --extractor rp documentos/ --model ollama:qwen2.5 --out out/`) and the gate's single-file rungs carry it (`--model ollama:qwen2.5`, `--model ollama:llava`); this issue is where it must be accepted on the batch form. **No default or fallback model exists**: an unpulled or unknown model fails with a typed reason naming the remedy (`kernel-cli.md` §5 `model_not_pulled`, exit `3`), never a substituted one — the same discipline `E03-01` asserts for warming.
- [ ] No new kernel-boundary type is introduced (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T05` — the verifiable criterion: *"One pass over a mixed-material folder routes each file correctly; passing both `--extractor` and `--pipeline` is an error."*
- `plan-03-pipelines.md` §8 — *"**FR-26**"*, proof *"One pass over a mixed-material folder routes per file; both flags together is an error."*
- `plan-03-pipelines.md` §3, acceptance commands step 3 — *"the alternative naming form, and the error when both are passed"*: `docflow run --extractor rp documentos/ --model ollama:qwen2.5 --out out/`, then `docflow run --extractor rp --pipeline M1-ErpVR documentos/ --out out/   # must be an error`.
- `plan-03-pipelines.md` §7b row 2 — *"`--extractor` and `--pipeline` are mutually exclusive"*: pass both. What breaking it looks like: *"the flag wins silently, so the caller thinks they declared a pipeline and got a diagnosis."*
- `plan-03-pipelines.md` §6 step 1 — *"Prepare inputs."* The wrong result this step guards against is the one this issue exists to prevent: *"choosing `--pipeline` for a folder with mixed materials and silently mis-routing every file whose material differs."*
- `plan-03-pipelines.md` §13, Track 4 — the command table: *"`docflow run --extractor r\|p\|rp <input> --out <dir>` — Material chosen per file by Diagnosis — Passing both `--extractor` and `--pipeline` is an **error**, never a precedence rule (`S3-T05`, `FR-26`)."*
- `prd.md` §5.3 **FR-26** — *"`--extractor r|p|rp` is the alternative to `--pipeline`, letting Diagnosis select the material per file. Passing both is an error."* And **FR-15** (stage 2) for the quality-not-presence rule the selector inherits.
- `traceability.md` §4.1 **FR-26** (task `S3-T05`).

**Out of scope for this issue**
- **`--dry-run`** to inspect the selection without running. Named as this task's own deferral in `wbs.md` §5 and `plan-03-pipelines.md` §2. `# TODO: [MVP]`.
- **The batch forms themselves.** One file, several files, one folder and the mirrored tree are `E05-02` (`S3-T06`); this issue assumes the input shape and decides the route.
- **The 13 codes.** `S3-T02` (E01) declares them; this issue uses them as the alternative naming form.
- **Material detection logic.** The per-file decision is Diagnosis's (`S2-T04`); this issue surfaces it and records it.
- **A precedence rule between `--extractor` and `--pipeline`.** **Never** — both together is an error (`FR-26`).
- **A default material, model or threshold when classification is uncertain.** **Never** (`prd.md` §10).
- **A per-corpus OCR engine choice.** Docling only, and it is never a setting. **Never** (ADR-001).
- **The invalidation flags over a mixed run.** `--force`/`--stage`/`--only` are `E06-01` (`S3-T08`).
- **Re-routing on a resumed run.** Resume continues the in-flight document's stage; it does not re-diagnose. `E06-02`'s (`S3-T09`).

**Effort**
**M** — one flag with three values over one selection operation, but the verification needs a **mixed-material fixture** and asserts three behaviours at once: correct per-file routing in a single pass, an error when both flags are passed, and the recorded decision. Multiple interacting concerns with a dependency on the Diagnosis gate (`wbs.md` §7).

**Owner**
**Surface** — `docflow/cli.py` is the Surface layer's artifact (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 2 row — the Diagnosis outcome vocabulary and the material/verdict shape the routed pipeline must emit unchanged. **Publishes** part of the Plan 3 row: the `--extractor` form as one of the two CLI routes.

---

### `E05-02` — implements `S3-T06`

**Title**
Batch input: one file, several files, one folder; mirrored output tree.

**Context**
The problem statement is *"eleven thousand documents must be read"* — and eleven thousand documents arrive as a tree, not as an argv list. `FR-28` fixes the three batch forms and the mirroring, and the mirroring is the half that is easy to get subtly wrong: a naive implementation walks the input, filters to files, and writes results into a flat `out/`, which loses the mapping between a result and its source the moment two directories hold a `factura-001.pdf`. The requirement is exact: `documentos/2024/enero/factura-001.pdf` → `out/2024/enero/factura-001.json`, **including empty directories** — because an empty directory in the input is a fact about the corpus that a structural diff will look for (`plan-03-pipelines.md` §6 step 10).

**Deliverable**
`docflow/batch.py`.

**Depends on**
- `S3-T02` — **inter-epic** (E01 → E05): batch resolves each input to a code.
- `S1-T18` — **external entry edge**: the product CLI shell (`run`, `status`, `jobs`, `pause`, `stop [--force]`) is what batch hangs off; this issue adds the input forms, not the verbs.

**Acceptance criteria**
- [ ] **One file** as input works: `docflow run --pipeline <CODE> <file> --out <dir>`.
- [ ] **Several files** as input works: the same command with multiple file arguments, each producing its own result.
- [ ] **One folder** as input works: the folder is walked and every document under it is processed.
- [ ] **The tree is mirrored**: `documentos/2024/enero/factura-001.pdf` → `out/2024/enero/factura-001.json`, with the relative path preserved exactly.
- [ ] **Empty directories are preserved** in the output — a structural diff of the input tree against `out/` reports no difference at the directory level.
- [ ] The mirroring is verified by a **structural diff of input vs output**, not by spot-checking one path (`plan-03-pipelines.md` §7b).
- [ ] The relative path is the only thing carried across: no absolute path, no input-root name and no hash is injected into the output path.
- [ ] Two files with the same basename in different directories produce **two** results, at their own mirrored paths, with no collision.
- [ ] No new kernel-boundary type is introduced (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T06` — the verifiable criterion: *"`documentos/2024/enero/factura-001.pdf` → `out/2024/enero/factura-001.json`; the tree is preserved exactly, **including empty directories**."*
- `plan-03-pipelines.md` §8 — *"**FR-28**"*, proof *"The tree is preserved exactly, empty directories included."*
- `plan-03-pipelines.md` §3, observable evidence — the mirrored-tree row: *"`documentos/2024/enero/factura-001.pdf` → `out/2024/enero/factura-001.json`; **empty directories preserved**"*, guarding against *"a flattened output tree, or a dropped directory."*
- `plan-03-pipelines.md` §6 step 10 — *"Verify the mirrored tree."* Diff the input tree's directory structure against `out/`. The wrong result: *"a flattened tree — the one thing `my_prompt.md` asks for by name."*
- `plan-03-pipelines.md` §7b row 3 — *"The mirrored tree is exact"*: structural diff of input vs output, **including empty directories**. What breaking it looks like: *"a flattened tree, or empty directories dropped."*
- `plan-03-pipelines.md` §6 step 5 — *"Measure the tree before the tree is walked."* Count the documents **and the directories, including empty ones**; the count is what `run.json` will later be checked against. The wrong result: *"an unbounded run whose completion cannot be distinguished from a truncated one."*
- `plan-03-pipelines.md` §13, Track 1 rung 2 — *"A small folder with **nested and empty** subdirectories"*: what it validates is *"the mirrored tree, the suffix rule, `run.json`"*; it fails fast on `S3-T06`, `S3-T07`.
- `plan-03-pipelines.md` §13, Track 2 — *"The tree mirrors the input"*: golden artifact = a nested folder with empty directories; must fail when broken by *"a flattened tree, or a dropped directory — the one thing `my_prompt.md` asks for by name"*; task `S3-T06`.
- `plan-03-pipelines.md` §11 — *"A batch accepts one file, several files, or a folder, and a folder input mirrors its tree in the output including empty directories."*
- `prd.md` §5.3 **FR-28** — batch accepts one file, several files, or a folder; folder input mirrors its tree.

**Out of scope for this issue**
- **Symlink and permission edge cases** in the mirrored tree. Named as this task's own deferral in `wbs.md` §5, `plan-03-pipelines.md` §2 and §7d (declared PoC limitation). `# TODO: [MVP]`.
- **What is written inside each mirrored directory.** The three artefacts and their suffix rule are `E04-02` (`S3-T07`); this issue reproduces the *structure* and names the result path.
- **Object-storage backends.** Whether the mirrored tree survives the move to object storage is carried **open** (`plan-03-pipelines.md` §12 **#10**, touching `S3-T06` and `S3-T07`): content addressing survives, but colocation of ledger and result is a filesystem property. `# TODO: [RELEASE]`.
- **Progress reporting for a folder run.** `run.json` is `E04-02`'s; this issue feeds it a unit set.
- **Selection of material per file.** `E05-01` (`S3-T05`); batch over `--extractor` input is the combination of the two, and the combination is exercised at rung 2 and rung 3 of Track 1.
- **Parallelism and slot bounds.** How many of the walked units run at once is the slot policy (`E03-01`) over K1's dispatch (`S1-T06`).
- **`--format`, `--schema`, `--failed` and the other deferred flags** over a folder. `# TODO: [MVP]`.
- **A per-folder manifest.** `run.json` is one per run at the output root (`FR-29`); a manifest per input directory would make the derived artefact authoritative at a smaller scope. **Never**.

**Effort**
**M** — three input forms and one structural property, where the property (mirroring including empty directories) is what the verification is really about and cannot be asserted from a single path. Needs a nested fixture with empty directories and a structural differ — a fixture-backed verification rather than a unit assertion (`wbs.md` §7).

**Owner**
**Surface** — `docflow/batch.py` is the Surface layer's artifact (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 row of `plans/README.md` §3 (the unit set K1 iterates over) and the CLI shell's verb contract (`S1-T18`). **Publishes** part of the Plan 3 row: *"the mirrored-tree and the three-artifact layout"* — with the mirrored tree being this issue's half.

---

## §4 Epic close condition

E05 is **`done`** when:

1. `E05-01` and `E05-02` are `done`, and
2. the capability is **demonstrable from the input side**: one pass over a mixed-material folder routes each file by its own material and records the decision; passing `--extractor` together with `--pipeline` exits as an **error**; and a structural diff of a nested fixture — empty directories included — against `out/` reports no difference; all three checked by running the commands, not by reading `batch.py`.
3. **Plan 3 DoD, per epic:** no new kernel, no new component, no new kernel-boundary type — this epic adds configuration and data (`plan-03-pipelines.md` §10, Task DoD). The batch walker is the one place in this plan that could grow into a scheduler; it must not.

**Does E05 gate `S3-T14`?** **Yes, directly — through `S3-T05`.** `S3-T14`'s dependency set names `S3-T05`, so E05 → E08 is a direct gate edge. `S3-T06` reaches the gate **transitively** through `S3-T07` → `S3-T08` → `S3-T09`. Both facts matter and they are not the same fact: the gate needs `S3-T05` because the first full run is *"one command, 11k files"* and the corpus's material mix is why §6 step 1 requires it, while it needs `S3-T06` because `run.json`'s `totals.discovered` is checked against a tree that must have been walked exactly. E05 is one of only two epics with a direct edge to the gate *and* a second path into it.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E05-01` | **FR-26** (`--extractor` is the alternative; both is an error) | no | One pass over a mixed-material folder routes per file; both flags together is an error |
| `E05-02` | **FR-28** (batch accepts one file, several files, or a folder; folder input mirrors its tree) | no | The tree is preserved exactly, empty directories included |

No issue in E05 has an empty mapping, and no number was invented. `traceability.md` §5 places `S3-T01`–`S3-T13` under `FR-25`…`FR-33`; both of this epic's issues sit in that range and each names its own requirement — the plan's **no gap, no orphan** result is stated in the index README §6.

**Open decision this epic carries, unresolved:**

| `plan-03-pipelines.md` §12 | Question | Touches | Why it stays open |
|---:|---|---|---|
| **#10** | Whether the mirrored tree survives the move to object storage | `E05-02` (`S3-T06`) and `E04-02` (`S3-T07`) | Content addressing does; colocation of ledger and result is a filesystem property, and object storage has no equivalent of *"beside"*. The PoC is filesystem-only and explicitly so. Recorded because these two tasks would change **shape**, not merely backend, if this is ever revisited — the mirrored tree is a filesystem affordance |

`plan-03-pipelines.md` §12 **#2** (what M0's targeted escalation means) touches `S3-T02` and `S3-T13` and therefore arrives at this epic only through the codes the selector chooses between; it is carried by E01 and E07, not here.

---

## §6 Risks

From `plan-03-pipelines.md` §9 only:

| Risk | L | I | Why it touches E05 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| *(none of the six §9 rows names `S3-T05` or `S3-T06`.)* | — | — | — | — |

**Stated rather than implied:** none of the six risk rows in `plan-03-pipelines.md` §9 names this epic's tasks, and none of the plan's three named execution risks lands on them either. The register's corpus-scale and wording-variant rows touch E02 and E03; the cost row touches E02; the merged-document and sampled-artefact rows touch E06, E07 and E08.

Two facts supply what the register does not:

- **`plans/README.md` §4 lists `S3-T06` among the tasks that can slip.** *"Can slip without delaying a stage close: … `S3-T06`/`S3-T07`/`S3-T10` (batch and layout can land in parallel with registry work)."* That is a scheduling permission, not a waiver: the gate's `totals.discovered` check (§6 step 5–6) and the mirrored-tree evidence (§3) both require `S3-T06` to be `done` before the corpus run, because a run whose tree walk is wrong produces a corpus of results at wrong paths. `S3-T05`, by contrast, **cannot slip** — it is named on the cannot-slip side of the same table.
- **The epic's risk is the one §9 names at the input boundary, in §6 step 1's words:** *"choosing `--pipeline` for a folder with mixed materials and silently mis-routing every file whose material differs."* That is `E05-01`'s subject, and it is a **silent** failure of exactly the class `prd.md` §1 makes the antagonist: the run completes, every file has a result, and some of them describe a route the caller never chose. The mitigation is the acceptance criterion that both flags together is an error, which is the strongest available form — it makes the mistake unexpressible rather than detectable.

---

