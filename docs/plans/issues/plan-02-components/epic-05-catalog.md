# E05 — External identity — the Catalog

| Field | Value |
|---|---|
| Epic ID | **E05** |
| Capability | External identity lookup in which `unverified` is a fact with a reason, distinguishable from a rejection and from never having been attempted |
| Issues | `E05-01` (`S2-T12`) — status `todo` |
| Issue count | **1** |
| Owner layer | **Domain** (`wbs.md` §8) — `docflow/components/catalog.py` |
| Wave span | **W7** |
| Effort total | **1 × M** |
| Source plan | [`../../plan-02-components.md`](../../plan-02-components.md) §2, §5 (`S2-T12`), §6 step 9, §7b, §8, §9 execution risk 3, §11, §12 open decision 1, §13 Track 2 |
| Depends on other epics | **E04** (cross-read consistency) |

---

## §1 Objective

E05 delivers the system's only point of contact with a **source it does not control** — and, more importantly, the **vocabulary** it uses to say so. The capability is not "a lookup against an external registry": it is that *an outage is not a rejection*. `plan-02-components.md` §7b's row states the failure in one line — **breaking it looks like "`unverified` collapses into a rejection, turning an incident into a queue of bad documents"** — and the plan's own summary of the whole component is that `unverified` ≠ invalid.

The reason this is a separate epic is vocabulary, not volume. `FR-23` obliges the **Contract** (`E06-01`) to emit a `catalog` verdict with a **reason on every field**, and the three reasons — `not_run` | `source_unavailable` | `pending_retry` — are the Catalog's to define. Without them, *never attempted* and *the source was down* are the same word (`sad.md` §11, `traceability.md` §7.3 defect 8). That single vocabulary is why this epic exists on its own, and why a capability with one issue an epic of one issue.

**Position on the schedule — read this before scheduling, because it is the plan's most subtle one.** The Catalog is drawn with a **dotted edge** in `plan-02-components.md` §5: *"emitted, never run — its only output today is reason `not_run`"*. It is **not** in `S2-T17`'s dependency set, so **no `E05 → E09` edge exists** in the epic graph, and `wbs.md` §6.2 lists `S2-T12` among the tasks that can slip past a stage close.

**But it is not a plain deferral, and this epic's §6 records why.** `FR-23` requires `E06-01` (`S2-T13`, Contract) to emit a `catalog` verdict carrying `not_run` on **every** field — and that value is defined *here*. This is **open decision #1**, and the plan registers its failure mode as **execution risk 3**: *"Building `S2-T13` before the `not_run` value is pinned produces either a missing verdict or an invented one. This is §12 #1 and it is why it is reviewed before `S2-T11` starts, not at the gate."* Gate-arbitrary. So `S2-T12` may slip past the close, but **its vocabulary may not** — and the epic that defines it is one wave ahead of the epic that consumes it.

---

## §2 Issues in this epic

| Issue | `wbs.md` task | Title | Wave | Depends on | Effort | PoC markers |
|---|---||---|---|:---:|---|:---:|---|
| `E05-01` | `S2-T12` | Catalog: external identity lookup, `unverified` ≠ invalid, owned retry queue | W7 | `S2-T11` → **E04** (inter) | M | `# TODO: [MVP]`: real external source and `--source` |

No intra-epic edges exist: E05 has a single issue.

This epic produces **no outgoing inter-epic edge** and has exactly **one incoming** — `E04 → E05`, its own dependency. It is a terminal leaf of the epic graph, as the Catalog is a terminal leaf of the plan's own: no epic and no pipeline consumes a Catalog *output* in the PoC. What it publishes is a vocabulary, and the direction in which that travels is **drawn as missing on purpose** (see §6).

---

## §3 Issue detail

### `E05-01` — implements `S2-T12`

**Title**
Catalog: external identity lookup, `unverified` ≠ invalid, owned retry queue.

**Context**
Three different situations look identical unless the vocabulary keeps them apart, and one of them is dangerous. A source that **was never asked** and a source that **was down** both leave a field with no external confirmation — and if both are recorded as `unverified` with no reason, then a temporary network failure becomes indistinguishable from a permanent absence of evidence. Worse, if `unverified` is collapsed into a **rejection**, an incident becomes a queue of bad documents: every document processed during the outage is marked wrong, and the retry that would have fixed it has nothing to key on. `plan-02-components.md` §6 step 9 states the criterion as *"the Catalog's absence is a fact, not a gap"*: the correct result is *"`unverified` with reason `not_run` on every field, because no pipeline runs the Catalog"*, and the wrong result is *"`catalog` absent, or `unverified` with no reason — which makes *never attempted* and *the source was down* the same word (`FR-23`)"*.

**Deliverable**
`docflow/components/catalog.py`

**Depends on**
`S2-T11` — **inter-epic** (E04 → E05). The Catalog's inputs are values that have already survived contrast; an external lookup run before consistency would confirm a value that may yet change. Intra-epic: n/a. Inter-epic: this is the epic's only edge.

**Acceptance criteria**
- [ ] `docflow/components/catalog.py` exists and performs an external identity lookup with an **`unverified` outcome distinct from a rejection**.
- [ ] A **non-responding source yields `unverified`, never a rejection** — asserted on a source that is deliberately made unreachable.
- [ ] The verdict carries its **reason**, and the three reasons remain **distinguishable**: `not_run` | `source_unavailable` | `pending_retry`.
- [ ] **`not_run` covers the PoC's actual case**: every field read `not_run`, because no pipeline invokes the Catalog (`plan-02-components.md` §5, §6 step 9).
- [ ] The **retry queue is visible in the output as a pending field, not a missing one** — the plan's explicit criterion: a queued item is a declared state, not an absence.
- [ ] The retry queue is **owned** by this component — nothing else in Stage 2 schedules or records a retry.
- [ ] There is **no `--source` flag** in the PoC, and no environment variable substitutes an external source (`plan-02-components.md` §2).
- [ ] `unverified` is **never** emitted as `null`, and a missing `catalog` verdict is impossible: the component's absence produces a *reasoned* absence.
- [ ] The component imports **ports only**; the import-isolation check passes over `docflow/components/catalog.py`.

**Test / evidence**
- `plan-02-components.md` §7b row 14 — *"An outage is not a rejection"*: test is *"A non-responding Catalog source"*; **breaking it looks like "`unverified` collapses into a rejection, turning an incident into a queue of bad documents"**; task cell `S2-T12` (`FR-22`).
- `plan-02-components.md` §7b row 15 — *"`unverified` always carries its reason"*: test is *"Assert a reason on every `catalog` verdict"*; **breaking it looks like "`not_run` and `source_unavailable` collapse into one word"**; task cells `S2-T12`, `S2-T13` (`FR-23`). The second task cell is why this issue's criterion is inherited by `E06-01`.
- `plan-02-components.md` §6 step 9 — *"Prove the Catalog's absence is a fact, not a gap"*: *"`verdicts.catalog` and its reason on every field"*; correct is *"`unverified` with reason `not_run` on every field"*; wrong is *"`catalog` absent, or `unverified` with no reason"*.
- `plan-02-components.md` §5, `S2-T12`'s verifiable cell — *"A non-responding source yields `unverified`, never a rejection; the retry queue is visible in the output as a pending field, not a missing one; the verdict's **reason** (`not_run` \| `source_unavailable` \| `pending_retry`) keeps 'never attempted' distinguishable from 'the source was down'. **No pipeline invokes it** in the PoC, so today every field reads `not_run`"*.
- `plan-02-components.md` §8 — **FR-22**, **FR-23**; proof is *"Non-responding source → `unverified`, never rejected; retry queue visible as a pending field; the three reasons stay distinguishable"*. `traceability.md` §4.1 assigns **FR-23** jointly to `S2-T13`, `S2-T14` **and** `S2-T12` — the only three-task requirement in Stage 2.
- `plan-02-components.md` §13, Track 2 — the *"`unverified` ≠ invalid"* golden artifact is *"A non-responding Catalog source"*, and it **must fail** when broken: *"A rejection is emitted where `unverified` belongs"*.
- `plan-02-components.md` §3, evidence table — the `catalog` row: correct is *"present, `unverified`, with a reason (`not_run` \| `source_unavailable` \| `pending_retry`)"*; the wrong result is *"absent, or `unverified` with no reason — collapsing *never attempted* with *the source was down* (`FR-23`, `sad.md` §11)"*.
- `plan-02-components.md` §11 — exit checklist item *"Every field carries a `catalog` verdict of `unverified` **with a reason**, and the three reasons … remain distinguishable"*.
- `plan-02-components.md` §7d — *"A live external Catalog source and its retry queue at scale"* is **not tested** at this stage: *"No pipeline runs the Catalog; only `not_run` and the non-responding path are asserted"*. This issue's evidence scope is that table's row, and nothing more.

**Out of scope for this issue**
- **No real external source and no `--source` flag.** `# TODO: [MVP]` (`plan-02-components.md` §2, §5).
- **No retry queue at scale.** *"the retry queue at scale"* is deferred with the source; the PoC asserts the **pending-field visibility** and nothing further. `# TODO: [MVP]`.
- **No cost/retry budget policy.** `count_tokens` before spending is `# TODO: [MVP]`; the circuit-breaker behaviour it feeds is Plan 1's `E04-06` (`plan-01-kernels.md`'s adapter: *"sustained unavailability degrades to `unverified`, never to rejection"*), **consumed** here rather than reimplemented.
- **No rejection on unavailability.** **Never** (`FR-22`) — the plan's own words: *"`unverified` collapses into a rejection, turning an incident into a queue of bad documents"*.
- **No `catalog` verdict without a reason.** **Never** (`FR-23`, `sad.md` §11, defect 8).
- **No vocabulary extension.** The three reasons are a **closed set** in the frozen contract (`plans/README.md` §3, Plan 2 row). A fourth reason would change the frozen row and re-open the gate. **Never** in this stage.
- **No adapter import.** **Never** (`sad.md` §1).
- **No `RUC`-style or jurisdiction-specific identity assertion.** External identity is whatever the configured source says; the PoC has no source, so every field reads `not_run`.

**Effort**
**M** — a small component with an outsized contract: three distinguishable reasons, a non-responding path, a retry queue whose *visibility* is the deliverable, and an absence that must be *reasoned* rather than `null`; needs a deliberately-unreachable source fixture plus a `not_run` path assertion (`wbs.md` §7).

**Owner**
**Domain** — `docflow/components/catalog.py` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 2 row: *the `catalog` reason vocabulary (`not_run` \| `source_unavailable` \| `pending_retry`)*. This issue is the vocabulary's sole author, and `E06-01` emits it on every field — including on fields the Catalog never saw. **Consumes** the Plan 1 row — the ports (an unavailable external source is a typed `Reason`, never an exception) and the closed `reason.code` set. **Contributes to** the *component artifact chain*: `work/<name>.catalog.json` (`sad.md` §9.1).

---

## §4 Epic close condition

E05 is **`done`** when:

1. `E05-01` is `done`, and
2. the capability is **demonstrable**, and checked by running it: a source made deliberately unreachable produces `unverified` with reason `source_unavailable` and **no rejection**; a field the Catalog never looked at produces `unverified` with reason `not_run`; a queued field appears as **pending** rather than missing; and a test **fails** if a `catalog` verdict is emitted without a reason.

**Does E05 gate `S2-T17`?** **No — not by dependency, and this is the one place where that has to be argued rather than asserted.** `S2-T12` does not appear in `S2-T17`'s dependency set (`wbs.md` §4), which is why the index README's graph draws **no `E05 → E09` edge** and why `plan-02-components.md` §5 marks the Catalog with a **dotted** edge — *"emitted, never run"*. `wbs.md` §6.2 lists `S2-T12` in the slip list, rendering it a plain slip for scheduling purposes.

**Does E05 gate anything else?** **It gates `E06-01` by vocabulary, and that is an edge the graph does not draw.** `S2-T13` (Contract) *"emits a `catalog` verdict **with a reason even where the Catalog never ran**"* (`plan-02-components.md` §5, §6 step 9, §11), and the reason's values are this issue's. The registration on this epic is explicit; the plan registers the consequence under `E03`'s §6 risk 3 and under §6 of this file. Two of `plan-02-components.md` §12's seven open decisions carry it (#1, and the pointer in §9 risk 3), and the plan's own instruction is to review it **before `S2-T11` starts** — one wave before this issue's own slot. E05's close condition therefore includes the vocabulary, not only the component.

---

## §5 Traceability

| Issue | `wbs.md` task | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E05-01` | `S2-T12` | **FR-22** ("Catalog: unavailability ≠ invalidity") · **FR-23** ("Verdict vector per field + trace" — **jointly**, with `S2-T13`/`S2-T14`) | no | Non-responding source → `unverified`, never rejected; retry queue visible as a pending field; the three reasons stay distinguishable |

No gap: `traceability.md` §4.1 assigns FR-22 to `S2-T12` alone and FR-23 to `S2-T13`, `S2-T14` **and** `S2-T12` — the widest joint assignment in Stage 2. The reverse check (`traceability.md` §5, `S2-T01`–`S2-T15` → `FR-12…FR-24`) finds no orphan here, and this epic is one of only two whose issues are **entirely FR-mapped** (with `E02`).

**Worth stating rather than leaving implicit:** FR-23 is simultaneously the requirement this epic's vocabulary satisfies and the one that creates the epic's odd schedule position. The Contract must emit `catalog` on every field; only this epic can say what the reason means; and no dependency edge records the obligation. The plan's answer to that tension is open decision **#1** — either `S2-T17` gains the dependency or `not_run` is defined where the Contract can reach it — and neither answer has been chosen. **This directory does not choose it either**; it records that `E05-01` freezes the vocabulary in W7 and that `E06-01` consumes it in W7.

---

## §6 Risks

From `plan-02-components.md` §9 only — the rows whose mitigation is carried by this epic:

| Risk | L | I | Why it touches E05 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Frontier LLM cost per token during validation** | H | M | The cost row's own mitigation names the **circuit breaker**: *"the circuit breaker degrades to `unverified`, never to rejection"*. That degradation is precisely this component's outcome vocabulary — the adapter cannot say *"maybe"* in a vocabulary the Catalog has not defined. | `E05-01` defines and asserts that `unverified` is a distinct outcome that **never** becomes a rejection (`FR-22`), and that it **always** carries its reason (`FR-23`) — so the breaker's degradation lands as a stated fact rather than an absence |

**Register rows whose *Owner stage* is 2 that do not materialise here, stated rather than implied.** Five of `plan-02-components.md` §9's rows touch other epics — **Docling install/portability**, **`pdftotext` as a poppler binary**, **GPU availability** (all `E02`), **Segmenter merged-document gap** (`E01`) and **Sampled artifact regenerated on resume** (`E03`, `E06`, `E09`). This epic has no external dependency of its own in the PoC — which is exactly why it can slip, and why its **vocabulary** cannot.

**The plan's third named execution risk is *about* this epic** (`plan-02-components.md` §9):

> *Slipping `S2-T12` into the gate without deciding it. The `catalog` reason vocabulary (`not_run`) is defined by `S2-T12`, yet `FR-23` obliges the **Contract** (`S2-T13`) to emit a `catalog` verdict with that reason on every field. Building `S2-T13` before the `not_run` value is pinned produces either a missing verdict or an invented one. This is §12 #1 and it is why it is reviewed **before `S2-T11` starts**, not at the gate.*

The mitigation is not a dependency edge — the plan declined to add one. It is a **review deadline**, and it fires one wave before this issue's slot. The consequence for scheduling is stated plainly: **`E05-01` can slip past `S2-T17` as a component, but the three reason values cannot be undefined when `E06-01` starts.** If the review resolves toward the dependency, the epic graph gains an `E05 → E09` edge and this epic's schedule position changes with it — recorded here as the *one* structural consequence of an open decision in this decomposition.

**Open decisions carried, not resolved:**

| `plan-02-components.md` §12 | Question | Touches in E05 | Effect if deferred past Stage 2 |
|---:|---|---|---|
| **#1** | **Whether `S2-T12` (Catalog) becomes a dependency of `S2-T17`.** `FR-23` obliges the Contract to emit `catalog` with the reason `not_run` on every field, and that value is the Catalog's to define — yet the dependency diagram marks the Catalog unreachable (`wbs.md` §6.2, dotted edge). *Either `S2-T17` gains the dependency, moving the Catalog onto the critical path, or `not_run` is defined somewhere the Contract can reach without the Catalog existing* | `S2-T12` **is** one of the four tasks it touches (with `S2-T13`, `S2-T14`, `S2-T17`) | **Live in this plan.** *"Building `S2-T13` before pinning `not_run` produces either a missing verdict or an invented one. The choice also changes the dependency table, which is the thing `wbs.md` §6.2 is derived from."* **Recommendation to settle at Wave 7, not at the gate** — recorded as open, not resolved. Wave 7 is this issue's own wave; the review that precedes it is **before `S2-T11` starts** |
| **#6** | **Whether the Reviewer's cases are aggregated after the run.** `03-cli.md` puts them in the per-document ledger; whether anything aggregates them is undefined | Not this epic's task, but the same *shape* of question — a per-document artifact whose aggregate is undefined | **PoC answer, not a gap:** *"`S2-T15` closes the loop at the per-document level, which is enough for the gate. Aggregation is a workflow feature, not a PoC requirement."* Carried in `E07`'s §6 |

Open decisions **#2** (M0 escalation) touches `E03`; **#3** (critical field) touches `E04`; **#4** (OCR correction) and **#7** (`pdftotext` fallback) touch `E02`; **#5** (`r` vs `p` tie-break) touches `E04`. None is resolved here. **None of the seven names `E05-01` except #1** — and #1 names it as the *value's* owner rather than as the decision's subject, which is the whole reason this epic's risk section exists.
