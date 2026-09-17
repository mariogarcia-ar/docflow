# Quickstart — what `docflow-kernel` can do today

**Status: honest, and mostly not yet.** This page covers the **lab surface** — the
`docflow-kernel` bench. It is not a kernel: it is the dispatcher all eight kernels are
meant to be probed through, and it is deliberately **half built**.

Everything below has been run, and every block is quoted from a real invocation. The
headline is the one thing worth reading even if you read nothing else:

> **Today the surface lists the eight kernels and dispatches to none of them.**
> Every operation is refused with `exit 4`, because the operation table is empty by
> design — `E07-01` (`S1-T20`) builds the dispatcher and **`E07-02` (`S1-T21`) fills
> the table.**

That is not a bug, a placeholder or a stand-in. It is the scheduling the issue
decomposition chose, and the section *"Why the table is empty"* below is where the
evidence for that claim lives.

---

## Setup

The entry point is already registered by `pyproject.toml` and installed in editable
mode:

```bash
pip install -e ".[dev]"
```

No `dev` extra exists yet (`# TODO: [MVP]`), so in practice the environment is the
conda one the four QA gates run in. The command resolves on `PATH`:

```bash
which docflow-kernel
# /opt/anaconda3/envs/py313_env/bin/docflow-kernel
```

A file path is not the only way in. The module is importable, which matters because
`docflow.kernel_cli` re-exports `main` as the **function**, not the module — the
frozen entry point is `docflow.kernel_cli:main`:

```python
import importlib

main_module = importlib.import_module("docflow.kernel_cli.main")   # the module
from docflow.kernel_cli import main                                # the function
```

`main_module.dispatch(argv)` returns an `Invocation` — exit code, stdout, stderr —
without touching a stream. That is what makes the surface testable without capturing
file descriptors.

## Where the code lives

| File | What it holds | Landed by |
|---|---|---|
| `docflow/kernel_cli/__init__.py` | re-exports `main` **as the function** | `E07-01` (`S1-T20`) |
| `docflow/kernel_cli/main.py` | the dispatcher, the envelope, the exit codes, `register()` | `E07-01` (`S1-T20`) |
| `docflow/kernel_cli/` per-kernel modules | **do not exist yet** — they declare the operations | `E07-02` (`S1-T21`) |
| the 17-row acceptance suite | **does not exist yet** | `E07-03` (`S1-T22`) |

This is a **package, never a `kernel_cli.py` module**, and the two entry points are
never crossed: `docflow` is the product surface and `docflow-kernel` is the bench.
`docflow run` never invokes `docflow-kernel`.

## The whole surface

Four things, and one of them works.

| Invocation | What it does | Today |
|---|---|---|
| `docflow-kernel --list` | The eight kernels, their determinism class, their adapter, and whether they are available | **works, exit `0`** |
| `docflow-kernel <kernel> <operation> [--flags]` | One operation on one kernel | **refused, exit `4`** — the table is empty |
| flags after the operation name | `--save`, `--verbose`, `--format json`, plus the operation's own | parsed, but unreachable |
| `docflow-kernel --help` | — | **does not exist**; `--help` is read as a kernel name |

## 1. `--list` — the inventory

This is the part that works, and it is genuinely useful: it answers *"what is built"*
in one machine-readable value.

```bash
docflow-kernel --list
```

```json
{
  "value": [
    {
      "kernel": "orchestrator",
      "code": "K1",
      "determinism": "deterministic",
      "adapter": "\u2014",
      "available": false,
      "detail": "not landed (docflow.kernels.orchestrator)"
    },
    {
      "kernel": "pdf",
      "code": "K2",
      "determinism": "deterministic",
      "adapter": "pdftotext",
      "available": true,
      "detail": null
    },
    {
      "kernel": "ocr",
      "code": "K4",
      "determinism": "sampled",
      "adapter": "docling",
      "available": true,
      "detail": null
    },
    {
      "kernel": "llm.frontier",
      "code": "K6",
      "determinism": "external",
      "adapter": "provider SDK",
      "available": false,
      "detail": "no provider key in the environment"
    }
  ],
  "evidence": {
    "terms": { "surface": "docflow-kernel" },
    "measurements": { "kernels": 8.0 },
    "observed": { "available": 6 }
  },
  "reason": null,
  "call_record": null
}
```

*(K3, K5, K7 and K8 are elided above for width — the real output carries all eight,
in the order K1…K8. The `observed` count is the real one.)*

`--list` emits **JSON, not an aligned table**. `kernel-cli.md` §4 shows the *content*
the table is meant to display; §6 fixes the *format*, and the format is the envelope.

### `available` is exactly `detail is None`

There is no second source of truth. `available: true` means *nothing is missing*;
`available: false` always names what is. Two kernels are unavailable today, for
**two different reasons**, and the surface keeps them apart:

| Kernel | `detail` | What it means |
|---|---|---|
| K1 `orchestrator` | `not landed (docflow.kernels.orchestrator)` | the module does not exist — `E05` owns it |
| K6 `llm.frontier` | `no provider key in the environment` | the module **is** landed; the credential is not |

That second row is the interesting one. K6's adapter was written and tested, and the
kernel still reports `unavailable` — correctly, because probing it also requires a
provider key and there is none. **`llm.frontier` must never be added to
`ALWAYS_AVAILABLE_KERNELS` to make the count look better**; its test accepts either
reason on purpose.

`--list` takes no other argument, and says so rather than ignoring one:

```bash
docflow-kernel --list --verbose
# --list takes no other argument        -> exit 4
```

## 2. Dispatching an operation — and why nothing dispatches today

Every one of these is refused, and the message is the point:

```bash
docflow-kernel pdf probe x.pdf        # unknown operation 'probe' for kernel 'pdf'
docflow-kernel store put a b          # unknown operation 'put' for kernel 'store'
docflow-kernel registry load x        # unknown operation 'load' for kernel 'registry'
docflow-kernel image info f.jpg       # unknown operation 'info' for kernel 'image'
docflow-kernel llm.local capabilities # unknown operation 'capabilities' ...
```

All four are `exit 4`. The inventory says `pdf`, `image`, `store` and `registry` are
**available**, and the surface still refuses to run a single thing on them — which
looks like a contradiction until you see which two facts are being kept apart.

### Why the table is empty

The operation table is initialised empty, with the reason written beside it:

```python
#: The operations the surface can dispatch, keyed by ``(kernel, operation)``.
#: Empty here on purpose: `E07-02` (`S1-T21`) fills it in as each adapter lands,
#: and this issue must not anticipate an adapter that does not exist.
_OPERATIONS: dict[tuple[str, str], Operation] = {}
```

`register(operation)` is the seam `E07-02` uses, and registration is deliberately
**unconditional**: an operation whose kernel module has not landed may still be
declared, and it is `--list` that reports the kernel as unavailable. That is what
keeps *"not built"* and *"not declared"* separate facts.

So the two rows of the table above are answering different questions. `available`
answers *"is the kernel built?"* — yes for K2, K3, K4, K5, K7, K8. The refusal
answers *"is this operation declared on the surface?"* — no for all of them. **The
kernels are ready and the surface is not**, and the quickstarts for K2–K5 are where
you drive them today: through the library, not through this command.

### The flag guards are deferred, not broken

This is worth proving rather than asserting, because with an empty table the flag
checks sit *behind* the operation lookup and are therefore unreachable from the
command line. Passing a table the way the tests do shows each guard firing correctly:

```python
import importlib

m = importlib.import_module("docflow.kernel_cli.main")

table = {("pdf", "probe"): m.Operation("pdf", "probe", lambda **params: None)}

m.dispatch(["pdf", "probe", "--engine", "pymupdf"], table=table).stderr
# --engine does not exist on this surface, and never will: a flag naming a document
# concept, an engine, a skippable validation or a default model is the drift this
# surface refuses.
```

Measured, with a table supplied, versus the registered surface:

| Input | With a table | Registered surface |
|---|---|---|
| `--engine pymupdf` | `exit 4` — *does not exist on this surface, and never will* | `exit 4` — *unknown operation 'probe'* |
| `--banana` | `exit 4` — *unknown flag '--banana'* | `exit 4` — *unknown operation 'probe'* |
| `--format yaml` | `exit 4` — *json is the default and the only machine format* | `exit 4` — *unknown operation 'probe'* |
| an `MVP`-declared operation | `exit 4` — *is not implemented in Stage 1 … does not run partially* | `exit 4` — *unknown operation* |

Two flags belong to the **dispatcher**, not the operation: `--verbose` (a line on
stderr) and `--save <dir>`. `--format` is accepted and only `json` is allowed. Every
other token after the operation name must start with `--`:

```bash
docflow-kernel pdf probe x.pdf --banana
# unexpected argument 'x.pdf'      <- a bare positional is not a flag
```

## Exit codes

The vocabulary is closed, and it is the same five values everywhere on this surface.

| Code | Constant | Meaning |
|---|---|---|
| `0` | `EXIT_VALUE` | a value came back |
| `2` | `EXIT_REASON` | **no value, and a typed `Reason` from the closed set** |
| `3` | `EXIT_PRECONDITION` | a precondition of the environment is unmet — a model not pulled, an asset missing, no engine |
| `4` | `EXIT_USAGE` | the *request* was wrong: unknown kernel, unknown operation, a flag that does not exist |
| `1` | `EXIT_INTERNAL` | a bug, or a vocabulary breach — never an answer about a document |

**The code is derived from the result, never passed by a handler.** A handler chooses
a *reason*; the surface decides what it means to a process. `exit_code_for()` reads
`value is not None` → `0`, otherwise looks the code up in `REASON_CODE_EXITS`. That
is what makes *"exit `2` is reserved for a typed `Reason`"* structural rather than
merely intended: nothing maps an exception to `2`.

An unknown reason code becomes `1`, not `2`. A code outside the vocabulary is a
*vocabulary breach*, and reporting it as `2` would collapse **broken** into **the
document answered**.

## Reading a result

The envelope is a frozen surface contract, and its four keys are always present, in
this order, on exits `0`, `2` and `3`:

```json
{
  "value": null,
  "evidence": {
    "terms": {},
    "measurements": {},
    "observed": { "page": 1.0 }
  },
  "reason": {
    "code": "blank_page",
    "message": "the page holds no text"
  },
  "call_record": null
}
```

`call_record` rides on the **`Call`**, not on the `KernelResult` — E01 froze the
result at three fields. That is why K6's adapter exposes `last_call_record` as a
property and `E07-02` composes the envelope from it.

`evidence` is not optional, and that is enforced upstream rather than here. A result
carrying neither a value nor evidence is refused at construction:

```text
ValueError: KernelResult requires evidence: a kernel call always observes something
(versions, parameters, measurements). A value without evidence cannot be
distinguished from a stand-in, and a failure without evidence cannot be diagnosed.
```

The encoder is **explicit, member by member**, never introspective: adding a boundary
field must not silently change the wire format. It raises on an unknown type rather
than calling `str(value)`, because a stringified object is a stand-in that reads like
data.

### Exit `1` has two paths, and only one is silent

Measured, and this is a real asymmetry rather than a summary:

| Path | stdout | stderr |
|---|---|---|
| a handler **raises** (a bug, or a result the encoder cannot handle) | empty | the traceback |
| `value` is `None` and `reason.code` is **outside** `REASON_CODE_EXITS` | **the envelope** | empty |

The first is the contract: *"exit `1` emits no `KernelResult`"*, asserted by the
suite. The second emits an envelope whose `value` is `null` and whose `reason.code`
is a name the vocabulary does not contain — so a consumer that branches on
`reason.code` alone will look for a meaning that does not exist, on a stream it was
told to expect nothing on.

**Both produce exit `1`**, so a script cannot tell them apart by exit code. Whether
that is a defect is not this document's call: it is recorded here, with the
measurement, because the two paths are reachable by different code and the prose
covers only one of them.

## There is no engine setting here, and no default anywhere

The forbidden vocabulary is enforced by the dispatcher itself, not only by a contract
test, and the two messages are deliberately distinct:

- **forbidden** — `--engine`, `--no-validate`, `--api-key`, `--fallback`,
  `--default-model`, `--verify`, and the document-concept words (`--field`,
  `--invoice`, `--cuit`, `--total`, `--document-type`, `--pipeline`, `--validator`,
  `--extractor`, `--golden`) → *"does not exist on this surface, and never will"*
- **unrecognized** — anything else → *"unknown flag"*

There is no `--verify` flag because verification runs on **every** ledger read, with
no flag (`E05-05`, `S1-T10`). There is no `--no-validate` because validation is
invariant in all 13 pipelines. And there is no default model, engine or threshold
anywhere in the code — a fallback that resolves an unknown name to a working one
changes every downstream value silently.

## What `docflow-kernel` does *not* do yet

| Not available | Where it lands |
|---|---|
| **Any dispatchable operation** — the whole reason to type `<kernel> <operation>` | `E07-02` (`S1-T21`) fills `_OPERATIONS` per kernel |
| The 17-row silent-failure acceptance suite | `E07-03` (`S1-T22`) |
| Per-kernel subcommands, one per port method | `E07-02` (`S1-T21`) |
| `docflow-kernel --help` | Not designed; `--help` is read as a kernel name and refused. `--list` is the discovery command |
| `--format yaml` | `# TODO: [MVP]` — `json` is the only machine format (`kernel-cli.md` §10) |
| A `[dev]` extra in `pyproject.toml` | `# TODO: [MVP]` |
| Executing a descriptor of domain components from the bench | Open decision — Stage 1 stays synthetic (`plan-01-kernels.md` §12 #1) |
| The `--save` root question | Open decision — a default root makes a recorded hash real while the bytes are disposable (`plan-01-kernels.md` §12 #2, `# TODO: [MVP]` at `_apply_save`) |
| A fallback or default model, engine or threshold flag | **Never** (`plans/README.md` §2) |
| A verdict, score or aggregate on stdout | **Never** (`kernel-cli.md` §3) |
| A ledger-trust `verify` subcommand | **Never** (`prd.md` §10) |

## Where the arrow points, and the one place it is short-circuited

`sad.md` §1 draws **domain → ports → adapters**. The dispatcher does not sit on that
path on purpose: `E07-01` is the bench *at the kernel layer*, and its own guard
asserts exactly that — the declaration lives in `tests/kernel_cli/test_main.py`:

```python
ALLOWED_DOCFLOW_IMPORT_PREFIXES: frozenset[str] = frozenset({"docflow.kernels"})
```

Every `docflow` import the dispatcher makes must start with one of those prefixes, so
`docflow.adapters` and `docflow.ports` are both out of bounds for it.

So `_apply_save` reaches `docflow.kernels.store` directly, and routes around
`ArtifactStore`. The adapter for that port exists (`docflow/adapters/store.py`) and
**nothing on this surface calls it**. The composition root that will is
`E07-02`'s deliverable, `docflow/kernel_cli/store.py`. Until it lands the arrow is
short-circuited one layer up, recorded at `_apply_save` as a `# TODO: [MVP]` rather
than left silent.

## The other seven kernels

| Kernel | State | Quickstart |
|---|---|---|
| K2 `pdf` | **Landed** | `kernel-pdf.md` |
| K3 `image` | **Landed** — and behind no port, deliberately | `kernel-image.md` |
| K4 `ocr` | **Landed** | `kernel-ocr.md` |
| K5 `llm.local` | **Landed** | `kernel-llm-local.md` |
| K6 `llm.frontier` | **Landed**, unavailable without a provider key | `kernel-llm-frontier.md` |
| K7 `store` | **Landed** — put/get/verify + the ledger, `ArtifactStore`'s adapter | — |
| K8 `registry` | **Landed** — load, schema-validate, `registry_hash` | — |
| K1 `orchestrator` | **Not yet** (`E05`) | — |

The five kernel quickstarts drive the **library**. This surface is the bench those
five will be probed through once `E07-02` registers their operations, and until then
`--list` is the only thing it will do for you.
