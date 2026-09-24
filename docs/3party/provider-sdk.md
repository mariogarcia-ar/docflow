# Provider SDK (hosted OpenAI-compatible API) — dossier

> Kind: Python library over a hosted HTTP API
> Processor / seam: `docflow.llm.primitives`
> Status: collecting (2026-09-24)

## A. Identity and provenance

| Field | Value |
|---|---|
| `engine` value in metadata | the provider/API name — `TBD` (the plan says "hosted OpenAI-compatible API") |
| Kind | **SDK** over HTTP; also usable as a client for a local OpenAI-compatible server (do not let that coupling leak past the seam) |
| Upstream | the provider's own API docs; SDK: `openai` (OpenAI Python SDK) |
| Context7 ID | `TBD` |
| Version this page was read against | local **openai 3.13.0**, `httpx` 0.28.1 (the SDK's transport) |

## B. Install, pin and version discovery

- **Install shape:** pip. **Pin home:** `pyproject.toml` (`LLM-09`'s `# TODO: [MVP] real transport` marks the point where this becomes real).
- **Version at runtime:** `importlib.metadata.version("openai")`. There is **no** server version to record for a hosted API; the recorded identity is the **provider name + model id** (plus, where the provider offers it, a response id and a `system_fingerprint`-style field).
- **Credentials:** never in the repository and never in this dossier — `.gitignore` covers `.env`, and this page documents the **shape** of the call, not a key. Absence of a key must be a `DEPENDENCY_ERROR`, not a silent fall back to a local model.
- **Absent / present check:** the SDK import happens **inside** the primitive, so `import docflow.llm.primitives` succeeds with the SDK absent.
- **Suite without it:** the scripted fake; no test performs a network call, and no test asserts a provider's output.

## C. Licence and distribution posture

- The SDK is permissively licensed (Apache-2.0 for `openai-python`, verify). The **service terms, data-retention policy and per-token cost** are the real constraints, and they are a Release-gate decision, not a PoC one.
- Sending documents to a hosted API is a data-handling decision: record what the PoC sends (prompt template + image/prompt payload) before any real document leaves the machine.

## D. Interface contract — the methods we need

| Primitive | SDK call |
|---|---|
| `generate_text` | `client.chat.completions.create(model=..., messages=[...], temperature=..., max_tokens=..., timeout=...)` |
| `generate_multimodal` | same call, with an image content part in the user message |
| `generate_structured` | same call with `response_format={"type": "json_schema", "json_schema": {...}}` (`json_object` is the weaker variant) |
| `list_models` | `client.models.list()` |
| `check_model_available` | membership of `models.list()` |
| `get_context_window` | **not exposed** by the OpenAI surface — `TBD`: declare per model, or drop the primitive for this provider |

**Construction:** `OpenAI(api_key=..., base_url=..., timeout=..., max_retries=...)`. `base_url` is what also makes the SDK reach a local vLLM/Ollama-compatible endpoint — using one shared client for two engines is exactly the coupling to avoid: one transport per primitive.

**Parameters that must be explicit:** `model`, `timeout`, `max_tokens`, `temperature` (and `seed` where supported). The SDK's own defaults are silences we do not want (`no default model, engine or threshold`).

## E. Inputs, outputs and artifact naming

| Field | Value |
|---|---|
| Inputs | JSON request body: `messages`, `model`, `response_format`, sampling parameters |
| Outputs | JSON: `choices[0].message.content`, `usage` (prompt/completion tokens), `finish_reason`, response id |
| Our naming | ours (`llm/` namespace); the provider writes nothing |
| Ordering | n/a (one response per call); the graph order belongs to the orchestrator |
| Encoding | JSON/UTF-8; structured output is only *likely* — schema validation after the call is mandatory |

## F. Determinism levers

| Lever | Enters `processing_key`? |
|---|---|
| `model` id | yes |
| `temperature`, `seed` (where supported), `max_tokens` | yes |
| `response_format` schema | yes |
| Prompt template version | yes |
| Provider-side model updates | **invisible** to us: a hosted model can change without a version bump. This is the strongest argument for the recorded response id/fingerprint and for never calling a provider result "reproducible" |

## G. Failure modes and our error mapping

The SDK raises typed exceptions; each maps to a kind + retryability.

| SDK exception | Our kind | Retry |
|---|---|---|
| `openai.AuthenticationError` | `DEPENDENCY_ERROR` (configuration, not a transient fault) | `NON_RETRYABLE` |
| `openai.PermissionDeniedError` | `PROVIDER_ERROR` | `NON_RETRYABLE` |
| `openai.NotFoundError` (unknown model) | `MODEL_UNAVAILABLE` | `NON_RETRYABLE` |
| `openai.BadRequestError` (context length, bad schema) | `CONTEXT_OVERFLOW` / `SCHEMA_ERROR` — split by the message/parameter, not by the class | `NON_RETRYABLE` |
| `openai.RateLimitError` | `PROVIDER_ERROR` | `RETRYABLE` (honour `retry-after` if present) |
| `openai.APITimeoutError` | `TIMEOUT` | `RETRYABLE` |
| `openai.APIConnectionError` | `PROVIDER_ERROR` | `RETRYABLE` |
| `openai.InternalServerError` | `PROVIDER_ERROR` | `RETRYABLE` |
| `openai.APIStatusError` (other) | `PROVIDER_ERROR` | decide by status |
| response body not JSON | `INVALID_JSON` | `RETRYABLE` |
| response JSON violating the schema | `SCHEMA_ERROR` | `RETRYABLE` |
| `ImportError` (SDK absent) | `DEPENDENCY_ERROR` | `NON_RETRYABLE` |

**Retry policy is ours.** The SDK ships its own retry behaviour (`max_retries`, default 2 — verify for the pinned version); our attempt history lives in `LLMAttempt` and a retry must preserve prior attempts. Two retry layers without a stated owner is a defect.

Error kinds per the subplan's posture list; the `LLMProvider` result/error types land in `llm/primitives/` (`LLM-02`), not in `contracts.py`.

## H. Seam ownership and the double

| Field | Value |
|---|---|
| Owning module | `docflow.llm.primitives` |
| Injection point | `monkeypatch.setattr("docflow.llm.primitives.<primitive>", fake_provider)` |
| What "native-shaped" means | provider-shaped payloads, usage counters and error classes — never our `LLMResult`; the fake is **scripted** and sequence-capable |
| Shared helper | does **not** apply (our symbol is replaced) |
| Other processors | none may reach a provider; the SDK import stays inside the primitive that needs it |

## I. Cost, latency and limits

- **Billed per token** — the only engine in the pipeline with a per-call cost; it is the strongest reason `processing_key`/reuse exists.
- Hard limits are provider-side: context window, output token cap, rate limits (per-minute/per-day), request size including images.
- Timeout and retries are `TODO: [MVP]` in the plan (`LLM-09`), so the place where they are implemented (`client` vs per-call `timeout=`) is still open.

## J. Alternatives and swap story

- Ollama and vLLM are the other two providers behind the same six primitives; the hosted API is the one with a different failure taxonomy (typed exceptions), which is why the mapping table above is the load-bearing part of a swap.
- A swap changes `llm/primitives/` only.

## K. Open questions and drift log

- [ ] Which provider/model for the PoC, and therefore what `engine` / `engine_version` record for a hosted call.
- [ ] Does the SDK's built-in retry stay enabled (and then who owns the timeout), or is it disabled in favour of `LLMAttempt` history?
- [ ] Is `seed` supported for the chosen model? If not, nothing about this provider is deterministic and that must be stated, not assumed.
- [ ] `get_context_window` has no OpenAI-compatible endpoint: declare per model, or mark the primitive unsupported for this provider.
- [ ] Context7 ID to cite for SDK answers.
- [ ] Drift log: (2026-09-24) openai 3.13.0 + httpx 0.28.1 installed; **no call was made** and no key is present. Every fact above is from the SDK's documented surface.
