# Registry — prompts and schemas

The asset root the LLM processor resolves its identifiers against. `--assets-dir registry` is what
makes it the base directory; every example below states it.

## Layout

```
registry/
  manifest.json                              the inventory of what lives here
  template/                                  prompt templates  (see `--template`)
    extraction/invoice.md                       the base reading
    extraction/invoice_deteccion.md             the fast-fail gate
    extraction/invoice_desglose.md              the tax breakdown
    extraction/invoice_rubro.md                 the line-of-business fields
    extraction/invoice_clasificacion.md         the classification judgement
    extraction/vision.md                        the VLM reading of a page image
    review/invoice.md                           review of a text extraction
    review/vision.md                            review of a vision extraction
  schema/                                    response schemas  (see `--schema`)
    extraction/invoice.schema.json
    extraction/invoice_detection.schema.json
    extraction/invoice_desglose.schema.json
    extraction/invoice_rubro.schema.json
    extraction/invoice_clasificacion.schema.json
    review/invoice.schema.json
```

## How an identifier resolves

`--template extraction/invoice` → `<assets-dir>/template/extraction/invoice.md`
`--schema extraction/invoice` → `<assets-dir>/schema/extraction/invoice.schema.json`

A nested identifier is not special: the loader joins the two path components, so `extraction/…` is
just a sub-directory. Nothing is guessed — an identifier that does not resolve is a typed
`DEPENDENCY_ERROR` naming the path it looked for.

Three placeholders a template may carry, and no others:

| Placeholder | Replaced with |
|---|---|
| `<doc>` | the request's document text, sanitized |
| `<extra>` | `extra_context` as canonical JSON |
| `<schema>` | the loaded schema as canonical JSON |

A template that asks for a placeholder the request cannot fill is a `DEPENDENCY_ERROR`, never an
empty substitution: a prompt that reads as if the document were empty is a different question.

## The six steps, and the ids you pass

Every pair below was verified against the real loader: template loads, schema validates, and the
document is substituted (no literal `{…}` survives into the prompt).

| Step | `--template` | `--schema` |
|---|---|---|
| Base reading | `extraction/invoice` | `extraction/invoice` |
| Detection (gate) | `extraction/invoice_deteccion` | `extraction/invoice_detection` |
| Tax breakdown | `extraction/invoice_desglose` | `extraction/invoice_desglose` |
| Classification | `extraction/invoice_clasificacion` | `extraction/invoice_clasificacion` |
| Line of business | `extraction/invoice_rubro` | `extraction/invoice_rubro` |
| Review | `review/invoice` | `review/invoice` |
| Vision | `extraction/vision`, `review/vision` | none — see the limits below |

Note the spelling: the **detection** template is `deteccion` (Spanish) while its schema is
`detection` (English). That is the one pair where the two identifiers do not match, and it is easy
to get wrong — a mismatched pair is a `DEPENDENCY_ERROR`, not a silent fallback.

## Local

**Ollama** — native transport (`/api/chat`), no key, default endpoint `http://localhost:11434`:

```bash
python scripts/tools/llm.py --assets-dir registry \
    call tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1 --task extract \
    --template extraction/invoice --schema extraction/invoice
```

Check the model is really there first — `llm.py models` lists what the daemon serves, and the
tag has to match exactly (`llama3.1:latest` is a different string from `llama3.1`):

```bash
python scripts/tools/llm.py --assets-dir registry \
    models tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model llama3.1
```

**vLLM** — OpenAI-compatible transport, default endpoint `http://localhost:8000/v1`:

```bash
vllm serve Qwen/Qwen2.5-7B-Instruct --max-model-len 8192   # in another shell

python scripts/tools/llm.py --assets-dir registry \
    call tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider vllm --model Qwen/Qwen2.5-7B-Instruct --task extract \
    --template extraction/invoice --schema extraction/invoice \
    --context-window 8192
```

`--context-window` is not optional in practice on anything but Ollama: only Ollama states a window
(it reads `num_ctx` from `/api/show`), and every other provider answers `None`, which the processor
reads as *cannot tell* rather than as *fits*.

## Remote

**OpenAI** — `openai` and `openai_compatible` are the same transport; the endpoint is what differs:

```bash
python scripts/tools/llm.py --assets-dir registry \
    call tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider openai --model gpt-4o-mini --task extract \
    --template extraction/invoice --schema extraction/invoice \
    --option base_url=https://api.openai.com/v1 \
    --option api_key="$OPENAI_API_KEY"
```

**DeepSeek** — OpenAI-compatible wire format:

```bash
python scripts/tools/llm.py --assets-dir registry \
    call tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider openai_compatible --model deepseek-chat --task extract \
    --template extraction/invoice --schema extraction/invoice \
    --option base_url=https://api.deepseek.com/v1 \
    --option api_key="$DEEPSEEK_API_KEY"
```

Before either of those, ask what the endpoint serves — `models` also runs `check_model_available`,
an exact-string membership test, so a near-miss id fails there rather than in your first paying
call:

```bash
python scripts/tools/llm.py --assets-dir registry \
    models tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider openai_compatible --model deepseek-chat \
    --option base_url=https://api.deepseek.com/v1 --option api_key="$DEEPSEEK_API_KEY"
```

**Claude / Anthropic — not wired.** `anthropic` is absent from `PROVIDER_KINDS`, so the name is
refused before any request: this processor speaks `Authorization: Bearer` against
`POST /chat/completions`, while Anthropic's own API is `x-api-key` + `anthropic-version` against
`POST /v1/messages`. Their OpenAI-compatibility layer *may* work via
`--provider openai_compatible --option base_url=https://api.anthropic.com/v1/`, but it is untested
here and nothing guarantees it accepts `response_format: json_schema` — which is exactly what
`--schema` sends.

The `.env.example` at the repository root is the template for these values; the bench still takes
them from flags today.

## Prove it resolves without spending a token

Stop Ollama, or just leave it unstarted, and run a node. If the assets resolve, the failure is at
the provider, not at the asset — and a `request_key` still comes back, which only exists once the
prompt was built:

```bash
python scripts/tools/llm.py --assets-dir registry node <file.txt> \
    --provider ollama --model llama3.1 --task extract \
    --template extraction/invoice --schema extraction/invoice
# errors: PROVIDER_ERROR "ollama could not be reached"        ← assets were fine
#         request_key: c32f1f77…                              ← prompt was built

# …and with an identifier that does not exist:
# errors: DEPENDENCY_ERROR "the template 'x' does not resolve to a readable asset"
#         metadata.path: …/registry/template/x.md
```

## Limits worth knowing

- **`graph`, `fake` and `resume` cannot use this registry.** They run the built-in chain, whose
  descriptor hardcodes `template: "simple_extract"` and `schema: "simple"` per node, and its node
  ids are `classify` / `extract_a` / `extract_b` / `compare` / `validate` / `consolidate`. Against
  `--assets-dir registry` those two identifiers do not exist, so the run stops with a
  `DEPENDENCY_ERROR`. Use `call` and `node` with this registry; the five-step layered extraction is
  not expressible as the PoC's fixed chain today.
- **`--template` / `--schema` / `--task` are ignored on `graph` and `resume`** for the same
  reason: the descriptor's values win.
- **`<extra>` renders `{}` from every caller today.** Both `llm.py` and `workflow.py` pass
  `extra_context={}`, so `review/invoice`, `review/vision` and `extraction/invoice_rubro` — the
  three steps that consume a previous step's output — build a prompt with an empty proposal block.
  They are written and loadable; no caller fills them yet.
- **`llm.py` cannot send images.** It hardcodes `images=[]`, so `extraction/vision` and
  `review/vision` are reachable only through `workflow.py` (`--allow-vlm`,
  `--image-prepare-for-vlm`).
- **`$comment` is not allowed in a schema.** The validator enforces a closed keyword set and sends
  the schema to the provider verbatim, where OpenAI's `strict: true` rejects unknown keywords; so
  the design notes that used to live in `$comment` are kept below instead.

## Schema design notes

These were the `$comment` fields of each schema, moved here when the schemas became loader assets.

**`extraction/invoice`** — The BASE READING step of the layered extraction: the seven printed
fields, and ONLY those. This schema was trimmed to the answer itself, so the four `analisis_*`
working-notes fields the earlier design kept FIRST in the object are gone. The cost is recorded
here rather than left implicit: with no analysis field to settle who the emitter is before the
model commits to cuit_emisor/razon_social_emisor, the emitter-versus-recipient disambiguation now
rests on the prompt's rules alone — and getting that pair wrong was measured on a real receipt that
prints both its own CUIT and the customer's. Grammar-constrained generation (Ollama compiles this
schema to a GBNF grammar, and the model's entire output must satisfy it) now emits exactly these
seven properties, in the order declared. The other four scopes are RESERVED artifacts (`detection`,
`desglose`, `rubro`, `clasificacion`). The two fields that asked *is this a receipt* live in
`invoice_detection.json`, not here. It carries no critical-severity field on purpose —
`importe_total_facturado` moved to the step that holds the arithmetic combination that confirms it.

**`extraction/invoice_clasificacion`** — The CLASSIFICATION step of the layered extraction. It asks
for a JUDGEMENT about the document rather than a reading of it. `analisis_evidencia_rubro` comes
first: it forces the model to name the printed evidence for a line-of-business BEFORE picking one of
the eight enum values, which is the guard against rule 4 (never invent categoria_gasto from the
provider's name alone). `categoria_gasto` also feeds the line-of-business step, so this step must
settle before `invoice_rubro.json` can run. `centro_de_costo` is answered 'null' here on purpose: it
is completed by a later classification step, and the contract keeps the key so a consumer reads one
shape.

**`extraction/invoice_desglose`** — The TAX BREAKDOWN step of the layered extraction. It is a
SEPARATE artifact from `invoice.json` because it is a different domain of knowledge: reading a
printed amount is not the same as understanding Argentine IVA mechanics (net vs gross, why a rate is
discriminated, what 'no gravado' means). `analisis_condicion_iva` comes FIRST on purpose: it forces
the model to settle the emitter's IVA condition and whether rates are discriminated BEFORE it
commits to any amount, which is the actual judgement call in this step (rule 3's Factura C branch).
Grammar-constrained decoding (Ollama's `format` param) generates properties in declaration order, so
this genuinely happens first, not as an afterthought. A receipt that does not discriminate IVA has
nothing to put in the amount fields.

**`extraction/invoice_detection`** — The DETECTION step of the layered extraction — the fast-fail
gate. It is a SEPARATE artifact from `invoice.json` because it answers a different question: not
*what does this document say* but *is this document a receipt at all*. It declares FIRST of the
reserved steps because it is the one step whose answer could refuse the document before the others
ask about its paper. `indicios_detectados` is a scratchpad field, not a printed value: it exists so
an 8B model reasons in-band before committing to the boolean, instead of pattern-matching straight
to true/false. It must come FIRST in the object (grammar-constrained decoding via Ollama's `format`
generates properties in declaration order) so the reasoning happens before the verdict, not after
it. Both remaining fields are DERIVED rather than printed, so neither can earn DOCUMENT_CONTENT: a
boolean has no physical anchor in the paper to be anchored to. `comprobante_valido` is the 23-field
contract's own name for this field; its `false` IS the abstention, so the enum deliberately carries
no `null` escape.

**`extraction/invoice_rubro`** — The LINE-OF-BUSINESS step of the layered extraction: fields that
only apply to one line of business. It runs ONLY when `categoria_gasto` (the classification step)
already says Restaurante or Combustible - the caller decides that in code, so the model is never
asked 'does this apply?'. `analisis_rubro_aplica` is a one-line check, kept deliberately short: this
step is narrow by design (only two possible fields), so a heavy scratchpad would cost more than it
returns on an 8B model. It still comes first so the model confirms which field is in scope before it
decides null vs. a printed number.

**`review/invoice`** — The shape a review verdict must have. A field_verdict's enum is
agree | disagree | uncertain; a disagree carries a suggested_value. The model supplies only the
verdicts, so this file is the MODEL-facing shape. The engine supplies the caller-facing metadata
(reviewer, extractor_reviewed, producer) itself; a model cannot know who it is or whom it reviews.
`reason` and `suggested_value` are plain strings, not nullable (`["string","null"]`): the pipeline's
convention everywhere else is the sentinel string `"null"` for 'no value', never a JSON null, and
mixing the two broke grammar-constrained generation on Ollama (type as an array is poorly supported
by its GBNF compiler). Both are `required` so the model always fills them, using `"null"` as the
not-applicable case.

## Manifest

`manifest.json` lists every asset with its key and its format, and the keys are the paths relative
to this directory — so they match the layout above and the `--template` / `--schema` identifiers
without a translation step. It is an inventory, not a loader input: the loader resolves an
identifier against `template/` and `schema/` directly.

---

## Notes on what changed to make this the asset root

The registry was restructured from `prompts/` + `schemas/` (`.txt` / `.json`) to `template/` +
`schema/` (`.md` / `.schema.json`), because the loader resolves exactly those two directory names
and those two suffixes.

Templates were also rewired to the loader's placeholders: `{text}` → `<doc>`, and `{proposal}` /
`{rubro}` → `<extra>`. The brace style was never resolved by anything — it would have been sent to
the model as the literal string `{text}` in place of the receipt.
