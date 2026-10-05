# llm-frontier — one call, one schema

The layered registry ([`../llm-local/`](../llm-local/README.md)) asks a model five questions and
carries five answers, because a small local model needs the steps kept apart. A frontier model does
not: its window holds the page, the OCR text and the whole rule book at once, and it follows a long
instruction better than five short ones. This root is that same analysis folded into **one
extraction and one review**.

```
registry/llm-frontier/
  template/extraction/invoice.md              one pass: gate, header, taxes, line of business, quantity
  template/extraction/invoice_vision.md       the same, over a page with no OCR text
  template/review/invoice.md                  one pass over all 27 fields
  template/review/invoice_vision.md           the same, over a page with no OCR text
  schema/extraction/invoice.schema.json       one object, 27 required fields
  schema/extraction/invoice_vision.schema.json  a copy of it — one shape for both media
  schema/review/invoice.schema.json           field_verdicts, minItems 27
  schema/review/invoice_vision.schema.json    a copy of it
```

The prompts are long on purpose: every rule the five steps stated is stated in the one prompt, so
the answer does not depend on which step asked. The `_vision` twin is that same prompt with its
medium section rewritten — the rules are duplicated, because the loader has no include and each
template is a standalone asset. Keep the pair in step: `sed -n`-comparing them should show only the
medium lines.

## What is unified

| Layered registry | Here |
|---|---|
| `invoice_deteccion` gate, then refuse | `comprobante_valido` is a field of the same answer |
| `invoice` — 7 printed fields | same 7 fields, same rules |
| `invoice_desglose` — 10 tax fields | same 10 fields, same rules |
| `invoice_clasificacion` — 4 fields | same 4 fields, same rules |
| `invoice_rubro` — 3 fields, rubro decided outside | the line of business is settled in this pass and picks which quantity is in scope |
| `invoice_vision*` — a second family for the page image | `extraction/invoice_vision` is that family's single prompt, for the page with no OCR text; it is the same answer shape, and its schema is a byte-identical copy |
| 5 extraction calls + reviews of 2 of them | 1 extraction call + 1 review call |

## How to invoke it

The template follows the medium, as in `llm-local`:

| What you have | Extraction | Review |
|---|---|---|
| OCR or native text | `extraction/invoice` | `review/invoice` |
| text **and** the page | `extraction/invoice` + `--image` — the pixels decide where the text garbles | `review/invoice` + `--image` |
| **only** the page (no OCR) | `extraction/invoice_vision` | `review/invoice_vision` |

`extraction/invoice` quotes a document, so it needs the text. `extraction/invoice_vision` carries no
`<doc>` — the attached page *is* the document, which is what makes the no-OCR case work. Provider
recipes (OpenAI, DeepSeek, vLLM, Ollama) live in
[`../llm-local/README.md`](../llm-local/README.md) → *Local* / *Remote* — the flags are the same.

```bash
DOC=tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt
IMG=tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.jpg

# 1 — text only
python scripts/tools/llm.py --assets-dir registry/llm-frontier --out var/run/reading call $DOC \
    --provider openai --model gpt-frontier --task extract \
    --template extraction/invoice --schema extraction/invoice

# 1b — text plus the page: the same template, and the pixels decide where the text garbles
python scripts/tools/llm.py --assets-dir registry/llm-frontier --out var/run/reading-page call $DOC \
    --image $IMG --image-tokens 2800 \
    --provider openai --model gpt-frontier --task extract \
    --template extraction/invoice --schema extraction/invoice

# 1c — no OCR at all: the page IS the document. Its own template and its own --out
python scripts/tools/llm.py --assets-dir registry/llm-frontier --out var/run/reading-pixels call $IMG \
    --image-tokens 2800 \
    --provider openai --model gpt-frontier --task extract \
    --template extraction/invoice_vision --schema extraction/invoice_vision

# 2 — one review of that answer
python scripts/tools/llm.py --assets-dir registry/llm-frontier --out var/run/review call $DOC \
    --provider openai --model gpt-frontier-other --task review \
    --template review/invoice --schema review/invoice \
    --extra proposal=@var/run/reading/invoice.json

# 2c — the review of the no-OCR answer: the page replaces the text
python scripts/tools/llm.py --assets-dir registry/llm-frontier --out var/run/review-pixels call $IMG \
    --image-tokens 2800 \
    --provider openai --model gpt-frontier-other --task review \
    --template review/invoice_vision --schema review/invoice_vision \
    --extra proposal=@var/run/reading-pixels/invoice_vision.json
```

The artifact is named after the schema's last component, so the text answer lands as `invoice.json`
and the pixel answer as `invoice_vision.json`; each call above takes its own `--out`, so a review
never overwrites the answer it audits.

`prompt` renders any of them without spending a token — the cheap way to check an edit:

```bash
python scripts/tools/llm.py --json --assets-dir registry/llm-frontier prompt $DOC \
    --provider openai --model gpt-frontier --task extract \
    --template extraction/invoice --schema extraction/invoice

# the no-OCR one: the page is the input, and no document is stated at all
python scripts/tools/llm.py --json --assets-dir registry/llm-frontier prompt $IMG \
    --image-tokens 2800 \
    --provider openai --model gpt-frontier --task extract \
    --template extraction/invoice_vision --schema extraction/invoice_vision
```

**The review needs no contract.** The criteria are written into the review prompt, so the only extra
context it takes is `<extra:proposal>`. In the layered registry the proposal is audited against the
schema it was extracted under; here the prompt states the rules itself, which is cheaper than
handing the reviewer two documents that say the same thing.

## What differs from `llm-local` — read before mixing answers

- **The gate is inside.** `comprobante_valido` is answered in the same object as everything else, so
  a refused page still produces a complete, schema-valid answer: from `tipo_comprobante` onward
  every field is `null`, and the three working notes say what was seen. There is no early exit and
  no second call — which is the price of one call: a refusal costs the same as a reading.
- **Every data field is nullable, `moneda` included.** The layered schema makes `moneda`
  non-nullable because its reading step only runs on an accepted receipt; here the refusal case has
  to be expressible.
- **`alicuotas_detectadas` is `null` when the page prints no rate**, which is a different answer
  from a printed 0% rate — that one is the code `"0"`. The layered schema has no null to spend here.
- **The quantity follows the line of business decided in the same pass.** `categoria_gasto` is
  settled first, then exactly one of `cantidad_comensales_personas` (Restaurante) and
  `cantidad_litros` (Combustible) is filled. Nothing is deduced: diners never come from the item
  count, litres never from amount ÷ price.
- **`centro_de_costo` is still always `null`** — it is an accounting assignment, not a reading —
  and the review judges it as such: any other value is a `disagree`.
- **Five fields are never adjudicated** by the review: `indicios_detectados`, `notas`,
  `analisis_condicion_iva`, `analisis_evidencia_rubro`, `analisis_rubro_aplica`. Their verdict is
  always `ignored`, so the other 22 carry the audit.
- **Answers are not interchangeable between roots.** The two schemas overlap in field names, not in
  shape. A caller that reads `llm-local`'s readings must not feed them into this review, or the
  reverse.

## Limits

- **The text template still refuses an image alone.** `extraction/invoice` quotes a document, so a
  call whose input is only a page image stops with a `DEPENDENCY_ERROR` before the provider is
  reached: there is no text for `<doc>`, and no empty substitution is made. That is what the
  `_vision` twin exists for.
- **The reverse mistake is silent, and it is the caller's.** A *text* input handed to
  `extraction/invoice_vision` is not refused: the template carries no `<doc>`, so nothing complains,
  no image is attached, and the prompt still reads as if a page were — the document is dropped and
  the model answers about a page it never received. Check the `images` list in the rendered payload
  (the `prompt` subcommand prints it) before spending a token; the vision template is for a page
  input, and only for that.
- **Structured output is the provider's promise, not ours.** `--schema` sends
  `response_format: json_schema`, so the endpoint has to accept it; Anthropic's own API is not wired
  into `PROVIDER_KINDS` and would have to go through its OpenAI-compatibility layer, untested. See
  `../llm-local/README.md` → *Remote*.
