# Quickstart — what `docflow-kernel` can do today

**Status: honest, and the bench is open.** This page covers the **lab surface** — the
`docflow-kernel` bench. It is not a kernel: it is the dispatcher all eight kernels are
probed through, and as of `E07-02` (`S1-T21`) it dispatches.

Everything below has been run, and every block is quoted from a real invocation. The
headline:

> **49 commands, and 39 of them dispatch.** The other ten are declared, listed, and
> exit `4` naming themselves as unavailable — which is what keeps *"not built"* apart
> from *"does not exist"*.

That is the whole design in one sentence. The rest of this page is the evidence.

---

## Setup

The entry point is registered by `pyproject.toml` and installed in editable mode:

```bash
pip install -e ".[dev]"
```

No `[dev]` extra exists yet (`# TODO: [MVP]`), so in practice the environment is the
conda one the four QA gates run in. The command resolves on `PATH`:

```bash
which docflow-kernel
# /opt/anaconda3/envs/py313_env/bin/docflow-kernel
```

One runtime dependency was added for this surface: **PyYAML**, because a descriptor is
a `.yaml` file and the kernel layer may import no third party. The reader therefore
lives in the composition root, behind `read_descriptor`'s injected seam.

### A file path is not the only way in

The package re-exports `main` as the **function**, not the module — the frozen entry
point is `docflow.kernel_cli:main`:

```python
import importlib

main_module = importlib.import_module("docflow.kernel_cli.main")   # the module
from docflow.kernel_cli import main                                # the function
```

That distinction bites: `main` in a test must be **the module** if it is to reach
`dispatch`, the exit codes or the reason vocabulary:

```python
main = importlib.import_module("docflow.kernel_cli.main")
main.dispatch(["registry", "hash", "--root", "registry"])   # an Invocation
```

`dispatch()` returns an `Invocation` — exit code, stdout, stderr — without touching a
stream. That is what makes the surface testable without capturing file descriptors, and
it is why every assertion in the suite goes through it.

## Where the code lives

| Path | What it holds | Landed by |
|---|---|---|
| `docflow/kernel_cli/__init__.py` | re-exports `main` **as the function**, and **registers the surface** | `E07-01`, `E07-02` |
| `docflow/kernel_cli/main.py` | the dispatcher, the envelope, the exit codes, `register()` | `E07-01` (`S1-T20`) |
| `docflow/kernel_cli/commands/` | the 49 operations, one module per kernel, plus `surface.py` | `E07-02` (`S1-T21`) |
| `descriptors/synthetic-3stage.yaml` | the Stage 1 closing flow | `E08-01` (`S1-T19`) |
| `registry/policies/thresholds.json` | the policy values the commands read | `E07-02`, policy `S3-T04` |
| `tests/kernel_cli/test_commands.py` | the flag/port contract test | `E07-02` |
| `tests/kernel_cli/test_matrix.py` | the 17-row silent-failure suite | `E07-03` (`S1-T22`) |
| `tests/kernel_cli/test_gate.py` | the closing flow, step by step | `E08-01` (`S1-T19`) |

Two entry points, never crossed: `docflow` is the product surface, `docflow-kernel` is
the bench, and `docflow run` never invokes it.

### Why the surface is assembled at the package's import

Registering inside `main.main` would make the dispatcher import the composition root
while the composition root imports the dispatcher — **a genuine import cycle**, which
Pylint reports as seven `cyclic-import` findings. It did, until the registration moved
to `docflow/kernel_cli/__init__.py`. The entry point is `docflow.kernel_cli:main`, so
importing the package is what running the command does.

`commands/surface.py` offers both forms, and the split is what keeps a test's view of
the surface its own:

```python
surface.build()          # pure: the table, without declaring anything
surface.register_all()   # the side-effecting form, whose only caller is the package
```

## The whole surface

| Invocation | What it does | Today |
|---|---|---|
| `docflow-kernel --list` | The eight kernels, their determinism class, their adapter, and whether they are available | **works, exit `0`** |
| `docflow-kernel <kernel> <operation> [flags]` | One operation on one kernel | **39 dispatch, 10 refuse with exit `4`** |
| `--repeat N` | Run N times and report the per-repetition hashes | works — see *Determinism* |
| `docflow-kernel --help` | — | **does not exist**; `--help` is read as a kernel name |

### The 39 that dispatch

| Kernel | `now` commands |
|---|---|
| K1 `orchestrator` | `plan` `run` `status` `jobs` `pause` `resume` `stop` `ledger-read` `manifest-rebuild` |
| K2 `pdf` | `probe` `classify` `tokens` `render` `split` |
| K3 `image` | `info` `legibility` `rescale` `crop` |
| K4 `ocr` | `capabilities` `engine-info` `read` |
| K5 `llm.local` | `capabilities` `warm` `structured` `vision` |
| K6 `llm.frontier` | `capabilities` `warm` `structured` `vision` |
| K7 `store` | `put` `get` `verify` `ls` `ledger-read` `manifest-rebuild` |
| K8 `registry` | `validate` `hash` `show` `ls` |

### The 10 that refuse

`pdf facts`, `pdf images`, `image deskew`, `image phash`, `image tile`, `llm.local ps`,
`llm.local pull`, `llm.local generate`, `llm.frontier judge`, `llm.frontier
count-tokens`.

They are **declared**, so they are listed and they are distinguishable from a typo:

```bash
docflow-kernel pdf facts x.pdf
# pdf facts is not implemented in Stage 1 (kernel-cli.md §9 marks it `MVP`). It does
# not dispatch and does not run partially.                     -> exit 4
```

Compare a kernel or operation that genuinely does not exist:

```bash
docflow-kernel pdf invented          # unknown operation 'invented' for kernel 'pdf'
```

Two messages, two facts. That is the point of declaring an unimplemented operation
rather than omitting it.

## 1. `--list` — the inventory

```bash
docflow-kernel --list
```

```json
{
  "value": [
    { "kernel": "orchestrator",  "code": "K1", "determinism": "deterministic", "adapter": "—",            "available": true,  "detail": null },
    { "kernel": "pdf",           "code": "K2", "determinism": "deterministic", "adapter": "pdftotext",    "available": true,  "detail": null },
    { "kernel": "image",         "code": "K3", "determinism": "deterministic", "adapter": "raster library", "available": true,  "detail": null },
    { "kernel": "ocr",           "code": "K4", "determinism": "sampled",       "adapter": "docling",      "available": true,  "detail": null },
    { "kernel": "llm.local",     "code": "K5", "determinism": "sampled",       "adapter": "ollama",       "available": true,  "detail": null },
    { "kernel": "llm.frontier",  "code": "K6", "determinism": "external",      "adapter": "provider SDK", "available": false, "detail": "no provider key in the environment" },
    { "kernel": "store",         "code": "K7", "determinism": "deterministic", "adapter": "filesystem",   "available": true,  "detail": null }
  ],
  "evidence": {
    "terms": { "surface": "docflow-kernel" },
    "measurements": { "kernels": 8.0 },
    "observed": { "available": 7 }
  },
  "reason": null,
  "call_record": null
}
```

*(the real output carries all eight rows in the order K1…K8; the eighth, `registry`, is
elided above for width. The `observed` count is the real one.)*

`--list` emits **JSON, not an aligned table**. `kernel-cli.md` §4 shows the *content*
the table is meant to display; §6 fixes the *format*, and the format is the envelope.

### `available` is exactly `detail is None`

There is no second source of truth. Today **seven of eight** report available, and the
one that does not is the interesting row:

| Kernel | `detail` | What it means |
|---|---|---|
| K6 `llm.frontier` | `no provider key in the environment` | the module **is** landed and its adapter is written; the credential is not |

K6's adapter exists and is tested, and the kernel still reports unavailable —
correctly, because probing it also needs a provider key. **`llm.frontier` must never be
added to `ALWAYS_AVAILABLE_KERNELS` to make the count look better**; its test accepts
either reason on purpose.

`--list` takes no other argument, and says so rather than ignoring one:

```bash
docflow-kernel --list --verbose
# --list takes no other argument        -> exit 4
```

## 2. The closing flow — the gate, invocable from a shell

This is the flow Stage 1 exists to close. `descriptors/synthetic-3stage.yaml` declares
three stages over two units, with **no domain noun anywhere**: no field, no document
type, no pipeline code.

```yaml
unit: synthetic
units:
  - U-0001
  - U-0002
stages:
  - name: acquire
    kernel: store
    op: put
    slot: cpu
  - name: transform
    kernel: pdf
    op: probe
    needs: [acquire]
    slot: cpu
  - name: persist
    kernel: store
    op: put
    needs: [transform]
    slot: cpu
```

### Validate without executing

```bash
docflow-kernel orchestrator plan descriptors/synthetic-3stage.yaml --out O
# exit 0, and the output tree does not exist afterwards
```

The wrong result this guards against is *a `plan` that already ran work*.

### Run it

```bash
docflow-kernel orchestrator run descriptors/synthetic-3stage.yaml --out O
# exit 0
```

`run.json` carries `state`, `totals`, `stages`, `outcomes`, `inflight` — plus
`control`, `attempts` and `unverified`, which are additive:

```json
{
  "state": "complete",
  "totals": { "units": 2, "stages": 6, "done": 6, "running": 0, "failed": 0,
              "pending": 0, "blocked": 0, "stale": 0, "skipped": 0 },
  "inflight": [],
  "unverified": {}
}
```

### Read the ledger — **with** its verification outcome

```bash
docflow-kernel orchestrator ledger-read O/U-0001
```

```json
{
  "value": {
    "unit": "U-0001",
    "stages": {
      "acquire":   { "state": "done", "attempts": 1, "cache_key": "8b2efd6236816bdb…" },
      "transform": { "state": "done", "attempts": 1, "cache_key": "1b0aa01c02a47856…" },
      "persist":   { "state": "done", "attempts": 1, "cache_key": "448281d8542484be…" }
    },
    "unverified": {}
  },
  "evidence": { "observed": { "trustworthy": "true" } },
  "reason": null,
  "call_record": null
}
```

**Verification is an outcome of reading, never a request.** There is no `--verify` flag
and no ledger-trust `verify` subcommand, on either surface, in any stage. So delete a
`done` stage's artifact by hand and read again — with **no flag**:

```bash
rm O/U-0001/artifacts/4fa9a374245d7b5a…
docflow-kernel orchestrator ledger-read O/U-0001
```

```json
{
  "value": {
    "stages": { "transform": { "state": "done", … } },
    "unverified": { "transform": "artifact_missing" }
  },
  "evidence": { "observed": { "trustworthy": "false" } }
}
```

Two things to notice, and both are deliberate:

- **the recorded state is left `done`.** Rewriting it to `pending` would destroy the
  fact that the claim was ever made. `unverified` is an *addition*, not a correction.
- **the code is `artifact_missing`, from the closed set.** A caller branches on a code,
  never on a message.

A plain `run` afterwards **re-dispatches** that stage and says so under `unverified`,
rather than skipping it as complete.

### Interrupt it, and see what survives

`pause` and `resume` are K1's port methods. There is **no product `resume` verb** —
continuing is *"run it again"*.

```bash
docflow-kernel orchestrator pause O          # exit 0, control: "paused"
docflow-kernel orchestrator run … --out O    # dispatched: []   held: ["U-0001", "U-0002"]
docflow-kernel orchestrator resume O         # exit 0
docflow-kernel orchestrator run … --out O    # dispatched: []   skipped: 6
```

A held run reports what it did **not** reach — `held`, kept apart from `skipped`,
because held work has not been done and reporting it as skipped would read as complete.

### Kill it mid-stage, for real

`tests/kernel_cli/_kill_harness.py` runs the flow in a **subprocess** and sends itself
`SIGKILL` from inside the interrupted stage's own operation — after `store.begin` wrote
`running`, before the operation produced anything:

```bash
python tests/kernel_cli/_kill_harness.py O transform
# exit 137
```

```json
{ "acquire": "done", "transform": "running", "persist": "pending" }
```

**`running`, not `pending` and not `done`.** `pending` would read as *never began* — the
failure the whole crash-recovery design exists to prevent — and `done` would be a claim
about bytes that may be partial.

An injected exception at the same point would leave the same ledger, which is why the
harness is a subprocess and the signal is real: a simulated kill and a real one are
different evidence.

Two more things the kill shows:

- **the second unit has no ledger at all.** `_ensure_ledger` declares a unit's stage set
  when the unit is **opened**, so a unit the scheduler never reached has nothing
  declared. Writing an all-`pending` ledger for it would claim a stage set no run had
  reached.
- **the resume repeats only what the interruption cost.** The stage that completed is
  preserved; the next `run` re-runs the interrupted stage and what follows it.

### Rebuild the manifest — through both doors

```bash
B=$(shasum O/run.json | cut -d' ' -f1)
rm O/run.json

docflow-kernel orchestrator manifest-rebuild O    # exit 0
shasum O/run.json | cut -d' ' -f1                 # == $B

rm O/run.json
docflow-kernel store manifest-rebuild --out O     # exit 0
shasum O/run.json | cut -d' ' -f1                 # == $B
```

**Byte-identical, and the same value from both doors.** One operation, one authority:
`rebuild_index()` reads the ledger tree and nothing else, and K7's `rebuild_manifest`
delegates to it — K7 owns the bytes and the ledger files, K1 owns what a run means.

## 3. Determinism, demonstrated by `--repeat`

`--repeat N` runs the command N times and reports a hash per repetition, under a
`repetitions` key that appears **only** when the flag is given — the four-key envelope
is fixed by `kernel-cli.md` §6, so adding a key unconditionally would change it for
every other caller.

```bash
docflow-kernel registry hash --root registry --repeat 3
# repetitions: 3 entries, 1 distinct hash  — K8 is deterministic
```

**The flag reports, and never retries.** Retrying until two answers agree is forbidden
for a sampled kernel (`kernel-cli.md` §7): it manufactures the agreement it pretends to
find. Nothing on this surface compares two answers to decide whether to try again.

A count that would demonstrate nothing is refused, as a **usage error**: `--repeat`'s
value is the caller's own text, and §5 gives *"bad flag"* to exit `4`:

```bash
docflow-kernel registry hash --root registry --repeat 0
# --repeat must be at least 1; got 0. Running the operation zero times and reporting
# success would demonstrate nothing.                            -> exit 4
```

## Exit codes

The vocabulary is closed, and it is the same five values everywhere on this surface.
**All five were reached deliberately**, and the commands that reach them are:

| Code | Constant | Reached by | Meaning |
|---|---|---|---|
| `0` | `EXIT_VALUE` | `registry hash --root registry` | a value came back |
| `2` | `EXIT_REASON` | `pdf render … --dpi 300` on a 150 DPI scan | **no value, and a typed `Reason`** — *the document answered* |
| `3` | `EXIT_PRECONDITION` | `registry validate --root /nonexistent` | a precondition is unmet — a model not pulled, an asset missing, no engine |
| `4` | `EXIT_USAGE` | `pdf facts x.pdf` | the *request* was wrong |
| `1` | `EXIT_INTERNAL` | `store put /nonexistent` | a bug, or a vocabulary breach — never an answer about a document |

**The code is derived from the result, never passed by a handler.** A handler chooses a
*reason*; the surface decides what it means to a process. `exit_code_for()` reads
`value is not None` → `0`, otherwise looks the code up in `REASON_CODE_EXITS`. That is
what makes *"exit `2` is reserved for a typed `Reason`"* structural rather than merely
intended: nothing maps an exception to `2`.

An unknown reason code becomes `1`, not `2`. A code outside the vocabulary is a
*vocabulary breach*, and reporting it as `2` would collapse **broken** into **the
document answered**.

`stdout` is valid JSON on `0`, `2` and `3`; `4` and `1` emit **no** envelope at all.
`stderr` is the human log and never carries a second machine document, so
`docflow-kernel … | jq` is safe.

## Reading a result

The envelope is a frozen surface contract: four keys, always present, in this order, on
exits `0`, `2` and `3`.

```json
{
  "value": null,
  "evidence": {
    "terms": { "engine": "docling", "engine_version": "2.126.0" },
    "measurements": {},
    "observed": { "page": 1.0 }
  },
  "reason": { "code": "blank_page", "message": "the page holds no text" },
  "call_record": null
}
```

`call_record` rides on the **`Call`**, not on `KernelResult` — E01 froze the result at
three fields. It is populated for **K6** only: K6's adapter exposes `last_call_record`
and `last_raw_completion` as properties, and `E04-06` recorded why they are properties
rather than port members. K5 implements the same port and exposes neither, because an
Ollama call has no provider-side revision and no cost to report — so `call_record` is
`null` for it, which is the accurate answer rather than a stand-in.

`evidence` is not optional, enforced upstream rather than here:

```text
ValueError: KernelResult requires evidence: a kernel call always observes something
(versions, parameters, measurements). A value without evidence cannot be
distinguished from a stand-in, and a failure without evidence cannot be diagnosed.
```

The encoder is **explicit, member by member**, never introspective: adding a boundary
field must not silently change the wire format. It **raises** on an unknown type rather
than calling `str(value)` — a stringified object is a stand-in that reads like data.

That refusal is not theoretical. It caught a real defect here: two commands returned
kernel-layer objects (`Registry`, `Ledger`) that the envelope cannot carry, so both were
**unrunnable** — and the encoder's refusal named the problem instead of a `str()` that
would have published a stand-in. Both now report a description.

## 4. One command = one port method

The surface is a *window onto the ports*, not a second API. Every command maps to
exactly one port method and every flag to one parameter of it — and that is
**asserted**, not intended:

```bash
pytest tests/kernel_cli/test_commands.py
```

The contract test reads each command's declared flags and compares them against the
**live protocol signature** (`inspect.signature`), so a port method that is renamed
reddens the suite rather than drifting. It also asserts the forbidden vocabulary as an
**exact absence** over every command.

The measure is a **transcription of `kernel-cli.md` §9**, not the surface's own table.
That distinction is the whole point: a test that walked the registered table and
asserted *every registered command has a port method* would pass on an **empty**
registration. `plan-01-kernels.md` §9 names that as the risk this issue exists to
falsify, and the falsifier found four real gaps on its first run:

| Gap | What it was |
|---|---|
| `store ls` missing | §9 lists it as an index with no port method, and no module declared it |
| five file flags with renamed counterparts | a port takes text, a command takes a path — `--prompt-file` → `prompt`, `--schema-file` → `schema`, `--image` → `images` |
| `--correct` with no port parameter | it gates the corrected artifact, a registry policy value (`ADR-009`) — declared and refused rather than dropped |
| four port methods with no command under the naive name mapping | §9's grouped `ledger-begin / commit / fail` row cannot be derived by hyphenating underscores |

A flag with no counterpart is what turns a bench into a second product API, so the
exceptions are **declared as data** (`FILE_FLAG_PARAMETERS`, `SURFACE_ONLY_FLAGS`,
`PORT_COMMAND_NAMES`) rather than exempted silently — a genuinely orphaned flag has
nowhere to hide.

## A walkthrough: every `now` command, called once

The sections above are organised by **concept** — the gate, determinism, exit codes —
and the kernel pages cover K2-K6 in depth. This section is organised by **kernel**, and
covers the two kernels no other page does: K7 `store` and K8 `registry`. Every block is
a real invocation with its output quoted verbatim; K1's gate is above, and K2-K6 are
their own quickstarts.

### K7 `store` — four commands against one root

`put` writes into a root and reports the artifact's **descriptor**, not its bytes:

```console
$ docflow-kernel store put /tmp/k7/blob.bin --media-type application/octet-stream --root /tmp/k7/store
# value: { "sha256": "328e9e92651ae2b7d98680319b452d87b2dee11929ef100d4084cde8f267c3af",
#          "size_bytes": 2000, "media_type": "application/octet-stream",
#          "path": "artifacts/328e9e92...f267c3af" }
# exit 0
```

`verify` asks whether the stored bytes still hash to their own name — and the answer is
a **bool as the value**, so a store that failed verification is exit `0` with
`value: false`, not exit `2`. The question was answered; the answer was *no*.

```console
$ docflow-kernel store verify 328e9e92...f267c3af --root /tmp/k7/store
# value: true
# exit 0
```

`get` reads them back, and by default **out of band** — stdout carries the descriptor
and the bytes stay in memory unless you ask for them:

```console
$ docflow-kernel store get 328e9e92...f267c3af --root /tmp/k7/store
# value: { "sha256": "328e9e92...f267c3af", "size_bytes": 2000,
#          "media_type": "application/octet-stream", "path": null }
# exit 0

$ docflow-kernel store get 328e9e92...f267c3af --root /tmp/k7/store --save /tmp/k7/out
# value: { ..., "path": "artifacts/328e9e92...f267c3af" }
# exit 0
```

**This command was unrunnable until recently, and it is the third instance of the
class this page describes in §"Reading a result".** The port's `get` answers with bare
`bytes`, which is not one of the seven boundary types, so the encoder refused it — exit
`1`, *"no envelope encoding for bytes"*, on every call. The earlier fix named `Registry`
and `Ledger`; `bytes` was missed because a *buffer* looks like something the surface
obviously handles, and the contract test compares **flags**, never the type a handler
returns. Now it is wrapped as the boundary's `Bytes`, which is also what lets its own
`--save` work at all — `_apply_save` can only write a value it recognises as a buffer.

`ls` reads the **ledger tree**, not the artifact directories, and that is a real
distinction:

```console
$ docflow-kernel store ls --root /tmp/k7/store
# value: []
# exit 0
```

The store above holds one artifact and `ls` reports none, because a direct `put` writes
`artifacts/<sha>` and no ledger — the ledger is written when a *unit* is opened and
staged (`store.begin`/`commit`, which is K1's path). So `ls` answers *"what has been
claimed in a unit"* rather than *"what bytes are on disk"*, and the two differ whenever
something was stored outside a run. Worth knowing before reaching for `ls` as an
inventory.

```console
$ docflow-kernel store ledger-read missing-unit --root /tmp/k7/store
# reason.code: "artifact_missing"
# reason.message: "FileNotFoundError: No ledger at missing-unit/missing-unit.ledger.json..."
# exit 2
```

### K8 `registry` — validating the corpus policy

`validate` loads the whole declared asset set and reports what it found, with each
asset's hash:

```console
$ docflow-kernel registry validate --root registry
# value: { "root": "registry",
#          "assets": { "policies/thresholds.json": {
#              "sha256": "cd046da8714b4eee...b2cb9364", "format": "json", "bytes": 123 } },
#          "asset_count": 1 }
# exit 0
```

`hash` is the identity of that whole set — the value a cache key can carry:

```console
$ docflow-kernel registry hash --root registry
# value: "7dcc19cbf02ccfffc7175a64ec689ea09c5bbb08c180246cedd1411849befd04"
# exit 0
```

`ls` names an asset's **keys**, which is how you find out what policy a corpus actually
declares before a command refuses for want of one:

```console
$ docflow-kernel registry ls --asset policies/thresholds.json --root registry
# value: ["diagnosis.min_dpi", "image.legibility_threshold", "reader.correct",
#         "reader.min_chars"]
# exit 0
```

`show` reads one of them, and answers with the **key** as well as the value — a bare
`100.0` would be a number with nothing to attribute it to:

```console
$ docflow-kernel registry show --asset policies/thresholds.json \
    --key image.legibility_threshold --root registry
# value: { "image.legibility_threshold": 100.0 }
# exit 0
```

A key the asset does not declare is a precondition failure, not an empty answer:

```console
$ docflow-kernel registry show --asset policies/thresholds.json --key nope --root registry
# reason.code: "asset_missing"
# reason.message: "Asset 'policies/thresholds.json' declares no key 'nope'."
# exit 3
```

Exit `3` rather than `2`: no question was asked of a document, so this is *the call
could not be made* — and the message names both halves of the lookup instead of
reporting a missing value.

### The other six

| Kernel | Commands | Measured in |
|---|---|---|
| K1 `orchestrator` | 9 | the closing flow above, plus *Interrupt it* and *Rebuild the manifest* |
| K2 `pdf` | 5 | `kernel-pdf.md` |
| K3 `image` | 4 | `kernel-image.md` |
| K4 `ocr` | 3 | `kernel-ocr.md` |
| K5 `llm.local` | 4 | `kernel-llm-local.md` |
| K6 `llm.frontier` | 5 | `kernel-llm-frontier.md` |

Four of those six have `MVP` operations that exit `4`; the full set of ten is listed
under *The 10 that refuse* above.

## There is no engine setting here, and no default anywhere

The forbidden vocabulary is enforced by the dispatcher itself, not only by the contract
test, and the two refusals are deliberately distinct:

- **forbidden** — `--engine`, `--no-validate`, `--api-key`, `--fallback`,
  `--default-model`, `--verify`, and the document-concept words (`--field`,
  `--invoice`, `--cuit`, `--total`, `--document-type`, `--pipeline`, `--validator`,
  `--extractor`, `--golden`) → *"does not exist on this surface, and never will"*
- **unrecognized** — anything else → *"unknown flag"*

The two vocabularies are matched against the **flag name**, not the token, so the
attached spelling gets the right refusal:

```bash
docflow-kernel store put f.txt --cuit=1
# --cuit does not exist on this surface, and never will: a flag naming a document
# concept, an engine, a skippable validation or a default model is the drift this
# surface refuses.                                              -> exit 4

docflow-kernel store put f.txt --root=somewhere
# --root takes its value as a separate argument: write --root <value>, not '--root=somewhere'
```

The `--flag=value` form is refused rather than accepted, because accepting it silently
would give every parameter two spellings to keep in step.

There is no `--verify` flag because verification runs on **every** ledger read. There
is no `--no-validate` because validation is invariant in all 13 pipelines. And there is
no default model, engine or threshold anywhere in the code — a fallback that resolves an
unknown name to a working one changes every downstream value silently.

### Corpus policy comes from the registry, or the command refuses

Thresholds are registry policy with no override (`ADR-009`), so a command that needs one
reads it through `--root` and **refuses** when it is absent — never defaulting, because a
defaulted threshold is this surface deciding what *blank* or *blurry* means:

```bash
docflow-kernel image legibility page.jpg
# measurements: { "laplacian_variance": 676.47, "contrast": 0.23, "skew_estimate": -5.0 }
```

A missing key is a typed reason naming it, and **a command reading a key the registry
does not declare answers `asset_missing` for every input** — which is invisible,
because the refusal is a typed reason rather than an error. `image legibility` shipped
with exactly that defect: it asked for `image.legibility_threshold` while the registry
declared three other keys. A test now compares the keys the command modules read against
the keys the registry declares, and it was falsified by removing the key.

## What `docflow-kernel` does *not* do yet

| Not available | Where it lands |
|---|---|
| The nine `MVP` commands listed above | `# TODO: [MVP]` — each exits `4` naming itself |
| `docflow-kernel --help` | Not designed; `--help` is read as a kernel name and refused. `--list` is the discovery command |
| `--format yaml` | `# TODO: [MVP]` — `json` is the only machine format (`kernel-cli.md` §10) |
| A `[dev]` extra in `pyproject.toml` | `# TODO: [MVP]` |
| `--slots cpu=n,gpu=n,remote=n` as a grammar | `--jobs` moves the `cpu` bound; a parser for the full grammar is `# TODO: [MVP]` (`S3-T11`) |
| Moving PyYAML behind a `[kernel-cli]` extra | `# TODO: [MVP]` — the parser is only the bench's |
| Executing a descriptor of domain components from the bench | Open decision — Stage 1 stays synthetic (`plan-01-kernels.md` §12 #1) |
| The real 13 pipeline descriptors | `S3-T01` |
| A fixture generator for the matrix | **Done** — `tests/fixtures/matrix/build.py` |
| A fallback or default model, engine or threshold flag | **Never** (`plans/README.md` §2) |
| A verdict, score or aggregate on stdout | **Never** (`kernel-cli.md` §3) |
| A ledger-trust `verify` subcommand | **Never** (`prd.md` §10) |

## Where the arrow points

`sad.md` §1 draws **domain → ports → adapters**. The dispatcher does not sit on that
path, on purpose: `E07-01` is the bench *at the kernel layer*, and its own guard asserts
exactly that — the declaration lives in `tests/kernel_cli/test_main.py`:

```python
ALLOWED_DOCFLOW_IMPORT_PREFIXES: frozenset[str] = frozenset({"docflow.kernels"})
```

The composition root is the **one admitted exception**, by exact name rather than a
widened prefix:

```python
ALLOWED_COMPOSITION_IMPORT: str = "docflow.kernel_cli.commands"
```

The arrow that guard exists for is a dispatcher that imports an *adapter*, which would
make the kernel layer depend on a vendor. The composition root is not a vendor — it is
the same layer, and it is the only place adapters may be bound to commands. An import of
anything else under `docflow.kernel_cli` still fails.

## Verifying it all

```bash
pytest                                          # 959 tests
ruff check . && ruff format --check .           # lint and format
pylint src tests                                # the second linter
pytest tests/kernel_cli/                        # the bench's own three suites
```

The bench's suites, and what each is for:

| Suite | Tests | What it proves |
|---|---|---|
| `test_main.py` | 84 | the dispatcher, the five exit codes, the envelope, `--save` |
| `test_commands.py` | 13 | the flag/port contract, the forbidden vocabulary, the policy keys |
| `test_matrix.py` | 20 | the 17-row silent-failure matrix, with generated fixtures |
| `test_gate.py` | 18 | the closing flow, step by step, including a real `SIGKILL` |

Two of those are worth a sentence more. `test_matrix.py` asserts **a `reason.code`,
never a message string**, and asserts each fixture still *provokes* its row separately
from the row's outcome — because a fixture that lost its provoking property yields a
passing test that measures nothing. That happened twice while building it: the first
`scan-hidden-layer.pdf` carried **visible** text, and the first `three-invoices.pdf` had
six characters per page, enough to classify as an *image*. The fixture looked right and
measured nothing.

`test_gate.py` names its runbook step in every test name, and
`test_every_step_of_the_runbook_has_an_assertion` fails if a step loses its test — a
gate whose runbook has a hole is a gate with a hole, and the hole is invisible because
the suite is green.

## The other seven kernels

| Kernel | State | Quickstart |
|---|---|---|
| K2 `pdf` | **Landed** | `kernel-pdf.md` |
| K3 `image` | **Landed** — and behind no port, deliberately | `kernel-image.md` |
| K4 `ocr` | **Landed** | `kernel-ocr.md` |
| K5 `llm.local` | **Landed** | `kernel-llm-local.md` |
| K6 `llm.frontier` | **Landed**, unavailable without a provider key | `kernel-llm-frontier.md` |
| K7 `store` | **Landed** — and now reachable as `store put/get/verify/ls` | — |
| K8 `registry` | **Landed** — and now reachable as `registry validate/hash/show/ls` | — |
| K1 `orchestrator` | **Landed** — the closing flow above is it | — |

The five kernel quickstarts drive the **library**. This surface is the bench those five
are now also probed through, one operation at a time — which is what `kernel-cli.md` §1
asks for: *the kernels are a cornerstone of the project, so they must be tested
independently before the domain layer is built on top of them.*
