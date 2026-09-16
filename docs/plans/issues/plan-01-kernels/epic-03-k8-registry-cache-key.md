# E03 — K8 Registry & the cache key

| Field | Value |
|---|---|
| Epic ID | **E03** |
| Capability | K8 Registry as versioned data + the 7-term cache key |
| Issues | `E03-01` (`S1-T04`) — `todo` · `E03-02` (`S1-T05`) — `todo` |
| Issue count | **2** |
| Owner layer | **Kernels** (`wbs.md` §8) — `docflow/kernels/` |
| Wave span | **W2 → W3** |
| Effort total | **2 × M** |
| Source plan | [`../../plan-01-kernels.md`](../../plan-01-kernels.md) §2, §5 (`S1-T04`, `S1-T05`), §7b, §8, §12 open decision 4 |
| Depends on other epics | **E01** (boundary types) |

---

## §1 Objective

E03 delivers two capabilities that only exist together: **registry data that is versioned, validated and fail-fast**, and the **7-term cache key** that carries the registry's hash as a mandatory term. The registry is not a config file — it is versioned data whose identity is a hash, and that hash is what makes `--force --stage extract.p` precise instead of a blanket invalidation (`kernel-cli.md` §9, K8).

It is a separate deliverable because it is the epic where *"the system cannot produce a value"* stops being a runtime hope and becomes a **key**: a malformed asset stops the run, a missing asset is never defaulted, and a prompt change changes the hash and therefore invalidates the cache entries that depended on it. The plan's third claim — *a value the system cannot produce is reported as a reason rather than as a plausible stand-in* (`plan-01-kernels.md` §1) — is enforced at the registry boundary and propagated by the cache key, which is why the two issues belong to one capability and not to two.

---

## §2 Issues in this epic

| Issue | Title | Wave | Depends on | Effort | PoC markers |
|---|---|:---:|---|:---:|---|
| `E03-01` | K8 registry: load, schema-validate, fail fast, `registry_hash` | W2 | `S1-T01` → **E01** (inter-epic) | M | `# TODO: [MVP]`: per-asset registry hashing (plan §12 #4) |
| `E03-02` | Cache key: the 7-term formula including registry hash and model revision | W3 | `S1-T04` → **E03** (intra-epic) | M | — |

Intra-epic edge: `E03-02` → `E03-01` (the cache key consumes the hash the registry produces). Not drawn as an epic edge.

---

## §3 Issue detail

### `E03-01` — implements `S1-T04`

**Title**
K8 registry: load, schema-validate, fail fast, compute `registry_hash`.

**Context**
A missing prompt, pattern or schema that is silently substituted with an empty one produces a run that completes and extracts nothing — indistinguishable from a corpus with no extractable fields (`kernel-cli.md` §9, K8). And a registry that cannot say *which version of itself* it is cannot tell a caller why a stage must be recomputed. This issue makes both failures impossible: unusable data stops the run, and usable data has a single, reproducible identity.

**Deliverable**
`docflow/kernels/registry.py`

**Depends on**
`S1-T01` — **inter-epic** (E01 → E03). The registry exchanges `Reason`; it does not define it.

**Acceptance criteria**
- [ ] `docflow/kernels/registry.py` exists and exposes load, schema-validate and hash operations.
- [ ] A **malformed** asset **stops the run** — the load fails with a typed `Reason` and no run proceeds.
- [ ] A **missing** asset is **never defaulted** — no empty asset is substituted, and the failure names the missing asset (`kernel-cli.md` §5 code `asset_missing`, exit `3`).
- [ ] A schema-invalid asset fails with the code `asset_invalid`, exit `3`.
- [ ] **Changing one prompt changes the hash** — the hash is a function of the loaded asset content, not of paths, timestamps or file order.
- [ ] The same registry content yields the same hash across two independent loads.
- [ ] The hash is emitted as a single value, and there is a command that prints it (`registry hash`, `kernel-cli.md` §9).
- [ ] No default asset, no fallback asset and no empty-asset substitution exists anywhere in the load path.

**Test / evidence**
- `kernel-cli.md` §11 **row 17** (K8 — a missing asset defaulted, producing a run that extracts nothing): command `registry validate --root R` with one asset removed; assertion *exit `3`, naming the missing asset; no default substituted*. Status `now` — Stage 1 CI gate.
- `plan-01-kernels.md` §6 step 2 — `docflow-kernel --list` is where an unavailable adapter must read `no`; the same honesty requirement applies to assets, and row 17 is where it is asserted.
- `plan-01-kernels.md` §8 — row 17; malformed-asset test; hash-change test (requirement **FR-10**).
- `kernel-cli.md` §9 (K8) — `registry validate`, `registry hash`, `registry show`, `registry ls` are all `now`.

**Out of scope for this issue**
- **No per-asset hashing.** One hash today. Per-asset hashing would make `--force --stage extract.p` more precise **and would change the cache-key formula**, i.e. re-open the gate — `plan-01-kernels.md` §12 open decision **#4**. Carried here as `# TODO: [MVP]`; **not resolved**.
- **No cache-key formula.** The registry *produces* a hash; how many terms the key has and what they are is `E03-02`.
- **No registry content.** Patterns, prompts, schemas and policies are Plan 3's (`S3-T04`). This issue builds the loader, not the data.
- **No corpus policy semantics.** That policy lives in the registry with no CLI flag and no environment variable (ADR-009, `prd.md` NFR-06a) — the *rule* is fixed; the *assets* arrive at `S2-T04`/`S3-T12`.
- **No domain noun.** A registry keyed by a document concept would be a component wearing the wrong name. **Never**.

**Effort**
**M** — multiple interacting concerns (load, validate, hash, fail-fast error typing) against a filesystem root, with three distinct failure modes to test separately; needs fixtures (`registry-broken/`) rather than a pure unit test (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/registry.py` (`wbs.md` §8).

**Frozen contract touched**
**Consumes** the Plan 1 frozen row `plans/README.md` §3: `Reason`. Produces the `registry_hash` term that row names — but the *key* is frozen at `E03-02`.

---

### `E03-02` — implements `S1-T05`

**Title**
Cache key: implement the 7-term formula including registry hash and model revision.

**Context**
Idempotency, `--force` and precise invalidation all rest on one function: if the key omits a term, two genuinely different computations collide and the second one is skipped as already done. Two of the seven terms are the ones most likely to be dropped as *"always the same"* — the registry hash and the model revision — and dropping either produces a correct-looking run that reuses an answer computed under different prompts or a different model.

**Deliverable**
`docflow/kernels/cache_key.py`

**Depends on**
`S1-T04` — **intra-epic** (E03 → E03). Externally: `S1-T01` via E01.

**Acceptance criteria**
- [ ] `docflow/kernels/cache_key.py` exists and computes a key from exactly **seven** terms.
- [ ] Each of the seven terms is **individually unit-tested**: changing it alone changes the key.
- [ ] Two runs with the same six terms and a **different registry hash** produce **different** keys — the explicit criterion from `plan-01-kernels.md` §5.
- [ ] A change to the **model revision** changes the key; the model *tag* alone is not the term (a moving tag is not an identity — `kernel-cli.md` §9, K5).
- [ ] The registry hash and the model revision are both **mandatory**: no construction path exists that produces a key with either omitted, defaulted or substituted with a constant.
- [ ] Recomputing the key for identical inputs is stable across processes and across runs.
- [ ] The key is inspectable **before** any expensive call — `--resolve-only` reports the cache-key terms (`kernel-cli.md` §8).

**Test / evidence**
- `plan-01-kernels.md` §7b row 6 — *"The cache key carries all 7 terms"*: unit test per term plus the registry-hash term test; breaking it looks like *"the registry hash or the model revision is dropped as 'always the same'"*.
- `plan-01-kernels.md` §8 — per-term unit tests; the registry-hash term test (requirements **FR-08**, **NFR-03**).
- `kernel-cli.md` §8 — the `--resolve-only` envelope, whose `cache_key_terms` field exposes `model_revision` and `registry_hash`; this is how the key becomes observable without executing.
- Consumers: `E05-01`'s orchestrator dispatch uses the key to decide dispatch; `S3-T12`'s `--force`/`--stage` semantics (Plan 3) depend on it, which is why the formula is frozen here.

**Out of scope for this issue**
- **No forced invalidation logic.** `--force`, `--stage`, `--only` with downstream invalidation are `S3-T08` (Plan 3). This issue produces the key; it does not implement the override.
- **No hashing of registry assets.** How the registry turns its own content into a hash is `E03-01`.
- **No engine/threshold term as a setting.** No default or fallback model, engine or threshold exists anywhere (`plans/README.md` §2), so no term resolves to one. **Never**.
- **No caching layer.** The key decides **when** work is skipped; the store holds the bytes. A caching layer as infrastructure is `# TODO: [RELEASE]`.
- **No `--rebuild`-shaped flag.** `# TODO: [MVP]` (`prd.md` §7).

**Effort**
**M** — one formula, but seven terms each needing an independent test, plus the explicit cross-term collision case; interacting concerns rather than a heavyweight dependency (`wbs.md` §7).

**Owner**
**Kernels** — `docflow/kernels/cache_key.py` (`wbs.md` §8).

**Frozen contract touched**
**Freezes** `plans/README.md` §3, Plan 1 row: *the 7-term cache key*. Plan 2's escalation ladder is expressed entirely in these terms and may not change the formula.

---

## §4 Epic close condition

E03 is **`done`** when:

1. `E03-01` and `E03-02` are `done`, and
2. the capability is **demonstrable**: removing one asset from a registry root stops the run with exit `3` naming it (never a default), and changing a single prompt changes both the `registry hash` output and the computed cache key — shown by running the two commands, not by reading the loader.

**Does E03 gate `S1-T19`?** **Yes, transitively, and it is the expensive one.** No entry in `S1-T19`'s dependency set names `S1-T04` or `S1-T05`; the edges are E01 → E03 → E05 (`S1-T06` depends on `S1-T05`) and then E05 → E08. `S1-T04` and `S1-T05` are links 4 and 5 of the 9-link serial spine (`wbs.md` §6.2) — the chain is 9 links *because* `S1-T05` consumes the registry hash, so a chain that skipped `T04` would not be a chain.

---

## §5 Traceability

| Issue | FR / NFR (`traceability.md` §4) | Gap? | Evidence of the mapping |
|---|---|:---:|---|
| `E03-01` | **FR-10** ("K8 as versioned data, fail fast") | no | `S1-T22` row 17; malformed-asset test; hash-change test |
| `E03-02` | **FR-08** ("7-term cache key") · **NFR-03** ("Restart cost bounded") | no | unit test per term; registry-hash term test |

No issue in E03 has an empty mapping. `traceability.md` §5 places `S1-T04`/`S1-T05` in the orchestrator/store/ledger spine group.

---

## §6 Risks

From `plan-01-kernels.md` §9 only:

| Risk | L | I | Why it touches E03 | Mitigation carried by this epic |
|---|:---:|:---:|---|---|
| **Model resolved by capability, not name** — a silent fallback changes every downstream value | L | H | The model revision is a cache-key term: if an unknown model were ever substituted, the key would silently change identity for every downstream artifact. The key is the mechanism that makes the substitution *visible*. | The model-revision term is mandatory and individually tested; no construction path can default it. The fail-fast itself is `E04-07`'s. |
| **Manifest drift** — `run.json` disagreeing with the ledgers | M | M | Not this epic's mechanism, but the registry hash is one of the terms the ledger's stage identity derives from, so a registry that cannot reproduce its hash makes the ledger's claims unreproducible. | The hash is reproducible from content alone across independent loads (acceptance criterion). |

**Open decision carried, not resolved:** `plan-01-kernels.md` §12 **#4** — *whether `registry hash` is per-asset*. It touches `S1-T04` (one hash today) and `S1-T05` (the hash is a cache-key term). Deferring it past Stage 1 leaves a coarse-but-never-wrong hash; resolving it as "per-asset" **would change the cache-key formula and therefore re-open this gate**. It is recorded here and is not silently closed.
