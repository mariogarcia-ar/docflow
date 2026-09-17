# E02 — Registry assets & the policy/setting boundary

| Field | Value |
|---|---|
| Epic ID | **E02** |
| Capability | Registry assets & the policy/setting boundary — the registry as the sole source of corpus policy, and the split between policy (no override) and operational settings (CLI → env → `.env` → default) |
| Issues | `E02-01` (`S3-T04`) — status `todo` · `E02-02` (`S3-T12`) — status `todo` |
| Issue count | **2** |
| Owner layer | **Data** (`wbs.md` §8) — `registry/patterns/`, `registry/prompts/`, `registry/schemas/`, `registry/policies/`, `.env.example` |
| Wave span | **W1 → W2** |
| Effort total | **1 × L · 1 × S** |
| Source plan | [`../../plan-03-pipelines.md`](../../plan-03-pipelines.md) §2, §5 (`S3-T04`, `S3-T12`), §3 (the `.env.example` evidence row), §6 step 3, §7b rows 9–10 and the invalid-mapping rows, §8, §9 execution risk 1, §12 #1, #4, #6, §13 |
| Depends on other epics | **E03** (`S3-T11` → `S3-T12`) · entered from `S1-T04` and `S2-T11` (external) |

---

## §1 Objective

E02 delivers the layer that decides **whether a `done` claim can be checked at all**. Its capability is two-sided and the two sides must land together: the **registry becomes the sole source of corpus policy** (patterns, prompts, schemas, and the five threshold values), and the **boundary between policy and operational settings becomes explicit and testable** — CLI → env → `.env` → default governs **paths, slots, model and host only**, and `CUT_CONFIDENCE`, `MIN_CHARS`, `MIN_DPI`, `CORRECT`, `TOLERANCE_AMOUNTS` are registry assets with **no environment variable and no CLI flag** (ADR-009, `prd.md` NFR-06a).

The reason the boundary is a capability and not a detail: the registry hash is a mandatory cache-key term (`sad.md` §5). If a threshold could arrive out of band, a stage could be `done` under a setting nothing recorded — output that changed without the key changing, and therefore a `done` nobody can check (`sad.md` §5.1). That is the whole argument, and it is why `plan-03-pipelines.md` §9 calls `S3-T12` *"the cheapest task in the plan and the most expensive to skip."*

It is a separate deliverable because it is the **Data layer's contract with the runtime**: the assets and the boundary they sit behind. It is not the machine (that is E03's slot and resource policy), not the descriptors (E01), and not the surface that reads the settings (E05/E06). Above all it is not a settings module in code — the five policy values are **data**, and the only new artifact is `.env.example` and the falsifiable statement that certain names are not settings.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E02-01` | `S3-T04` | Registry assets: anchors/patterns, extraction prompts, field schemas, policies (critical fields, tolerances) | W1 | `S1-T04`, `S2-T11` — external (`S1-T04` = K8 registry; `S2-T11` = Validator's escalation ladder) | L | `# TODO: [MVP]`: real corpus patterns; prompt versioning |
| `E02-02` | `S3-T12` | **Operational** `DOCFLOW_*` settings + precedence, and policy assets declared as **not** settings | W2 | `S3-T11` → **E03** (inter-epic) · `S1-T04` — external | S | — |

No intra-epic edges exist: E02's two issues are independent inside the epic. `E02-01` opens in W1 from interfaces frozen by Plan 1 and Plan 2; `E02-02` opens in W2 because it needs the slot policy (`S3-T11`, E03) before it can state a precedence chain over slots. The depend**ence** between them is therefore inter-epic on one side and external on the other — they are a pair by capability, not by order.

---

## §3 Issue detail

### `E02-01` — implements `S3-T04`

**Title**
Registry assets: anchors/patterns, extraction prompts, field schemas, policies (critical fields, tolerances).

**Context**
At 11k files the corpus's wording variants cannot be enumerated up front (`plan-03-pipelines.md` §9). The response is not a smarter extractor: it is that **patterns are registry data**, so adding a variant is a hash change rather than a deployment, and the improved prompt makes the stale `done` claims **visibly** stale because the registry hash is a cache-key term. This issue populates the four asset families that make that true, and it does the one thing the plan says cannot be done in code: **it defines "critical field" as policy data** (`plan-03-pipelines.md` §8, `S3-T04`). A critical-field definition expressed as an expression in a module is a convention; as an asset it is a versioned fact that contrast and escalation both read.

**Deliverable**
`registry/patterns/`, `registry/prompts/`, `registry/schemas/`, `registry/policies/`.

**Depends on**
`S1-T04` and `S2-T11` — both **external entry edges**. `S1-T04` is K8's load/validate/hash mechanism (a Plan 1 freeze); `S2-T11` is the Validator's escalation ladder, whose scope is set by the critical-field policy this issue authors (a Plan 2 freeze). Intra-epic: n/a. Inter-epic: none.

**Acceptance criteria**
- [ ] All four asset families exist under their documented paths: `registry/patterns/`, `registry/prompts/`, `registry/schemas/`, `registry/policies/`.
- [ ] **A prompt edit changes the registry hash, and therefore every `extract.p` key.** Verified by editing one prompt, printing `registry hash` before and after, and observing the affected keys change while unaffected stages stay valid.
- [ ] **A missing asset fails fast**: `registry validate` exits non-zero naming the asset; nothing is defaulted to an empty asset (`kernel-cli.md` §5 `asset_missing`, §9 K8).
- [ ] **"Critical field" is defined as policy data, not code** — the definition lives in `registry/policies/`, is versioned, and is read by the contrast scope and the escalation ladder rather than reimplemented at each call site (`plan-03-pipelines.md` §8, `S3-T04`).
- [ ] **Tolerances are policy data**: `TOLERANCE_AMOUNTS` (and the identifier/date exactness rule) live in `registry/policies/`, normalised-before-compare per `FR-20` (`traceability.md` §4.1).
- [ ] The five corpus threshold values — `CUT_CONFIDENCE`, `MIN_CHARS`, `MIN_DPI`, `CORRECT`, `TOLERANCE_AMOUNTS` — exist **only** as registry key paths, and **no** environment variable or flag spelling of any of them is live (ADR-009; the historical `DOCFLOW_*` spellings are dead names, `sad.md` §12 ADR-009).
- [ ] Every asset is versioned data loaded and schema-validated through K8; no asset is read from a path outside the registry root.
- [ ] A manifest of the assets is derivable, so the four families and the pipeline descriptors are one registry with one hash.
- [ ] No new kernel-boundary type is introduced (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T04` — the verifiable criterion: *"A prompt edit changes the registry hash and therefore every `extract.p` key; a missing asset fails fast; 'critical field' is defined as policy data, not code."*
- `plan-03-pipelines.md` §8 — *"**FR-10** (K8 as versioned data at corpus scale), **FR-20** (tolerances), **FR-21** (critical fields scope contrast)"*, with proof *"A prompt edit changes the registry hash and every `extract.p` key; missing asset fails fast; critical field is policy data."*
- `plan-03-pipelines.md` §6 step 3 — *"Confirm the registry is the sole source of policy."* `docflow-kernel registry validate`, then `registry hash`. The wrong result this step guards against: *"a policy value arriving out of band, changing output **without entering the cache key** — a `done` stage produced under a setting nothing recorded (ADR-009, `sad.md` §5.1)."*
- `plan-03-pipelines.md` §7b rows for the registry: the invariant *"No policy value can be set from the environment or a flag"* is `S3-T12`'s test, but it can only pass if the values are assets — which is this issue's assertion.
- `kernel-cli.md` §9 (K8) — `registry show`, `registry ls`, `registry hash`; the fail-fast rule *"A malformed asset stops the run. A missing asset is never defaulted"*; and *"`registry hash` is the operation to reach for when asking why a `--force --stage` is needed."*
- `kernel-cli.md` §11 **row 17** — a missing asset defaulted, producing a run that extracts nothing: exit `3` naming the missing asset, no default substituted.
- `prd.md` §4.2, `FR-10` — K8 holds patterns, prompts, schemas, business rules, policies, pipelines and the model catalog as versioned data; a missing asset fails the run fast; nothing is defaulted.
- `sad.md` §5.1, `§14` — the Stage 3 column for K8 is *"**13 pipeline descriptors**"* over the assets this issue populates; §5.1 is the reason the policy/setting split exists at all.
- `plan-03-pipelines.md` §13, Track 3 — *"Registry assets … A wording variant is a **hash change, not a deployment**."*

**Out of scope for this issue**
- **Real corpus patterns.** The assets are populated to close the flow, not to cover the corpus's variant space. `# TODO: [MVP]`.
- **Prompt versioning.** Each prompt is one asset behind one registry hash; per-prompt version history is deferred. `# TODO: [MVP]`.
- **The precedence chain and `.env.example`.** Stating which values are settings — and proving the five policy values are not — is `E02-02` (`S3-T12`).
- **One asset store or several, and a per-asset hash.** Carried open (`plan-03-pipelines.md` §12 **#4**, which touches `S3-T04` and `S3-T12`). A single hash means a prompt tweak invalidates a schema version: **coarse but never wrong**, which is why it is acceptable for the PoC.
- **A per-document cost ceiling.** No flag and no policy carries one; the `CallRecord` records what was spent, so the data to set a ceiling exists only after the first run. Carried open (`plan-03-pipelines.md` §12 **#6**, touching `S3-T04` and `S3-T11`).
- **The critical-field definition itself.** Carried **open** (`plan-03-pipelines.md` §12 **#1**): the plan states where the policy asset must land, not what the definition is. Shipping a definition by convention would defeat the point of shipping it as data.
- **A policy value settable from the environment or a flag.** **Never** (ADR-009, `prd.md` NFR-06a).
- **A per-corpus engine or model choice as an asset.** The OCR engine is Docling and only Docling, and it is never a setting; there is no default or fallback model, engine or threshold anywhere. **Never** (ADR-001, `prd.md` §10).
- **The 6 Validator business-rule categories.** Deferred from Plan 2. `# TODO: [MVP]`.
- **A live Catalog source.** No pipeline runs the Catalog. `# TODO: [MVP]`.

**Effort**
**L** — four asset families plus the critical-field definition, each needing its own schema, its own fail-fast behaviour and its own hash-consequence test; and the load-bearing verification is cross-cutting — the prompt-edit-changes-the-key test touches K8, the cache key and the extraction stages at once. A heavyweight consequence (every `extract.p` key in the run moves) rather than heavyweight machinery (`wbs.md` §7).

**Owner**
**Data** — `registry/patterns/`, `registry/prompts/`, `registry/schemas/`, `registry/policies/` are the Data layer's artifacts (`wbs.md` §8).

**Frozen contract touched**
**Consumes** `plans/README.md` §3, Plan 1 row — K8's load/validate/`registry_hash` contract and the 7-term cache key whose registry-hash term this epic is what feeds. Consumed by nothing further at Plan 1's level; its own output is part of the Plan 3 row E08 publishes.

---

### `E02-02` — implements `S3-T12`

**Title**
**Operational** `DOCFLOW_*` settings + precedence, and policy assets declared as **not** settings.

**Context**
This is the plan's cheapest task and the one the plan names as most expensive to skip (`plan-03-pipelines.md` §9, execution risk 1). If `MIN_DPI` or `TOLERANCE_AMOUNTS` can arrive from the environment, the corpus run's output was produced under settings that never entered the registry hash — so every ledger's `done` is a claim nobody can check, and the run's results are neither reproducible nor precisely invalidatable. The issue therefore does two things that must be done together: it documents and tests the **operational** precedence chain for the values that legitimately vary per machine, and it makes the **five policy values' non-settability** a tested fact rather than a convention. `.env.example` names them **only to say so**, which is a deliberate, load-bearing emptiness. It also settles the layer `S2-T04` consumes.

**Deliverable**
`.env.example` + `registry/policies/`.

**Depends on**
- `S3-T11` — **inter-epic** (E03 → E02). The precedence chain must govern **slots**, so the slot policy has to exist before the chain can be stated over it.
- `S1-T04` — **external entry edge**: K8 is where the policy assets land and where they are hashed.

**Acceptance criteria**
- [ ] Precedence is **CLI → environment → `.env` → default**, and it governs **paths, slots, model and host only** (`prd.md` NFR-06).
- [ ] `.env.example` documents every operational `DOCFLOW_*` setting that exists, and **names the five policy values only to say they cannot be set** (`CUT_CONFIDENCE`, `MIN_CHARS`, `MIN_DPI`, `CORRECT`, `TOLERANCE_AMOUNTS`).
- [ ] **A test asserts no policy value can be set from the environment**: setting each of the five names has no effect on the resolved configuration or the registry hash.
- [ ] **No CLI flag exists for any of the five on the product or pipeline surface**, and a search asserts the absence of a `--min-dpi`-shaped flag there. The **lab surface is the stated exception and is not in scope to change**: `docflow-kernel ocr read … --correct` is `now` in `kernel-cli.md` §9 (K4) and `--correct` is in §10's **allowed** lab flag vocabulary; it is *lab-only*, corresponds to `reader.correct` in `registry/policies/thresholds.yaml`, and *gates the corrected artifact only* (`kernel-cli.md` §9). What `NFR-06a` forbids is a policy value reachable from the environment or from a **product** flag, because that changes output without entering the registry hash.
- [ ] **`--force`, `--stage` and `--only` are not settable by environment** — setting `DOCFLOW_FORCE=1`, `DOCFLOW_STAGE=validate`, `DOCFLOW_ONLY=failed` must not persist a default that reprocesses done work or silently narrows a later run (`NFR-06`; the mechanism lands at `S3-T08`, the assertion here).
- [ ] The historical spellings are documented as **dead names** rather than silently absent, so a grep for them lands on the reason (`sad.md` §12 ADR-009: `DOCFLOW_CUT_CONFIDENCE`, `DOCFLOW_MIN_CHARS`, `DOCFLOW_MIN_DPI`, `DOCFLOW_CORRECT`, `DOCFLOW_TOLERANCE_AMOUNTS`, and the `--cut-confidence`-shaped flags derived from them).
- [ ] **This settles the layer `S2-T04` consumes**: the Diagnosis gate reads its thresholds from the registry assets this issue declares, and `NFR-06a`'s line between policy and configuration is the one it reads.
- [ ] The precedence chain is covered by a **precedence test** over at least `DOCFLOW_JOBS`, a path setting, the model and the host.
- [ ] No new kernel-boundary type is introduced (`plan-03-pipelines.md` §10, Task DoD).

**Test / evidence**
- `plan-03-pipelines.md` §5 row `S3-T12` — the verifiable criterion in full, including *"A test asserts no policy value can be set from the environment. This settles the layer `S2-T04` consumes."*
- `plan-03-pipelines.md` §8 — *"**NFR-06**, **NFR-06a**"*, proof *"Precedence test over operational settings; the 'no policy value is settable from the environment' test."*
- `plan-03-pipelines.md` §3, observable evidence — the `.env.example` row: *"names the five policy values **only to say they cannot be set**; operational settings carry the CLI → env → `.env` → default chain"*, guarding against *"a policy value settable from the environment, which changes output without entering the cache key (ADR-009, `NFR-06a`)."*
- `plan-03-pipelines.md` §6 step 3 — attempt to set a policy value from the environment **and** from a flag; the correct result is two failures.
- `plan-03-pipelines.md` §7b — *"No policy value can be set from the environment or a flag"*: set each of the five names and search for a corresponding flag. What breaking it looks like: *"a threshold arrives out of band, changing output **without entering the registry hash** — the `done`-and-no-longer-correct failure `sad.md` §5.1 describes."* And *"`--force`, `--stage`, `--only` are never settable by environment"*: set `DOCFLOW_FORCE=1`, `DOCFLOW_STAGE=validate`, `DOCFLOW_ONLY=failed` and observe.
- `sad.md` §5.1 — *"It follows that corpus policy and operational settings are **two surfaces, not one chain** (ADR-009): operational settings have the CLI → environment → `.env` → default precedence, and policy has no precedence at all."*
- `sad.md` §12 ADR-009 — the decision, its consequences, and the paragraph of historical names kept so a grep still lands there.
- `traceability.md` §4.2 — **NFR-06a** (stage 2, 3; tasks `S2-T04`, `S3-T12`) and **NFR-06** (stage 1, 3; tasks `S1-T18`, `S3-T12`); §7.3 defect 3 — the thresholds lived in the environment and the registry at once, and ADR-009 resolved it to the registry with no override.
- `prd.md` §7 — the historical flag spellings are deferred, not live.

**Out of scope for this issue**
- **The invalidation mechanism.** That a forced stage re-pends everything downstream is `S3-T08` (E06). This issue asserts only that `--force`/`--stage`/`--only` cannot arrive from the environment.
- **The slot policy itself.** `DOCFLOW_JOBS` bounds and `gpu=1` are `S3-T11` (E03); this issue states the precedence chain **over** them.
- **One asset store or several, and a per-asset hash.** Carried open (`plan-03-pipelines.md` §12 **#4**, touching `S3-T04` and `S3-T12`).
- **A per-deployment threshold tweak.** Requires a registry change rather than an environment variable — **accepted deliberately**, because an out-of-band tweak would change output without changing the key (`sad.md` §12 ADR-009). **Never** as an environment variable.
- **A `--min-dpi`, `--min-chars`, `--cut-confidence` or `--tolerance-amounts` flag on any product surface.** **Never** (ADR-009, `prd.md` NFR-06a). `--correct` is the one name on the five-value list that already exists as a flag: it is **lab-only** (`kernel-cli.md` §9 K4, §10) and is explicitly out of scope to change here — the prohibition is on exposing policy to the product surface or the environment, not on the lab vocabulary.
- **A default or fallback value for any policy asset.** A missing asset fails fast; nothing is defaulted. **Never** (`prd.md` FR-10, `kernel-cli.md` §5 `asset_missing`).
- **Telemetry for the resolved configuration.** `# TODO: [RELEASE]` (`plan-03-pipelines.md` §2).
- **Secrets.** `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY` and `DOCFLOW_OLLAMA_HOST` are environment-only and never flags (`prd.md` NFR-05); this issue documents the host as an operational setting and does not touch the key handling.

**Effort**
**S** — a documentation file, a precedence test and an absence test. The verification is small but it is the whole deliverable: two failures (environment, flag) must be *demonstrated*, and the `--force`/`--stage`/`--only` non-settability must be asserted rather than assumed (`wbs.md` §7).

**Owner**
**Data** — `.env.example` and `registry/policies/` are Data's artifacts (`wbs.md` §8). The CLI behaviour that *reads* the chain is Surface's, and this issue asserts on it rather than owning it.

**Frozen contract touched**
**Publishes** the Plan 3 row of `plans/README.md` §3: *"`.env.example` and the policy/setting split."* **Consumes** the Plan 1 row's `registry_hash` contract (the term that makes the split load-bearing) and the Plan 2 row's `catalog` reason vocabulary (`not_run` \| `source_unavailable` \| `pending_retry`) only insofar as `S2-T04`'s layer is settled here.

---

## §4 Epic close condition

E02 is **`done`** when:

1. `E02-01` and `E02-02` are `done`, and
2. the capability is **demonstrable from the outside**: editing one prompt changes the printed registry hash; removing one asset makes `registry validate` exit non-zero naming it; setting each of the five policy names in the environment changes nothing; and a search finds no `--min-dpi`-shaped flag — four checks run from a shell, not read from `.env.example`.
3. **Plan 3 DoD, per epic:** no new kernel, no new component, no new kernel-boundary type — this epic adds configuration and data (`plan-03-pipelines.md` §10, Task DoD).

**Does E02 gate `S3-T14`?** **Yes, directly — with two separate edges, which is the plan's riskiest asymmetry.** `S3-T14`'s dependency set names **both** `S3-T04` and `S3-T12`, so E02 → E08 is carried twice (index README §3, rows 8–9). No other epic reaches the gate through two of its own issues. The reason is that the gate needs the assets to exist *and* the boundary to hold: the corpus run is the first run whose `done` claims span 11k documents, and `plan-03-pipelines.md` §9 execution risk 1 is precisely that starting it before `S3-T12` settles the split produces a corpus whose results are neither reproducible nor precisely invalidatable. **`S3-T12` is the single task in this plan whose omission silently corrupts the gate's evidence rather than failing it.**

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E02-01` | **FR-10** (K8 as versioned data), **FR-20** (tolerances), **FR-21** (critical-field scope of contrast) | no | Prompt edit moves the registry hash and every `extract.p` key; a missing asset fails fast; "critical field" is policy data |
| `E02-02` | **NFR-06** (operational precedence), **NFR-06a** (corpus policy is registry data, not configuration) | no | The precedence test over `DOCFLOW_JOBS`/paths/model/host; the "no policy value is settable from the environment" test |

No issue in E02 has an empty mapping. `plan-03-pipelines.md` §8 lists exactly these three FRs against `S3-T04` and these two NFRs against `S3-T12`, and `traceability.md` §4.2 places `NFR-06a` at stages 2 and 3 with tasks `S2-T04`, `S3-T12` — which is why this issue is described as settling the layer `S2-T04` consumes and not as owning it.

**Open decisions this epic carries, unresolved:**

| `plan-03-pipelines.md` §12 | Question | Touches | Why it stays open |
|---:|---|---|---|
| **#1** | What defines a "critical field" | `E02-01` (`S3-T04`) — *where the policy asset must land* — and `E07-01` (`S3-T13`) | The plan fixes the **location** of the definition, not the definition. This is the last stage at which it can be data rather than a code convention; if unresolved, `S3-T04` ships a critical-field policy by convention and contrast is either paid everywhere or scoped by a guess |
| **#4** | One asset store or several, and whether `registry hash` is per-asset | `E02-01`, `E02-02` | A single hash means a prompt tweak invalidates a schema version — **coarse but never wrong**. At 11k files the cost is a broader `--force` than strictly needed, not an incorrect result |
| **#6** | What is in the per-document cost ceiling | `E02-01` (would be a policy asset), `E03-01` (interacts with slots/budgets) | No flag and no policy carries a ceiling; the `CallRecord` records what was spent, so the data to set one exists after the first run — the honest PoC position |

None is resolved anywhere in this directory.

---

## §6 Risks

From `plan-03-pipelines.md` §9 only, keeping the rows that name this epic's tasks:

| Risk | L | I | Why it touches E02 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Unknown wording variants in the corpus** — at 11k files the variants cannot be enumerated up front | H | H | `E02-01` owns the patterns and prompts that are the mitigation. The risk is high because there is no way to list the variants in advance. | `EpVR` tolerates variation; **patterns are registry data, so adding a variant is a hash change rather than a deployment**; the Reviewer promotes repeats into rules. `E02-01` makes the first clause true and leaves the Reviewer half to `S2-T15` |
| **Frontier LLM cost per token during validation** | H | M | `E02-01` authors the "critical field" policy that **scopes contrast**, which is the mitigation the register names. | Contrast scoped to critical fields only (registry policy); the circuit breaker degrades to `unverified`, never to rejection; `# TODO: [MVP]` a per-document cost ceiling — which is exactly §12 open decision **#6**, carried here unresolved |

The remaining §9 rows — the 11k-file scale, the golden-set circularity, the merged-document gap, the sampled-artefact regeneration — do not name `S3-T04` or `S3-T12` and are carried by E03, E06, E07 and E08.

**The plan-specific execution risk that lands squarely on this epic** (`plan-03-pipelines.md` §9, way 1):

> **Starting the corpus run before `S3-T12` settles the policy/setting split.** If `MIN_DPI` or `TOLERANCE_AMOUNTS` can arrive from the environment, the run's output was produced under settings that never entered the registry hash — so every ledger's `done` is a claim nobody can check, and the corpus run's results are neither reproducible nor invalidatable precisely. `S3-T12` is `S` effort and it gates `S3-T14`. It is the cheapest task in the plan and the most expensive to skip.

E02's close condition is written to make that risk unenterable: the four shell checks in §4 are all *before* the corpus run, and `E02-02` is the second of the two edges into the gate.

---

