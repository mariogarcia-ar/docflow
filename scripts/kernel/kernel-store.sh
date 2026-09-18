#!/usr/bin/env bash
#
# Every `docflow-kernel store` command, run against one file.
#
# K7 is content-addressed storage: the file's name in the store is its own SHA-256
# digest, and `get`/`verify` have nothing but that hash to reach it by (`FR-11`).
# This driver therefore cannot exercise `get` without first producing something to
# get, so it **puts a file, reads its digest back from the envelope, and drives the
# rest against that** - a driver calling `get` with a made-up hash would only
# measure the refusal path.
#
# `--save` is what makes the last step visible: `get` returns bytes, and without a
# save directory it reports a descriptor whose `path` is null, because bytes are
# out of band by default (`kernel-cli.md` §6).
#
# Usage:
#   scripts/kernel/kernel-store.sh [file] [--root <dir>] [--save <dir>]
#
# See `_lib.sh` for the reporting rules, which are shared with the other drivers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/kernel/_lib.sh
. "$SCRIPT_DIR/_lib.sh"

K_KERNEL="${DOCFLOW_KERNEL:-docflow-kernel}"
DEFAULT_FILE="registry/policies/thresholds.json"

usage() {
  cat <<'EOF'
Usage: scripts/kernel/kernel-store.sh [file] [--root <dir>] [--save <dir>]

  file          the file to store and read back. Defaults to
                registry/policies/thresholds.json
  --root <dir>  the store root. Default: var/kernel-store/store
  --save <dir>  where `get` writes the bytes it read. Default:
                var/kernel-store/delivered

Environment:
  DOCFLOW_KERNEL     the command to invoke. Defaults to `docflow-kernel`.
  KERNEL_STORE_ROOT  the store root, if you prefer it to --root.

The root is **wiped** at the start, so a run is reproducible: a store that
already held the bytes would make `put` a no-op and the digests would not be
comparable across runs.
EOF
}

K_INPUT="$DEFAULT_FILE"
STORE_ROOT="var/kernel-store/store"
SAVE_DIR="var/kernel-store/delivered"

# `--root` is parsed here rather than by `k_parse_args`, because it is this
# driver's own flag: `k_parse_args` handles the positional and `--save`.
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --root)
      if [ $# -lt 2 ]; then
        echo "--root needs a directory" >&2
        exit 4
      fi
      STORE_ROOT="$2"
      shift 2
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done

K_INPUT="${KERNEL_STORE_INPUT:-$DEFAULT_FILE}"
set -- "${ARGS[@]+"${ARGS[@]}"}"
k_parse_args "$@" || exit $?
if [ "$K_HELP" -eq 1 ]; then
  usage
  exit 0
fi
FILE="$K_INPUT"
SAVE_DIR="${K_SAVE:-$SAVE_DIR}"

k_require_kernel || exit $?
k_require_file "$FILE" || exit $?

rm -rf "$STORE_ROOT" "$SAVE_DIR"
mkdir -p "$STORE_ROOT" "$SAVE_DIR"

k_reset
k_banner "file: $FILE"

k_params \
  "media-type" "application/json" \
  "root" "$STORE_ROOT" \
  "save" "$SAVE_DIR"
echo

echo "K7 - put, then read back what was stored"

k_run "put" store put "$FILE" --media-type application/json --root "$STORE_ROOT"

# The digest is read **from the envelope**, not computed here. Computing it would
# assert that this driver's idea of the hash matches the store's, which is not the
# question: the question is whether the digest the store *reported* resolves.
DIGEST="$(
  "$K_KERNEL" store put "$FILE" --media-type application/json --root "$STORE_ROOT" 2>/dev/null |
    python3 -c '
import json, sys
try:
    print(json.load(sys.stdin)["value"]["sha256"])
except Exception:
    print("")
' 2>/dev/null || echo ""
)"

if [ -n "$DIGEST" ]; then
  k_run "verify" store verify "$DIGEST" --root "$STORE_ROOT"
  k_run "get(--save)" store get "$DIGEST" --root "$STORE_ROOT" --save "$SAVE_DIR"
  k_run "ls" store ls --root "$STORE_ROOT"
else
  echo "  (put reported no digest, so verify/get/ls have nothing to address)"
fi

k_section "K7 - the ledger commands"
# `ledger-read` needs a unit directory, and `manifest-rebuild` an output root.
# Neither exists in a bare store, so these measure the refusal - which is the
# honest answer here, and `--soft` says so out loud rather than hiding it.
k_run --soft "ledger-read(no unit)" store ledger-read "$STORE_ROOT" --root "$STORE_ROOT"
k_run --soft "manifest-rebuild" store manifest-rebuild "$STORE_ROOT"

k_summary
