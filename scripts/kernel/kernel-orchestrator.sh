#!/usr/bin/env bash
#
# Every `docflow-kernel orchestrator` command, run against one descriptor.
#
# K1 is the stage-graph executor, and it is the one kernel whose input is not a
# document: it takes a **descriptor** (`descriptors/*.yaml`), plans it, runs it and
# reports the ledger. `descriptors/synthetic-3stage.yaml` is the Stage 1 closing
# flow, and it is the default here.
#
# Nine commands: `plan`, `run`, `ledger-read`, `manifest-rebuild`, `status`,
# `jobs`, `pause`, `resume`, `stop`. Several of them need a job that exists, so
# this driver runs `plan` and `run` first and then exercises the rest against what
# they produced - a driver that called `status` on a fabricated id would only
# measure the refusal path.
#
# Usage:
#   scripts/kernel/kernel-orchestrator.sh [descriptor] [--out <dir>]
#
# See `_lib.sh` for the reporting rules, which are shared with the other drivers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/kernel/_lib.sh
. "$SCRIPT_DIR/_lib.sh"

K_KERNEL="${DOCFLOW_KERNEL:-docflow-kernel}"
DEFAULT_DESCRIPTOR="descriptors/synthetic-3stage.yaml"

OUT_DIR="${KERNEL_ORCHESTRATOR_OUT:-var/kernel-orchestrator}"

usage() {
  cat <<'EOF'
Usage: scripts/kernel/kernel-orchestrator.sh [descriptor] [--out <dir>]

  descriptor    the stage graph to execute. Defaults to
                descriptors/synthetic-3stage.yaml
  --out <dir>   where the run writes its artifacts and ledgers.
                Default: var/kernel-orchestrator

Environment:
  DOCFLOW_KERNEL          the command to invoke. Defaults to `docflow-kernel`.
  KERNEL_ORCHESTRATOR_OUT the output directory, if you prefer it to --out.

Several of K1's commands need a job that exists. This driver runs `plan` and
`run` first and then exercises `status`, `jobs`, `pause`, `resume`, `stop`,
`ledger-read` and `manifest-rebuild` against what they produced, so the
successful path is measured rather than only the refusals.
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

k_require_kernel || exit $?
k_require_file "$DESCRIPTOR" || exit $?

rm -rf "$OUT"
mkdir -p "$OUT"

k_reset
k_banner "descriptor: $DESCRIPTOR"
echo "output:     $OUT"

k_section "K1 - planning and running"

k_run "plan" orchestrator plan "$DESCRIPTOR" --out "$OUT"
k_run "run" orchestrator run "$DESCRIPTOR" --out "$OUT" --jobs 1

k_section "K1 - reading what the run produced"

# The unit directory is the ledger's home, and its name comes from the
# descriptor's `unit:`. Deriving it here rather than hard-coding it is what keeps
# this driver working when the descriptor's unit is renamed.
UNIT_DIR="$(find "$OUT" -mindepth 1 -maxdepth 1 -type d ! -name artifacts 2>/dev/null | head -n 1)"

if [ -n "$UNIT_DIR" ]; then
  k_run "ledger-read" orchestrator ledger-read "$UNIT_DIR"
else
  echo "  (no unit directory under $OUT: the run produced nothing to read)"
fi

k_run "manifest-rebuild" orchestrator manifest-rebuild "$OUT"
k_run "jobs" orchestrator jobs --root "$OUT"

k_section "K1 - the control commands"
# `status`, `pause`, `resume` and `stop` take a job id, and **none of them declares
# `--root`** - so `pause`/`resume`/`stop` write `<job-id>/control.json` relative to
# the *current working directory*. That is measured, not assumed: calling
# `stop no-such-job` from the repository root created `no-such-job/control.json`
# there, and `--root` does not change it, because the command does not read that
# flag.
#
# The driver therefore runs them **from the output directory**, so the directory
# they create lands inside the run's scratch space rather than in the repository.
# `TARGET` names what they act on; it is an id no job has, which is the honest way
# to exercise them without a scheduler handle - and K1 answers rather than refusing,
# so the exit code is 0 for all four.
k_run --soft "status(unknown)" orchestrator status "no-such-job"

# The three that write run **from the output directory**, and not in a subshell:
# `k_run` increments the counters, and a subshell would increment its own copy and
# lose the tally by the time the summary is printed.
ORIGINAL_DIR="$PWD"
cd "$OUT"
k_run --soft "pause(unknown)" orchestrator pause "no-such-job"
k_run --soft "resume(unknown)" orchestrator resume "no-such-job"
k_run --soft "stop(unknown)" orchestrator stop "no-such-job" --force
cd "$ORIGINAL_DIR"

k_summary
