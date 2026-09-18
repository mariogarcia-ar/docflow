#!/usr/bin/env bash
#
# The **product** CLI — `docflow` — as opposed to the lab bench.
#
# Two entry points, two audiences, and they are never crossed
# (`.github/copilot-instructions.md`, `kernel-cli.md` §2):
#
#   docflow          the product surface: `run`, `status`, `jobs`, `pause`, `stop`
#   docflow-kernel   the lab bench, driven by `scripts/kernel/kernel-*.sh`
#
# `docflow run` is the closing flow of Stage 1: it takes a **descriptor**, plans it,
# executes the stage graph and writes a ledger per unit plus a `run.json` manifest.
# The verbs are the *scheduler's* — a job is a handle on a run — while the bench's
# `orchestrator` verbs are the *engine's*. That is why this driver is short: the
# product surface is five verbs over one run, not nine operations over one kernel.
#
# Usage:
#   scripts/kernel/kernel-cli.sh [descriptor] [--out <dir>]
#
# See `_lib.sh` for the reporting rules, which are shared with the other drivers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/kernel/_lib.sh
. "$SCRIPT_DIR/_lib.sh"

#: The **product** entry point. Overridable so the driver can be pointed at a
#: build under test, the same way `DOCFLOW_KERNEL` does it for the bench.
K_CLI="${DOCFLOW_CLI:-docflow}"

DEFAULT_DESCRIPTOR="descriptors/synthetic-3stage.yaml"
OUT_DIR="${KERNEL_CLI_OUT:-var/kernel-cli}"

usage() {
  cat <<'EOF'
Usage: scripts/kernel/kernel-cli.sh [descriptor] [--out <dir>]

  descriptor    the stage graph to run. Defaults to
                descriptors/synthetic-3stage.yaml
  --out <dir>   where the run writes its artifacts and ledgers.
                Default: var/kernel-cli

Environment:
  DOCFLOW_CLI       the product command to invoke. Defaults to `docflow`.
  KERNEL_CLI_OUT    the output directory, if you prefer it to --out.
  KERNEL_CLI_JOB    a job id for `status`/`pause`/`stop`, when you have one.

This drives the **product** CLI (`docflow`), not the lab bench (`docflow-kernel`).
The bench has its own drivers next to this one; `docflow run` never invokes it.
EOF
}

K_INPUT="$DEFAULT_DESCRIPTOR"
K_SAVE="$OUT_DIR"
k_parse_args "$@" || exit $?
if [ "$K_HELP" -eq 1 ]; then
  usage
  exit 0
fi
DESCRIPTOR="$K_INPUT"
OUT="$K_SAVE"

# `k_require_kernel` reads `K_KERNEL` for the command to check. This driver drives
# the *product* CLI, so the check is pointed at it - never at `docflow-kernel`,
# which is a different entry point for a different audience.
K_KERNEL="$K_CLI"

k_require_kernel || exit $?

# **The two surfaces read different descriptor formats, and that is a real
# difference rather than a rough edge.** `docflow` parses JSON: the descriptor
# loader takes an injected reader, and the kernel layer imports no third-party
# library, so YAML belongs to the lab surface (`cli.py`, `_read_descriptor_mapping`).
# `docflow-kernel` owns the YAML binding.
#
# A `.yaml` descriptor is therefore **converted here** rather than passed through,
# which is what makes this driver able to use the same fixture as the bench's. The
# conversion is a translation of one committed file, not a parser: the shape is
# read out of the YAML by hand, and a descriptor with anything the driver does not
# recognise is refused rather than approximated.
JSON_DESCRIPTOR="$OUT_DIR/descriptor.json"

rm -rf "$OUT"
mkdir -p "$OUT"

if ! python3 - "$DESCRIPTOR" "$JSON_DESCRIPTOR" <<'PYTHON'
"""Convert the descriptor into the JSON the product CLI reads.

`yaml.safe_load` is used rather than a hand-rolled reader: the committed
descriptor is YAML, PyYAML is already installed for the bench's own binding, and a
home-made parser would be a second one to keep in step. `safe_load` refuses
arbitrary Python objects, which is the only thing this file needs.

The output is the *whole* mapping, unchanged. Neither surface may reinterpret a
descriptor: K1 "executes graphs it did not write", and a converter that pruned or
renamed a key would be a second authority on the format.
"""

import json
import pathlib
import sys

try:
    import yaml
except ImportError:
    print("PyYAML is not installed: pip install pyyaml", file=sys.stderr)
    raise SystemExit(3)

source = pathlib.Path(sys.argv[1])
target = pathlib.Path(sys.argv[2])

try:
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
except yaml.YAMLError as refused:
    print(f"{source} is not readable YAML: {refused}", file=sys.stderr)
    raise SystemExit(4)

if not isinstance(payload, dict):
    print(f"{source} must hold a mapping, not {type(payload).__name__}", file=sys.stderr)
    raise SystemExit(4)

unrecognised = sorted(set(payload) - {"unit", "units", "stages"})
if unrecognised:
    # Refused rather than dropped: a key this converter does not know may be one
    # the engine would have honoured, and silently discarding it would change the
    # graph the product CLI is asked to run.
    print(f"{source} carries key(s) this converter does not know: {unrecognised}", file=sys.stderr)
    raise SystemExit(4)

target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PYTHON
then
  echo "could not convert '$DESCRIPTOR' into the JSON the product CLI reads." >&2
  echo "The product CLI parses JSON; only the lab surface parses YAML." >&2
  exit 4
fi

k_reset
k_banner "descriptor: $DESCRIPTOR"

k_params \
  "as JSON" "$JSON_DESCRIPTOR" \
  "out" "$OUT" \
  "cli" "$K_CLI"
echo

echo "the product surface (docflow)"

# With no verb, the CLI prints its usage. It is exit 4 - a usage error - and it is
# run because it is the only discovery command the product surface has: there is
# no `docflow --help`.
k_exec "no verb (usage)" "$K_CLI"

# The verbs. `run` and `jobs` are exercised for real; `status`, `pause` and `stop`
# take a job id, and a fresh run does not mint one, so they are called with an id
# no job has and are `--soft`: an unknown id is a legitimate answer, not a fault.
k_exec "run" "$K_CLI" run "$JSON_DESCRIPTOR" --out "$OUT"
k_exec "jobs" "$K_CLI" jobs --root "$OUT"

JOB_ID="${KERNEL_CLI_JOB:-no-such-job}"
k_exec --soft "status($JOB_ID)" "$K_CLI" status "$JOB_ID" --root "$OUT"
k_exec --soft "pause($JOB_ID)" "$K_CLI" pause "$JOB_ID" --root "$OUT"
k_exec --soft "stop($JOB_ID)" "$K_CLI" stop "$JOB_ID" --root "$OUT" --force

k_section "the usage paths"

# Each verb refuses a missing argument with its own message, and each is exit 4.
# They are run because the messages are the surface's documentation.
k_exec "run (no descriptor)" "$K_CLI" run
k_exec "status (no id)" "$K_CLI" status
k_exec "unknown verb" "$K_CLI" not-a-verb

k_section "what the run produced"

if [ -d "$OUT" ]; then
  find "$OUT" -type f | sort | sed "s|^$OUT|  $OUT|" | head -n 12
  echo
  echo "  (the manifest is derived and rebuildable; the ledgers under each unit"
  echo "   directory are the record — prd.md FR-11)"
else
  echo "  nothing: $OUT does not exist"
fi

k_summary
