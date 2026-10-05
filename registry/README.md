# Registry — prompts and schemas

The asset root the LLM processor resolves its identifiers against. `--assets-dir registry` is what
makes it the base directory; every example below states it.

## Layout

```
registry/
  manifest.json                              the inventory of what lives here
  template/                                  prompt templates  (see `--template`)
    README.md                                   which fields each prompt extracts, and from which medium
    extraction/invoice.md                       the base reading
    extraction/invoice.reasoning.md             the base reading — reasoning variant
    extraction/invoice_deteccion.md             the fast-fail gate
    extraction/invoice_deteccion.reasoning.md   the fast-fail gate — reasoning variant
    extraction/invoice_desglose.md              the tax breakdown
    extraction/invoice_desglose.reasoning.md    the tax breakdown — reasoning variant
    extraction/invoice_rubro.md                 the line-of-business fields
    extraction/invoice_rubro.reasoning.md       the line-of-business fields — reasoning variant
    extraction/invoice_clasificacion.md         the classification judgement
    extraction/invoice_clasificacion.reasoning.md
                                                the classification judgement — reasoning variant
    extraction/invoice_vision.md                the VLM reading of a page image
    extraction/invoice_vision.reasoning.md      the VLM reading of a page image — reasoning variant
    extraction/invoice_vision_deteccion.md      the fast-fail gate, read from the page image
    extraction/invoice_vision_deteccion.reasoning.md
                                                the fast-fail gate, read from the page image — reasoning variant
    extraction/invoice_vision_desglose.md       the tax breakdown, read from the page image
    extraction/invoice_vision_desglose.reasoning.md
                                                the tax breakdown, read from the page image — reasoning variant
    extraction/invoice_vision_clasificacion.md
                                                the classification judgement, read from the page image
    extraction/invoice_vision_clasificacion.reasoning.md
                                                the classification judgement, read from the page image — reasoning variant
    extraction/invoice_vision_rubro.md          the line-of-business fields, read from the page image
    extraction/invoice_vision_rubro.reasoning.md
                                                the line-of-business fields, read from the page image — reasoning variant
    review/invoice.md                           review of a text extraction
    review/invoice.reasoning.md                 review of a text extraction — reasoning variant
    review/invoice_desglose.md                  review of the tax breakdown
    review/invoice_desglose.reasoning.md        review of the tax breakdown — reasoning variant
    review/invoice_vision.md                    review of a vision extraction
    review/invoice_vision.reasoning.md          review of a vision extraction — reasoning variant
    review/invoice_vision_desglose.md           review of a vision tax breakdown
    review/invoice_vision_desglose.reasoning.md
                                                review of a vision tax breakdown — reasoning variant
    review/general.md                           review of any step, against its own schema
    review/general.reasoning.md                 review of any step — reasoning variant
  schema/                                    response schemas  (see `--schema`)
    README.md                                   the shape of every answer
    extraction/invoice.schema.json
    extraction/invoice_detection.schema.json
    extraction/invoice_desglose.schema.json
    extraction/invoice_rubro.schema.json
    extraction/invoice_clasificacion.schema.json
    extraction/invoice_vision.schema.json
    extraction/invoice_vision_detection.schema.json
    extraction/invoice_vision_desglose.schema.json
    extraction/invoice_vision_clasificacion.schema.json
    extraction/invoice_vision_rubro.schema.json
    review/invoice.schema.json
    review/invoice_desglose.schema.json
    review/general.schema.json
    review/invoice_vision.schema.json
    review/invoice_vision_desglose.schema.json
```

## How an identifier resolves

`--template extraction/invoice` → `<assets-dir>/template/extraction/invoice.md`
`--schema extraction/invoice` → `<assets-dir>/schema/extraction/invoice.schema.json`

A nested identifier is not special: the loader joins the two path components, so `extraction/…` is
just a sub-directory. Nothing is guessed — an identifier that does not resolve is a typed
`DEPENDENCY_ERROR` naming the path it looked for.

Four spellings of placeholder, and no others:

| Placeholder | Replaced with |
|---|---|
| `<doc>` | the request's document text, sanitized |
| `<extra>` | the whole `extra_context` mapping as canonical JSON |
| `<extra:key>` | `extra_context["key"]` alone — a string verbatim, anything else as canonical JSON |
| `<schema>` | the loaded schema as canonical JSON |

Those four are the only spellings the loader *resolves*, and it resolves them in one pass. Any other
angle-bracketed tag is left exactly as it is written, which is what delimits the data: each template
wraps its inputs in XML tags — `<document>`, `<contract>`, `<proposal>`, `<line_of_business>` — and
the placeholder sits inside the pair (`<document>` / `<doc>` / `</document>`). The tag separates
instructions from data for the model, and after substitution nothing but the tag and the request's
own text remains: no banner, no marker line, and no literal `<doc>`.

`<extra:key>` is how a template takes two or more inputs and gives each its own section: it is the
same mapping `<extra>` renders whole, addressed one key at a time. The key must be in
`extra_context` — `review/invoice` carrying `<extra:proposal>` refuses a request that carries no
`proposal`, because a review prompt with an empty proposal block asks a different question. The
review template also carries `<extra:contract>`, and it is the reviewed step's own **schema**
(`--extra contract=@registry/schema/extraction/invoice.schema.json`): the reviewer judges each
proposed value against the same format the extractor's answer had to satisfy, so its verdicts and
its `suggested_value`s obey that format instead of second-guessing it from plausibility. The
schema is the format — fields, types, enums, `required`, `additionalProperties` — and the rules
that decide each value are stated in the prompts, never in the schema's descriptions.

A template that asks for a placeholder the request cannot fill is a `DEPENDENCY_ERROR`, never an
empty substitution: a prompt that reads as if the document were empty is a different question.
Resolution is one pass over the template, so text that *arrives* in `<doc>` is inserted and never
scanned again — a receipt that prints `<extra>` prints it.

## The steps, and the ids you pass

Every pair below was verified against the real loader: template loads, schema validates, and the
document is substituted (no literal `{…}` survives into the prompt).

| Step | `--template` | `--schema` | Role — model |
|---|---|---|---|
| Base reading | `extraction/invoice` | `extraction/invoice` | T1 extract — `gemma3:12b` |
| Detection (gate) | `extraction/invoice_deteccion` | `extraction/invoice_detection` | T1 extract — `gemma3:12b` |
| Tax breakdown | `extraction/invoice_desglose` | `extraction/invoice_desglose` | T1 extract — `gemma3:12b` |
| Classification | `extraction/invoice_clasificacion` | `extraction/invoice_clasificacion` | T1 extract — `gemma3:12b` |
| Line of business | `extraction/invoice_rubro` | `extraction/invoice_rubro` | T1 extract — `gemma3:12b` |
| Review | `review/invoice`, `review/general` | `review/invoice` | T2 review — `deepseek-r1:8b`, T3 review — `qwen3.5:9b`, plus `--extra contract=<step schema>` |
| Vision — base reading | `extraction/invoice_vision` | `extraction/invoice_vision` | V1 extract — `qwen3-vl:8b` |
| Vision — detection (gate) | `extraction/invoice_vision_deteccion` | `extraction/invoice_vision_detection` | V1 extract — `qwen3-vl:8b` |
| Vision — tax breakdown | `extraction/invoice_vision_desglose` | `extraction/invoice_vision_desglose` | V1 extract — `qwen3-vl:8b` |
| Vision — classification | `extraction/invoice_vision_clasificacion` | `extraction/invoice_vision_clasificacion` | V1 extract — `qwen3-vl:8b` |
| Vision — line of business | `extraction/invoice_vision_rubro` | `extraction/invoice_vision_rubro` | V1 extract — `qwen3-vl:8b`, plus `--extra rubro=<line>` |
| Vision — reviews | `review/invoice_vision`, `review/invoice_vision_desglose` | `review/invoice_vision`, `review/invoice_vision_desglose` | V2 review — `ministral-3:8b`, plus `--extra proposal=<step answer>` |

Every step above ships **two** prompts: the identifier in the table (the instruct one) and the same
identifier with a `.reasoning` suffix — `extraction/invoice_deteccion` →
`extraction/invoice_deteccion.reasoning`. Both drive the same schema, and the schema is the one the
table names; every vision step ships its schema under its own name —
`extraction/invoice_vision_desglose` for the breakdown read from the page,
`review/invoice_vision_desglose` for its review — and its prompts state the answer's shape as well.
Only the prompt changes between the pair: the instruct one states the rules, the reasoning one
states the criteria, and the second is meant for a model with `think:true`.

Note the spelling: the **detection** template is `deteccion` (Spanish) while its schema is
`detection` (English). That is the one pair where the two identifiers do not match, and it is easy
to get wrong — a mismatched pair is a `DEPENDENCY_ERROR`, not a silent fallback.

### Instruct and reasoning: one schema, two prompts

Every step that reads or judges text exists twice — an instruct prompt and a reasoning prompt —
and both drive the **same** schema: the schema fixes the shape of the answer, the prompt fixes how
the model is asked to reach it. They are separate files on purpose: flipping `think` over one
prompt is not the same thing as asking the question the other architecture answers. The reasoning
variant of a pair is the same identifier with a `.reasoning` suffix — `extraction/invoice` →
`extraction/invoice.reasoning`, `review/invoice` → `review/invoice.reasoning` — and the two share
the schema.

### The absent value is the real `null`

Every asset answers the absent case with the JSON `null`, never the string `"null"`: the prompts
say `null`, a schema declares the field `["string","null"]`, and an enum that admits an absent
value lists the `null` itself (`tipo_comprobante`, `categoria_gasto`,
`condicion_impositiva_dominante`). Type-array nullability was verified against Ollama 0.31.1
(`gemma3:4b`, `qwen3.5:9b`) with `format` set to these schemas: the GBNF compiler accepts the
union and the model emits a real `null`. `validate_schema` enforces a union `type` like any
other, so the nullable declaration is a rule the answer is checked against, not an annotation.

### `tipo_comprobante` is a five-value alphabet

The class field admits the three printed letters — `"A"`, `"B"`, `"C"` — and the two codes that
are classes in their own right, `"090"` and `"099"`, printed by receipts that do not comply with
RG 1415. The AFIP three-digit codes for the three classes are **not** separate values: `"001"`,
`"006"` and `"011"` are those same classes written differently, so a labelled form such as
`"COD.01"` is answered as the letter it names (`"A"`). There is no preference to weigh between
the two spellings — the value is the letter either way.

| | instruct prompt | reasoning prompt |
|---|---|---|
| Instructions | operational — what to do | criteria — what makes an answer right |
| Ambiguity | resolved by a stated rule | resolved by naming the evidence |
| `think` | `false` | `true` |
| `temperature` | `0` | `0.5–0.7`, per model |
| `num_ctx` | the minimum that holds prompt + document + answer (≈4096 to start) | larger, because the reasoning shares the window (8192+) |
| Latency | low | higher |

Use the instruct prompt when the location of a field is known, the rules are clear, and the run
should be fast and deterministic; use the reasoning prompt when several candidates must be
distinguished, blocks related, or contradictory information weighed. Both extraction variants pass
`--schema extraction/invoice`, and both review variants pass `--schema review/invoice` — the
schema is shared, only the framing of the question changes.

`think: true` together with `format: schema` is not guaranteed by the model or by the Ollama
version: it is verified per template. The expected shape is the reasoning in `message.thinking` and
the final JSON, alone, in `message.content`; the schema constrains that final answer only, and both
reasoning prompts ask for exactly that.

Both prompts of a pair are versioned and evaluated independently, against the same labelled
dataset: per-field accuracy, correct `null`, false positives, invented values, invalid JSON and
latency — never a handful of manual examples.

## How to use them, step by step

The layered extraction is five calls, not one: each step is its own artifact with its own schema,
and the order is the contract. Each role runs its own model, so the reviewer never shares the
extractor's biases: **T1** extracts, **T2** and **T3** review it, and on the vision path **V1**
extracts and **V2** reviews. Only the three provider flags change between transports — the examples below are
Ollama, and every one of them works the same against vLLM or a hosted API by swapping `--provider`
/ `--model` / `--option` (see *Local* and *Remote* below).

```bash
REG=registry
DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt
T1=gemma3:12b     # the extractor: steps 0 to 4
T2=deepseek-r1:8b # the reviewer: step 5
T3=qwen3.5:9b     # the second reviewer: step 6

# 0 — the gate: is this a receipt at all? Run it first and refuse cheaply.
python scripts/tools/llm.py --assets-dir $REG call $DOC \
    --provider ollama --model $T1 --task detection \
    --template extraction/invoice_deteccion --schema extraction/invoice_detection

# 1 — the base reading: the seven printed fields. It takes its own --out because the bench names
#     each step artifact after the schema's LAST path component, and step 5's schema ends in
#     `invoice` too: sharing a directory would let the review overwrite the answer it audits.
python scripts/tools/llm.py --assets-dir $REG --out var/run/reading call $DOC \
    --provider ollama --model $T1 --task extract \
    --template extraction/invoice --schema extraction/invoice

# 2 — the tax breakdown
python scripts/tools/llm.py --assets-dir $REG call $DOC \
    --provider ollama --model $T1 --task desglose \
    --template extraction/invoice_desglose --schema extraction/invoice_desglose

# 3 — the classification judgement
python scripts/tools/llm.py --assets-dir $REG call $DOC \
    --provider ollama --model $T1 --task clasificacion \
    --template extraction/invoice_clasificacion --schema extraction/invoice_clasificacion

# 4 — the line-of-business fields (Restaurante / Combustible only) — <extra:rubro>.
#     The condition itself is the classification step's answer, so a literal is stated here.
python scripts/tools/llm.py --assets-dir $REG call $DOC \
    --provider ollama --model $T1 --task rubro \
    --template extraction/invoice_rubro --schema extraction/invoice_rubro \
    --extra rubro=Restaurante

# 5 — the review: a second model audits step 1's reading — <extra:proposal>, judged against
#     <extra:contract>. KEY=@FILE reads the value from a file, which is how step 1's answer gets
#     here: it was written verbatim as invoice.json (the `<stem>.json` the bench readme describes)
#     under the `--out` step 1 was given. The contract is step 1's schema — the format each
#     proposed value must have — and the reviewer's own criteria say what each value must be.
#     Without it the reviewer loses even that shape, and its suggested_value can break the
#     extraction format — a run once proposed the word "FACTURA" where rule 7 requires the bare
#     letter "A". A template that asks for either
#     placeholder and does not receive it stops at load with a DEPENDENCY_ERROR naming the key.
#     A reasoning reviewer loops instead of answering unless its thinking is switched off: with
#     `think` left unset, deepseek-r1:8b put all 2,000 tokens of a bounded run into the reasoning
#     channel and emitted no content at all, and with no `num_predict` ceiling that trace can only
#     end by filling `num_ctx` — ten minutes for this prompt, well past `timeout`. `think=false` is
#     the brake that makes it stop; the sampling values are the model card's, not a house style, and
#     `num_ctx` plus `timeout` are the room and the time the answer needs.
python scripts/tools/llm.py --assets-dir $REG --out var/run/review call $DOC \
    --provider ollama --model $T2 --task review \
    --template review/invoice --schema review/invoice \
    --extra proposal=@var/run/reading/invoice.json \
    --extra contract=@registry/schema/extraction/invoice.schema.json \
    --option think=false \
    --option temperature=0.6 --option top_p=0.95 --option repeat_penalty=1.0 \
    --option presence_penalty=0.0 --option num_ctx=16384 --option timeout=600

# 6 — a second review: step 5's audit run again with qwen, so the two verdicts can be compared.
#     It takes its own `--out` because both reviews file under the schema's last path component
#     (`invoice`), and one directory would let this verdict overwrite the one it is checking.
#     qwen3.5:9b states `think=false` too, for the same reason step 5 does, and `min_p` keeps the
#     sampling tight; `num_ctx` and `timeout` are step 5's room and time.
python scripts/tools/llm.py --assets-dir $REG --out var/run/review-qwen call $DOC \
    --provider ollama --model $T3 --task review \
    --template review/invoice --schema review/invoice \
    --extra proposal=@var/run/reading/invoice.json \
    --extra contract=@registry/schema/extraction/invoice.schema.json \
    --option think=false --option temperature=0.2 --option min_p=0.05 \
    --option num_ctx=16384 --option timeout=600
```

`--task` is a label: it is recorded in the result and never reaches the model. `--template` and
`--schema` are what select the step. `--extra` is what fills `<extra:KEY>`, and it is repeatable:
`KEY=VALUE` states a value inline and `KEY=@FILE` reads it from a file, so a step that consumes the
previous one is two commands joined by a path. A `--option` value is read as JSON, so
`temperature=0` reaches the provider as the number `0` and not as `"0"` — which Ollama rejects
outright. Those options do not have to be retyped on every command: `llm.py` also reads `.env` at
the repository root, and `DOCFLOW_ASSETS_DIR` plus the `DOCFLOW_LLM_*` values — the window, the
timeout and sampling values such as `temperature`, `top_p`, `min_p`, `repeat_penalty`,
`presence_penalty` and `think` — are what keep them short: `.env.example` names every one of them,
and a run that used the file says so on its `config:` line. The file carries one model's sampling
set, so when two reviewers disagree on it — as steps 5 and 6 do — the second states its own on the
command. Pin the seed when you want a run you can reproduce:

```bash
    --option temperature=0 --option seed=7
```

### Chaining the steps

Steps 4 and 5 read a previous step's answer, and that arrives through `extra_context`. The CLI
carries it with `--extra KEY=@FILE` when the answer is already on disk; the library is what you need
when the value is a live object, as it is in the loop below, and it is the only route that sends
images, which is the whole of the vision path. So the five roles are driven from the library here:

```python
import json
from pathlib import Path

from docflow.llm import LLMInput, process_llm_request

ASSETS = Path("registry")
# The reviewed step's schema is the format the reviewer checks the proposal against; the rules
# that decide each value live in the review template, never in the schema.
CONTRACT = json.loads((ASSETS / "schema/extraction/invoice.schema.json").read_text())
DOC = Path(
    "tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt"
).read_text()
PAGE = Path(
    "tests/fixtures/expected-extraction/dbc07b17-2538-4611-9e51-7e161aaf7ba5.jpg"
)
# One model per role, never the same one twice: the reviewer audits, it does not agree with itself.
T1 = "gemma3:12b"      # reads the text
T2 = "deepseek-r1:8b"  # reviews the text reading
T3 = "qwen3.5:9b"      # reviews the text reading again
V1 = "qwen3-vl:8b"     # reads the page image
V2 = "ministral-3:8b"  # reviews the vision reading
# The provider controls every role shares: the local endpoint, the window, and a timeout well
# above the 30 s default (a review carries the document, the proposal and the schema; a vision call
# carries a whole page as image tokens). The window is stated with the processor's own key, which is
# the one the pre-flight checks *and* the one the Ollama transport asks the daemon for; `temperature=0`
# keeps the extractor deterministic.
OPTIONS = {
    "base_url": "http://localhost:11434",
    "temperature": 0,
    "context_window": 16384,
    "timeout": 300,
}
# What one page image costs, as this caller measured it: the pre-flight adds it to the text estimate,
# and a request carrying images whose cost nobody stated comes back *unmeasured* rather than blessed.
# It is ignored by a call that attaches no image, so one value serves both paths. The two fixture
# pages measured 2 800 and 1 150 tokens against the same 615-token prompt; the larger one is stated,
# because an over-estimate refuses a call that would have fit, and an under-estimate blesses one
# that will not.
IMAGE_TOKENS = 2800
# The reviewers' decoding values are their model cards', not a house style. Each is layered over
# the shared options for its own step. `think=False` is not a decoding value but the brake both
# reviewers need: it is what keeps a reasoning reviewer from spending its whole window in the
# reasoning channel instead of answering, and deepseek-r1:8b loops without it.
DEEPSEEK_OPTIONS = {
    "think": False,
    "temperature": 0.6,
    "top_p": 0.95,
    "repeat_penalty": 1.0,
    "presence_penalty": 0.0,
}
QWEN_OPTIONS = {
    "temperature": 0.2,
    "min_p": 0.05,
    "think": False,
}


def step(
    task,
    template,
    schema,
    *,
    model=T1,
    extra=None,
    document=DOC,
    images=(),
    options=None,
):
    """Run one step of one path."""
    return process_llm_request(
        LLMInput(
            task=task,
            provider="ollama",
            model=model,
            template=template,
            document=document,
            images=list(images),
            extra_context=extra or {},
            schema=schema,
            options=dict(OPTIONS if options is None else options),
            graph=None,
            metadata={"assets_dir": str(ASSETS), "image_tokens": IMAGE_TOKENS},
        )
    )


def field(result, name):
    """Return one field of an answer, refusing anything that did not validate."""
    if not result.schema_valid:
        raise RuntimeError(f"{result.task}: {result.validation_errors}")
    return result.parsed_response[name]


# T1 — the text path: the gate first, then the reading and its two extra scopes.
gate = step("detection", "extraction/invoice_deteccion", "extraction/invoice_detection")
if not field(gate, "comprobante_valido"):
    raise SystemExit("the gate refused the document: it is not a receipt")

reading = step("extract", "extraction/invoice", "extraction/invoice")
breakdown = step(
    "desglose", "extraction/invoice_desglose", "extraction/invoice_desglose"
)
classification = step(
    "clasificacion",
    "extraction/invoice_clasificacion",
    "extraction/invoice_clasificacion",
)

# Step 4 is conditional, and the condition is decided in code, never asked to the model.
categoria = field(classification, "categoria_gasto")
rubro = None
if categoria in {"Restaurante", "Combustible"}:
    rubro = step(
        "rubro",
        "extraction/invoice_rubro",
        "extraction/invoice_rubro",
        extra={"rubro": categoria},
    )

# T2 — the reviewer of the text reading: it audits the proposal against the contract step 1 ran
# under, so a verdict is a rule check and not an opinion.
review = step(
    "review",
    "review/invoice",
    "review/invoice",
    model=T2,
    extra={"proposal": reading.parsed_response, "contract": CONTRACT},
    options={**OPTIONS, **DEEPSEEK_OPTIONS},
)

# T3 — the same reading audited by a second model: a disagreement between the two is information,
# which is why the reviewers are never the same model.
review_qwen = step(
    "review",
    "review/invoice",
    "review/invoice",
    model=T3,
    extra={"proposal": reading.parsed_response, "contract": CONTRACT},
    options={**OPTIONS, **QWEN_OPTIONS},
)

# The vision path runs when the text path fails the checks, not instead of it. V1 reads the page
# image: no document, and its own schema compiles the answer's shape into a grammar.
vision = step(
    "vision_extract",
    "extraction/invoice_vision",
    "extraction/invoice_vision",
    model=V1,
    document=None,
    images=[PAGE],
)

# V2 — the reviewer of that reading: the same page, plus the proposal it audits.
vision_review = step(
    "vision_review",
    "review/invoice_vision",
    "review/invoice_vision",
    model=V2,
    document=None,
    images=[PAGE],
    extra={"proposal": vision.parsed_response},
)
```

The other four steps exist on the vision path with the same shape, and are not spelled out above:
`extraction/invoice_vision_deteccion`, `…_desglose`, `…_clasificacion` and `…_rubro` each take
`model=V1`, `document=None`, `images=[PAGE]` and their own schema, exactly as `vision` does —
`…_rubro` also takes `extra={"rubro": …}` from the caller. The breakdown is judged by
`review/invoice_vision_desglose`, the criteria-bearing reviewer that is the vision counterpart of
`review/invoice_desglose`, with `extra={"proposal": …}` and `extra={"contract": …}`.

The other half of every `extra={…}` is the template. `review/invoice` names each input in its own
section, and the section name is what pairs an input with a placeholder:

```markdown
--- DOCUMENT (OCR) ---
<doc>
--- END OF DOCUMENT ---

--- EXTRACTION CONTRACT (the schema the proposed values must satisfy) ---
<extra:contract>
--- END OF CONTRACT ---

--- PROPOSED EXTRACTION (to review) ---
<extra:proposal>
--- END OF EXTRACTION ---
```

`<doc>` is filled by the `document` argument, `<extra:proposal>` by
`extra={"proposal": reading.parsed_response}`, and `<extra:contract>` by the reviewed step's own
schema; `extraction/invoice_rubro` is the same shape with `<extra:rubro>`. The contract is what
makes the reviewer the extractor's judge rather than a second opinion: it names each field and
declares the format its value must have — the schema is the shape of the answer, and the rules
that decide a value live in the prompts, never in the schema's descriptions. The reviewer's own
criteria (one block per field, mirroring the extractor's rules) then say what each value must be,
so a proposed value is "disagree" when it breaks a criterion or the declared format, not when it
merely looks unlikely — and a `suggested_value` is only valid when it satisfies both. **Every text template opens with the document and states its instructions after
it**, never the reverse: the five T1 steps then share a byte-identical prefix — the same block plus
the same OCR text — and Ollama reuses the KV it cached for that prefix, so the document is tokenized
once per run instead of once per step. The instructions, which differ from step to step, sit after
the document where changing them cannot invalidate what is cached. The cache holds only while
`num_ctx` and `keep_alive` stay the same across the calls: a different window makes Ollama reprocess
the whole document, so state the window once (`.env`, or `--option num_ctx=…` on every command) and
keep it there. A template may name as many elements as it has inputs — two `<extra:key>`
placeholders take two keys of that one mapping, each landing where the template puts it — and a key
the template names and the caller omits is a `DEPENDENCY_ERROR` naming it, before any provider call.
A key the caller passes that the template never names is simply not inserted.

Five things that are not decoration:

- **`metadata["assets_dir"]` is required.** The library has no default asset root, so a request
  without it is a `DEPENDENCY_ERROR` — the same identifier must not resolve differently depending
  on the working directory.
- **`metadata["output_dir"]` is optional, and its absence means "write nothing"**, not "write
  somewhere guessed". Add `Path("var/run")` and the run persists `final_result.json` there.
- **`options` is where the provider controls live** (`base_url`, `api_key`, `timeout`,
  `max_attempts`, `context_window`) — those are consumed by the processor. Every other key in it is
  copied into the provider's request body as a decoding parameter.
- **The vision steps carry the page instead of the document.** They carry it in `images`, leave
  `document` at `None` rather than an empty string, and pass their own `schema` — a step reads pixels
  or it reads text, and a request that pretends to do both is not the step it says it is.
- **Failures come back inside the result**, typed, in `status` and `errors`; nothing is raised
  across the contract. So a caller checks `result.schema_valid` before reading a field — which is
  what `field()` above exists to force.

This sequence was exercised twice, and its ends have since been run live. The six text calls first
ran against the scripted provider double: all six resolve their assets, reach the provider, and each
`extra={…}` key lands in the placeholder that names it — `<extra:rubro>` resolving to `Restaurante`
in the line-of-business prompt and `<extra:proposal>` to the proposed extraction in the review
prompt, with no raw placeholder surviving into either. The two vision calls ran against a live
Ollama on a real receipt image, with `qwen2.5vl:7b` standing in for `qwen3-vl:8b` and
`ministral-3:8b` (those two tags are not pulled on this bench yet): both returned `SUCCESS` — V1 a
reading of the page, V2 a `field_verdicts` array over it.

Steps 1 and 5 have since been run live on the fixture above, through the CLI exactly as *How to use
them* prints them: the base reading returned `SUCCESS` with a schema-valid seven-field answer, and
the review returned `SUCCESS` with a `field_verdicts` array — in 302 s, which is why the block states
a timeout at all. Four of its settings are that run reporting what the harness needs rather than a
preference: the default 30 s gave `TIMEOUT`; Ollama's default context gave an **empty** answer,
`done_reason: length`, the reviewer having reasoned 2,861 tokens before the window closed and
answered nothing; `--option temperature=0` arrived as the string `"0"` — which Ollama refuses with
HTTP 500 — until the tool learned to read an option value as JSON; and one `--out` for both steps let
the review overwrite `invoice.json`, the very answer it was auditing, because the two schemas end in
the same path component. The named placeholders are not among the surprises: `<extra:proposal>`
carried step 1's answer into step 5's prompt intact, and the reviewer contradicted it field by field.

## Local

**Ollama** — native transport (`/api/chat`), no key, default endpoint `http://localhost:11434`:

```bash
python scripts/tools/llm.py --assets-dir registry \
    call tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model gemma3:12b --task extract \
    --template extraction/invoice --schema extraction/invoice
```

Check the model is really there first — `llm.py models` lists what the daemon serves, and the
tag has to match exactly (`gemma3:12b` is a different string from `gemma3`, which resolves to
another size):

```bash
python scripts/tools/llm.py --assets-dir registry \
    models tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt \
    --provider ollama --model gemma3:12b
```

The four tags above are the recommendation, not an inventory: `gemma3:12b` and `deepseek-r1:8b` are
the text path, `qwen3-vl:8b` and `ministral-3:8b` the vision path — pull the ones your daemon does
not serve yet before citing them.

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
    --provider ollama --model gemma3:12b --task extract \
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
- **`llm.py` reaches `extra_context` only through `--extra`.** A value is text: inline, or the
  contents of the file `KEY=@FILE` names — nothing parses it, because `<extra:KEY>` renders a string
  verbatim and a saved answer already is the JSON text. So `review/invoice`, `review/invoice_vision`
  and `extraction/invoice_rubro` — the three steps that consume a previous step's output — run from
  the CLI only when each named key is stated; a key the caller leaves out stops the run at load time
  with a `DEPENDENCY_ERROR` naming it, rather than rendering a proposal block that reads as empty.
  `workflow.py` still fills none of them, and its chain does not read this registry.
- **`llm.py` cannot send images.** It hardcodes `images=[]`, so the vision steps — every
  `extraction/invoice_vision*`, plus `review/invoice_vision*` — are not reachable from the CLI:
  drive them from the library, as in *Chaining the steps* above. `workflow.py`'s `--allow-vlm` /
  `--image-prepare-for-vlm` enable its own chain, and that chain does not read this registry.
- **`$comment` is not allowed in a schema.** The validator enforces a closed keyword set and sends
  the schema to the provider verbatim, where OpenAI's `strict: true` rejects unknown keywords; so
  the design notes that used to live in `$comment` are kept below instead. The enforced set is
  `type`, `required`, `properties`, `additionalProperties`, `items`, `enum` and `minItems`, plus the
  annotations `title`, `description` and `default` — a schema that states anything else is refused
  at load time with `SCHEMA_ERROR`, by name, rather than silently validated under a rule nobody
  applied.

## Schema design notes

These were the `$comment` fields of each schema, moved here when the schemas became loader assets.

**The schema is the format, not the rules.** Every schema here declares structure only — `type`,
`enum`, `required`, `additionalProperties` — and no `description` states how a value is found or
chosen. The rules live in the templates: the extraction prompts hold what each field must be, and
`review/invoice` restates them as the reviewer's own criteria. A rule written into a schema
description would be a second source of truth drifting from the first, and the decoder's grammar
does not read descriptions anyway.

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

Its amounts are strings, and a zero is a zero however it is written: `"0,00"` and `"0"` are the
same value, so a proposal that states a zero where the page prints one — or where a criterion
states one for a tax the page does not show — is agreed with, never corrected into another
spelling. That is the single exception to "as printed": the separator of a zero is a rendering,
not a value. Without it the pair argues with itself, which is what it did — a `disagree` whose
`suggested_value` was the proposal's own `"0,00"`.

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
agree | disagree | uncertain | ignored; a disagree carries a suggested_value. `ignored` marks an
open field the review does not adjudicate (`notas`). A `disagree`
carries a real
correction — the value the document shows, in the field's contract format — and a `suggested_value`
of `null` is for a field that is genuinely not printed: rejecting a printed value without naming
what should stand in its place is `uncertain`, not `disagree`, which is why the template forbids it.
The model supplies only the verdicts, so this file is the MODEL-facing shape. The engine supplies
the caller-facing metadata
(reviewer, extractor_reviewed, producer) itself; a model cannot know who it is or whom it reviews.
Both `reason` and `suggested_value` are `required`, so the model always fills them. `reason` is a
plain string — it is the support for a verdict, and there is always one. `suggested_value` is
nullable (`["string","null"]`): the correcting value on a `disagree`, and the real JSON `null`
otherwise.

**`extraction/invoice_vision`** — The VLM reading of a page image: the same seven printed fields as
`extraction/invoice`, and a byte-for-byte copy of it. The two templates ask for the same fields, so
the copy exists to give the step its own artifact — a registry asset is named after the step that
reads it, the way `extraction/invoice_desglose` is — and to constrain the reading's decoder with a
grammar instead of leaving the answer's shape to prose.

**`review/invoice_vision`** — The verdict vector over the vision reading: `field_verdicts` over the
same seven fields, and a copy of `review/invoice` for the same reason. It carries the weight on this
side, because the template names no field of its own — it judges whatever proposal it is handed —
so this file is the one that says which fields a vision review answers. A vision review of another
step's proposal states that step's own review schema instead.

**The four review schemas that count their own verdicts** — `review/invoice`, `review/invoice_vision`,
`review/invoice_desglose` and `review/invoice_vision_desglose` carry a `minItems` equal to the number
of field names their `field` enum lists (7, 7, 10, 10). The enum closes the *vocabulary* of a review;
`minItems` is what closes its *count*, and the difference was measured: asked the same breakdown
review four times, `deepseek-r1:8b` twice answered 8 and 9 of the 10 verdicts and stopped — a
schema-valid answer that had quietly left fields unadjudicated. `review/general.schema.json` states
no count on purpose: its `field` is unconstrained, so it has none to state.

**The five vision schema copies** — `extraction/invoice_vision_detection`, `…_desglose`,
`…_clasificacion`, `…_rubro` and `review/invoice_vision_desglose` — repeat the same rule: each is a
byte-for-byte copy of the schema of the step it reads, because a vision template asks for the same
fields as its text twin. One shape, two names: the name says which step and which path, and a change
to a step's fields is a change to both of its schemas.

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
`{rubro}` → `<extra:proposal>` / `<extra:rubro>`. The brace style was never resolved by anything —
it would have been sent to the model as the literal string `{text}` in place of the receipt.
