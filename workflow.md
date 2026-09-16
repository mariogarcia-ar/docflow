# Workflows

The thirteen input pipelines, built out of the components defined in `components.md`.

`components.md` defines the **components** (named by what they produce). `README.md` defines the **three method flows** (Rules, Interpretation, Vision — named by what the extractor receives). This document defines the **thirteen input pipelines** and maps each one onto those components.

**Terminology note.** The source notes in `my_prompt.md` call these "flujos"; `README.md` uses that word for the method flows. To keep the two apart, this document calls the input-routed ones **pipelines**, and codes them `M<material>.<extractor>`.

---

## Thirteen pipelines are a matrix, not thirteen designs

The thirteen come from two independent choices multiplied out, plus the one material where only one choice is possible:

| Axis | Question | Values |
|---|---|---|
| **Material** | How does the text reach us? | **M0** arrives as text · **M1** extracted from a text PDF · **M2** OCR of an image PDF · **M3** OCR of an image · **M4** never text (pixels only) |
| **Extractor** | How do we read values from it? | **.R** rules · **.P** prompts · **.B** both |

$$4 \text{ text-available materials} \times 3 \text{ extractor modes} + 1 \text{ pixels-only material} \times 1 = 13$$

| | Material path | `.R` rules | `.P` prompts | `.B` both |
|---|---|:---:|:---:|:---:|
| **M0** | text arrives directly | 1 | 2 | 3 |
| **M1** | text PDF → extract text | 4 | 5 | 6 |
| **M2** | image PDF → convert → OCR | 7 | 8 | 9 |
| **M3** | image → OCR | 10 | 11 | 12 |
| **M4** | image → (no text ever) | — | 13 | — |

**M4 has one variant only.** Regex needs a string to run on, and M4 never produces one — pixels go to the model and fields come back. So the matrix is 4×3+1, and every other material supports all three extractor modes.

**The material path and the extractor are independent.** M0 and M3 differ only in how text is obtained; `.R` and `.P` differ only in how that text is read. Neither choice constrains the other, which is why the count multiplies rather than adds.

---

## The material axis is acquisition cost

Seen across all five materials, the axis is not really *what the input is* but *what has to happen before there is text*:

| Material | Steps before text exists | Acquisition cost |
|---|---|---|
| **M0** | none — it arrives as text | **zero** |
| **M1** | extract text from a PDF | low |
| **M2** | rasterize, then OCR | high |
| **M3** | OCR | high |
| **M4** | never — the model reads pixels | n/a (no text) |

**M0 is the floor, and it makes the rest of the model legible.** With acquisition cost at zero, M0 is nothing but *extraction → validation → reporting*. Every other material is that same pipeline with work prepended to obtain the text. This is the cleanest available statement of what the system actually does: the pipeline is extraction plus verification, and the materials are five ways of arriving at its input.

**Why M0 is a real case, not a degenerate one.** `my_prompt.md` describes a library consumed as includes or as a CLI, and a caller that already holds text is a natural consumer — text from a web form, a database field, an upstream system, or an OCR step run elsewhere. Requiring such a caller to wrap its text in a PDF to re-extract it would be an artificial constraint.

---

## The thirteen pipelines

With an ID for reference, in the sequence each one follows.

| # | Code | Pipeline |
|---|---|---|
| 1 | `M0.R` | text → rules → validate → report |
| 2 | `M0.P` | text → prompts → validate → report |
| 3 | `M0.B` | text → rules / prompts → validate → report |
| 4 | `M1.R` | text PDF → extract text → rules → validate → report |
| 5 | `M1.P` | text PDF → extract text → prompts → validate → report |
| 6 | `M1.B` | text PDF → extract text → rules / prompts → validate → report |
| 7 | `M2.R` | image PDF → convert img → OCR → rules → validate → report |
| 8 | `M2.P` | image PDF → convert img → OCR → prompts → validate → report |
| 9 | `M2.B` | image PDF → convert img → OCR → rules / prompts → validate → report |
| 10 | `M3.R` | image → OCR → rules → validate → report |
| 11 | `M3.P` | image → OCR → prompts → validate → report |
| 12 | `M3.B` | image → OCR → rules / prompts → validate → report |
| 13 | `M4.P` | image → prompts → validate → report |

### The validation sequence is invariant

Every pipeline follows **one sequence**, fixed in order:

```
[acquisition] → [extraction] → validate → report
```

| Stage | Varies by | Applies to |
|---|---|---|
| **Acquisition** | Material | M1–M4; empty at M0 |
| **Extraction** | Extractor mode | all thirteen |
| **Validate** | — never | all thirteen |
| **Report** | — never | all thirteen |

**No pipeline skips validation**, including the rules-only ones. A regex match proves a value was **captured**, not that it is **correct** — `README.md` states that a bad anchor in Rules is detected *only* by cross-flow contrast, because the value is real and carries the correct shape and type. Text of impeccable provenance does not make a value correctly anchored, so no acquisition quality excuses the check. The same holds for `M0.R`: it is the same read as `M1.R`, differing only in where the text came from.

**What the sequence guarantees to the consumer.** Because every one of the thirteen passes through the Validator and the Contract, a field always arrives with the four check verdicts and a trace, whatever route produced it. That is what makes the pipelines substitutable rather than merely similar. If a pipeline could skip validation, the consumer could not tell a validated field from an unvalidated one — a difference invisible in the report unless it is enforced here.

---

## Material paths

Each defined once; the extractor is layered on top.

### M0 — text arrives directly

```mermaid
graph LR
    A["Text"] --> B["Extractor"] --> C["Validate"] --> D["Report"]
```

**No acquisition step at all.** There is no Reader, no Diagnosis, and no conversion — the caller supplies the text and the pipeline begins at extraction.

**The traceability ceiling is set by the caller.** M0 has the strongest trace any material can offer, because a character offset into text is the most precise pointer available — but the offset is only meaningful against *the text that was actually processed*. If the caller's original document and the text it passes are not the same artifact, the offset points into the passed text and no further. This should be explicit in the contract, since it is the one thing M0 cannot verify for itself.

**Nothing here is lossy, and nothing is checked either.** M0 inherits no acquisition risk — no OCR error, no reading-order heuristic — but also no acquisition *evidence*. `components.md`'s Diagnosis detects what is present and adapts it; M0 has no such gate, because a string has no legibility to measure. If the caller passes text extracted badly elsewhere, M0 cannot tell.

### M1 — text PDF

```mermaid
graph LR
    A["Text PDF"] --> B["Extract text<br/>pdftotext"] --> C["Extractor"] --> D["Validate"] --> E["Report"]
```

**Honest reduction.** Conversion needs no correction — `components.md` is clear that a converter does not read badly, it transcribes what is there, and that applying a language model "just in case" can only introduce damage.

**The trade.** `pdftotext` produces reading order heuristically: it does not associate a table header with rows continuing on the next page, and does not collapse a header repeated across five pages. That is the Reconstructor's job and it is not being done. Broken linear text still looks plausible, so the failure is quiet.

**M1 is M0 plus one step**, and that step is where M1's only liability enters. Worth stating plainly: with `pdftotext` removed, M1 becomes M0.

### M2 — image PDF

```mermaid
graph LR
    A["Image PDF"] --> B["Convert to image"] --> C["OCR"] --> D["Extractor"] --> E["Validate"] --> F["Report"]
```

**M2 is M3 with a conversion prefix.** Once rasterized, the steps are identical, so `M2.*` and `M3.*` should share one implementation with a switch at the front. Six of the thirteen pipelines are really three designs with a prefix; divergence between them would be an accident rather than a decision.

### M3 — image via OCR

```mermaid
graph LR
    A["Image"] --> B["OCR"] --> C["Extractor"] --> D["Validate"] --> E["Report"]
```

**What it loses:** everything visual. Layout, signatures, seals, checkboxes, logos — `components.md` notes the Vision flow is the one that sees signatures and seals, and M3 by construction does not.

**What it inherits:** OCR error is in the text. A pattern has to tolerate the misreads OCR actually produces; a prompt may quietly "repair" a digit it should have flagged. Validation is what catches either, which is why it is not optional here.

### M4 — image, direct prompt

```mermaid
graph LR
    A["Image"] --> B["Prompt<br/>multimodal model"] --> C["Validate"] --> D["Report"]
```

**The only pipeline with no text anywhere in it.** No OCR, no regex, and nothing to contrast against.

**What it uniquely sees:** the model gets pixels, so it is the only pipeline that can use visual evidence — a signature, a seal, a checkbox, a logo — as part of extraction rather than as something lost in conversion.

**What it uniquely risks:** with one fused read there is no second opinion, and with no text intermediate there is no offset to trace — the trace is a bounding region, inherently less precise than a character offset.

**Diagnosis is absent by design**, matching `README.md`'s note that Vision uses neither Diagnosis nor Reader. The consequence: nothing measures legibility before the model reads, so a bad input surfaces as low-confidence extraction rather than as a routing decision.

---

## Extractor modes

Each defined once; the material path is beneath it.

### `.R` — rules only

Regex over the text. **Invents nothing** and is deterministic; it either captures a value that is there or fails.

**Two limits, and the second is the serious one:**

- Needs one pattern per wording variant, and at 11k files the variants are unknown.
- **An anchor error is invisible.** `README.md` is explicit that a bad anchor in Rules is detected *only* by cross-flow contrast, because the value is real and has the correct shape and type. With no second read, `.R` has no way to notice it took the value from the neighboring block.

So `.R` is the cheapest mode and, on its own, the one with the least ability to catch its own characteristic error. Note that a clean text source does not help with this at all — the anchor error is independent of acquisition quality.

### `.P` — prompts only

A prompt over the text (or over pixels, in M4). **Tolerates wording variation**, which is what makes it viable when the corpus is unknown.

**Two limits:**

- **Can invent values.** Arithmetic and check digit in the Validator are what catch this — which is why validation is not optional.
- **Can misattribute.** A real value assigned to the wrong field, which is `README.md`'s semantic-confusion failure mode.

**Trace** is a quote + offset for text materials, a bounding region for M4.

### `.B` — both

Runs `.R` and `.P` over the **same text** and lets Consistency compare them.

**This is the only mode that produces contrast**, and contrast is the one mechanism that catches a plausible-but-false value: a total of 15400 that was 1540 passes shape, type and content, and has no check digit. Nothing internal sees it. A disagreement between two reads does.

**Why it is cheap.** `components.md` reserves cross-flow contrast because each method flow re-acquires the document. Here the text is in hand, so a second read costs one extra call on critical fields, not a second pass over the document.

**`.B` is not available in M4**, because there is no text for a regex to run on.

---

## What each of the thirteen buys

| # | Code | Validated | Deterministic | Invents values | Contrast | Sees visuals | Trace |
|---|---|:---:|:---:|:---:|:---:|:---:|---|
| 1 | `M0.R` | ✓ | Yes | No | — | No | exact offset |
| 2 | `M0.P` | ✓ | No | Yes | — | No | quote + offset |
| 3 | `M0.B` | ✓ | — | — | **✓** | No | exact + quote |
| 4 | `M1.R` | ✓ | Yes | No | — | No | exact offset |
| 5 | `M1.P` | ✓ | No | Yes | — | No | quote + offset |
| 6 | `M1.B` | ✓ | — | — | **✓** | No | exact + quote |
| 7 | `M2.R` | ✓ | Yes | No | — | No | exact offset |
| 8 | `M2.P` | ✓ | No | Yes | — | No | quote + offset |
| 9 | `M2.B` | ✓ | — | — | **✓** | No | exact + quote |
| 10 | `M3.R` | ✓ | Yes | No | — | No | exact offset |
| 11 | `M3.P` | ✓ | No | Yes | — | No | quote + offset |
| 12 | `M3.B` | ✓ | — | — | **✓** | No | exact + quote |
| 13 | `M4.P` | ✓ | No | Yes | — | **✓** | bounding region |

**`Validated` is ✓ in all thirteen**, which is the invariant from above and not a coincidence to read past. Every difference between pipelines lies in *what they produce* — determinism, whether they can invent a value, whether a second read exists, what evidence they can see, how precisely a value can be traced. None of them lies in whether the output was checked.

**Only 4 of the 13 have contrast**, and they are exactly the `.B` ones. The other nine produce a single read, so each carries one of these blind spots:

| Blind spot | Pipelines | What goes undetected |
|---|---|---|
| **Single read, `.R`** | 1, 4, 7, 10 | A bad anchor — a real value taken from the wrong place |
| **Single read, `.P`** | 2, 5, 8, 11, 13 | A plausible-but-false value, and a bad anchor |
| **None of the above** | 3, 6, 9, 12 (`.B`) | — contrast is present |
| **No visual evidence** | 1–12 | Signatures, seals, checkboxes, logos |
| **No offset** | 13 | Precise traceability |

**Read this table as residual risk, not as coverage.** Validation already runs on all thirteen, so these blind spots are what remains *after* the four checks — the failures the Validator structurally cannot see. That is why they matter: they are the gap the validator does not close, and the only remedies are contrast (`.B`) or an external source (`Catalog`, which no pipeline runs).

**This table is the whole decision surface.** Choosing a pipeline is choosing which residual blind spot to accept. The extractor choice is not a detail — it decides whether the pipeline can catch its own characteristic error — and the material choice is not a detail either, but note *what it does not decide*: it has no effect on the `.R` anchor blind spot or the `.P` invention risk, which are properties of the reader, not of how the text arrived.

---

## Contrast is cheapest at M0

`components.md` reserves cross-flow contrast because running two method flows is expensive — each re-acquires the document. Acquisition cost is zero at M0 and already paid at M1, M2 and M3:

| Pipelines | Contrast available | Incremental cost |
|---|---|---|
| 3 (`M0.B`) | **Yes** — rules and prompts over text in hand | one call on critical fields |
| 6, 9, 12 (`M1.B`, `M2.B`, `M3.B`) | **Yes** — same text, already obtained | one call on critical fields |
| 1, 2, 4, 5, 7, 8, 10, 11 | No — a single read | — |
| 13 (`M4.P`) | No — a single fused read, nothing to compare against | — |

Running both costs one extra call on critical fields, not a second acquisition. **This is the strongest argument for `.B` when the material is text**: it is the only mode whose characteristic failure is detectable. At M0 the argument is at its strongest, because there is no acquisition cost to weigh against it at all.

---

## Component usage

| Component | M0 | M1 | M2 | M3 | M4 |
|---|:---:|:---:|:---:|:---:|:---:|
| **Segmenter** | — | — | — | — | — |
| **Identifier** | — | — | — | — | — |
| **Diagnosis** | — | *selector* | *selector* | *selector* | *selector* |
| **Reader** | — | ✓ conversion | ✓ OCR | ✓ OCR | — |
| **Reconstructor** | — | — | — | — | — |
| **Validator** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Consistency** | ◐ `.B` only | ◐ `.B` only | ◐ `.B` only | ◐ `.B` only | — |
| **Catalog** | — | — | — | — | — |
| **Contract** | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Reviewer** | ✓ | ✓ | ✓ | ✓ | ✓ |

✓ runs in full · ◐ only in the `.B` variants · — does not run · *selector* gates the pipeline, does not run inside it

**M0 runs no acquisition component at all** — no Diagnosis, no Reader. It is the clearest view of the invariant tail: Validate and Report, with nothing before them.

**Diagnosis selects where it can.** Choosing M1 over M2 asks whether the PDF has a usable text layer — exactly Diagnosis's question in `components.md`, including its warning that the check must be **quality, not presence**, because an old bad OCR layer is not a text layer. Choosing M0 is a caller assertion rather than a detection: there is no artifact to diagnose, only text handed over. So M0 also moves the most trust onto the caller.

**Validate and Report run in all thirteen.** The Validator does not care how a value was obtained, so schema, type, content and check-digit checks apply unchanged. The Contract is what makes the thirteen substitutable: the consumer receives the same output shape whichever route a file took.

---

## What the pipelines give up

| Removed | Consequence | Detectable downstream? |
|---|---|---|
| **Segmenter** | Assumes one file = one document. Fields from a second document overwrite the first's | **No** — `components.md` calls this unrecoverable and silent |
| **Identifier** | No type, so no template routing and no evidence record | Only as a badly extracted field, at the end |
| **Reconstructor** | No cross-page table continuity, no header collapsing, no reading order | Partially: as missing or misattributed fields |
| **Catalog** | Identity fields never checked against an external source | Only by a human eventually noticing |

**Silent losses per pipeline:**

| Pipelines | Silent losses |
|---|---|
| 3, 6, 9, 12 (`.B`) | The **Segmenter** |
| 1, 2, 4, 5, 7, 8, 10, 11 | The **Segmenter**, and the blind spot of a single read |
| 13 | The **Segmenter**, a second read, and precise traceability |

**The Segmenter is the one gap no pipeline closes**, and M0 shows why it is unavoidable rather than an oversight: a caller handing over a string has already made the segmentation decision outside the system. There is nothing to segment — and equally, no way to check that the string holds one document rather than three. Every other reduction degrades into something visible; a merge error produces output that looks correct.

---

## Escalation

A pipeline that cannot finish must escalate, not send the case straight to review.

```mermaid
graph LR
    A["Pipeline"] --> B{"Done?"}
    B -->|"yes"| C["Report"]
    B -->|"no: invalid field"| D["Targeted<br/>render the region"]
    B -->|"no: missing field"| E["Whole document<br/>re-read"]
    D --> F["Contrast against<br/>the pipeline's value"]
    E --> G["Cascade<br/>from Diagnosis"]
    F --> C
    G --> C
```

`components.md` makes the Validator the single place where "could not" is defined: a pipeline failure is not a new kind of failure, it is the existing escalation with a lower starting point.

| Kind | What is there | Cost |
|---|---|---|
| **Invalid field** | Value, page, offset | Renders the region. Cheap and precise |
| **Missing field** | Nothing to point at | Whole document re-read — no saving over the cascade |

**A pipeline has less to point at than the cascade**, because without the Reconstructor it has no resolved structure to locate a field in. So where the cascade escalates cheaply, a pipeline can escalate expensively. The number that decides whether a pipeline pays: **cost saved on the files it handles, against cost of files it hands on having done partial work.**

**Escalation also recovers contrast.** A pipeline's value exists, so when the cascade re-reads the field the two values can be compared exactly as two flows are — a second opinion already paid for.

**M0 escalates differently and should be considered separately.** Rendering a region is meaningless for text that has no page and no image — there is nothing to render. So `M0.P`'s targeted escalation has to mean re-reading a span of the supplied string with a narrower question, or handing the whole string back to the cascade. Which one applies is unresolved, and it is the one place where M0 breaks an assumption the other materials share.

---

## Report is shape-identical across pipelines

Every pipeline reports through the **Contract**, so outputs have the same shape and the consumer needs no per-pipeline logic.

| Verdict | Cascade | `.R` variants | `.P` variants | `.B` variants |
|---|---|---|---|---|
| `shape` / `type` / `content` / `digit` | From Validator | Same | Same | Same |
| `consistency` | Reinforcement or disagreement | `null` | `null` | set — both reads compared |
| `catalog` | Verified / unverified | `unverified` | `unverified` | `unverified` |

**One field the Contract should carry for M0 and M1.** Both trace into text the system did not produce, so the offset is only meaningful against the exact string that was processed. Recording a hash of that string alongside the trace would make the offset verifiable later; without it a trace into supplied text is a pointer to something that may no longer exist in that form.

**This is the argument for the verdict vector over a score.** With a single confidence number, a pipeline's output and the cascade's would collapse to the same scale and the difference would vanish — a field nobody cross-checked would look identical to one that survived contrast. Kept separate, the consumer can require `consistency` on critical fields and accept `null` elsewhere, which is precisely the information needed to choose a pipeline per document type.

---

## Open questions

- **What M0's targeted escalation means.** With no page or image, "render the region" has no meaning. Either it becomes "re-read a span of the string", or M0 escalates only to the cascade. Unresolved, and unique to M0.
- **Whether M0 accepts text with a declared provenance.** A caller may hold text extracted elsewhere by an unknown process. Whether M0 records *how* the text was obtained affects how much its verdicts can be trusted, and today there is nowhere to put that.
- **Whether M0's trace should carry a hash of the processed text.** Without it, an offset points into a string that may not be reproducible.
- **Which pipeline, and who decides.** The thirteen are keyed by material and extractor, but nothing says whether the caller declares the pipeline or the system infers it. This is sharpest at M0 and at M3-vs-M4: M0 is an assertion with nothing to diagnose, and for an image, M3 and M4 are both valid with a real cost/verification trade between them.
- **Whether `.B` is the default for text materials.** It is the only mode that catches its own characteristic failure, and the extra cost is one call on critical fields rather than a re-read. The argument for ever choosing `.R` or `.P` alone needs stating.
- **What decides `.R` vs `.P` inside `.B` when they disagree.** Consistency can break a tie by arithmetic, but only for fields with an arithmetic relation. For an identifier, disagreement has no tie-breaker.
- **What defines a "critical field".** Both the contrast policy and the target of escalation depend on it, and today it exists only as an expression in `components.md`.
- **Whether OCR correction is part of the OCR step.** `components.md` has the Reader correcting OCR output (scoped to characters and spacing, never digits, raw text retained for audit). The thirteen pipelines do not list it, so it is either inside "OCR" or absent.
- **What happens before OCR in M2 and M3.** Neither lists preprocessing, yet `components.md` has input adaptation (rescale, compress) and treats legibility as distinct from resolution. A blurred photo passed straight to OCR is the one outcome it calls invalid.
- **Whether the Segmenter is needed after all.** It is the only silent gap. A cheap continuity check — page numbering, header recurrence — may be enough to keep it, though M0 gives it nothing to inspect.
- **Whether M4's model is the same one the cascade's Vision flow uses**, or a cheaper specialist. It decides whether tuning and the golden set carry over.
- **What the extraction prompt is built from.** Per document type, derived from the schema, or shared with the general Interpretation flow. If shared, tuning carries over; if not, there are two prompt sets to maintain.
- **`pdftotext` is a poppler dependency** (external binary). It needs a stated version and a fallback, or M1 silently depends on whatever the host has.
- **Whether M2 and M3 should share one implementation.** They are the same pipeline with a conversion prefix, so six of the thirteen are three designs with a prefix.
