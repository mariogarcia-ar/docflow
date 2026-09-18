#!/usr/bin/env bash
#
# Every `docflow-kernel pdf` command, run against one document.
#
# `kernel-cli.md` §9 lists eight commands for K2: six `now` (probe, classify,
# tokens, layout, render, split) and two `MVP` (facts, images). This driver runs
# all eight and reports each one's exit code and a summary of its answer.
#
# Usage:
#   scripts/kernel/kernel-pdf.sh [document] [--save <dir>]
#
# See `_lib.sh` for the reporting rules, which are shared with the other drivers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/kernel/_lib.sh
. "$SCRIPT_DIR/_lib.sh"

K_KERNEL="${DOCFLOW_KERNEL:-docflow-kernel}"
DEFAULT_DOCUMENT="tests/fixtures/pdf_large/MetodoCITRA17-APL.pdf"

# The provenance of each value is captured **before** the default is applied, so
# "given" and "defaulted" stay distinguishable. Reading `$DPI` after assigning the
# default would report every run as defaulted, which is the opposite of what the
# block is for.
PAGE_SOURCE="$([ -n "${PAGE:-}" ] && echo given || echo default)"
PAGES_SOURCE="$([ -n "${PAGES:-}" ] && echo given || echo default)"
DPI_SOURCE="$([ -n "${DPI:-}" ] && echo given || echo default)"

PAGE="${PAGE:-}"
PAGES="${PAGES:-}"
DPI="${DPI:-72}"

usage() {
  cat <<'EOF'
Usage: scripts/kernel/kernel-pdf.sh [document] [--save <dir>]

  document      the PDF to exercise. Defaults to
                tests/fixtures/pdf_large/MetodoCITRA17-APL.pdf
  --save <dir>  where the command outputs go. `render` and `split` write through
                K7's store; `tokens` and `layout` have their stdout redirected
                there, because `--save` is scoped to commands returning bytes.
                Without it nothing is written and the two that return bytes
                report a descriptor whose `path` is null.

Environment:
  DOCFLOW_KERNEL   the command to invoke. Defaults to `docflow-kernel`.
  KERNEL_PDF_SAVE  the save directory, if you prefer it to --save.
  PAGE             the single page for `classify`. Default: 1
  PAGES            the page selection for the range commands. See below.
  DPI              the resolution for `render`. Default: 72

PAGES accepts the same grammar as `--pages` (`kernel-cli.md` §9):

  1          one page ....................... PAGES=1
  2-5        a contiguous range .............. PAGES=2-5
  1,3,5      a selection, gaps included ...... PAGES=1,3,5
  10-12,20   ranges and single pages together  PAGES=10-12,20
  all        every page in the document ...... PAGES=all

Order matters only where the command says it does: `pdf split` **honours** the
order you give (`--pages 5,1` puts page 5 first), while `pdf layout` **refuses**
a reordered selection rather than sorting it, because its result is the reader's
own concatenation.

Left unset, PAGES adapts to the document — it comes from the document's own
`probe`, so a two-page file is exercised as `1-2` rather than failing on a range
that does not exist. The run prints the value and where it came from.

Examples:

  # every command against the committed fixture, writing nothing
  kernel-pdf.sh

  # a specific selection, rendering at 150 DPI, all output under var/pdf
  PAGES=2-5 DPI=150 kernel-pdf.sh --save var/pdf

  # one page of one document -- PAGE drives `classify`, PAGES the range commands
  PAGE=7 PAGES=7 kernel-pdf.sh documentos/factura.pdf

  # the whole document, output kept for inspection
  PAGES=all kernel-pdf.sh --save /tmp/full

Without PAGES the selection is `1-3` (or `1-2`, or `1`, when the document is
shorter) — never a range the document does not have.
EOF
}

K_INPUT="$DEFAULT_DOCUMENT"
K_SAVE="${KERNEL_PDF_SAVE:-}"
k_parse_args "$@" || exit $?
if [ "$K_HELP" -eq 1 ]; then
  usage
  exit 0
fi
DOCUMENT="$K_INPUT"
SAVE_DIR="$K_SAVE"

k_require_kernel || exit $?
k_require_file "$DOCUMENT" || exit $?

if [ -n "$SAVE_DIR" ]; then
  mkdir -p "$SAVE_DIR"
fi

# The adaptive selection, and why it is not a convenience: a hard-coded `1-3`
# fails a two-page document with exit 4 - a usage error about a range the caller
# never wrote - and the failure looks like a defect in the document rather than a
# bad default here. The count comes from the same probe the kernel validates
# against.
#
# Each of the three values records where it came from, because the output is what
# a reader uses to tell a typed parameter from a derived one. `PAGES` is the one
# that matters: it is capped by the document, so seeing `1-2 (from the document:
# 2 page(s))` explains why a two-page run did not ask for three.
page_count=""
if [ -z "$PAGE" ] || [ -z "$PAGES" ]; then
  page_count="$(
    "$K_KERNEL" pdf probe "$DOCUMENT" 2>/dev/null | python3 -c '
import json, sys
try:
    print(int(json.load(sys.stdin)["value"]["measurements"]["page_count"]))
except Exception:
    print(1)
' 2>/dev/null || echo 1
  )"

  if [ -z "$PAGE" ]; then
    PAGE="1"
    PAGE_SOURCE="default"
  fi

  if [ -z "$PAGES" ]; then
    if [ "$page_count" -ge 3 ]; then
      PAGES="1-3"
    elif [ "$page_count" -eq 2 ]; then
      PAGES="1-2"
    else
      PAGES="1"
    fi
    PAGES_SOURCE="from the document: $page_count page(s)"
  fi
fi

k_reset
k_banner "document: $DOCUMENT"

k_params \
  "page" "$(k_note "$PAGE" "$PAGE_SOURCE")" \
  "pages" "$(k_note "$PAGES" "$PAGES_SOURCE")" \
  "dpi" "$(k_note "$DPI" "$DPI_SOURCE")"
if [ -n "$SAVE_DIR" ]; then
  k_params "save" "$SAVE_DIR"
else
  k_params "save" "$(k_note "none" "bytes stay out of band")"
fi
echo

echo "K2 - 'now' commands"

# Every reading command's output lands in the save directory, by whichever route the
# command supports. Two commands need a route each, and the driver hides the
# difference:
#
#   - `render` and `split` return `Bytes`, so they take the kernel's own `--save`,
#     which routes the buffer through K7;
#   - `probe`, `classify`, `tokens` and `layout` answer an observation record, a
#     list or a `str` - none of which `--save` accepts, because it is scoped to
#     commands *returning bytes* (`kernel-cli.md` §10). Their stdout is redirected
#     to the same directory instead.
#
# What the redirect writes is the **whole envelope**, not the extracted value, so
# the `evidence` and the `reason` stay beside the answer.
if [ -n "$SAVE_DIR" ]; then
  k_save "probe" "$SAVE_DIR/probe.json" pdf probe "$DOCUMENT"
  k_save "classify(p$PAGE)" "$SAVE_DIR/classify-p$PAGE.json" pdf classify "$DOCUMENT" --page "$PAGE"
  k_save "tokens(p$PAGES)" "$SAVE_DIR/tokens-p$PAGES.json" pdf tokens "$DOCUMENT" --pages "$PAGES"
  k_save "layout(p$PAGES)" "$SAVE_DIR/layout-p$PAGES.json" pdf layout "$DOCUMENT" --pages "$PAGES"

  k_run "render(p$PAGES,dpi$DPI)" pdf render "$DOCUMENT" --pages "$PAGES" --dpi "$DPI" --save "$SAVE_DIR"
  k_run "split(p$PAGES)" pdf split "$DOCUMENT" --pages "$PAGES" --save "$SAVE_DIR"
else
  k_run "probe" pdf probe "$DOCUMENT"
  k_run "classify(p$PAGE)" pdf classify "$DOCUMENT" --page "$PAGE"
  k_run "tokens(p$PAGES)" pdf tokens "$DOCUMENT" --pages "$PAGES"
  k_run "layout(p$PAGES)" pdf layout "$DOCUMENT" --pages "$PAGES"
  k_run "render(p$PAGES,dpi$DPI)" pdf render "$DOCUMENT" --pages "$PAGES" --dpi "$DPI"
  k_run "split(p$PAGES)" pdf split "$DOCUMENT" --pages "$PAGES"
fi

# Run deliberately, and expected to exit 4. An `MVP` command that *dispatched*
# would be the defect: it would mean the surface implemented something the
# artifacts say is not built yet.
k_section "K2 - 'MVP' commands (must exit 4)"
k_run "facts(p$PAGE)" pdf facts "$DOCUMENT" --page "$PAGE"
k_run "images(p$PAGE)" pdf images "$DOCUMENT" --page "$PAGE"

k_summary
