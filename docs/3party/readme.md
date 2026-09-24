# docflow — third-party utilities dossier

> Status: **collection area, in progress.** This folder is *not* a plan artifact and nothing
> here is frozen: `docs/plan/` remains the decision record where it and this folder disagree.
> What this folder is, is the place where the **facts about the engines we depend on** are
> written down once, so that a seam, a pin, a version string or an error mapping is not
> guessed from memory.
>
> One file per utility (`poppler.md`, `docling.md`, …), plus this index and the field
> template in §4–§5. Nothing here is code, and nothing here is a test.
**Collected 2026-09-24:** all eight pages of §2 exist (`poppler.md`, `opencv.md`,
`pillow.md`, `docling.md`, `ollama.md`, `vllm.md`, `provider-sdk.md`, `tooling.md`), each
covering field groups A–K. What is left in them is `TBD` and the `- [ ]` open questions in
§8 — not missing prose.
## 1. Why this folder exists

The plan fixes one engine per processor and reaches it from exactly one seam, which makes a
small number of third-party facts load-bearing:

| Plan decision | The third-party fact it needs |
|---|---|
| Engines are fixed per contract (`README.md` §9.3): PDF → Poppler, Image → OpenCV/Pillow, OCR → Docling, LLM → Ollama/vLLM/API | what each engine *is* (binary, library or service), and what it is *not* |
| `metadata.json` records `engine` + `engine_version` in every artifact (`PDF-10`, `GEN-12`) | how the version is read at runtime, and what the value looks like |
| Engines are pinned in `pyproject.toml` (`GEN-05`, single pin home) | the pin name, the pinned version, and what "bumping it" can change |
| A concrete engine is reached only from that processor's own `primitives/` | the exact call the seam makes, and the native shape it hands back |
| Each of `pdf` / `image` / `ocr` ships an in-memory engine fake injected **at the engine call** (`README.md` §9.7) | what "native" means for this engine — argv + exit code + stderr, pixels + raw scores, or an object |
| The suite runs whole with **no engine installed** (`GEN-21`) | whether the engine is a system binary, a pip extra or a service |
| Licence posture is decided **before Release** (`subplan-procesador-pdf.md` §risks) | the licence, and what it constrains |

**What this folder is not.** It is not a test tier and not a second source of truth about
behaviour. `docs/feedback/no-tests-on-third-parties.md` stands unchanged: we do not test
Poppler, OpenCV, Docling, Ollama, vLLM or a hosted API, and no fact collected here may become
an assertion about an engine's output, determinism or version. The dossier exists so that
**our** seam and **our** double are correct — nothing more.

## 2. Layout

```
docs/3party/
  readme.md          this file — the index and the field template
  poppler.md         PDF engine (CLI binaries)
  opencv.md          image engine (primary)
  pillow.md          image engine (fallback)
  docling.md         OCR engine (the only one)
  ollama.md          provider engine (local HTTP service)
  vllm.md            provider engine (local OpenAI-compatible service)
  provider-sdk.md    provider engine (hosted API)
  tooling.md         pytest / ruff / pylint / coverage — developer tooling, not an engine
```

The first six + `provider-sdk.md` describe engines that the pipeline calls in production.
`tooling.md` is kept separate because a tool that never runs inside a processor has no seam,
no `engine_version` and no double.

## 3. Index

`Kind` is what the seam actually calls. `Seam` is where it is reached from — a concrete
engine is never reached from anywhere else.

| Utility | Kind | Processor | Seam (owner) | Pin home | Version seen locally | Context7 ID | Doc status |
|---|---|---|---|---|---|---|---|
| Poppler | CLI binaries (`pdftotext`, `pdfimages`, `pdfseparate`, `pdftoppm`, `pdftocairo`, `pdfinfo`) | `pdf` | `docflow.pdf.primitives` | system package — not pinnable in `pyproject.toml` | **25.02.0** | `/websites/pdf2image_readthedocs_io_en` (CLI contract), `/fdawgs/node-poppler` (binary inventory), `/cbrunet/python-poppler` (bindings, unused) | collecting — `poppler.md` |
| OpenCV | Python library (`cv2`) | `image` | `docflow.image.primitives` | `pyproject.toml` | **5.0.0.93** (both `opencv-python` and `-headless`) | `/websites/opencv_5_0` | collecting — `opencv.md` |
| Pillow | Python library (`PIL`) | `image` | `docflow.image.primitives` | `pyproject.toml` | **12.3.0** | `/python-pillow/pillow/12.3.0` | collecting — `pillow.md` |
| Docling | Python library (`+` CLI) | `ocr` | `docflow.ocr.primitives` | `pyproject.toml` (`OCR-02`) | **2.126.0** (core 2.95.0, ibm-models 4.0.2) | `/websites/docling-project_github_io_docling` | collecting — `docling.md` |
| Ollama | Local HTTP service | `llm` | `docflow.llm.primitives` | not pinned by us (service) | client **0.31.1**, server not running | `/websites/ollama_api` | collecting — `ollama.md` |
| vLLM | Local HTTP service (OpenAI-compatible) | `llm` | `docflow.llm.primitives` | not pinned by us (service) | **not installed** | `/websites/vllm_ai_en_stable` | collecting — `vllm.md` |
| Provider SDK | Python library over a hosted API | `llm` | `docflow.llm.primitives` | `pyproject.toml` (`LLM-09`) | `openai` **3.13.0** (+ `httpx` 0.28.1) | `/openai/openai-python` (resolved, not queried) | collecting — `provider-sdk.md` |
| pytest / ruff / pylint / coverage | Developer tooling | — | — | `pyproject.toml` | 9.1.1 / 0.16.7 / 4.0.8 / 7.16.0 | `TBD` | collecting — `tooling.md` |

`Version seen locally` is **evidence about this machine, not the pin**: `pyproject.toml`
still has `dependencies = []`, so no engine is pinned yet. It exists so that the next reader
knows which version the collected facts were checked against.

### Context7 coverage

Six of the eight pages carry a **resolved Context7 ID**, and five of them have been queried:
`poppler` (three IDs — there is no canonical CLI reference, so the CLI contract comes from a
subprocess wrapper's source), `opencv`, `docling`, `ollama`, `pillow` and `vllm`. Two remain
open:

| Page | Why | Next step |
|---|---|---|
| `provider-sdk.md` | ID **resolved and recorded**, method query not yet spent | query `/openai/openai-python` at the snapshot closest to the pinned version |
| `tooling.md` | pytest/ruff/pylint are not API surfaces we code against | optional, probably never |

The docs server answers **three library lookups per request**, so this coverage took two
passes with the budget spent on the libraries whose `TBD`s were load-bearing (maximum
method-verification value per call). A page with `TBD` is not an uncollected page: it means
the ID has not been cited yet.

## 4. What we must capture — the field set

Every `<utility>.md` answers these groups. A field that is genuinely unknown is written
`TBD`; it is never left blank and never filled with a plausible guess (the no-silent-default
rule applies to prose too).

### A. Identity and provenance

| Field | Why we need it | Where it comes from |
|---|---|---|
| Display name and the name used in code (`engine` value in `metadata.json`) | one canonical name — two names for one seam is a defect (`README.md` §7) | the pin in `pyproject.toml`, the subplan |
| Kind: CLI binary / Python library / HTTP service / SDK | decides what "native" means for the double and how absence is detected | upstream docs |
| Upstream repository and documentation URL | the authority for everything below | upstream |
| Context7 library ID, plus the version the answers were read for | so the next reader re-checks instead of trusting this file | Context7 |
| Maintainer and release cadence | how fast a pin goes stale | upstream |

### B. Install, pin and version discovery

| Field | Why we need it | Where it comes from |
|---|---|---|
| How it is installed (`pip` extra, system package, container image, external service) | `pip install -e ".[dev]"` must describe the development environment honestly | upstream |
| Exact pin as committed, and the pin syntax (`==`, floor, range) | `GEN-05` — one pin home | `pyproject.toml` |
| Whether the suite can run with it **absent**, and what "absent" looks like | `GEN-21` — the CI job installs nothing and must stay green | the import/call the seam makes |
| Command or API that reads the version at runtime (`<bin> -v`, `__version__`, `pip show`, `/api/version`) | `engine_version` in `metadata.json` | upstream |
| The exact string format that command returns, and how it is normalized before recording | a recorded version we cannot parse is not a version | upstream |
| What stage the pin is checked at (import time vs. call time) | the seam must not bind the engine at import time | the subplan double table |

### C. Licence and distribution posture

| Field | Why we need it | Where it comes from |
|---|---|---|
| Licence of the engine itself | the PDF subplan flags Poppler's GPL as a distribution constraint with a decision deferred to Release | upstream `LICENSE` |
| Licence of the Python wrapper we pin, if different from the engine | a permissive wrapper over a copyleft binary is the common trap | package metadata |
| Whether we redistribute the binary or only call it | the difference between "use" and "convey" | deployment plan |
| Any attribution or notice obligation | Release checklist | upstream |

### D. Interface contract — what the seam actually calls

| Field | Why we need it | Where it comes from |
|---|---|---|
| For a CLI: the exact argv shape, including flag spellings and value forms | the primitive builds this; a wrong flag is a silent empty artifact | `--help` of the installed version, upstream man page |
| For a library: the function/class entry points, their signatures and defaults | the primitive translates them | upstream API docs |
| For a service: base URL, endpoint, method, content type | the primitive's transport | upstream API docs |
| Which arguments are **required to be explicit** (never defaulted silently) | the plan forbids a silent default engine, model or threshold | subplan design section |
| Where the seam resolves the engine (module import, call time, injected) | the fake patches that attribute | subplan double table |

### E. Inputs, outputs and artifact naming

| Field | Why we need it | Where it comes from |
|---|---|---|
| Accepted input formats and the options that change them | the primitive's closed option list | upstream |
| Output format(s), and how the caller names the files | deterministic artifact names (`page_001`, `image_001.png`) are our contract, not the engine's | upstream + subplan |
| Whether the engine writes files, returns values, or both | decides whether the double returns artifacts or objects | the subplan double table |
| Page/section ordering guarantees in the output | determinism class is ours to enforce | upstream |
| Encoding of textual output | native text and markdown must not arrive in an unknown encoding | upstream |

### F. Determinism levers

| Field | Why we need it | Where it comes from |
|---|---|---|
| The parameters that change output (dpi, thresholds, model, temperature, seed) | the plan's determinism class lists exactly these as inputs to the key | upstream |
| Which of them enter `processing_key` and which are normalized away | reuse correctness | subplan design section |
| Anything non-deterministic the engine itself admits to | recorded as an accepted trade-off, never as covered (`GEN-17`) | upstream |

### G. Failure modes — observable to us, mapped to our errors

| Field | Why we need it | Where it comes from |
|---|---|---|
| How failure is signalled (exit code, exception type, HTTP status, error object) | the engine has no opinion about our taxonomy | upstream |
| The concrete signals we translate (exit codes, stderr substrings, exception classes) | the typed error model (`PDFError.type`, `OCRErrorType`, …) must be reachable | upstream + the subplan error table |
| The mapping table: engine signal → our error type → `recoverable` | one place, so two primitives cannot map the same signal twice | the subplan error section |
| Which failures are pre-engine (our validation, before the call) and which are injected | the test plan splits pre-engine from injected failure | the subplan test plan |
| Whether the double can produce each signal | the fake must reach every documented failure path | the subplan double table |

### H. Seam ownership and the double

| Field | Why we need it | Where it comes from |
|---|---|---|
| The owning primitives module, and the symbols of the closed list | "a name that is not there does not exist" | the subplan primitives section |
| The injection point for the in-memory fake, and the exact patched attribute | the double convention (`README.md` §9.7) | the subplan double table |
| What "native-shaped" means here — what the fake returns and what it must **not** return | a fake that returns our translated type deletes the translation layer's coverage | the subplan double table |
| Whether the shared helper in `tests/fakes/engines/convention.py` applies | it applies only where the seam reaches an engine *namespace* | `convention.py` docstring |
| Whether any other processor may reach this engine | never — cross-processor reach is a defect | `README.md` §7 |

### I. Cost, latency and limits

| Field | Why we need it | Where it comes from |
|---|---|---|
| Typical latency and the dominant cost driver (pages, dpi, tokens, model size) | `processing_key`/reuse exists because this work is expensive | upstream + measurement |
| Hard limits (file size, page count, context window, rate limit) | a limit we discover in production is a bug we shipped | upstream |
| Timeout/retry posture, and where it lives | the primitive owns the call, so the primitive owns the timeout | subplan design section |
| Whether the engine is local, self-hosted or billed per call | the PoC/Release posture | `docs/idea/` |

### J. Alternatives and swap story

| Field | Why we need it | Where it comes from |
|---|---|---|
| The alternative(s) considered and why the chosen one won | the plan asserts each engine is swappable behind the contract; this is the evidence | `docs/idea/` §"Implementaciones reemplazables" |
| What a swap would touch (primitives only — never the contract or the workflow) | it is the test of whether the seam is honest | subplan engine-encapsulation section |
| What a swap would break in the double | a seam change is a double change | the subplan double table |

### K. Open questions and drift log

| Field | Why we need it | Where it comes from |
|---|---|---|
| Open questions as `- [ ]` items, never as prose speculation | an unanswered question stays visible | this folder |
| A dated log of version bumps and what changed in our seam | the plan's drift risk is caught on the pin bump | this folder |
| Anything the plan and this dossier disagree on | the plan wins; the divergence is recorded, not silently fixed | both |

## 5. Per-utility template

Copy this into `<utility>.md` and delete the guidance lines when the page is complete.

```markdown
# <Utility> — dossier

> Kind: CLI binary | Python library | HTTP service | SDK
> Processor / seam: docflow.<processor>.primitives
> Status: TBD | collecting | complete (date)

## A. Identity and provenance
## B. Install, pin and version discovery
## C. Licence and distribution posture
## D. Interface contract
## E. Inputs, outputs and artifact naming
## F. Determinism levers
## G. Failure modes and our error mapping
## H. Seam ownership and the double
## I. Cost, latency and limits
## J. Alternatives and swap story
## K. Open questions and drift log
```

## 6. Gathering rules

- **Read the version we actually pin**, not the latest one. Documentation drift is the normal
  case, not the exception.
- **Record where a fact came from and when.** A Context7 answer cites its library ID and the
  version it was read for; a `--help` transcript names the binary and its version.
- **Prefer primary sources** in this order: the installed binary or package → the upstream
  repository/man page → Context7 → a blog post (marked as such, and only as a lead).
- **Never invent a value.** Unknown is `TBD`; a question is a `- [ ]` item.
- **No secrets.** No API keys, tokens, credentials or authenticated endpoint URLs — a hosted
  provider is documented by shape, not by key.
- **Docs only.** This folder adds no code, no test and no dependency; it never becomes the
  place where a behaviour is *proved*.
- **English**, like the rest of `docs/` outside `docs/idea/`.

## 7. Definition of done for a utility page

- [ ] Every field group A–K is answered, or explicitly `TBD` with an open question.
- [ ] `engine` and the runtime `engine_version` command are stated, with the exact returned
      string shape for the **pinned** version.
- [ ] The licence, and whether we redistribute the artifact, are stated.
- [ ] The seam, its closed symbol list and the fake's injection point match the subplan
      verbatim — a divergence is reported, not reconciled here.
- [ ] The failure signals we translate are listed with the engine signal on the left and our
      error type on the right.
- [ ] No statement in the page is an assertion about engine behaviour that a test would have
      to reproduce (`docs/feedback/no-tests-on-third-parties.md`).

## 8. Open questions seeded from the plan

These are collected facts the plan currently leaves implicit; each belongs to exactly one
utility page, and each page now carries the same question in its own §K.

- [x] `poppler`: the exit codes and stderr strings we map to `PDFErrorType` — **answered**:
      the Xpdf exit codes `0 / 1 / 2 / 3 / 99` are common to the man pages of all these
      binaries, and the `pdf2image` precedent (treat `b"Syntax Error"` in stderr as fatal)
      supplies the stderr half. The mapping table lives in `poppler.md` §G; which failures are
      pre-engine (`validate_pdf`) rather than injected is recorded there too.
- [x] `poppler`: how `engine_version` is read and normalized — **answered**: `<bin> -v` on
      each binary, two lines, take the token after `version` (`poppler.md` §B).
- [x] `docling`: the reading path behind `get_engine_version` (`OCR-02`) — **answered**:
      `docling.__version__`, with `docling-core` and `docling-ibm-models` versions visible
      from the CLI (`docling.md` §B). Which of the three is *the* value remains open there.
- [x] `ollama`: which endpoint answers `check_model_available` and `get_context_window` —
      **answered**: `GET /api/tags` (membership, and a SHA256 digest per model) and
      `POST /api/show` (`parameters`, incl. `num_ctx`) — `ollama.md` §D.
- [ ] `poppler`: which binary renders a page — `pdftoppm` or `pdftocairo`? `PDF-05` defines
      `render_page_to_image` but the subplan names only `pdftotext` / `pdfimages` /
      `pdfseparate` as the encapsulated binaries. Both candidates are documented in
      `poppler.md` §D; the choice is still `TBD`.
- [ ] `poppler`: the GPL licence posture and whether the PoC ships the binary at all.
- [ ] `opencv` / `pillow`: which wheel to pin (`opencv-python` vs `-headless`) and which of
      the closed primitive list requires OpenCV only — `opencv.md` §K names the four with no
      Pillow equivalent, but the swap is not attempted.
- [ ] `ollama` / `vllm` / provider SDK: the transport posture (`HTTP` vs SDK) behind
      `LLM-09`'s `# TODO: [MVP] real transport`, and where the timeout lives.
- [ ] `llm`: what `engine` / `engine_version` mean for a provider call — the service, the
      model, or both. Each provider page carries the variant of the question.
