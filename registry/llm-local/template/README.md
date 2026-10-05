# Templates — which fields each prompt extracts, and from which medium

Every template in this folder is one question asked of one model. This README answers, per
template, two things: **which fields the answer carries** and **which medium the answer is read
from**. The *format* of an answer — types, enums, `required`, `additionalProperties` — is the
schema beside it (`../schema/…`), never this file; where this file and a schema disagree, the
schema wins.

The step order, the roles and the models are in [`../README.md`](../README.md); this file is the
field-and-medium index, and [`../schema/README.md`](../schema/README.md) is the shape-and-keyword
index of the schemas those fields are declared in.

## The two media

| Medium | What the model receives | Template family | Document side |
|---|---|---|---|
| **text** | the page's text, substituted into `<doc>` | `extraction/invoice…` — no `_vision` in the identifier | the request's document text — OCR output or a native text layer, chosen upstream by source selection |
| **page image** | the page image itself, attached by the call | `extraction/invoice_vision…` | the pixels — a photograph, a scan or a render |

`_vision` in the identifier is the only marker, and it is decisive: a text template quotes the
document with `<doc>`, a vision template carries no `<doc>` at all because *the image is the
document*. Mounting an image on a text template, or handing a text document to a vision template,
is a typed `DEPENDENCY_ERROR` — never an empty substitution, because a prompt that reads as if the
page were blank asks a different question.

Both families carry the same steps, under the same step suffixes, over the **same fields**:

| Step | Text template | Image template |
|---|---|---|
| Detection (gate) | `extraction/invoice_deteccion` | `extraction/invoice_vision_deteccion` |
| Base reading | `extraction/invoice` | `extraction/invoice_vision` |
| Tax breakdown | `extraction/invoice_desglose` | `extraction/invoice_vision_desglose` |
| Classification | `extraction/invoice_clasificacion` | `extraction/invoice_vision_clasificacion` |
| Line of business | `extraction/invoice_rubro` | `extraction/invoice_vision_rubro` |

The match is by **suffix**, and each half has its own schema of the same shape — one schema for the
text reading and one for the image reading. The one spelling that does not match is the gate: the
template is `deteccion` (Spanish), its schema is `detection` (English).

## The fields, step by step

`Text` and `Image` name the template that answers the field; the schema is `../schema/extraction/`
plus the identifier shown. Types are the schema's; `string | null` means the schema admits a real
JSON `null`, which is the answer for a value the document does not print.

### Detection — is this a receipt at all?

Template `extraction/invoice_deteccion` (text) / `extraction/invoice_vision_deteccion` (image) ·
schema `extraction/invoice_detection` · run first, so a non-receipt is refused cheaply.

| Field | Type · values | Meaning |
|---|---|---|
| `indicios_detectados` | `string` | a terse line naming the markers found (date, amount, items, emitter, CUIT, "factura"/"ticket"/"comprobante"), or what is missing — the evidence, written first |
| `comprobante_valido` | `string` · `"true"` \| `"false"` | whether the page records a commercial transaction (invoice, ticket, boarding pass, receipt, credit/debit note) |
| `motivo_rechazo` | `string \| null` | why the page was refused; non-null only when `comprobante_valido` is `"false"` |

### Base reading — the seven printed fields

Template `extraction/invoice` (text) / `extraction/invoice_vision` (image) ·
schema `extraction/invoice`.

| Field | Type · values | Meaning |
|---|---|---|
| `tipo_comprobante` | `string \| null` · `"A"` \| `"B"` \| `"C"` \| `"090"` \| `"099"` \| `null` | the class printed in the header; the bare letter, or the two classes that are codes of their own (`090`, `099`). A labelled form of a class code (`COD.01`) is answered as its letter (`A`) |
| `razon_social_emisor` | `string \| null` | the emitter's name, from the header block only — never the recipient's |
| `cuit_emisor` | `string \| null` | the emitter's CUIT, `XX-XXXXXXXX-X`, from the emitter block only, cut at the first character that is not a digit or a hyphen |
| `fecha_emision` | `string \| null` | the issue date exactly as printed, `DD/MM/YYYY` — not a due date, not a billing period |
| `nro_comprobante` | `string \| null` | the receipt number printed beside its own label, hyphen included when printed — not the point of sale, not the CAE, not the class |
| `moneda` | `string` · `"ARS"` \| `"USD"` | the only non-nullable field of the reading: `"USD"` when the document says `USD`/`U$S`, otherwise `"ARS"` |
| `notas` | `string \| null` | real observations printed on the receipt; an **open field** the review never adjudicates |

Where in the document the reading looks, as the template states it — this is the field-level
"medium" of the text path:

- **EMITTER** — the header block, above `Cliente:`. The only source for `razon_social_emisor` and
  `cuit_emisor`.
- **RECIPIENT** — the `Cliente:` block. It has its own name and CUIT and is *not* the emitter; a
  receipt often prints both CUITs, so the recipient's CUIT never feeds `cuit_emisor`.
- **TOTALS** — subtotal, IVA, total and any `Saldo Cta Cte`. A running-account balance is not an
  observation and does not belong in `notas`.

### Tax breakdown

Template `extraction/invoice_desglose` (text) / `extraction/invoice_vision_desglose` (image) ·
schema `extraction/invoice_desglose`.

| Field | Type · values | Meaning |
|---|---|---|
| `analisis_condicion_iva` | `string` | a terse note, written first: what IVA condition the emitter declares and whether the document discriminates IVA at all. An **open field** the review never adjudicates |
| `subtotal` | `string` | the net amount, or the total when the document does not discriminate |
| `iva` | `string` | the IVA *amount* in pesos, never the rate; `"0"` when IVA is not discriminated |
| `impuestos_internos` | `string` | the printed amount, or `"0"` |
| `percepcion_iibb` | `string` | the printed amount, or `"0"` |
| `otros_impuestos` | `string` | the printed amount, or `"0"` |
| `monto_no_gravado` | `string` | the printed amount, or `"0"` — non-taxed, which is not the same as exempt |
| `importe_total_facturado` | `string` | the total as printed, with no adjustments |
| `condicion_impositiva_dominante` | `string \| null` · `Responsable Inscripto` \| `Monotributo` \| `Exento` \| `No Categorizado` \| `Consumidor Final` \| `null` | the emitter's condition before IVA — the legend, not the rate |
| `alicuotas_detectadas` | `string` | the printed IVA rates with their AFIP codes — `0`, `2_5`, `5`, `10_5`, `21`, `27` — separated by `\|`. The rates, never the amounts |

Every amount is a **string**, returned exactly as printed (`"12.345,60"` stays `"12.345,60"`); the
one exception is a zero, which is the same answer however it is spelled (`"0"`, `"0,00"`, `"0.00"`).

### Classification — the line of business

Template `extraction/invoice_clasificacion` (text) / `extraction/invoice_vision_clasificacion`
(image) · schema `extraction/invoice_clasificacion`.

| Field | Type · values | Meaning |
|---|---|---|
| `analisis_evidencia_rubro` | `string` | a terse note, written first: which printed items or concept point to a line of business, as distinct from the provider's name — an **open field** the review never adjudicates |
| `categoria_gasto` | `string \| null` · `Restaurante` \| `Supermercado` \| `Hospedaje` \| `Combustible` \| `Movilidad/Pasajes` \| `Peajes` \| `Herramientas` \| `Otros` \| `null` | the emitter's line of business, from the printed items — never from the provider's name |
| `descripcion` | `string` | a short lowercase phrase of what was bought or rendered, taken from the printed line items |
| `centro_de_costo` | `string \| null` | **always `null` at extraction** — a later classification step fills it; it is not a reading of the receipt |

### Line of business — the conditional quantity

Template `extraction/invoice_rubro` (text) / `extraction/invoice_vision_rubro` (image) ·
schema `extraction/invoice_rubro` · carries `<extra:rubro>`, the settled line of business.

| Field | Type · values | Meaning |
|---|---|---|
| `analisis_rubro_aplica` | `string` | one short line, written first: which of the two quantity fields is in scope, and whether that datum is printed |
| `cantidad_comensales_personas` | `string \| null` | the number of diners, **only** when the line of business is `Restaurante`; otherwise `null`. As printed, without the unit |
| `cantidad_litros` | `string \| null` | the litres, **only** when the line of business is `Combustible`; otherwise `null`. As printed, without the unit |

Exactly one of the two quantity fields is in scope, and the line of business that decides it is
settled outside this step (it is the classification step's answer, passed as a literal). Neither
quantity is ever deduced — not diners from the number of items, not litres from amount ÷ price.

## The reviewers — no field is extracted, every field is judged

The review templates extract nothing: their answer is a verdict per field of a **proposal** another
model produced. The proposal, and the contract the proposal had to satisfy, arrive as extra
context; the document arrives as text or as the page image, exactly as in the extraction family.

| Template | Medium judged | Proposal fields judged | Extra inputs | Schema |
|---|---|---|---|---|
| `review/invoice` | document text | the 7 base-reading fields | `contract`, `proposal` | `review/invoice` |
| `review/invoice_desglose` | document text | the 10 tax-breakdown fields | `contract`, `proposal` | `review/invoice_desglose` |
| `review/invoice_vision` | page image | the 7 base-reading fields | `proposal` | `review/invoice_vision` |
| `review/invoice_vision_desglose` | page image | the 10 tax-breakdown fields | `contract`, `proposal` | `review/invoice_vision_desglose` |
| `review/general` | document text | any step's fields | `contract`, `proposal` | `review/general` |

`review/general` is the schema-agnostic reviewer: `field` is any string and the check is run against
whatever contract it is handed. The other four pin `field` to an enum — the exact field names of the
step they audit — and a `minItems` equal to that step's field count.

The answer shape, identical in all five schemas:

| Field | Type · values | Meaning |
|---|---|---|
| `field_verdicts` | `array` | one object per field of the proposal, same names, none added and none omitted |
| `field_verdicts[].field` | `string` | the key's name, as in the proposal |
| `field_verdicts[].verdict` | `string` · `agree` \| `disagree` \| `uncertain` \| `ignored` | `disagree` requires a value the document shows that should stand in place; `uncertain` when the document does not settle it |
| `field_verdicts[].reason` | `string` | one short line supporting the verdict |
| `field_verdicts[].suggested_value` | `string \| null` | the correction when the verdict is `disagree`; otherwise `null` |

An **open field** is never adjudicated: its verdict is always `ignored` and its `suggested_value`
`null`. Today that is `notas` in the base reading and `analisis_condicion_iva` in the tax breakdown;
the rest of the working notes (`analisis_evidencia_rubro`, `analisis_rubro_aplica`) are not
adjudicated by a dedicated reviewer, because no review template is shipped for those two steps.

Note on `review/invoice_vision`: its prompt describes the verdict object as `field` + `verdict` +
`suggested_value`, while `review/invoice_vision.schema.json` — the format the answer is validated
against — also requires `reason`.

## Instruct and reasoning: the same fields, twice

Every template ships with a `.reasoning` twin (`extraction/invoice` →
`extraction/invoice.reasoning`). The pair drives **one** schema and answers **one** field set; only
the framing changes — the instruct prompt states the rules, the reasoning prompt states the criteria
and is meant for a model with `think: true`. Which of the two is in the answer's name, not in the
fields: this README's tables hold for both.

## The placeholders a template needs filled

The medium a template reads is also what it must be handed, and a template that asks for a
placeholder the request cannot fill stops at load with a typed `DEPENDENCY_ERROR` naming the key:

| Placeholder | Where it appears | What must be supplied |
|---|---|---|
| `<doc>` | every text template | the request's document text |
| (none) | every `_vision` template | the page image, attached to the call |
| `<extra:rubro>` | `extraction/invoice_rubro`, `extraction/invoice_vision_rubro` | the settled line of business (`Restaurante` / `Combustible` / …) |
| `<extra:proposal>` | every review template | the answer being audited |
| `<extra:contract>` | `review/invoice`, `review/invoice_desglose`, `review/invoice_vision_desglose`, `review/general` | the audited step's own schema |
