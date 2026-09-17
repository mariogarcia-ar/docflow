# Finding 03 — is the kernel / port / adapter decoupling actually in place?

**Question.** `my_prompt.md` asks that kernel, port and adapter be separated, and names
`epic-04` as where that lives. This document answers whether the separation **holds**, by
measuring the tree rather than reading the design that describes it.

**Method.** Every claim below comes from a command run against the working tree on
2026-09-17: an AST walk of `src/docflow` for the import edges, an `isinstance` check of a
fake against each port, and an import of `docflow.ports` with every vendor module blocked at
`builtins.__import__`. The numbers are the output, not a summary of the artifacts.

---

## 1. Verdict

**The decoupling holds, and it is enforced structurally rather than by convention.** Of the
nine acceptance criteria that bear on it, **seven are met and two are not**, and both gaps
are the same gap: three of the five ports have no adapter behind them yet.

| # | Criterion (`E04-01`, and the epic's per-issue criteria) | Verdict |
|--:|---|:---:|
| 1 | `docflow/ports/` defines exactly five interfaces | **met** |
| 2 | **No adapter is importable from a port** | **met** |
| 3 | A fake satisfies each of the five ports, no real adapter imported | **met** |
| 4 | Every port method fully type-hinted, no `Any` | **met** |
| 5 | No domain noun in any port member | **met** |
| 6 | No port returns a bare value where a boundary requires a `Reason` | **met** |
| 7 | No port exposes a decision (score, verdict, routing) | **met** |
| 8 | The arrows point down only | **met** |
| 9 | Every port is reachable only through its port | **not met** — 3 of 5 have no adapter |

Criterion 9 is not one defect but three of different kinds, and the epic does not
distinguish them:

- **`PdfSource` — a structural gap.** The vendors (`pymupdf`, `pdftotext`) are called from
  inside `kernels/pdf.py`, which `sad.md` §1 classifies as adapters. The port has no
  implementer and could not have a pure pass-through one, because the kernel's reader is
  named `extract_tokens` where the port says `tokens`. See §4 Finding A.
- **`ArtifactStore` and `Registry` — a naming question.** K7 and K8 *are* the capability, so
  `kernels/store.py` and `kernels/registry.py` are the implementations and no vendor is
  involved. Whether they need a separate module is a question about layout.
- **`image` — correctly portless.** K3 is behind no port by design (`ports/__init__.py`
  records why), so it appears in no row above.

Also `E04-02`'s criterion 8, which asks for a thin adapter behind `PdfSource`. See §4.

---

## 2. The import graph, measured

An AST walk over the **22 source modules** under `src/docflow`, counting every imported
*name* (so `from x import A, B` counts twice). Rows import columns.

| from ↓ / to → | `kernels` | `ports` | `adapters` | `kernel_cli` |
|---|--:|--:|--:|--:|
| `kernels` | 16 | **0** | **0** | 0 |
| `ports` | 16 | 7 | **0** | 0 |
| `adapters` | 12 | 2 | 2 | 0 |
| `kernel_cli` | 9 | **0** | **0** | 1 |

The two zeros that matter:

- **`ports → adapters` is 0.** This is `ADR-004`'s rule and the one `E04-01` exists to
  protect. It is not merely zero by luck: `docflow/ports/_typing.py` carries
  `is_adapter_import`, which matches on **whole dotted segments** rather than a substring, so
  `docflow.adaptersomething` is not mistaken for the adapter package. The predicate is
  exercised against synthetic sources in `tests/ports/test_port_isolation.py`, and that
  module deliberately imports **nothing** from `docflow` — it loads the predicate from its
  file — so a port that breaks and cannot be imported still produces a real failure rather
  than a collection error.

- **`kernels → adapters` is 0.** K2 and K3 live in `kernels/` and depend on no vendor module.

### `ports → kernels` is 16, and that is correct

The same rule says ports *may* depend on the boundary types. All five do:

| Port module | Imports from `docflow.kernels` |
|---|---|
| `llm.py` | `types` → `Bytes`, `Evidence`, `KernelResult` |
| `ocr.py` | `types` → `Evidence`, `KernelResult`, `Token` |
| `pdf.py` | `types` → `Bytes`, `Evidence`, `KernelResult`, `Token` |
| `registry.py` | `types` → `Evidence`, `KernelResult` |
| `store.py` | `types` → `Artifact`, `KernelResult`, `Reason`; **`store` → `Ledger`** |

### The one edge worth questioning

`ports/store.py` imports `Ledger` from **`docflow.kernels.store`** — a module, not the frozen
types module. Read as "a port depends on an implementation module", that would be a breach.

**Measured, it is not.** `Ledger` is `@dataclasses.dataclass(frozen=True, slots=True)` with
**zero methods** — a value type that happens to live in the module that produces it, in the
same standing `Box` has in `kernels/types.py`. And `kernels/store.py` imports nothing beyond
the standard library and `kernels/types.py`:

```
import dataclasses, hashlib, json, os
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final
from docflow.kernels.types import Artifact, Reason
```

So the edge drags in **no transitive dependency** — no vendor, no component, no second
module. The proof is the import test in §3: `docflow.ports` imports cleanly with every vendor
blocked, and it could not if `Ledger` carried the store's implementation with it.

**What this does expose is that the guard is broader than the rule's letter.** The isolation
test allows any `docflow.kernels.*` prefix:

```python
allowed_local_prefixes = ("docflow.kernels", "docflow.ports")
```

The ADR's text says a port may import *the boundary types*. The guard permits the whole
`kernels` package. Today the difference is one value type and no harm; on the day a port
imports `kernels/pdf.py` for a helper, the guard will not object, and the arrow will have
turned while every test stays green. **Recorded, not fixed** — tightening it is a one-line
change to the prefix tuple plus a decision about where `Ledger` belongs, and that decision
touches a frozen boundary type.

---

## 3. The reuse test — do the ports actually stand on their own?

This is the test that decides whether the separation is real or described. Three parts, all
executed.

### 3a. A fake satisfies a port with no adapter imported

```python
from docflow.ports import OcrEngine, LlmEngine   # the port, nothing else

class FakeOcr:      # capabilities / engine_info / read
class FakeLlm:      # capabilities / warm / structured / vision / judge

isinstance(FakeOcr(), OcrEngine)   # True
isinstance(FakeLlm(), LlmEngine)   # True
```

Both `True`, because the ports are `@runtime_checkable` `Protocol`s. `tests/ports/test_ports.py`
carries a fake for **all five** — `FakePdfSource`, `FakeOcrEngine`, `FakeLlmEngine`,
`FakeArtifactStore`, `FakeRegistry` — and imports no real adapter to do it. That is `E04-01`'s
third criterion, and it is what makes the reuse claim in `ADR-004` reachable by a consumer
that has no vendor installed.

### 3b. The ports package imports with every vendor absent

`httpx`, `PIL`, `docling`, `fitz` and `pymupdf` were blocked at `builtins.__import__` and the
`docflow` modules purged from `sys.modules`:

```
docflow.ports: imports fine
```

**This is the property the whole layer exists for.** Everything above Stage 1 can run without
Poppler, without Docling, without Ollama and without a provider SDK — and it is now measured
rather than asserted.

### 3c. The adapters import in that same vendor-less world

```
adapters.docling   imports (vendor resolved lazily)
adapters.ollama    imports (vendor resolved lazily)
adapters.frontier  imports (vendor resolved lazily)
```

Each adapter defers its vendor import to first use (`_engine()`, `_http()`), so **importing an
adapter does not require its vendor to be installed** — only calling one does. That is what
lets the composition root name a concrete engine and still let a caller run the parts of the
system that do not need it.

---

## 4. Where the separation is incomplete

### Finding A — three of the five ports have no adapter behind them

| Port | Adapter in `docflow/adapters/` | Owner |
|---|---|---|
| `OcrEngine` | `docling.py` (`DoclingEngine`) | `E04-04` ✅ |
| `LlmEngine` | `ollama.py` (K5), `frontier.py` (K6) | `E04-05`, `E04-06` ✅ |
| `PdfSource` | **none** | `E04-02`'s criterion 8, recorded unmet |
| `ArtifactStore` | **none** | not named by any issue |
| `Registry` | **none** | not named by any issue |

`ls src/docflow/adapters/` returns exactly `docling.py`, `frontier.py`, `ollama.py`,
`_json_object.py` and `__init__.py`.

For `PdfSource` this was already recorded honestly in `epic-04-ports-adapters.md` §3 as one
criterion unmet. **Measuring it makes the gap sharper than the epic records it**, and it is
not the same kind of gap as the other two.

`kernels/pdf.py` is a module of **functions**; `PdfSource` is a `Protocol`. Measured
name by name:

| Port member | In `kernels/pdf.py` |
|---|:---:|
| `probe` | yes |
| `classify` | yes |
| `tokens` | **no** — the kernel calls it `extract_tokens` |
| `render` | yes |
| `split` | yes |

and the kernel carries three functions the port does not declare: `effective_dpi`,
`extract_tokens`, `layout_text`. Tested directly:

```python
isinstance(docflow.kernels.pdf, PdfSource)        # False
hasattr(docflow.kernels.pdf, "tokens")            # False  ← the only name that fails
```

So the module is **four fifths of the way** to satisfying the port, and the thing stopping
it is a **name**, not a missing capability.

### But the adapter is not merely absent — its work is fused into the kernel

This is the part the epic does not say, and it changes what the fix is.

`kernels/pdf.py` is where the **vendors live**: it imports `pymupdf` (lazily, at line 233)
and shells out to the **`pdftotext`** binary (`_READER_BINARY`, line 117). That is adapter
work — vendor translation — sitting inside a kernel module.

And the architecture classifies those very tools as **adapters** (`sad.md` §1):

```
Adapters:  Docling · pdftotext · Ollama · provider SDKs · filesystem
```

So `pdftotext` is an adapter in the architecture's own inventory and a line inside
`kernels/pdf.py` in the code. **That is a real inconsistency**, unlike `ArtifactStore` and
`Registry` in the paragraph below — for those two the kernel *is* the capability, so the
port is a mirror and no vendor is involved. For K2 a vendor **is** involved and it is not
behind the port.

**The clean split the architecture implies** is: an adapter owning the `pymupdf`/`pdftotext`
calls, and `kernels/pdf.py` keeping the analysis that sits on top of them — `classify`'s
`text`/`image`/`mixed`/`blank` decision, the invisible-text detection (`Tr 3` in the content
stream), `effective_dpi` from embedded pixels. Today both halves are in one file.

So the epic's reading — *"the gap is in the `Deliverable` line, not in the criterion; the
fix is a one-line deliverable change"* — **understates it**. Writing the adapter is not
adding a file that forwards to the kernel; it means **moving the vendor calls out** and
reconciling `tokens` against `extract_tokens`. That is a small refactor with a frozen port on
one side and a tested kernel on the other, not a one-line edit.

**What still holds regardless.** The behaviour the port exists to guarantee is already
there. With `pymupdf` blocked at `builtins.__import__`, `kernels/pdf.py` still imports, and
`_engine()` returns a typed `Reason` rather than raising:

```
_engine() → engine_unavailable
```

That is `sad.md` §1's *"a missing binary is a typed `Reason`, never a fallback reader"*,
satisfied by the kernel today. The missing piece is the **interface a caller depends on**,
not the degraded-failure behaviour.

**And nothing depends on it yet.** No composition root and no consumer exist (§4 Finding C),
so the gap is currently invisible at runtime — which is exactly why it is worth recording
rather than leaving to be discovered by the first consumer, the way `E04-02`'s criterion
would have been ticked by reading the kernel and assuming the adapter came with it.

For `ArtifactStore` and `Registry` there is a different answer, and it is not a gap in the
same sense: **K7 and K8 *are* the capability**, which `ports/__init__.py` states as the reason
they get one port each. `kernels/store.py` and `kernels/registry.py` are the implementations;
whether they need a separate thin adapter module is a question about naming, not about
coupling. The port is what a caller depends on, and the caller reaches the kernel through it
either way.

### Finding B — the epic's "five adapters" and its five ports are not the same five

`epic-04-ports-adapters.md` line 80 says:

> **No adapter.** The five adapters are `E04-02` … `E04-06`.

But `E04-02`…`E04-06` are `pdf`, `image`, `ocr`, `ollama`, `frontier` — and their deliverables
are five *kernel or adapter* modules, of which `image.py` is behind **no port at all** (K3
deliberately has none). The five *ports* are `PdfSource`, `OcrEngine`, `LlmEngine`,
`ArtifactStore`, `Registry`.

So the sentence reads as "one adapter per port" while actually describing "one module per
kernel". The two sets differ by three members in each direction:

```text
ports:     PdfSource   OcrEngine   LlmEngine   ArtifactStore   Registry
E04-02..06:  pdf        image       ocr         ollama        frontier
             ↑ no adapter            ↑ no port   ↑ LlmEngine twice
```

**This is a documentation defect, not a structural one** — the design is coherent, and
`E04-04`/`E04-05`/`E04-06` are correct when they name their adapters. What is wrong is a
sentence that invites the reader to count the two sets as the same five. It is recorded here
rather than edited, because the artifact is part of the frozen set and the wording change
belongs to whoever reopens it.

### Finding C — the composition root does not exist yet

The rule *"nothing imports an adapter except the composition root"* is currently satisfied
**vacuously**: `grep` finds no module in `src/` that imports an adapter. There is no
composition root — `src/docflow/` holds only `__init__.py`.

That is correct for the stage. `E07-01` deliberately registers **zero** operations
(`_OPERATIONS: dict = {}`), and the probe functions in `kernel_cli/main.py` test for an
adapter's *existence* with `importlib.util.find_spec` rather than importing it — which is why
`docflow-kernel --list` can report on K4–K6 without pulling Docling or a provider SDK into the
process. The wiring is `E07-02`'s, and until it lands the rule has no case to police.

---

## 5. What I did not verify

- **No test was mutated to prove the isolation guards fail when broken.** `E04-01`'s epic
  records 8/8 mutations falsified, but that was a different session and I did not re-run it.
  The claim in §2 rests on reading the predicate and its synthetic-source tests, plus the
  measured zero in the matrix.
- **`kernel_cli` is not covered by any import guard.** The `ports → adapters` and
  `kernels → adapters` zeros are enforced. The rule *"nothing imports an adapter except the
  composition root"* has no automated check — it is true today by absence of a consumer, not
  by a test.
- **`EP04-02`'s adapter criterion was not re-scoped**, only re-read. §4 Finding A restates the
  existing recorded resolution; it does not decide it.

---

## 6. Conclusion

The answer to the question is **yes, with one documented caveat and one documentation
defect**.

The separation is structural: adapters sit behind `Protocol`s, the ports import only the
frozen boundary types, the illegal direction is at a measured zero, and the ports package
imports in a world where no vendor exists. That last test is the one that would fail if the
decoupling were nominal, and it passes.

What is incomplete is **coverage**, not coupling: `OcrEngine` and `LlmEngine` have adapters,
and `ArtifactStore`/`Registry` are satisfied by their kernels because those kernels *are* the
capability. **`PdfSource` is the one port with a genuine structural gap** — its vendors
(`pymupdf`, `pdftotext`) are called from inside `kernels/pdf.py`, and `sad.md` §1 classifies
those same tools as adapters. Nothing above Stage 1 is coupled to a vendor, which is the
property that mattered; but nothing above Stage 1 can depend on `PdfSource` either, because
no implementer exists.

Two things are worth a decision, and neither is mine:

1. Whether to **tighten the isolation guard** from `docflow.kernels` to
   `docflow.kernels.types` (plus a home for `Ledger`). Today it allows more than the ADR's
   text, and the case it would allow is the one that turns the arrow.
2. Whether `ArtifactStore` and `Registry` should have thin adapter modules for symmetry, or
   whether their kernels stand as the implementations and the epic's "five adapters" sentence
   should be reworded instead.
3. Whether K2's vendor calls (`pymupdf`, `pdftotext`) move out of `kernels/pdf.py` into an
   adapter, as `sad.md` §1's own inventory already classifies them. This is the one of the
   three that is a **structural** gap rather than a naming or wording one, and it is worth
   settling before the first consumer couples to `kernels/pdf.py` directly.

---

## Appendix — how to reproduce

```bash
# the port set
ls src/docflow/ports/*.py

# the illegal direction, over the real tree
python -m pytest tests/ports/test_port_isolation.py -q

# the graph: AST walk counting imported names per layer
python - <<'PY'
import ast, pathlib, collections
ROOT = pathlib.Path("src/docflow")
print("ports importing adapters:",
      sum(1 for p in (ROOT/"ports").glob("*.py")
          for n in ast.walk(ast.parse(p.read_text()))
          if isinstance(n, ast.ImportFrom) and "adapters" in (n.module or "")))
PY
```
