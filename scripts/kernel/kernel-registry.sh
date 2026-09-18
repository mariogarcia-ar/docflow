#!/usr/bin/env bash
#
# Every `docflow-kernel registry` command, run against one registry root.
#
# K8 holds the corpus assets - patterns, prompts, schemas, policies - and its whole
# job is to **fail fast rather than substitute**: a missing asset is a typed
# `asset_missing`, never an empty one (`kernel-cli.md` §9, matrix row 17). That is
# why `--asset` takes the asset's *key*, which is its path inside the registry
# (`policies/thresholds.json`), and not a bare name.
#
# Four commands: `validate`, `hash`, `ls` and `show`. `ls` and `show` need an asset
# key, and this driver reads it from `validate`'s own report rather than
# hard-coding it - a driver that named the asset itself would stop working the day
# the registry gains a second one.
#
# Usage:
#   scripts/kernel/kernel-registry.sh [root]
#
# See `_lib.sh` for the reporting rules, which are shared with the other drivers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/kernel/_lib.sh
. "$SCRIPT_DIR/_lib.sh"

K_KERNEL="${DOCFLOW_KERNEL:-docflow-kernel}"
DEFAULT_ROOT="registry"

usage() {
  cat <<'EOF'
Usage: scripts/kernel/kernel-registry.sh [root]

  root          the registry root to inspect. Default: registry

Environment:
  DOCFLOW_KERNEL        the command to invoke. Defaults to `docflow-kernel`.
  KERNEL_REGISTRY_ROOT  the registry root, if you prefer it to the positional.
  KERNEL_REGISTRY_KEY   an asset key to read with `show`, by default the first one
                        `validate` reports.

The asset key is the asset's path inside the registry, e.g.
`policies/thresholds.json` - not a bare name. `show` reads a single key out of it,
and the key defaults to the first one the asset declares.
EOF
}

K_INPUT="$DEFAULT_ROOT"
k_parse_args "$@" || exit $?
if [ "$K_HELP" -eq 1 ]; then
  usage
  exit 0
fi
ROOT="$K_INPUT"

k_require_kernel || exit $?
k_require_dir "$ROOT" || exit $?

k_reset
k_banner "root: $ROOT"

echo "K8 - the registry itself"

k_run "validate" registry validate --root "$ROOT"
k_run "hash" registry hash --root "$ROOT"

# The asset key comes from `validate`'s report, so this driver follows the
# registry rather than assuming its contents. `KERNEL_REGISTRY_KEY` overrides it.
ASSET="${KERNEL_REGISTRY_KEY:-}"
if [ -z "$ASSET" ]; then
  ASSET="$(
    "$K_KERNEL" registry validate --root "$ROOT" 2>/dev/null | python3 -c '
import json, sys
try:
    assets = json.load(sys.stdin)["value"]["assets"]
    print(sorted(assets)[0] if assets else "")
except Exception:
    print("")
' 2>/dev/null || echo ""
  )"
fi

if [ -n "$ASSET" ]; then
  k_run "ls(--asset)" registry ls --root "$ROOT" --asset "$ASSET"

  # The first key inside the asset, again read rather than assumed: a policy file
  # whose first key were hard-coded here would break on the next registry edit.
  KEY="$(
    "$K_KERNEL" registry ls --root "$ROOT" --asset "$ASSET" 2>/dev/null | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin)["value"]
    print(value[0] if isinstance(value, list) and value else "")
except Exception:
    print("")
' 2>/dev/null || echo ""
  )"

  if [ -n "$KEY" ]; then
    k_run "show(--key)" registry show --root "$ROOT" --asset "$ASSET" --key "$KEY"
  else
    echo "  show                       skipped: the asset declares no key to read"
  fi
else
  echo "  ls/show                    skipped: validate reported no asset"
fi

k_section "K8 - a root that is not there"
# Matrix row 17: a registry with an asset missing must exit 3 **naming it**, and
# no default may be substituted. Pointing at a root that does not exist is the
# cheapest honest way to exercise it, and `--soft` records that the refusal is the
# expected answer rather than a fault.
k_run --soft "validate(missing)" registry validate --root "$ROOT/does-not-exist"

k_summary
