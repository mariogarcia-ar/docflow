#!/usr/bin/env bash
#
# Every driver in this directory, in order, with one verdict at the end.
#
# Eight drivers cover the eight kernels plus the product CLI. Running them one
# after another is what a smoke test is, and doing it here means the exit status
# answers one question: *is the whole surface reachable right now?*
#
# The order is deliberate: the cheap kernels first (registry, store), then the
# document ones, then the model ones, which are the slowest and the only ones
# needing a running service. A failure early therefore fails fast.
#
# What a non-zero exit means, and what it does not:
#
#   - a driver exits **1** when a command answered exit `1`, which §5 reserves for
#     a defect in the build. That is the only verdict `all.sh` treats as a fault.
#   - a driver exits **0** when every command answered within the contract, even
#     when most of them answered `2`, `3` or `4`. A scan is exit `2` because that
#     is what a scan is; an `MVP` command is exit `4` because it is declared and
#     not built. Those are results, not failures.
#
# Usage:
#   scripts/kernel/all.sh [--fast] [-v|--verbose]
#
# `--fast` skips the two drivers that need something outside the repository: the
# OCR models (~10 s a call) and a running Ollama.
#
# `-v`/`--verbose` prints the command behind every reported line. It is exported as
# `KERNEL_VERBOSE`, which is how it reaches the drivers: this script invokes each
# one with no arguments, and an environment variable crosses that boundary without
# teaching this script the argument grammar of eight others.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FAST=0
for option in "$@"; do
  case "$option" in
    --fast)
      FAST=1
      ;;
    -v|--verbose)
      KERNEL_VERBOSE=1
      export KERNEL_VERBOSE
      ;;
    -h|--help)
      sed -n '3,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown option '$option'" >&2
      exit 4
      ;;
  esac
done

# Order matters: cheap and self-contained first, so a broken build fails before
# ten seconds of ONNX loading.
DRIVERS=(
  "registry"
  "store"
  "orchestrator"
  "pdf"
  "image"
)

if [ "$FAST" -eq 0 ]; then
  DRIVERS+=("ocr" "llm" "cli")
else
  # `cli` is cheap and has no external dependency, so it stays even in `--fast`.
  DRIVERS+=("cli")
fi

FAILED=()
SKIPPED=()

printf 'running %s driver(s)%s\n' "${#DRIVERS[@]}" \
  "$([ "$FAST" -eq 1 ] && echo " (--fast: ocr and llm skipped)" || echo "")"

for name in "${DRIVERS[@]}"; do
  driver="$SCRIPT_DIR/kernel-$name.sh"
  if [ ! -x "$driver" ]; then
    echo
    echo "=== $name: NOT EXECUTABLE at $driver ===" >&2
    FAILED+=("$name")
    continue
  fi

  echo
  echo "======================================================================="
  echo "=== kernel-$name.sh"
  echo "======================================================================="

  if ! "$driver"; then
    FAILED+=("$name")
  fi
done

echo
echo "======================================================================="
echo "verdict"
echo "======================================================================="

if [ "${#FAILED[@]}" -eq 0 ]; then
  echo "  all ${#DRIVERS[@]} driver(s) stayed within the exit-code contract."
  echo "  exit 2/3/4 in a driver's summary are answers, not faults; only exit 1"
  echo "  would be, and no driver reported one."
  exit 0
fi

echo "  driver(s) reporting a defect: ${FAILED[*]}" >&2
echo >&2
echo "  A defect means a command answered exit 1 - a bug in the build, never a" >&2
echo "  document's answer (kernel-cli.md §5). Re-run that driver alone to see" >&2
echo "  which command, and read its stderr before suspecting the driver." >&2
exit 1
