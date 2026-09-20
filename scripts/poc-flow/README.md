# `scripts/poc-flow/` — the flow as a library

`my_flow.md`, implemented as a **library** that calls the `docflow` adapters
directly. `myflow.py` beside the package is one thin caller of it: the library is
the deliverable, the CLI is a way to reach it.

This is not `scripts/poc/`. That bench probes **one kernel at a time**, one
requirement per driver, to answer *"does this adapter work"*. This package answers
a different question, and it is the one `my_flow.md` exists for: *given one
document, what are its fields, and how much does each answer deserve to be
believed.*

Nothing here is imported from `scripts/poc/`. The lessons are, and they are named
where they apply — the DPI cap, the legibility gate before OCR, reading the shape
from the evidence, adversarially framed review. The code is new.

```bash
python scripts/poc-flow/myflow.py <document>            # one JSON verdict
python scripts/poc-flow/myflow.py <document> --pretty    # indented
python scripts/poc-flow/myflow.py <document> --own-cuit 30-12345678-9
```

`tests/fixtures/` is the corpus of record for a smoke run:

```bash
python scripts/poc-flow/myflow.py \
    tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf --pretty
```

## The one premise

> No model is the truth of the document. Confidence comes from documentary
> evidence, deterministic validations, agreement between independent sources, and
> a human when the ambiguity is real.

That premise is not decoration — it decides the shape of everything below. The
engine scores **candidates**, never bare values; a validator is allowed to say
*I cannot tell*; and no model's opinion is ever enough on its own to promote a
value.

## Running: what it costs

The flow is not free, and the cost is per document:

| Step | Cost | Skips when |
|---|---|---|
| route + read (§2) | ms per page, plus a render per page | — |
| OCR on a rendered page | ~1.5 s warm, ~10 s cold for the first call in the process | the page's shape carries a text layer |
| text lane A | one local generation | the document produced no text |
| text lane B (review) | one local generation | lane A produced no fields |
| vision lane A + B | two local generations | no vision model is configured, or no page rendered |

The local models come from Ollama and must already be pulled
(`deepseek-r1:1.5b`, `gemma3`, `qwen2.5vl`, `granite-vision:2b`). A missing model
is a **refusal reported in `notes`**, never a silent fallback to a different one.

## The library

| Module | Owns | Section of `my_flow.md` |
|---|---|---|
| `_bootstrap.py` | puts `src/` on `sys.path`; the artifacts root | — |
| `config.py` | every dial: models, thresholds, margins, family points, the veto list | §4.1, §6.2, §6.5 |
| `artifacts.py` | loads `artifacts/`, load-or-refuse | §0 |
| `route.py` | the routing **decision**, pure — text / pixels / aside | §2 |
| `material.py` | executes the route through the adapters; the tier | §2 |
| `fields.py` | the data contract: `EvidenceSignal`, `FieldCandidate`, `FieldDecision`, `FieldResult` | §5, §6.5 |
| `validators.py` | CUIT checksum, date, arithmetic — PASS / FAIL / UNKNOWN | §6.2–§6.4 |
| `extract.py` | the candidate producers: regexp, lane A, lane B, cross-modal | §4 |
| `engine.py` | the MoE consensus: merge, veto, score, gate | §6 |
| `run.py` | `run(path, config, own_cuits=…)` — read → extract → decide | §1 |

`run` is the entry point. It returns a `FieldResult`:

```python
from flow import run

result = run(path, own_cuits=frozenset({"30123456789"}))
result.extracted  # {field: raw_value} — CONFIRMED fields only
result.decisions  # {field: FieldDecision} — decision, reason codes, score, margin
result.trace  # {field: [FieldCandidate]} — every signal kept, including UNKNOWN
result.notes  # refused calls, missing lanes, fields named for escalation
```

## What the engine actually does

`engine.py` combines **signals per candidate** instead of counting votes. Four
invariants are enforced in code, not in prose:

| Invariant | Where it lives |
|---|---|
| **I2** the score belongs to the candidate, and candidates with the same `normalized_value` merge *before* scoring | `fields.merge_candidates`, called first in `engine.decide_field` |
| **I3** a hard refutation vetoes; no score compensates | `FieldCandidate.vetoed`; a vetoed candidate is kept in the trace and never reaches the winner |
| **I4** max one signal per family | `engine._family_score` — within a family only the highest PASS counts |
| **I10** `UNKNOWN` scores nothing, penalises nothing, never vetoes | every validator returns the three states; `_family_score` ignores UNKNOWN |

### Signals, and what each is worth

| Family | Worth | Earned when |
|---|---|---|
| `DETERMINISTIC` | +3 | a strong rule passes: CUIT checksum, a date that exists, `subtotal + IVA == importe_total_facturado` within tolerance, QR agreement |
| `DOCUMENT_CONTENT` | +2 | the value is mechanically present in the text (`verified`) |
| `CROSS_MODAL` | +2 | the text lane and the vision lane agree on the same normalized value |
| `SAME_MATERIAL` | +1 | the reviewer says `agree` — capped at 1 even when regexp agrees too |
| `LAYOUT_HISTORY` | +1 | an **active** template matches (not yet implemented) |
| soft refutation | −2 | the reviewer says `disagree`, or a non-vetoing validator FAILs |
| contrary evidence | −3 | the document points at another value (not yet implemented) |

### Vetoes are a closed list

A `FAIL` vetoes **only** if its name is in `config.VETO_CODES`. Anything else is a
soft refutation. That is `my_flow.md` §6.3's rule: a veto must be enumerable, or
it is a rule that can only be discovered by being surprised.

```
CUITS_CHECKSUM_INVALID   CUITS_OWN_AS_EMISOR   DATE_NONEXISTENT   ARITHMETIC_INCONSISTENT
```

**An incomplete equation cannot veto.** `arithmetic_signal` answers `UNKNOWN` when
`subtotal`, `iva` or `importe_total_facturado` is missing or unparseable — the prime cost of a
missing component is exactly what an inconsistency looks like, so the flow is not
allowed to confuse them (§6.4).

### Decision

```
CONFIRMED  score ≥ T(severity, tier)  and  margin ≥ margin(severity)  and  gate satisfied
ESCALATE   score < 2, or every candidate vetoed
REVIEW     otherwise
```

| Severity | Fields | T native | T OCR | Margin | Gate requires |
|---|---|---|---|---|---|
| `critica` | `importe_total_facturado`, `iva` | 5 | 5 | ≥ 2 | `DETERMINISTIC` or `CROSS_MODAL` |
| `alta` | `cuit_emisor`, `fecha_emision` | 3 | 5 | ≥ 2 | `DETERMINISTIC`, `CROSS_MODAL` or `NATIVE_ANCHOR` |
| `media` | `razon_social_emisor` | 3 | 4 | ≥ 1 | — |
| `baja` | `descripcion`, `categoria_gasto`, and anything unnamed | 3 | 4 | ≥ 1 | — |

Every decision carries at least one **stable reason code** (`CONF_SCORE_MARGIN_GATE`,
`REV_GATE_UNMET`, `ESC_LOW_SCORE`, …) from the closed set in `fields.REASON_CODES`.
They are what a metric, a dashboard or an escalation reason counts.

## The artifacts

`artifacts/` is the flow's **content**, separate from its code because prompts and
schemas change on different schedules and for different reasons (`my_flow.md` §0).

```
artifacts/
  prompts/          extract_texto.txt, extract_vision.txt        what to look for, how to read it
  prompts_reviews/  review_texto.txt, review_vision.txt          find errors in A, do not re-extract
  schema/           extraction.json                              23 fields — shared by A and B
  schema_review/    review.json                                  agree / disagree / uncertain
  schema-visual/    <emisor>-<tipo>-<fingerprint>.json            positional templates (K7, pending)
  schema-visual_reviews/                                         review of those templates (pending)
```

Three rules the artifacts obey:

- **An amount is returned as printed, as text.** The schema declares every amount
  `string`, not `number`: `17.898,30` survives as `"17.898,30"`, whereas a
  `number` gives back `17898.3` and silently drops the trailing zero. This is not
  a preference — it is the defect `scripts/poc/README.md` documents.
- **A prompt and its schema are separate files.** They are edited by different
  people for different reasons; one file would force two edits into one diff.
- **`schema-visual` is never injected into a prompt.** By **I4**, a signal that was
  an *input* of an extractor cannot count as corroboration of its *output*.
- **Every field is required and `null`-valued when absent.** The model declares
  what it did *not* find instead of silently omitting it; a partial answer would
  read as a document that lacks the field rather than as a model that stopped
  early.
- **The reviewer receives the proposal.** The review prompts carry `{proposal}`
  and the vision reviewer receives the page. A review prompt that names a proposal
  but carries no placeholder asks a model to grade something it was never shown —
  the exact `judge` pattern `my_flow.md` §4.1 rejects.

Loading is **load-or-refuse**: an absent or invalid artifact raises. A prompt that
arrived from nowhere would make the flow answer about a different document while
reporting success.

The prompt↔schema agreement is checked by `tests/fixtures/verify_pocflow.py`, the
port of `tests/kernels/test_committed_registry.py`'s agreement rules to this tree:

```bash
python tests/fixtures/verify_pocflow.py
```

## Why the pieces are shaped this way

**The routing rule is a value, not an `if`.** `route.decide` takes measurements and
returns a `Decision` carrying the evidence it was taken from. It imports no
adapter, so *"given this measurement, the route is X"* is checkable without paying
for the route — which matters, because the route it chooses is sometimes an OCR
call.

**Legibility gates the pixel route only, and before anything is read.** A page
with a text layer is read from its text, where legibility is not a property of
anything; refusing it there would discard a good extraction because its *image* is
blurred.

**The render resolution is a target, capped by what the page holds.** The adapter
refuses to upscale, and that refusal is right — an upscaled page is larger and no
more legible. Asking for the floor blindly would leave the page that most needs
exporting with no file at all.

**The shape is read from the *evidence*, even when there is no value.** `classify`
answers a blank page with `value=None` while still reporting `shape='blank'`.
Reading the shape only alongside a value collapses *blank* into *unmeasurable* —
two different facts that call for two different routes.

**Reviewer verdicts are new candidates, not promotions.** A `disagree` softens A by
−2 and the reviewer's `suggested_value` starts its own score **from zero**: B's
opinion alone cannot overrule A, for the same reason the frontier's cannot (§6).

**A missing second reading is not a divergence.** *The two readings differ* is a
finding about the document; *nobody read it twice* is an absence of evidence.
Conflating them makes an uncalled check look like a detected problem.

## What is not implemented

Stated here rather than discovered by reading the code. Each has a `TODO: [MVP]`
at the site where it belongs.

- **Resolver → engine loop (§7).** No re-entry, no 2-loop cap, no
  `ESC_NO_NEW_EVIDENCE`.
- **Frontier escalation (§8).** `ESCALATE` is *reported* in `notes`; nothing is sent
  to a frontier model and there is no HITL queue.
- **Lane-on-demand (§6.5).** The Anexo A ladder — run the vision lane when the gate
  cannot close — is not wired.
- **Learning and templates (§9).** No `LAYOUT_HISTORY`, no
  `shadow → active → stale → retired`, no shadow statistics, no audit sampling.
- **The Anexo A reachability test (I8).** Nothing fails the build when a
  (field, tier) pair loses its path to CONFIRMED. **This is the most valuable
  missing piece**, because it is the guard on the thresholds being wrong.
- **QR extraction (§4.2).** No QR decode, so `DETERMINISTIC` currently comes only
  from the CUIT checksum, the date and the arithmetic.
- **`required_components` per `tipo_comprobante` (§6.4).** The arithmetic validator
  assumes the net-plus-VAT combination and answers `UNKNOWN` when a component is
  missing. A Factura C does not discriminate IVA and would be judged wrong by this
  assumption.

Field names now match the schema: the engine's severities and the arithmetic
validator use `importe_total_facturado`, not `total` — the schema and the registry
are the downstream contract, and the engine adapts to them.

## Conventions this package follows

- **The library is the deliverable.** `myflow.py` parses arguments and prints;
  everything else is a library call.
- **`docflow` imports come after `ensure_docflow_importable()`.** The adapters are
  only importable once `src/` is on `sys.path`, so the import order is load-bearing
  and the `wrong-import-position` disable is stated with that reason.
- **A suppression states why the rule does not apply.** Every pylint disable in
  this package carries a comment naming the reason — a record whose shape *is* the
  contract, an import order the adapters force, a pipeline whose step order is the
  argument.
- **No silent stand-in.** A refused call is recorded in `notes`; a missing model
  skips its lane loudly; `UNKNOWN` is a state the engine understands rather than a
  zero that hides a gap.
- **No aggregate confidence.** There is no score for the document — only per-field
  verdicts, per-candidate scores, and the signals behind them.

## Quality gates

```bash
ruff check scripts/poc-flow          # clean
ruff format --check scripts/poc-flow # clean
pylint scripts/poc-flow/flow scripts/poc-flow/myflow.py   # exit 0
python tests/fixtures/verify_pocflow.py                     # artifacts agree
```

`scripts/poc-flow/` is **not** in `pytest`'s `testpaths`, so the project's own
suite does not collect it. The pure modules — `route`, `validators`, `fields`,
`engine` — import no adapter and can be exercised with constructed values:

```bash
python -c "
import sys; sys.path.insert(0, 'scripts/poc-flow')
from flow.validators import cuit_signal, arithmetic_signal
from flow.config import FAMILY_POINTS
print(cuit_signal('30-71548265-3', own_cuits=frozenset(), family_points=FAMILY_POINTS))
"
```

## See also

- `my_flow.md` — the specification this implements. Where the two disagree, the
  document wins and the code is the defect.
- `scripts/poc/README.md` — the per-kernel probes, and the measured findings this
  package's design decisions come from.
- `docs/artifacts/` — `prd.md`, `sad.md`, `wbs.md`: the decisions that predate both.
- `registry/prompts/extraction/invoice.txt` and
  `registry/schemas/extraction/invoice.json` — the downstream contract the
  `poc-flow` artifacts are ported from.
