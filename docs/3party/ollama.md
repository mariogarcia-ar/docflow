# Ollama — dossier

> Kind: local HTTP service (with a client binary)
> Processor / seam: `docflow.llm.primitives`
> Status: collecting (2026-09-24)

## A. Identity and provenance

| Field | Value |
|---|---|
| `engine` value in metadata | `ollama` (see the open question on what `engine`/`engine_version` mean for a provider call) |
| Kind | **HTTP service** on `localhost:11434` (`/api/*`), reached either over HTTP or through the bundled client |
| Upstream | <https://ollama.com>; API reference: `github.com/ollama/ollama/blob/main/docs/api.md` |
| Context7 ID | `TBD` |
| Maintainer / cadence | Ollama; frequent releases |
| Version this page was read against | local client **0.31.1** (server **not running** on 2026-09-24) |

## B. Install, pin and version discovery

- **Install shape:** a service, not a pip dependency — it cannot be installed by `pip install -e ".[dev]"`, and it is **not** pinned by `pyproject.toml`. `TBD`: record the supported client/server range as documentation instead.
- **Version at runtime:** `ollama --version` prints the **client** version and warns when no server is reachable ("Warning: could not connect to a running Ollama instance / Warning: client version is 0.31.1" — observed locally). The **server** version is `GET /api/version`. Which one is `engine_version` is an open question (K).
- **Absent / present check:** the provider SDK/HTTP client is imported **inside** the primitive (`LLM-02`), so `import docflow.llm.primitives` succeeds with no provider installed; "no server listening" is a call-time failure, mapped to `PROVIDER_ERROR` (retryable).
- **Suite without it:** the LLM double is **scripted** (`LLM-03`) — responses are not deterministic, and `LLM-08` needs a sequence.

## C. Licence and distribution posture

- Ollama (engine) is **MIT**; the **models** are separately licensed and are downloaded by the user, not shipped by us — check each model's licence before a model name is hardcoded anywhere. `TBD`.
- Exposure caveat from the upstream docs: if Ollama is ever bound to a public interface, only `/api/generate` and `/api/chat` should be exposed — never the pull/delete endpoints. The PoC keeps it on localhost.

## D. Interface contract — the methods we need

| Primitive (`subplan-procesador-llm-call.md` §3) | Ollama call |
|---|---|
| `generate_text` | `POST /api/generate` with `{model, prompt, stream: false, options}` → `response` |
| `generate_multimodal` | `POST /api/chat` with a `message` whose `images` field carries base64 images (vision models) |
| `generate_structured` | `POST /api/chat` (or `/api/generate`) with **`format`** set to a JSON schema → the response matches the schema. `format: "json"` is the weaker JSON-mode variant |
| `list_models` | `GET /api/tags` → locally available models (the names usable as `model`) |
| `check_model_available` | membership of `list_models`, or `POST /api/show` for model details — `TBD` which |
| `get_context_window` | `TBD` — likely `POST /api/show` (model info); verify before relying on it |
| model load/unload | `POST /api/generate` with an **empty prompt** loads the model; `keep_alive` controls how long it stays resident (default `5m`) |

**Request details that matter**

- `stream: false` is required for a single response object instead of a stream of chunks — the primitive must send it explicitly rather than depend on the default.
- `options` carries the model parameters (`temperature`, `seed`, `num_ctx`, …). For **reproducible** output the seed must be set explicitly; Ollama documents the seed option for exactly that.
- Message roles: `system`, `user`, `assistant`, `tool`.
- Missing/unknown model: HTTP **404** with `{"error": "model ... not found"}` → `MODEL_UNAVAILABLE`; no silent substitution of another installed model.

## E. Inputs, outputs and artifact naming

| Field | Value |
|---|---|
| Inputs | prompt text, optional images (base64), model name, options, JSON schema |
| Outputs | JSON over HTTP: `response` / `message.content`, plus counters (`done`, `eval_count`, durations) |
| Our naming | the `llm/` artifact namespace decides the files; the service writes nothing |
| Ordering | n/a (one response); the graph order is the orchestrator's |
| Encoding | JSON/UTF-8; a schema-constrained `format` is the mechanism that keeps the payload parseable |

## F. Determinism levers

| Lever | Enters `processing_key`? |
|---|---|
| `model` (and its digest/tag) | yes |
| `temperature`, `seed` | yes |
| `num_ctx` / other `options` | yes |
| Prompt template version | yes — template version is part of the key by plan |
| `keep_alive`, `stream` | no (transport/lifetime) |
| Server version | recorded in metadata; a hosted/quantized variant can change output without a version change |

**Not deterministic by nature:** sampling without a fixed seed. Recorded as an accepted trade-off (`GEN-17`), never as covered by a test.

## G. Failure modes and our error mapping

| Engine signal | Our kind (subplan §3.7 posture) | Retry |
|---|---|---|
| connection refused / no server | `PROVIDER_ERROR` | `RETRYABLE` |
| HTTP 404 `model not found` | `MODEL_UNAVAILABLE` | `NON_RETRYABLE` |
| request exceeds the context window (error text) | `CONTEXT_OVERFLOW` | `NON_RETRYABLE` — detect from the message; `TBD` exact string |
| client-side timeout | `TIMEOUT` | `RETRYABLE` |
| response is not JSON / not the schema | `INVALID_JSON` / `SCHEMA_ERROR` | schema failure is retryable; a malformed body is not |
| provider 5xx | `PROVIDER_ERROR` | `RETRYABLE` |
| SDK/library missing | `DEPENDENCY_ERROR` | `NON_RETRYABLE` |

Error kind names come from the subplan's posture list (`PROVIDER_ERROR`, `TIMEOUT`, `MODEL_UNAVAILABLE`, `CONTEXT_OVERFLOW`, `INVALID_RESPONSE`, `INVALID_JSON`, `SCHEMA_ERROR`, `DEPENDENCY_ERROR`, `INTERNAL_ERROR`), each marked `RETRYABLE` / `NON_RETRYABLE`. The `LLMProvider` result/error types themselves land in `llm/primitives/` (`LLM-02`), not in `contracts.py` — verified: `contracts.py` today has `LLMStatus`, `LLMValidationState`, `Usage`, `Timing`, `LLMAttempt` and no error enum.

## H. Seam ownership and the double

| Field | Value |
|---|---|
| Owning module | `docflow.llm.primitives` |
| Injection point | `monkeypatch.setattr("docflow.llm.primitives.<primitive>", fake_provider)` — the provider primitive the call resolves |
| What "native-shaped" means | provider-shaped responses (text, JSON body, error status) — never our `LLMResult`; the fake is **scripted** and must be able to return a sequence |
| Shared helper | `missing_from_double(...)` does **not** apply (the seam replaces a symbol of ours) |
| Other processors | none may reach a provider, and the SDK import stays inside the primitive |

## I. Cost, latency and limits

- Local inference: latency scales with model size × prompt tokens; the PoC's dominant cost is generation time, not money.
- Limits: context window (model-specific, discoverable via the model info — see `get_context_window`), and the machine's RAM/VRAM.
- Timeout posture: owned by the primitive; Ollama has `keep_alive` for residency, not a request timeout.

## J. Alternatives and swap story

- **vLLM** and a **hosted OpenAI-compatible API** are the other two provider engines behind the same six primitives (`generate_text`, `generate_multimodal`, `generate_structured`, `list_models`, `check_model_available`, `get_context_window`). A swap changes `llm/primitives/` only.
- The scripted fake is provider-agnostic by design, which is what makes the swap testable.

## K. Open questions and drift log

- [ ] `engine_version`: client version, server version, model digests, or all three? A recorded model tag without a digest does not identify the weights.
- [ ] `get_context_window` and `check_model_available`: which endpoint (`/api/show` vs `/api/tags`) — verify against the running server before `LLM-09`.
- [ ] The exact error string for a context overflow, so `CONTEXT_OVERFLOW` is detected rather than guessed.
- [ ] Is the call made with `httpx` (installed, 0.28.1) or the `ollama` client package? That choice sets the timeout knob.
- [ ] Context7 ID to cite for Ollama API answers.
- [ ] Drift log: (2026-09-24) client 0.31.1 present at `/opt/homebrew/bin/ollama`; **no server running**, so no endpoint was exercised — every endpoint above is from upstream documentation, not from a live call.
