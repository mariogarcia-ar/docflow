# vLLM — dossier

> Kind: local HTTP service (OpenAI-compatible)
> Processor / seam: `docflow.llm.primitives`
> Status: collecting (2026-09-24)

## A. Identity and provenance

| Field | Value |
|---|---|
| `engine` value in metadata | `vllm` (see the open question on what `engine`/`engine_version` mean for a provider call) |
| Kind | **HTTP service**: `vllm serve <model>` exposes an OpenAI-compatible API on a local port |
| Upstream | <https://docs.vllm.ai> — "OpenAI-Compatible Server" |
| Context7 ID | `TBD` |
| Maintainer / cadence | vLLM project (PyTorch Foundation); fast-moving releases |
| Version this page was read against | docs of the 0.8.x/`stable` line; **not installed locally** (no `vllm` binary in the venv) |

## B. Install, pin and version discovery

- **Install shape:** a served process (pip package + a GPU/CPU host), **not** a dependency of `docflow`. `pyproject.toml` cannot pin it; the honest record is a documented supported range plus the served model name. `TBD`.
- **Version at runtime:** `GET /v1/models` returns the served model id(s); the server version comes from `/version` or the startup log (`TBD` — verify). There is no `vllm.__version__` for a remote service.
- **Absent / present check:** no import happens at module level, so the seam survives a machine with no vLLM (and no server) — exactly like Ollama.
- **Suite without it:** the scripted fake (`LLM-03`); no test starts a server.

## C. Licence and distribution posture

- vLLM is **Apache-2.0**; **model weights are licensed separately** — the same caveat as Ollama, and the one that actually constrains distribution.
- A served model is infrastructure we operate, not code we ship.

## D. Interface contract — the methods we need

| Primitive | vLLM endpoint |
|---|---|
| `generate_text` | `POST /v1/chat/completions` (chat template) or `POST /v1/completions` (raw text models) |
| `generate_multimodal` | `POST /v1/chat/completions` with an image content part (vision models) |
| `generate_structured` | `POST /v1/chat/completions` with `response_format={"type": "json_schema", "json_schema": {...}}` — enforced by **guided decoding** at the token level |
| `list_models` | `GET /v1/models` (OpenAI shape) |
| `check_model_available` | membership of `GET /v1/models` |
| `get_context_window` | `TBD` — the OpenAI-compatible surface does not expose it; the serving flag `--max-model-len` is the authority |

**Details that matter**

- **Endpoint choice:** `/v1/completions` applies to text-generation models (`--task generate`) and does **not** support `suffix`; `/v1/chat/completions` needs a chat template. Embeddings and transcriptions endpoints exist but are out of scope.
- **Guided decoding backends:** vLLM's default backend is `auto` (it picks per request); **XGrammar** is the default since ~0.6 (caches well, good for repeated schemas), **Guidance/xgrammar** trade-offs favour dynamic or multi-tenant schemas. `--guided-decoding-backend` can pin it explicitly. A pinned backend is a determinism lever for structured output.
- **`--served-model-name`**: the model id in our request must match the served name, not the local path — a mismatch is a `MODEL_UNAVAILABLE`, not a silent fallback.
- Server flags seen in the docs that touch our behaviour: `--max-model-len` (context), `--chat-template`, `--enable-prefix-caching` (latency only), `--guided-decoding-backend`.
- **Parallel-tool-calling and `user` parameters are ignored** by vLLM's chat endpoint — worth knowing before a request depends on them.
- Timeout is ours (client-side), because the server has no per-request timeout flag for generation.

## E. Inputs, outputs and artifact naming

| Field | Value |
|---|---|
| Inputs | OpenAI-shaped `messages`, `model` (the served name), `response_format`, `temperature`, `seed`, `max_tokens` |
| Outputs | OpenAI-shaped JSON: `choices[].message.content`, `usage` counters, `finish_reason` |
| Our naming | ours (`llm/` namespace); the service writes nothing |
| Ordering | n/a (one response per call) |
| Encoding | JSON/UTF-8; a schema-constrained `response_format` is what makes the payload parseable |

## F. Determinism levers

| Lever | Enters `processing_key`? |
|---|---|
| `model` (the served id) | yes |
| `temperature`, `seed` | yes |
| `response_format` / schema | yes |
| Guided-decoding backend, `--max-model-len`, quantization and GPU | **server-side** — these change output without any request change. They are recorded in metadata, not in the key |
| Server/vLLM version | recorded in metadata |

**Not deterministic by nature:** sampling; and a server reconfiguration (quantization, backend) that no request parameter reveals. Accepted trade-off, never "covered".

## G. Failure modes and our error mapping

| Engine signal | Our kind | Retry |
|---|---|---|
| connection refused / server down | `PROVIDER_ERROR` | `RETRYABLE` |
| HTTP 404 / model id not served | `MODEL_UNAVAILABLE` | `NON_RETRYABLE` |
| HTTP 400 context-length exceeded | `CONTEXT_OVERFLOW` | `NON_RETRYABLE` |
| HTTP 400 malformed schema / unsupported `response_format` | `SCHEMA_ERROR` or `PROVIDER_ERROR` (an **unsupported** feature is not a bad payload — distinguish them) | `NON_RETRYABLE` |
| client-side timeout | `TIMEOUT` | `RETRYABLE` |
| body is not JSON | `INVALID_JSON` | `RETRYABLE` |
| body is JSON but violates the schema | `SCHEMA_ERROR` | `RETRYABLE` |
| HTTP 5xx | `PROVIDER_ERROR` | `RETRYABLE` |
| HTTP client library missing | `DEPENDENCY_ERROR` | `NON_RETRYABLE` |

Error kinds per the subplan's posture list; the `LLMProvider` result/error types land in `llm/primitives/` (`LLM-02`).

## H. Seam ownership and the double

| Field | Value |
|---|---|
| Owning module | `docflow.llm.primitives` |
| Injection point | `monkeypatch.setattr("docflow.llm.primitives.<primitive>", fake_provider)` |
| What "native-shaped" means | provider-shaped payloads and error statuses; the fake is **scripted** (sequence-capable for `LLM-08`) |
| Shared helper | does **not** apply (our symbol is replaced, not an engine namespace) |
| Other processors | none may reach a provider |

## I. Cost, latency and limits

- One call's latency scales with prompt + generation length; `--enable-prefix-caching` reduces repeat-prompt latency (latency only, not output).
- Hard limits: `--max-model-len` (context), GPU memory (batch/parallelism), and any rate limit imposed by the deployment.
- Local/self-hosted: cost is the machine, not a per-call bill.

## J. Alternatives and swap story

- Ollama (local, `/api/*`) and a hosted OpenAI-compatible API are the siblings behind the same six primitives. Because vLLM's surface *is* the OpenAI shape, the provider SDK is often the client for both — which is precisely the coupling the seam must keep out of the rest of the code.
- A swap changes `llm/primitives/` only, and must not change the schema-constrained path: `generate_structured` is the primitive whose behaviour differs most between providers.

## K. Open questions and drift log

- [ ] Where does the **server version** come from (endpoint vs startup log) for `engine_version`?
- [ ] Does our `generate_structured` rely on guided decoding always being available, or does it validate the response afterwards regardless? (Validation is mandatory per the plan; the backend is an optimisation.)
- [ ] Is `seed` honoured identically across providers? If not, "reproducible" must be claimed per provider, not globally.
- [ ] `get_context_window`: read from a health/metadata endpoint, from configuration, or declared per model?
- [ ] Context7 ID to cite for vLLM serving answers.
- [ ] Drift log: (2026-09-24) vLLM is **not installed** in this venv and no server is running — every fact above is from upstream documentation. Nothing was exercised live.
