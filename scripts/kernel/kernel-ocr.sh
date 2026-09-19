#!/usr/bin/env bash
#
# Every `docflow-kernel ocr` command, run against one raster.
#
# K4 is Docling behind the `OcrEngine` port, and it is `sampled` rather than
# deterministic (`sad.md` §4): two runs need not agree byte for byte, so this
# driver reports what each command *measured* rather than asserting a value. The
# reading it produces is not a hash to compare - it is tokens with coordinates,
# and `confidence` is `float | null`, where `null` is never coerced to `1.0`.
#
# Three commands on the port (`capabilities`, `engine-info`, `read`) plus the
# adapter's own `layout`, which is not on `OcrEngine`: `plans/README.md` §3 freezes
# the port's methods, so a fourth would re-open `E04-04`'s gate. Engine logs go to
# stderr, so stdout stays one parseable JSON document.
#
# **On the ~10 s**, which is a per-invocation fact rather than a first-call one: each
# `k_run` is a **new process**, so every `ocr read` reloads the ONNX models. Measured
# in this workspace, three consecutive calls took 9.04 s, 8.95 s and 11.25 s - there is
# no warm call to be fast. The driver prints the marker on every run for that reason,
# not only the first.
#
# Usage:
#   scripts/kernel/kernel-ocr.sh [image] [--pages <sel>] [--dpi N] [--lang <code>]
#
# See `_lib.sh` for the reporting rules, which are shared with the other drivers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/kernel/_lib.sh
. "$SCRIPT_DIR/_lib.sh"

K_KERNEL="${DOCFLOW_KERNEL:-docflow-kernel}"
DEFAULT_IMAGE="tests/fixtures/casos/66e6e0ea-e910-41f4-9037-13f0309812c1.jpg"

PAGES="${KERNEL_OCR_PAGES:-}"
DPI="${KERNEL_OCR_DPI:-}"
LANG="${KERNEL_OCR_LANG:-}"
TOLERANCE="${KERNEL_OCR_TOLERANCE:-}"
ORIENTATION="${KERNEL_OCR_ORIENTATION:-}"

# Whether `layout` asks for a table's cells. `--tables` is presence-shaped, so an
# unset variable is simply an absent flag rather than `false`.
TABLES="${KERNEL_OCR_TABLES:-}"

usage() {
  cat <<'EOF'
Usage: scripts/kernel/kernel-ocr.sh [image] [--pages <sel>] [--dpi N] [--lang <c>]
                                    [--tolerance N] [--orientation <axis>] [--tables]
                                    [-v|--verbose]

  image             the raster or PDF to read. Defaults to
                    tests/fixtures/casos/66e6e0ea-e910-41f4-9037-13f0309812c1.jpg
  --pages <sel>     the page selection for a multi-page input, e.g. 1-2
  --dpi N           the resolution the page is read at
  --lang <code>     the language hint
  --tolerance N     how far apart two tokens may sit and still share a row, in the
                    boxes' units at --dpi. Absent means 25.0 * dpi / 72, the
                    legacy's points converted
  --orientation <a> `horizontal` or `vertical`; absent means the dominant one the
                    boxes support, reported either way
  --tables          keep a table's cells in the reading. Off by default: without
                    it a table is absent entirely, because a table item carries no
                    text of its own
  -v, --verbose     print the command each line came from, as it ran.

Environment:
  DOCFLOW_KERNEL            the command to invoke. Defaults to `docflow-kernel`.
  KERNEL_VERBOSE            1 for the same trace as `--verbose`.
  KERNEL_OCR_PAGES          the page selection, if you prefer it to --pages
  KERNEL_OCR_DPI            the resolution, if you prefer it to --dpi
  KERNEL_OCR_LANG           the language hint, if you prefer it to --lang
  KERNEL_OCR_TOLERANCE      the row tolerance, if you prefer it to --tolerance
  KERNEL_OCR_ORIENTATION    the axis, if you prefer it to --orientation
  KERNEL_OCR_TABLES         non-empty to pass --tables

The `read` marker says every call is slow because every call is: each `k_run` is a new
process, so the ONNX models are loaded again. Measured: 9.04 s, 8.95 s, 11.25 s for
three consecutive calls - there is no warm call. Engine logs go to stderr, so stdout is
always one parseable JSON document.
EOF
}

K_INPUT="$DEFAULT_IMAGE"

# This driver's own flags. `k_parse_args` would reject them as unknown, so they
# are consumed here and the rest is handed on.
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --pages)
      [ $# -ge 2 ] || { echo "--pages needs a selection" >&2; exit 4; }
      PAGES="$2"
      shift 2
      ;;
    --dpi)
      [ $# -ge 2 ] || { echo "--dpi needs a number" >&2; exit 4; }
      DPI="$2"
      shift 2
      ;;
    --lang)
      [ $# -ge 2 ] || { echo "--lang needs a code" >&2; exit 4; }
      LANG="$2"
      shift 2
      ;;
    --tolerance)
      [ $# -ge 2 ] || { echo "--tolerance needs a number" >&2; exit 4; }
      TOLERANCE="$2"
      shift 2
      ;;
    --orientation)
      [ $# -ge 2 ] || { echo "--orientation needs an axis" >&2; exit 4; }
      ORIENTATION="$2"
      shift 2
      ;;
    --tables)
      TABLES=1
      shift
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

k_parse_args "${ARGS[@]+"${ARGS[@]}"}" || exit $?
if [ "$K_HELP" -eq 1 ]; then
  usage
  exit 0
fi
IMAGE="$K_INPUT"

k_require_kernel || exit $?
k_require_file "$IMAGE" || exit $?

# The `read` flags are collected into an array, so an unset one is simply absent
# rather than passed as an empty string. A bare `--pages ""` would be a usage
# error about a selection the caller never wrote.
READ_FLAGS=()
[ -n "$PAGES" ] && READ_FLAGS+=(--pages "$PAGES")
[ -n "$DPI" ] && READ_FLAGS+=(--dpi "$DPI")
[ -n "$LANG" ] && READ_FLAGS+=(--lang "$LANG")
[ -n "$TABLES" ] && READ_FLAGS+=(--tables)

# The same collection for `layout`, which adds the two ordering parameters. They
# are separate arrays rather than one, so `layout` never receives a flag `read`
# does not declare and `read` never receives an ordering one.
#
# Copied element by element rather than with `("${READ_FLAGS[@]+...}")`: wrapping
# that expansion in quotes makes the whole thing **one** element with the quotes
# left in it, so `layout` received a literal `"--tables"` and refused it. The
# `${arr[@]+...}` guard exists for `set -u` on an empty array, and the length test
# below covers the same case without the quoting hazard.
LAYOUT_FLAGS=()
if [ ${#READ_FLAGS[@]} -gt 0 ]; then
  LAYOUT_FLAGS=("${READ_FLAGS[@]}")
fi
[ -n "$TOLERANCE" ] && LAYOUT_FLAGS+=(--tolerance "$TOLERANCE")
[ -n "$ORIENTATION" ] && LAYOUT_FLAGS+=(--orientation "$ORIENTATION")

k_reset
k_banner "image: $IMAGE"

# Only the values that were given are listed: an unset `--pages`/`--dpi`/`--lang`
# is **absent** from the invocation rather than empty, so printing it would name a
# parameter the call does not carry.
k_params_args=()
[ -n "$PAGES" ] && k_params_args+=(pages "$PAGES")
[ -n "$DPI" ] && k_params_args+=(dpi "$DPI")
[ -n "$LANG" ] && k_params_args+=(lang "$LANG")
[ -n "$TOLERANCE" ] && k_params_args+=(tolerance "$TOLERANCE")
[ -n "$ORIENTATION" ] && k_params_args+=(orientation "$ORIENTATION")
[ -n "$TABLES" ] && k_params_args+=(tables "$(k_note "on" "cells join the reading")")
if [ ${#k_params_args[@]} -gt 0 ]; then
  k_params "${k_params_args[@]}"
else
  k_params "selection" "$(k_note "engine default" "no --pages, --dpi or --lang given")"
fi
echo

echo "K4 - the engine"
k_run "capabilities" ocr capabilities
k_run "engine-info" ocr engine-info

k_section "K4 - reading"
# Every invocation is a new process, so this is not a first-call cost: the models are
# reloaded on each `k_run`. Measured: 9.04 s, 8.95 s, 11.25 s for three consecutive
# calls.
echo "  (each read loads ONNX models: ~10s)"
# Measured: running several of these drivers at once makes this call abort with
# SIGABRT (exit 134) - ONNX model loading and the OCR pass together are memory
# hungry, and the abort is resource contention rather than a defect in the
# surface. Eight consecutive runs with nothing else in flight all exit 0. If you
# see 134 here, run it alone before suspecting the build.
k_run --soft "read" ocr read "$IMAGE" ${READ_FLAGS[@]+"${READ_FLAGS[@]}"}

k_section "K4 - ordering (the adapter's, not the port's)"
# `layout` is not a port method: `E04-04` freezes `OcrEngine`'s, so a fourth would
# re-open that gate. It is the OCR counterpart of `pdf layout`, with the one
# difference that a recogniser has no font metrics - so the rows are rebuilt from
# the boxes and the result is rows of blocks, not a character grid.
k_run --soft "layout" ocr layout "$IMAGE" ${LAYOUT_FLAGS[@]+"${LAYOUT_FLAGS[@]}"}
# The same call with a tolerance narrow enough to keep a table's header on its own
# row. Measured on casos/66cd35e9: the header sits at y=249 and the first item row
# at y=263, so a tolerance above the row pitch merges them.
k_run --soft "layout (tolerance 6)" ocr layout "$IMAGE" ${READ_FLAGS[@]+"${READ_FLAGS[@]}"} --tolerance 6

k_section "K4 - the correction gate"
# `--correct` is a VALUE flag, not a boolean: a bare `--correct` exits 4 with
# *"--correct requires a value"*, and `--correct true` gates the corrected
# artifact, which needs a registry policy the engine cannot read yet
# (`# TODO: [MVP]`, ADR-009). Both are worth seeing, so both are run.
k_run "read --correct (bare)" ocr read "$IMAGE" --correct
k_run --soft "read --correct true" ocr read "$IMAGE" --correct true

k_summary
