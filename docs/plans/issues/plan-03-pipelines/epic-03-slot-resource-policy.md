# E03 — Slot & resource policy for the corpus

| Field | Value |
|---|---|
| Epic ID | **E03** |
| Capability | Slot & resource policy for the corpus — `DOCFLOW_JOBS` bounds CPU work, `gpu` is bounded to one in-flight generation per device, and the Ollama model is loaded once across the run |
| Issues | `E03-01` (`S3-T11`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Data** (`wbs.md` §8) — `.env.example` + slot config |
| Wave span | **W1** |
| Effort total | **1 × M** |
| Source plan | [`../../plan-03-pipelines.md`](../../plan-03-pipelines.md) §2, §5 (`S3-T11`), §6 step 4, §7b (`keep_alive`/slot rows), §8, §9 (the 11k-file row), §12 #6, #7 |
| Depends on other epics | **none** — entered from `S1-T09` (typed slots) and `S1-T15` (the Ollama adapter) as external entry edges |

---

## §1 Objective

E03 delivers the machine's half of the corpus problem: **before 11k files are walked, the run's resource policy is settled.** Its capability is that `DOCFLOW_JOBS` bounds CPU work, that `gpu` is bounded to **one in-flight generation per device**, and that the Ollama model is **loaded once across the whole run** (`keep_alive`). The point is not throughput — it is that the corpus run's per-stage timings stay *meaningful*. Eight concurrent GPU generations queueing behind each other do not run eight times faster; they make each stage's recorded latency a function of contention rather than of work, which destroys the baseline `S3-T14` is supposed to record (`NFR-11`).

It is a separate single-issue epic because **slot and resource policy is a different deliverable from registry data**. E02 authors what the corpus *means* (patterns, critical fields, tolerances); E03 authors how much of the machine the corpus may take. `sad.md` §5.1 requires those two surfaces to stay apart — policy has no override, operational settings have a precedence chain — and folding slot policy into the assets epic would put "how many jobs run" and "what counts as a critical field" in one deliverable. The artifact is `.env.example` plus slot configuration, owned by **Data**, while the slots it bounds are a Plan 1 mechanism (`S1-T09`) that this plan configures rather than extends.

**What E03 is not.** It is not the slot *implementation* — typed slots, barriers and unit-contained failure are the Plan 1 freeze (`S1-T09`, `sad.md` §7.2), and Stage 3 adds no new slot type. It is not the precedence chain over the settings it introduces (that is `E02-02`). It is not a scheduler, a queue or a VRAM allocator: `gpu = 1` is a declared simplification with an acknowledged undefined competition policy (`plan-03-pipelines.md` §12 #7).

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E03-01` | `S3-T11` | Slot and resource policy for the corpus | W1 | `S1-T09` (typed slots) · `S1-T15` (Ollama adapter / `warm`) — both **external entry edges** | M | `# TODO: [RELEASE]`: per-device VRAM scheduling beyond `gpu=1` |

No intra-epic edges exist: E03 is a single-issue epic. It carries **two** external entry edges and no inter-epic dependency, which is why it opens in W1 alongside `S3-T01` and `S3-T04` and is one of the three independent heads of the plan.

---

## §3 Issue detail

### `E03-01` — implements `S3-T11`

**Title**
Slot and resource policy for the corpus.

**Context**
`prd.md` §6 `NFR-04` fixes that `--jobs`/`DOCFLOW_JOBS` bounds CPU work and that GPU work is serialized to one in-flight generation per device, and `sad.md` §7.2 states why: *"A single `--jobs 8` is wrong for this workload: eight page renders and eight Ollama generations are not eight of the same thing."* Stage 1 built the mechanism — typed slots `cpu`/`gpu`/`remote` with a default bound of 1 per device for `gpu` (`sad.md` §7.2) — and Stage 3 is where the policy stops being theoretical, because **the corpus run mixes both** kinds of work for the first time (`plan-03-pipelines.md` §12 #7). The failure this issue prevents is quiet: a corpus run whose ledger records per-stage timings that describe queueing rather than work.

**Deliverable**
`.env.example` + slot config.

**Depends on**
- `S1-T09` — **external entry edge**: typed slots, barriers and unit-contained failure are already built (Plan 1 freeze); this issue sets their bounds, not their shape.
- `S1-T15` — **external entry edge**: the Ollama adapter's `warm` operation and the digest-recorded-at-first-use behaviour are what `keep_alive` and the loaded-once claim rest on.

Intra-epic: n/a. Inter-epic: none.

**Acceptance criteria**
- [ ] **`DOCFLOW_JOBS` bounds CPU work**: the number of concurrent CPU-bound operations (renders, CPU-side kernel work) never exceeds the value, and a run at `--jobs 8` is observably bounded.
- [ ] **`--jobs` is the CLI counterpart of that bound**, and the pair is 1:1: `--jobs N` and `DOCFLOW_JOBS=N` resolve through the same precedence chain to the same slot bound, and the flag has no effect `DOCFLOW_JOBS` cannot also express (`plans/README.md` §6 Track 4: *no flag without a counterpart*). `--jobs` appears in the gate's command (`S3-T14`) because this issue is what defines it.
- [ ] **`gpu` is bounded to one in-flight generation per device** — no two generations run concurrently on the same device, and the bound is enforced by the slot rather than by the caller's discipline.
- [ ] **The Ollama model is loaded once across the run** (`keep_alive`): the model is warmed at the start and stays resident, so the first generation is not the only one paying load cost and later stages do not each reload it.
- [ ] The slot bounds are **operational settings**, not policy assets: they carry the same CLI → env → `.env` → default chain as paths, model and host, and they are **not** among the five registry policy values (`prd.md` NFR-06, NFR-06a).
- [ ] No default or fallback model exists: warming a model that is not pulled fails with a typed reason naming the remedy (`kernel-cli.md` §5 `model_not_pulled`, exit `3`), never a substituted model.
- [ ] The slot configuration is documented in `.env.example` alongside the operational settings, and the GPU bound is stated as a **declared simplification**, not as a tuned value.
- [ ] The configuration is exercised **before** the corpus run, not during it (`plan-03-pipelines.md` §4 entry condition 7).
- [ ] No new kernel-boundary type is introduced; no new slot type is added (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T11` — the verifiable criterion: *"`DOCFLOW_JOBS` bounds CPU work; `gpu` is bounded to one in-flight generation per device; the Ollama model is loaded once across the run (`keep_alive`)."*
- `plan-03-pipelines.md` §8 — *"**NFR-04**"*, proof *"`DOCFLOW_JOBS` bounds CPU; `gpu` bounded to one generation per device; `keep_alive` across the run."*
- `plan-03-pipelines.md` §7b — *"GPU work is serialized and the model is loaded once"*: slot test; `keep_alive` check across a run. What breaking it looks like: *"two concurrent generations queueing, making per-stage timings meaningless."*
- `plan-03-pipelines.md` §6 step 4 — *"Settle slots and disk before the run."* `DOCFLOW_JOBS` set to the machine; confirm `gpu` is bounded to 1; confirm the model is warmed once. The wrong result this step guards against: *"eight concurrent generations queueing behind each other so the ledger's per-stage timings become meaningless."*
- `plan-03-pipelines.md` §9 — the 11k-file-scale row: *"Stage 1 proved resume on a synthetic flow; **slot and disk policy settled at `S3-T11` before the corpus run**; the first run is interruptible by design."*
- `sad.md` §7.2 — the slot table (`cpu` / `gpu` / `remote`, contended by, default bound, bounded by) and *"each model is loaded once"*.
- `prd.md` §6 **NFR-04** — `--jobs`/`DOCFLOW_JOBS` bounds CPU work; GPU work is serialized to one in-flight generation per device.
- `kernel-cli.md` §9 (K5) — `llm.local warm` and `capabilities` are `now`; *"Reports the **model digest**, never the tag alone — `qwen2.5` is a moving tag and the digest is the identity."*
- `wbs.md` §9 — *"GPU availability for local models (Ollama) … `gpu` slot bounded to one generation per device; never a silent fallback model"* (owner stage 2, carried into 3 by `S3-T11`).

**Out of scope for this issue**
- **Per-device VRAM scheduling beyond `gpu=1`.** Concurrent OCR and generation compete for VRAM on one device and the competition policy is undefined. `# TODO: [RELEASE]`.
- **A scheduler, a work queue or a priority policy.** Slots are bounds; ordering is the orchestrator's dependency dispatch (`S1-T06`). No new mechanism here.
- **A new slot type.** `cpu` / `gpu` / `remote` is closed by Plan 1 (`S1-T09`); adding one would be a kernel-boundary change. **Never** in this plan.
- **The precedence chain itself.** That CLI → env → `.env` → default governs slots is asserted by `E02-02` (`S3-T12`); this issue states the bounds.
- **Disk policy beyond what `S3-T11` settles.** The register names disk alongside slots; capacity planning for intermediates and full-page bitmaps is not a PoC deliverable.
- **A throughput or latency target.** The first full run sets the baseline with **no target asserted** (`NFR-11`). **Never** at this stage.
- **A per-document cost ceiling.** Carried open (`plan-03-pipelines.md` §12 **#6**): without a ceiling, escalation decides how much a document may cost, and `--only failed` re-runs are unbounded in the same way. Recorded, not resolved.
- **Telemetry on slot occupancy.** `# TODO: [RELEASE]`.

**Effort**
**M** — one configuration surface, but three distinct behaviours must hold simultaneously and be observed rather than configured: a CPU bound, a GPU serialization bound and a model loaded once. The `keep_alive` check and the serialization check are both cross-invocation observations over a run, not unit assertions (`wbs.md` §7).

**Owner**
**Data** — `.env.example` and the slot configuration are Data's artifacts (`wbs.md` §8). The slots themselves are Plan 1's Kernels-layer mechanism (`S1-T09`), configured here and not extended.

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — *the 5 exit codes and the closed `reason.code` set* (for the typed no-model-available failure) and the typed-slot model. **Publishes** part of the Plan 3 row: the `.env.example` operational half of the policy/setting split, whose other half is E02's.

---

## §4 Epic close condition

E03 is **`done`** when:

1. `E03-01` is `done`, and
2. the capability is **demonstrable before the corpus run**, from the outside: `DOCFLOW_JOBS` visibly bounds concurrent CPU work; the `gpu` slot is shown to serialize generations; and the model is shown to be loaded once across a run rather than per stage — checked by observation during a run, not by reading `.env.example`.
3. **Plan 3 DoD, per epic:** no new kernel, no new component, no new kernel-boundary type — this epic adds configuration and data (`plan-03-pipelines.md` §10, Task DoD).

**Does E03 gate `S3-T14`?** **Transitively, via E02.** `S3-T14`'s dependency set does not name `S3-T11`. But `S3-T12` depends on `S3-T11`, and `S3-T12` is one of the gate's five direct predecessors — so E03 reaches the gate through exactly one path: `S3-T11` → `S3-T12` → `S3-T14`. It is also a prerequisite of the *quality* of the gate's evidence rather than of its reachability: a gate closed with an unbounded GPU slot would pass every acceptance check and record a baseline that describes queueing, which is a baseline nobody can build against.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E03-01` | **NFR-04** (CPU bounded by `--jobs`; GPU serialized to one generation per device) | no | The slot test and the `keep_alive` check across a run |

No gap and no orphan: `traceability.md` §4.2 places `NFR-04` at stages 1 and 3 with tasks `S1-T09`, `S3-T11` — the Plan 1 mechanism and this plan's policy over it. Plan 3 has no gap and no orphan task at all (index README §6); the one deliberately uncovered requirement, `NFR-12` (deployment), is recorded in `traceability.md` §7.1 as having no task by design, `# TODO: [RELEASE]`, and this epic does not fill it.

**Open decisions this epic carries, unresolved:**

| `plan-03-pipelines.md` §12 | Question | Touches | Why it stays open |
|---:|---|---|---|
| **#7** | How many GPU slots exist, and whether the slot model is enough | `E03-01` (`gpu` bounded to 1 per device) | `gpu = 1` is a declared simplification: concurrent OCR and generation compete for VRAM on one device and the competition policy is undefined. This is the plan where it stops being theoretical, because the corpus run mixes both |
| **#6** | What is in the per-document cost ceiling | `E03-01` (would interact with slots/budgets), `E02-01` | Without a ceiling, escalation decides how much a document may cost. The `CallRecord` records what was spent, so the data exists after the first run — no PoC ceiling is set |

Neither is resolved here.

---

## §6 Risks

From `plan-03-pipelines.md` §9 only, keeping the rows that name `S3-T11`:

| Risk | L | I | Why it touches E03 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **The 11k-file scale on the first full run** — disk, memory for full-page bitmaps, wall time | H | H | `S3-T11` is the task the register names by number: *"slot and disk policy settled at `S3-T11` **before** the corpus run."* The risk is high because the run is the only thing that exercises the slot model. | Stage 1 proved resume on a synthetic flow; **slot and disk policy settled at `S3-T11` before the corpus run**; the first run is interruptible by design |

**The GPU-availability row is excluded from `plan-03-pipelines.md` §9 by construction** — its owner stage in `wbs.md` §9 is 2, so it does not appear in this plan's register. It still reaches this epic's subject, and the acceptance criteria carry its remedy verbatim: a typed error naming the remedy, `gpu` bounded to one generation per device, **never a silent fallback model** (`wbs.md` §9; `kernel-cli.md` §5 `model_not_pulled`, `model_unknown`).

**Stated rather than implied:** the plan-specific execution risk — *"the one that bites if the wave order is violated"* — has three ways, and **none of them names `S3-T11`**. The three concern starting the corpus before `S3-T12`, running it before `S3-T08`'s invalidation is proven, and closing the gate without `S3-T13`. E03's risk is of the other kind: not a violated order but an unsettled precondition, which the plan handles with an entry condition rather than an execution risk — §4 entry condition 7, *"Slot and disk policy can be settled before the corpus run, not during it."*

---

