# Decision — the test suite never crosses into a third party

> Status: **applied**. This note records the decision and supersedes the test-tier half of
> [`test-suite-cost.md`](test-suite-cost.md) and of
> [`plan-update-test-tiers.md`](plan-update-test-tiers.md). Where those two documents and
> this one disagree, **this note wins** and `docs/plan/README.md` §9.7 is the single source
> in the plan set.

## 1. The decision

**We do not test Poppler, OpenCV, Docling, Ollama, vLLM or a hosted API.**

- No test invokes, imports or asserts a third-party engine.
- No test asserts an engine's output values, an engine's version, or that the engine is
  deterministic.
- The suite proves **our** code only — contracts, translation, builders, validation,
  classification, atomic publication and workflow decisions — and runs whole with **no
  engine installed**.

The engines stay where they always were: reachable only from a processor's own
`primitives/`, in production. The test double is an **in-memory fake injected at the engine
call** and nowhere higher:

| Processor | Engine | Injection point | Why there |
|---|---|---|---|
| `pdf` | Poppler | the `subprocess.run` call in `pdf/primitives/` | Poppler is a CLI and returns no value: the fake hands back native artifacts plus an exit code and stderr |
| `image` | OpenCV (Pillow fallback) | the `image/primitives/` functions (`load_image`, the transformations) | the engine hands back pixel arrays and raw score values |
| `ocr` | Docling | `convert_image_with_docling` | never at `extract_docling_*`: that seam is the half of the module the fake must **exercise**, not replace |
| `llm` | Ollama / vLLM / API | the `llm/primitives/` provider seam | its fake stays **scripted**: responses are not deterministic, and `LLM-08` needs a sequence |

The fake is **native-shaped**: it returns what the engine would return, never our translated
type. It lives under `tests/fakes/engines/`, there is no `if engine is None: use_fake`
fallback, and nothing under `src/docflow/` imports `tests/`.

## 2. What changed in the plan

| Document | Change |
|---|---|
| `README.md` §7 | `pytest` means everything and needs no engine; no marker, no second tier |
| `README.md` §9.7 | decision #7 rewritten: "No test crosses into a third party"; the engine-double convention replaces the acceptance-engine recordings convention |
| `README.md` §5 (Phase 0) | Phase 0 deliverable: the engine-double convention and the `tests/fakes/engines/` layout |
| `README.md` §5 (Phase 1, Phase 4) | Phase 1 exit runs with no engine installed; Phase 4 close-out verifies the engine-double compliance instead of recording provenance |
| `README.md` §8 | new risk row: a hand-written double can drift from the engine's real shape — named, not covered |
| `subplan-procesador-pdf.md` §3, §5, §6, §7, §8 | engine double replaces the recording; the PNG pixel-dimension assertion (an engine-fidelity claim) is gone; one tier |
| `subplan-procesador-image.md` §3, §5, §6, §7 | engine double replaces the recording; the "assert 2–3 metric values with a tolerance" caveat is **deleted** — that was a claim about OpenCV |
| `subplan-procesador-ocr.md` §3.5.1, §5, §6, §7, §8 | engine double replaces the recording; the folded **engine-determinism check is deleted** — that was a claim about Docling; our ordering guarantee is proved on the double |
| `subplan-procesador-llm-call.md` §6 | the scripted fake is now described as the same family of double, kept scripted for a stated reason |
| `subplan-orquestador.md` §6, `wbs-orquestador.md` §ORC-19 | contract-level fakes vs. primitives-level engine doubles (was: contract fakes vs. replay loaders) |
| `PDF-14` / `IMG-15` / `OCR-14` | repurposed: in-memory engine double, one per processor. IDs and ranges unchanged — no renumbering, so every range citation stays valid |
| `wbs-general.md` | `GEN-05` drops the `engine` marker; `GEN-19`'s companion assertion covers the doubles; `GEN-21` runs the suite in an environment with **no** engine installed and drops the weekly real-tier job; `GEN-22` becomes the engine-double compliance audit; `GEN-17` records the drift trade-off; §7 DoR and §8 DoD carry the no-engine rule |

Removed outright: `tests/record_engine.py`, `tests/fixtures/engines/`, the replay loaders,
the `engine` marker, `pytest -m engine` / `pytest -m "not engine"`, the version-pin check,
the skip-when-absent rule, the weekly CI engine run and the "recordable vs. injected"
failure taxonomy.

## 3. What we deliberately give up

A hand-written fake can drift from the real engine's shape with nothing turning red: a shape
change on a branch the fake does not model would break translation in production while the
suite stays green. There is also no longer any test of the adapter lines in `primitives/`
that the fake replaces — the lines that pick flags, decode stdout and read exit codes.

Both are **named, accepted PoC trade-offs**, recorded as a resolved decision in `GEN-17` and
as a risk row in `README.md` §8 — not presented as covered. The mitigation is structural
rather than test-based: the seam is one small module per processor, the engine pins stay in
`pyproject.toml`, and a pin bump is the moment to re-read the double against the engine's
documented output.

**Not given up:** the mutation-falsified invariants, the atomic-publication failure paths,
the reuse/invalidation guarantees and the four QA gates. Those were never engine tests, and
they stay.

## 4. Verification of this revision

```bash
grep -rn 'record_engine\|fixtures/engines\|replay\|engine marker\|-m engine\|real tier\|fast tier\|stale recording' docs/plan/
grep -rn 'PDF-14\|IMG-15\|OCR-14\|GEN-21\|GEN-22' docs/plan/ | wc -l
pytest
ruff check .
ruff format --check .
pylint src tests
```

The first grep must return only the passages that *state the prohibition* ("there is no real
tier, no marker and no skip rule"); the second must show every range citation still
resolving, since no ID was renumbered.
