#!/usr/bin/env bash
#
# Every `docflow-kernel image` command, run against one raster.
#
# K3 has four `now` commands (`info`, `legibility`, `rescale`, `crop`) and three
# `MVP` ones (`deskew`, `phash`, `tile`). Two of its refusals are documented rather
# than surprising, and this driver says so out loud:
#
#   - **`legibility` needs the registry**, because the threshold is corpus policy
#     with no override (`ADR-009`). A run without `--root` answers `asset_missing`.
#   - **`rescale` cannot succeed from this surface at all.** `source_dpi` is read
#     only from `image info`, and `info` reports no DPI - so it answers
#     `unsupported_format` for every image. That is `E04-03`'s open gap, recorded
#     in `docs/quickstart/kernel-image.md`, and the library path works because the
#     caller supplies the value.
#
# Usage:
#   scripts/kernel/kernel-image.sh [image] [--root <dir>] [--save <dir>]
#
# See `_lib.sh` for the reporting rules, which are shared with the other drivers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/kernel/_lib.sh
. "$SCRIPT_DIR/_lib.sh"

K_KERNEL="${DOCFLOW_KERNEL:-docflow-kernel}"
DEFAULT_IMAGE="tests/fixtures/expected-extraction/dbc07b17-2538-4611-9e51-7e161aaf7ba5.jpg"

#: The region `crop` reads. Small and away from the edges, so it is inside any
#: fixture this driver is pointed at - a region outside the image is exit 4, which
#: is a real answer but not the one a smoke test is looking for.
REGION="${KERNEL_IMAGE_REGION:-10,10,50,50}"
TARGET_DPI="${KERNEL_IMAGE_TARGET_DPI:-72}"

usage() {
  cat <<'EOF'
Usage: scripts/kernel/kernel-image.sh [image] [--root <dir>] [--save <dir>]

  image         the raster to exercise. Defaults to
                tests/fixtures/expected-extraction/dbc07b17-...jpg
  --root <dir>  the registry root `legibility` reads its threshold from.
                Default: registry
  --save <dir>  where the commands that return bytes write them.

Environment:
  DOCFLOW_KERNEL          the command to invoke. Defaults to `docflow-kernel`.
  KERNEL_IMAGE_ROOT       the registry root, if you prefer it to --root.
  KERNEL_IMAGE_REGION     the crop region, as x,y,w,h. Default: 10,10,50,50
  KERNEL_IMAGE_TARGET_DPI the rescale target. Default: 72

`rescale` is expected to refuse (exit 2, `unsupported_format`): `source_dpi` is
read only from `image info`, and `info` reports no DPI. That is `E04-03`'s open
gap, not a fault in this run.
EOF
}

K_INPUT="$DEFAULT_IMAGE"
REGISTRY_ROOT="${KERNEL_IMAGE_ROOT:-registry}"
SAVE_DIR=""

# `--root` is this driver's own flag; `k_parse_args` handles the positional and
# `--save`.
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --root)
      if [ $# -lt 2 ]; then
        echo "--root needs a directory" >&2
        exit 4
      fi
      REGISTRY_ROOT="$2"
      shift 2
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
SAVE_DIR="$K_SAVE"

k_require_kernel || exit $?
k_require_file "$IMAGE" || exit $?

if [ -n "$SAVE_DIR" ]; then
  mkdir -p "$SAVE_DIR"
fi

k_reset
k_banner "image: $IMAGE"

k_params \
  "region" "$REGION" \
  "target-dpi" "$TARGET_DPI" \
  "root" "$REGISTRY_ROOT"
if [ -n "$SAVE_DIR" ]; then
  k_params "save" "$SAVE_DIR"
else
  k_params "save" "$(k_note "none" "bytes stay out of band")"
fi
echo

echo "K3 - 'now' commands"

k_run "info" image info "$IMAGE"
k_run "legibility" image legibility "$IMAGE" --root "$REGISTRY_ROOT"

if [ -n "$SAVE_DIR" ]; then
  k_run --soft "rescale(dpi$TARGET_DPI)" image rescale "$IMAGE" --target-dpi "$TARGET_DPI" --save "$SAVE_DIR"
  k_run "crop($REGION)" image crop "$IMAGE" --region "$REGION" --save "$SAVE_DIR"
else
  k_run --soft "rescale(dpi$TARGET_DPI)" image rescale "$IMAGE" --target-dpi "$TARGET_DPI"
  k_run "crop($REGION)" image crop "$IMAGE" --region "$REGION"
fi

k_section "K3 - 'MVP' commands (must exit 4)"
k_run "deskew" image deskew "$IMAGE"
k_run "phash" image phash "$IMAGE"
k_run "tile" image tile "$IMAGE" --max-pixels 1000

k_summary
