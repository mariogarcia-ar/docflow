#!/usr/bin/env bash
#
# Shared helpers for the `scripts/kernel/*.sh` drivers.
#
# Each driver runs one kernel's commands against one input and reports what each
# one answered. The reporting rules are the same for all of them, so they live
# here rather than eight times over.
#
# Source it; do not execute it:
#
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   . "$SCRIPT_DIR/_lib.sh"
#
# Two things this file is careful about, and both matter more than the formatting:
#
# 1. **Exit codes are reported, not judged.** `2` and `4` are legitimate answers
#    (`kernel-cli.md` §5): a scan gives `classify` exit `2` because that is what a
#    scan *is*, and an `MVP` command exits `4` on every input because it is
#    declared and not built. A driver counts them. Exit `1` is the one that means
#    the build is broken, and it is reported as a defect.
#
# 2. **The summary comes from the envelope, never from the text.** Messages are
#    prose that changes between revisions; `value`, `reason.code` and
#    `measurements` are the contract. Grepping stdout would make a driver pass when
#    a message was reworded and fail when it was improved.

# --- Counters ----------------------------------------------------------------
#
# Every driver calls `k_reset` once, before its first `k_run`.

K_TOTAL=0
K_OK=0
K_REASON=0
K_PRECONDITION=0
K_USAGE=0
K_DEFECT=0

k_reset() {
  K_TOTAL=0
  K_OK=0
  K_REASON=0
  K_PRECONDITION=0
  K_USAGE=0
  K_DEFECT=0
}

# --- The envelope reader -----------------------------------------------------
#
# A file rather than `python3 -c`, and that is a correctness choice: the reader
# has nested quotes and an f-string-free body, and threading those through a shell
# string is how a driver ends up parsing the wrong thing. The envelope path is
# passed as an argument, so nothing here is interpolated by the shell.
#
# One Python process per command is not free, but parsing JSON in bash is not
# possible and `jq` is a dependency a driver has no business requiring. The cost is
# tens of milliseconds per command, against commands that read 59-page documents.

K_READER=""

k_reader_path() {
  if [ -z "$K_READER" ]; then
    K_READER="$(mktemp -t docflow-reader)"
    cat >"$K_READER" <<'PYTHON'
"""Summarise a KernelResult envelope in one line, for a human at a console."""

import json
import sys

path = sys.argv[1]
raw = open(path, encoding="utf-8").read().strip()

if not raw:
    print("(no output)")
    raise SystemExit(0)

try:
    envelope = json.loads(raw)
except json.JSONDecodeError:
    # Not every surface emits a KernelResult. The product CLI (`docflow`) answers
    # in prose - *"job 7f859e9c — 6 stage(s) run, 0 already done, 0 held"* - and
    # that is its contract, not a defect (`kernel-cli.md` §2: two entry points,
    # two audiences). Reporting the first line is the honest summary; calling it
    # unparseable would report one surface's format as the other's failure.
    first = raw.splitlines()[0] if raw.splitlines() else "(empty output)"
    print(first if len(first) <= 72 else first[:69] + "...")
    raise SystemExit(0)

reason = envelope.get("reason")
if reason is not None:
    print("reason " + str(reason.get("code", "?")))
    raise SystemExit(0)

value = envelope.get("value")
evidence = envelope.get("evidence") or {}
measurements = evidence.get("measurements") or {}
observed = evidence.get("observed") or {}


def count(key):
    """Read a measurement as a float, or zero when it is absent."""
    try:
        return float(measurements.get(key, 0))
    except (TypeError, ValueError):
        return 0.0


if value is None:
    # A value-less result with no reason cannot happen: KernelResult has exactly
    # two states. Printing nothing would hide a defect rather than show it.
    print("no value, no reason")
elif isinstance(value, bool):
    print(str(value))
elif isinstance(value, str):
    print(str(len(value)) + " char(s)")
elif isinstance(value, list):
    first = value[0] if value else None
    if isinstance(first, dict) and "page" in first:
        pages = sorted({item["page"] for item in value})
        print(str(len(value)) + " token(s) on page(s) " + str(pages))
    else:
        print(str(len(value)) + " item(s)")
elif isinstance(value, dict):
    if "delivery_name" in value:
        print(str(value.get("size_bytes")) + " bytes -> " + str(value["delivery_name"]))
    elif "sha256" in value and "media_type" in value:
        print(str(value["sha256"])[:16] + "  " + str(value["media_type"]))
    elif "page_count" in measurements:
        print(str(int(count("page_count"))) + " page(s)")
    elif "shape" in observed:
        print(
            "shape="
            + str(observed["shape"])
            + " chars="
            + str(int(count("char_count")))
            + " images="
            + str(int(count("image_count")))
        )
    elif "intact" in observed:
        print("intact=" + str(observed["intact"]))
    elif observed:
        # An `Evidence` value: the record *is* the answer for `probe`, `classify`,
        # `info` and the rest of the measuring commands. Naming the keys tells a
        # reader which observation to look at; a bare count would not.
        print("observed: " + ", ".join(sorted(observed)[:5]))
    elif value:
        print(str(len(value)) + " key(s): " + ", ".join(sorted(value)[:6]))
    else:
        print("empty mapping")
else:
    print(str(value))
PYTHON
  fi
  printf '%s' "$K_READER"
}

# --- Running one command -----------------------------------------------------
#
# `k_run [--soft] <label> <kernel> <operation> [args...]`
#
# `--soft` means *an abnormal exit here is not a defect*. It exists for the two
# commands whose refusal is documented rather than surprising:
#
#   - `image rescale` cannot succeed from this surface at all: `source_dpi` is
#     read only from `image info`, and `info` reports no DPI, so it answers
#     `unsupported_format` for every image (`E04-03`, still open).
#   - `llm.frontier` refuses before any call, because no provider key is set.
#
# Without `--soft`, an exit outside the contract's four values is a defect.

k_run() {
  local soft=0
  if [ "${1:-}" = "--soft" ]; then
    soft=1
    shift
  fi

  local label="$1"
  local kernel="$2"
  shift 2

  k_invoke "$soft" "$label" "$K_KERNEL" "$kernel" "$@"
}

# `k_exec [--soft] <label> <command> [args...]`
#
# The same thing for a command that is **not** `docflow-kernel <kernel> <op>`. The
# product CLI is `docflow <verb>`, with no kernel in the middle, so its driver
# cannot use `k_run` - and passing the command name as the kernel is what made
# every line of that driver read `unknown verb 'docflow'`.
k_exec() {
  local soft=0
  if [ "${1:-}" = "--soft" ]; then
    soft=1
    shift
  fi

  local label="$1"
  shift

  k_invoke "$soft" "$label" "$@"
}

# The shared body. It takes the command and its arguments whole, so the caller
# decides the shape of the invocation and only the reporting is common.
k_invoke() {
  local soft="$1"
  local label="$2"
  shift 2

  local out_file err_file reader
  out_file="$(mktemp)"
  err_file="$(mktemp)"
  reader="$(k_reader_path)"

  local code=0
  "$@" >"$out_file" 2>"$err_file" || code=$?

  local summary
  summary="$(python3 "$reader" "$out_file" 2>/dev/null || echo "(reader failed)")"

  # Commands that emit no envelope - a usage error, and every verb of the product
  # CLI - answer on stderr, where the first line is the message rather than the
  # usage block that follows it.
  if [ "$summary" = "(no output)" ] && [ -s "$err_file" ]; then
    summary="$(head -n 1 "$err_file")"
  fi

  K_TOTAL=$((K_TOTAL + 1))
  case "$code" in
    0) K_OK=$((K_OK + 1)) ;;
    2) K_REASON=$((K_REASON + 1)) ;;
    3) K_PRECONDITION=$((K_PRECONDITION + 1)) ;;
    4) K_USAGE=$((K_USAGE + 1)) ;;
    *)
      if [ "$soft" -eq 1 ]; then
        K_PRECONDITION=$((K_PRECONDITION + 1))
      else
        K_DEFECT=$((K_DEFECT + 1))
      fi
      ;;
  esac

  printf '  %-26s exit %s  %s\n' "$label" "$code" "$summary"

  rm -f "$out_file" "$err_file"
}

# --- Summary -----------------------------------------------------------------
#
# Prints the tally and returns 1 when a defect was seen, so the driver's exit
# status carries the verdict.

k_summary() {
  echo
  echo "summary: $K_TOTAL command(s)"
  printf '  exit 0  value produced       %s\n' "$K_OK"
  printf '  exit 2  document answered    %s\n' "$K_REASON"
  printf '  exit 3  precondition missing %s\n' "$K_PRECONDITION"
  printf '  exit 4  usage or MVP         %s\n' "$K_USAGE"

  if [ "$K_DEFECT" -gt 0 ]; then
    printf '  exit 1  DEFECT               %s\n' "$K_DEFECT"
    echo
    echo "exit 1 is a bug in the build, never a document's answer" \
      "(kernel-cli.md §5)." >&2
    return 1
  fi

  return 0
}

# --- Argument parsing --------------------------------------------------------
#
# `k_parse_args "$@"` sets `K_INPUT` (the positional, when one was given) and
# `K_SAVE` (from `--save`), and returns:
#
#   0  parsed: continue
#   4  a usage error, already reported on stderr: exit 4
#
# `--help` sets `K_HELP=1` and returns 0, because only the driver knows what its
# positional means and therefore how to describe itself.
#
# The caller sets `K_INPUT`'s default **before** calling, so *defaulted* and
# *given* stay distinguishable: a positional overwrites it, absence does not.

K_INPUT=""
K_SAVE=""
K_HELP=0

k_parse_args() {
  K_HELP=0

  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--help)
        K_HELP=1
        return 0
        ;;
      --save)
        if [ $# -lt 2 ]; then
          echo "--save needs a directory" >&2
          return 4
        fi
        K_SAVE="$2"
        shift 2
        ;;
      -*)
        echo "unknown option '$1'" >&2
        return 4
        ;;
      *)
        K_INPUT="$1"
        shift
        ;;
    esac
  done

  return 0
}

# --- Preconditions -----------------------------------------------------------

k_require_kernel() {
  if ! command -v "$K_KERNEL" >/dev/null 2>&1; then
    echo "the '$K_KERNEL' command is not on PATH." >&2
    echo "Install it with: pip install -e '.[dev]'  (from the repository root)" >&2
    return 3
  fi
  return 0
}

k_require_file() {
  if [ ! -f "$1" ]; then
    echo "no such file: $1" >&2
    return 4
  fi
  return 0
}

k_require_dir() {
  if [ ! -d "$1" ]; then
    echo "no such directory: $1" >&2
    return 4
  fi
  return 0
}

# --- Reporting helpers -------------------------------------------------------

k_banner() {
  echo "$1"
  echo
}

k_section() {
  echo
  echo "$1"
}

# --- The resolved parameters -------------------------------------------------
#
# `k_params <name> <value> [<name> <value> ...]`
#
# Prints the values a driver actually used, aligned, one per line:
#
#   document          tests/fixtures/pdf_large/MetodoCITRA17-APL.pdf
#   pages             1-3  (from the document: 59 page(s))
#   dpi               72
#
# It exists because a driver's output otherwise leaves the most important fact
# implicit. A reader sees `render(p1-3,dpi72)` in a label and cannot tell which of
# those values they typed and which the driver chose - and for a value that
# **adapts to its input**, like the page selection, that difference is the whole
# reason the driver has the logic it has.
#
# Pair the name and the value; a value may carry its own parenthetical note, which
# is how provenance travels without a second column to keep aligned.

k_params() {
  while [ $# -gt 1 ]; do
    printf '  %-16s %s\n' "$1" "$2"
    shift 2
  done
}

# `k_note <value> <provenance>` renders a value with where it came from, so a
# reader can tell a typed parameter from a derived one at a glance.
k_note() {
  printf '%s  (%s)' "$1" "$2"
}
