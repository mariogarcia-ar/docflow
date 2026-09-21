# Finding — how one Ollama call is built

| Field | Value |
|---|---|
| Written | 2026-09-21 |
| Subject | `src/docflow/adapters/ollama.py` (K5, `llm.local`) and `src/docflow/adapters/ollama_results.py` |
| Method | the five endpoints read live against `ollama 0.31.1`, plus an HTTP-body capture of each prompt/schema condition (`var/probe/conditions.py`) |
| Status | **Explanation** — a description of the mechanism as implemented and measured, not a defect report |
| Affects | every caller of K5: `flow/extract.py` (lanes A and B), `scripts/poc-flow-v2/myllmlocal.py`, `scripts/poc/batch_llm_local.py` |

This document answers one question: **what exactly does the adapter send, and what does
it keep?** Everything below is either read from the module or measured against the
running runtime. Where the code and a measurement disagree, the measurement is
reported.

---

## 1. The five endpoints

The transport is `httpx` speaking Ollama's HTTP API directly, not the `ollama` package.
The adapter uses five endpoints, and each one answers a question the others cannot:

| Endpoint | Method | Used by | Carries |
|---|---|---|---|
| `/api/tags` | GET | `_catalogue` | the **catalogue**: every model, with its `digest`, `details` and `capabilities` |
| `/api/show` | GET | *(declared, unused)* | one model in more detail — **and no digest** |
| `/api/version` | GET | `_runtime_revision` | the runtime's build string |
| `/api/ps` | GET | `_effective_context_length` | the models **currently loaded**, with their loaded window |
| `/api/chat` | POST | `_generate`, `warm` | the generation itself |

`/api/show` is declared as `_PATH_SHOW` and never called. That is deliberate and not
dead code: it is the endpoint an implementer reaches for first, and the note on
`_catalogue` exists to say why it cannot be used for identity — verified live,
`/api/show` answers with `capabilities`, `details`, `license`, `model_info`,
`modelfile`, `modified_at`, `parameters`, `template` **and no `digest` key at all**.

`/api/tags` is therefore the **only** endpoint that reports a digest. That asymmetry is
what makes identity resolution a catalogue read rather than a model read.

One generation touches **three or four** endpoints: `/api/tags` (identity), `/api/chat`
(the answer), `/api/ps` (the loaded window, read *after*), and `/api/version` once per
adapter instance (cached in `_adapter_revision`).

---

## 2. The request body, field by field

Every generation goes through one `_generate`, so there is exactly one request shape:

```json
{
  "model": "deepseek-r1:1.5b",
  "messages": [
    {"role": "user", "content": "…the prompt, with the document substituted…"}
  ],
  "stream": false,
  "format": {"type": "object", "properties": {"…": {}}},
  "options": {"num_ctx": 8192}
}
```

### `model`

A **string the caller names**, passed through untouched. It is never derived, never
defaulted, never resolved to a tag. A name that is well-formed but absent locally
produces `model_not_pulled` with `ollama pull <name>` in the message; a name the
catalogue matches nothing for produces the same. Nothing resolves to a working model by
accident.

The name is matched **with and without its tag** (`_digest_of`), because `qwen2.5` and
`qwen2.5:latest` are the same model to the runtime and only one of them appears in the
catalogue. The resolved **digest** — not the name — is what the evidence records, and
the digest is re-checked on every call: a `pull` under a moving tag changes the bytes
the name resolves to, and the change surfaces as `revision_changed: true` rather than as
a silent substitution.

### `messages`

**Always exactly one message, always `role: "user"`.** There is no `system` role
anywhere in the adapter, and no conversation history: K5 has no session concept. The
prompt string is the whole of `content`.

For a vision call the same single message gains an `images` key holding base64 strings:

```json
{"role": "user", "content": "…", "images": ["iVBORw0KG…"]}
```

`_encode_image` accepts a `Bytes` value (reading `.data`), raw `bytes`, or anything
`bytes()` accepts. Payload extraction happens before encoding, so a `Bytes` and the same
bytes are the same image.

### `format`

This is the field that carries **the schema**, and it deserves its own section — see §3.

### `options`

The sampling parameters. **The port has no options parameter**: `LlmEngine.structured`
takes `(model, prompt, schema)` and nothing else. So the only dial is the environment,
read at call time by `_options_from_environment`:

| Environment variable | Forwarded as |
|---|---|
| `DOCFLOW_OLLAMA_TEMPERATURE` | `temperature` |
| `DOCFLOW_OLLAMA_TOP_P` | `top_p` |
| `DOCFLOW_OLLAMA_TOP_K` | `top_k` |
| `DOCFLOW_OLLAMA_SEED` | `seed` |
| `DOCFLOW_OLLAMA_NUM_PREDICT` | `num_predict` |
| `DOCFLOW_OLLAMA_NUM_CTX` | `num_ctx` |

Anything outside `_FORWARDED_OPTIONS` is **dropped, not refused** — the runtime owns its
own option vocabulary, and refusing an unknown name would couple this adapter to
whatever the runtime adds next.

Three measured details a reader should not have to rediscover:

- **Everything is coerced.** A value containing `.` becomes `float`, otherwise `int`
  (verified: `NUM_CTX=0.5` → `0.5`).
- **A malformed value is ignored, not fatal.** Verified: `NUM_CTX=abc` and `NUM_CTX=''`
  produce `{}` — no options at all — rather than a failure. The comment says why: a typo
  in an optional tuning value must not make the runtime unusable.
- **No range validation.** Verified: `NUM_CTX=-1` is forwarded as `-1`. The adapter does
  not second-guess the runtime's own limits.

`num_ctx` is the one option with a *reason* rather than a preference: without it the
runtime applies its own window (measured, 4096 on this machine), and a generation cut by
that window could not be told from one cut by a window the caller chose.

### `stream`

Always `false`. The adapter reads one JSON object, not an event stream. `judge` is the
only operation that appends anything to the prompt — `JSON_ANSWER_INSTRUCTION`, from
`_json_object.py`, because a rubric asks for a *judgement* rather than a *shape* and a
model left free to reply in prose will do exactly that.

---

## 3. `format` — the schema as grammar

**`format` is never omitted.** When a caller supplies no schema, the adapter still sends
one:

```json
"format": {"type": "object"}
```

An empty schema is not the same as no schema: it constrains generation to *an object*
and nothing more. This is why a caller cannot tell "the schema was empty" from "the
schema was satisfied" by looking at the answer, and why the difference between the two
conditions in §5 is a difference of **enforcement**, not of mechanism.

The schema reaches the runtime as the grammar of the answer. What that means in
practice — all measured in §5:

- A key the schema does not declare **cannot appear** in the output.
- A value outside a declared `enum` **cannot be emitted**.
- A key the schema *does* declare can be filled with a **plausible wrong value**: the
  grammar constrains form, never truth.

That last point is the whole reason the schema is a separate artifact from the prompt.
The prompt decides *what to ask and about which paper*; the schema decides *what shape
the answer must have*. Neither substitutes for the other.

---

## 4. The response, and what is recorded

The adapter reads five things out of the response body:

| Response field | Recorded as |
|---|---|
| `message.content` | parsed as the answer; the **raw string** is kept as `observed["raw_completion"]` |
| `done_reason` | `observed["done_reason"]` — `stop` or `length` |
| `prompt_eval_count` | `measurements["prompt_tokens"]` — the tokens the runtime **actually evaluated** |
| `eval_count` | `measurements["completion_tokens"]` |
| `total_duration` | `measurements["total_duration_ms"]` (nanoseconds → ms) |

Plus one thing the body does **not** carry: `measurements["prompt_characters"]`, computed
locally as `len(prompt) + sum(len(str(i)) for i in images)`.

That pair of numbers exists because of a measured silent failure — see §6.1.

The answer itself must be a JSON **object**. `load_object` is shared with K6 and enforces
exactly that: a completion that is valid JSON but not an object is refused as
`unsupported_format`, because such an answer cannot satisfy a schema and reporting it as
an absence would make it indistinguishable from a model that said nothing.

---

## 5. What each prompt/schema condition actually earns

Measured on one fixture (`tests/fixtures-txt/casos/66cd35e9-…-4c7e7c39d6b0.txt`), the
registry's own prompt (`registry/prompts/extraction/invoice.txt`) and schema
(`registry/schemas/extraction/invoice.json`), 3 runs each, against a hand-transcribed
ground truth of 7 fields.

| Condition | `format` sent | 1.5B | 4B |
|---|---|---:|---:|
| prompt only | `{"type": "object"}` | 2/7 | 6/7 |
| prompt + schema | the full schema | 2/7 | 6/7 |
| **schema only** | the full schema | **0/7** | **1/7** |

Three things this table says, none of them obvious:

**With a capable model, prompt-only and prompt+schema score the same.** `gemma3:4b` reads
the seven keys out of the prompt's `Claves:` list and answers them correctly either way.
The difference is not the *count* — it is the **class of failure** the condition permits.
Without a schema, `deepseek-r1:1.5b` answers `{"type_comprobante": "ARS", "razon_social
emisor": "ROSARIOS"}`: keys the prompt never asked for, one of them with a space. No
downstream code can flag that as an error, because nothing compares the keys against a
list.

**Schema-only is not the strict case — it is a fiction generator.** With no prompt, two
things vanish at once: **the document** (`{text}` lives in the prompt) and **the rules**
(*"do not invent any absent or illegible value"* lives in the prompt). What survives is
grammar alone: the model is asked for *an object with these keys* with no subject. With
`gemma3:4b`, which scores 6/7 in the other two conditions:

```json
{"tipo_comprobante": "B", "razon_social_emisor": "Tornatura del Producto",
 "cuit_emisor": "30-67891-45-0", "fecha_emision": "2023-10-26",
 "nro_comprobante": "456789",
 "notas": "Solicitud de reintegro por producto defectuoso."}
```

Not one of those values is in the document. It is a complete, internally coherent,
perfectly-formed invoice. This is the `B.10` failure mode in its purest form: the
dangerous output is not the noise, it is the **plausible value**.

Schema-only is unreachable from `myllmlocal.py` (`--prompt` is required, and a template
without `{text}` is refused as a usage error). The adapter permits the shape; no client
asks for it. It was measured by calling `OllamaEngine().structured("", SCHEMA)` directly.

**Corollary for the artifacts: enriching the schema with `description`s makes it worse.**
Adding Spanish descriptions to the four fields that carried none made `deepseek-r1:1.5b`
return **the description text as the value** (`"fecha_emision": "DD/MM/AAAA"`,
`"notas": "OBSERVaciones (o null)"`). The same failure the `enum`-in-prose defect produced
(`cierre-circuitos.md` R4). Explanations belong in the **prompt**; the schema carries
shape.

---

## 6. The three silent failures

Each of these was measured, and each is why a specific piece of code exists. None of them
raises an error on its own.

### 6.1 An oversized prompt is cut without a signal

The runtime truncates a prompt too large for `num_ctx` **and reports nothing**. In the
adapter's own recorded measurement, one ~2,429-token prompt with room left to answer came
back evaluated at **130** tokens under `num_ctx: 256` with `done_reason: "stop"` — no
failure, a confident answer to a question partly discarded. The same prompt at
`num_ctx: 1024` evaluated 514 tokens and reported `length`, so **whether the cut surfaces
at all depends on the window**.

This is why the adapter records **both** `prompt_tokens` (evaluated) and
`prompt_characters` (sent). Deciding it inside the adapter would need a tokenizer, and a
characters-per-token constant would be the kernel inventing a threshold — which `prd.md`
FR-15 forbids. So the two facts are recorded and left where a caller can see them
disagree.

The same failure has a second face: a prompt large enough relative to `num_ctx` is
refused outright rather than truncated. Verified live with a 4,005-token prompt against
`num_ctx: 256`:

```json
HTTP 400
{"error":"{\"error\":{\"code\":400,\"message\":\"request (4005 tokens) exceeds the
 available context size (256 tokens), try increasing it\",…
 \"type\":\"exceed_context_size_error\",\"n_prompt_tokens\":4005,\"n_ctx\":256}}"}
```

Note the shape: the message is **nested twice, with the inner document JSON-encoded as a
string**. That is why `ollama_results.runtime_complaint` unpeels the outer object *only
far enough to get a readable sentence* and interprets nothing. It is also why **`400` is
`unsupported_format` and not `model_not_pulled`**: a refused request is a fact about *this
request* — usually an oversized prompt — for a model whose `capabilities` call has just
succeeded. Reporting it as *the name is not known* sends a reader looking for a missing
model that is not missing.

### 6.2 A truncated completion parses cleanly

The runtime signals a cut with `done_reason: "length"`. Verified live with
`num_predict: 4` → `done_reason: length`, `eval_count: 4`.

The danger is the interaction with JSON: a completion severed after the last complete
field **parses cleanly**, which is exactly how a partial answer is mistaken for a whole
one. So the truncation check happens **before** `load_object`, and the raw completion is
preserved on the evidence either way. A truncated call is distinguishable from a
complete one without re-invoking the model.

### 6.3 A model tag is a moving pointer

`qwen2.5` is a moving tag: pulling it again mid-run changes the thing that produced every
later value, and nothing in the output would say so. The digest is read from `/api/tags`,
recorded at first use, and compared for the rest of the run — so a swap becomes a
**difference** (`revision_changed: true`) rather than a surprise.

A second, quieter version of the same problem: **the loaded window is not the declared
window.** A model whose metadata declares 8192 loads under 4096 when the caller names no
`num_ctx`. The loaded value is only in `/api/ps`, and only for **loaded** models — so the
adapter reads it **after** the call, never before (a pre-call read reports the previous
call's window; verified: preloaded 4096, asked 1024, pre-call read said 4096). `None`
means *not currently loaded*, and the declared value is deliberately **not** substituted
for it, because the two answer different questions.

---

## 7. What the adapter refuses to do

These are design obligations, not omissions. Each is enforced by a test or an AST scan.

- **No default or fallback model.** An unknown name produces `model_unknown`; an absent
  one produces `model_not_pulled` with the remedy in the message. Nothing resolves to a
  working model by accident.
- **No secret in a parameter.** No signature carries an API key; the endpoint host comes
  from `DOCFLOW_OLLAMA_HOST` (default `http://127.0.0.1:11434`), because a local
  runtime's address is an operational setting and a credential is not.
- **No retry until two answers agree.** Attempts are counted and reported
  (`observed["attempts"]`); the pattern is made visible rather than forbidden by hope.
- **No confidence aggregation.** A sampled kernel's *value* is not assertable — the
  **evidence** is. Every success returns `Evidence` with the identity terms, the
  measurements and the observations, and nothing that reads like a score.
- **No threshold invented locally.** Where the runtime's behaviour needs a number the
  adapter does not have (a tokenizer, a chars-per-token ratio), it records the inputs and
  declines to decide.

---

## 8. What this document does *not* say

It does not say which model to use. The measurement in §5 shows `gemma3:4b` scoring 6/7
where `deepseek-r1:1.5b` scores 2/7 on the same prompt — but `flow/config.py`'s
`TEXT_MODEL_A` is set to the 1.5B, and whether that is a budget, latency, or a leftover
default is a **decision the configuration has not recorded**. The docstring in
`ollama.py` says a model is never substituted from anywhere; it says nothing about which
one a caller should name.

It does not say the schema should hold the prompt, or the prompt the schema. §5 is the
measurement that both directions of that idea make things worse: embedding the schema in
the prompt reintroduces the `enum`-as-prose defect, and embedding explanations in the
schema makes the model return them as values.

It does not cover `frontier.py` (K6). The two adapters share one rule — `load_object` —
and nothing else: they differ in transport, reason codes, response fields and truncation
signal, which is why the shared rule lives in `_json_object.py` and the rest does not.
