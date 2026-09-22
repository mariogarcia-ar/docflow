#!/usr/bin/env bash
#
# Every `docflow-kernel llm.local` and `llm.frontier` command.
#
# K5 and K6 are the two model kernels, and they are the two classes where **the
# value is not what a test may assert** (`kernel-cli.md` §7): K5 is `sampled` and
# K6 is `external`, so the answers vary between runs and a driver that compared
# two would be measuring the sampler. What is stable is the *evidence* - the model
# digest, the token counts, the call record - and that is what this reports.
#
# The two kernels differ in one way that decides whether they can run at all:
#
#   - **K5 needs Ollama running with a model pulled.** Six are installed in this
#     workspace; the default is the smallest, so the driver stays quick.
#   - **K6 needs a provider key.** Without one every command refuses *before*
#     making a call, so this driver expects refusals there and says so. Its
#     `capabilities` is the exception: it describes the adapter's own
#     configuration and succeeds with no credential.
#
# The schema and prompt the structured calls need are generated into the output
# directory rather than committed: they are this driver's inputs, not the
# project's assets, and a reader should not have to go looking for them.
#
# Usage:
#   scripts/kernel/kernel-llm.sh [--model <tag>] [--frontier-model <provider:model>]
#
# See `_lib.sh` for the reporting rules, which are shared with the other drivers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/kernel/_lib.sh
. "$SCRIPT_DIR/_lib.sh"

K_KERNEL="${DOCFLOW_KERNEL:-docflow-kernel}"

#: The default local model. `deepseek-r1:8b`, not `smollm2:latest`: on
#: `chicos/22f0e9af-...-p1.txt` (a 1 589-byte file) `smollm2` intermittently ran away
#: into an unbounded repetition loop - measured once in 5 calls with no token
#: ceiling - and a sequential driver with a 600 s per-call ceiling stalls on it with
#: no output between files. `deepseek-r1:1.5b` answered 10 of 10 on the same file in
#: 4-11 s each, and refuses an oversized prompt with HTTP 400 rather than dropping it
#: silently. Override with `--model` or `KERNEL_LLM_MODEL`.
DEFAULT_MODEL="deepseek-r1:8b"

#: A vision-capable model, which is a different requirement from a text model.
DEFAULT_VISION_MODEL="qwen2.5vl:3b"

#: K6 names its model as `<provider>:<model>`, with a colon.
DEFAULT_FRONTIER_MODEL="anthropic:claude-sonnet-4-6"

# The provenance is captured **before** any default is applied, so `given` and
# `default` stay distinguishable. `--model` overwrites these further down.
MODEL_SOURCE="$([ -n "${KERNEL_LLM_MODEL:-}" ] && echo "KERNEL_LLM_MODEL" || echo default)"
VISION_SOURCE="$([ -n "${KERNEL_LLM_VISION_MODEL:-}" ] && echo "KERNEL_LLM_VISION_MODEL" || echo default)"
FRONTIER_SOURCE="$([ -n "${KERNEL_FRONTIER_MODEL:-}" ] && echo "KERNEL_FRONTIER_MODEL" || echo default)"

MODEL="${KERNEL_LLM_MODEL:-$DEFAULT_MODEL}"
VISION_MODEL="${KERNEL_LLM_VISION_MODEL:-$DEFAULT_VISION_MODEL}"
FRONTIER_MODEL="${KERNEL_FRONTIER_MODEL:-$DEFAULT_FRONTIER_MODEL}"

WORK="${KERNEL_LLM_WORK:-var/kernel-llm}"

usage() {
  cat <<'EOF'
Usage: scripts/kernel/kernel-llm.sh [--model <tag>] [--frontier-model <p:m>]
                                   [-v|--verbose]

  --model <tag>           the local model to call. Default: deepseek-r1:8b
  --frontier-model <p:m>  the frontier model, as provider:model.
                          Default: anthropic:claude-sonnet-4-6
  -v, --verbose           print the command each line came from, as it ran.

Environment:
  DOCFLOW_KERNEL            the command to invoke. Defaults to `docflow-kernel`.
  KERNEL_VERBOSE            1 for the same trace as `--verbose`.
  KERNEL_LLM_MODEL          the local model
  KERNEL_LLM_VISION_MODEL   the vision model. Default: qwen2.5vl:3b
  KERNEL_FRONTIER_MODEL     the frontier model
  KERNEL_LLM_WORK           where the generated prompt and schema go

K5 is `sampled` and K6 is `external` (`kernel-cli.md` §7), so neither value is
comparable between runs - this reports what each call *measured*, not what it
answered. K6 refuses before any call without a provider key: `DOCFLOW_FRONTIER_KEY`
plus `DOCFLOW_FRONTIER_MAX_TOKENS`. Its `capabilities` succeeds regardless.
EOF
}

# This driver's own flags, consumed before `k_parse_args` sees the rest.
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --model)
      [ $# -ge 2 ] || { echo "--model needs a tag" >&2; exit 4; }
      MODEL="$2"
      MODEL_SOURCE="--model"
      shift 2
      ;;
    --frontier-model)
      [ $# -ge 2 ] || { echo "--frontier-model needs provider:model" >&2; exit 4; }
      FRONTIER_MODEL="$2"
      FRONTIER_SOURCE="--frontier-model"
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

k_require_kernel || exit $?

mkdir -p "$WORK"
PROMPT="$WORK/prompt.txt"
SCHEMA="$WORK/schema.json"
VISION_SCHEMA="$WORK/vision-schema.json"
IMAGE="${KERNEL_LLM_IMAGE:-tests/fixtures/matrix/page.png}"

# The schema constrains generation through Ollama's `format` field. **Nothing
# validates the answer afterwards** - deliberately: a model can satisfy a schema
# structurally and still be useless, so the surface reports what came back rather
# than pretending a shape is a fact.
cat >"$PROMPT" <<'EOF'
Answer with a JSON object. Use 1500 as the total.
EOF
cat >"$SCHEMA" <<'EOF'
{
  "type": "object",
  "properties": {"total": {"type": "integer"}},
  "required": ["total"],
  "additionalProperties": false
}
EOF
cat >"$VISION_SCHEMA" <<'EOF'
{
  "type": "object",
  "properties": {"description": {"type": "string"}},
  "required": ["description"],
  "additionalProperties": false
}
EOF

k_reset

# The three models, as the parameter block every driver prints. A model is this
# driver's one parameter that changes what every line below it measures, so each is
# shown with where it came from - the flag, the environment, or the default.
k_params \
  "local model" "$(k_note "$MODEL" "$MODEL_SOURCE")" \
  "vision model" "$(k_note "$VISION_MODEL" "$VISION_SOURCE")" \
  "frontier model" "$(k_note "$FRONTIER_MODEL" "$FRONTIER_SOURCE")"
if [ -f "$IMAGE" ]; then
  k_params "image" "$IMAGE"
fi

k_section "K5 llm.local - 'now' commands (needs Ollama; sampled)"

k_run "capabilities" llm.local capabilities --model "$MODEL"
k_run "warm" llm.local warm --model "$MODEL"
k_run "structured" llm.local structured --model "$MODEL" --prompt-file "$PROMPT" --schema-file "$SCHEMA"

if [ -f "$IMAGE" ]; then
  k_run "vision" llm.local vision --model "$VISION_MODEL" --prompt-file "$PROMPT" --image "$IMAGE" --schema-file "$VISION_SCHEMA"
else
  echo "  vision                     skipped: no image at $IMAGE"
fi

k_section "K5 llm.local - the refusals worth seeing"

# `--model` is required and has no default (`kernel-cli.md` §8: a defaulted model
# is a silent substitution). The refusal names it.
k_run --soft "capabilities(no model)" llm.local capabilities
k_run --soft "capabilities(bad tag)" llm.local capabilities --model no-such-model:latest

k_section "K5 llm.local - 'MVP' commands (must exit 4)"
k_run "ps" llm.local ps --model "$MODEL"
k_run "pull" llm.local pull --model "$MODEL"
k_run "generate" llm.local generate --model "$MODEL" --prompt-file "$PROMPT"

k_section "K6 llm.frontier - 'now' commands (needs a provider key; external)"

# `capabilities` is the one that answers without a credential: it describes the
# adapter's configuration, not the provider's state.
k_run "capabilities" llm.frontier capabilities --model "$FRONTIER_MODEL"

# The gate chain, then the call. Each of these refuses with its own remedy, which
# is why they are `--soft`: a missing key is a precondition, not a fault.
k_run --soft "warm" llm.frontier warm --model "$FRONTIER_MODEL"
k_run --soft "structured" llm.frontier structured --model "$FRONTIER_MODEL" --prompt-file "$PROMPT" --schema-file "$SCHEMA"
if [ -f "$IMAGE" ]; then
  k_run --soft "vision" llm.frontier vision --model "$FRONTIER_MODEL" --prompt-file "$PROMPT" --image "$IMAGE" --schema-file "$VISION_SCHEMA"
fi

k_section "K6 llm.frontier - the naming and credential refusals"
# K6 names its model `<provider>:<model>` with a **colon**; a slash answers
# `model_unknown` and an unknown provider answers `provider_unknown`, each quoting
# what is configured.
k_run --soft "capabilities(slash)" llm.frontier capabilities --model anthropic/claude-sonnet-4-6
k_run --soft "capabilities(no provider)" llm.frontier capabilities --model nope:gpt

k_section "K6 llm.frontier - 'MVP' commands (must exit 4)"
k_run "judge" llm.frontier judge --model "$FRONTIER_MODEL"
k_run "count-tokens" llm.frontier count-tokens --model "$FRONTIER_MODEL"

k_summary
