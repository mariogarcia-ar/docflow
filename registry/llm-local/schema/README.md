# Schema — the shape of every answer

A schema is the **format** of one answer: its fields, their types, their enums, which fields are
required and whether anything else is allowed. It never says what a value must *be* — the rules
that decide a value live in the template beside it (`../template/…`), never in a schema's
`description`. Which fields each template extracts, and from which medium, is the field-level index
in [`../template/README.md`](../template/README.md); this file is the shape-and-keyword index.

A schema is resolved the same way a template is:

```
--schema extraction/invoice  →  <assets-dir>/schema/extraction/invoice.schema.json
```

The identifier in the docs omits the `.schema.json` suffix, and the two halves of a step pair are
spelled to match their medium: `extraction/invoice` for the text reading, `extraction/invoice_vision`
for the answer read from the page image.

## What a schema file may contain

The loader checks the file's **own** keyword set before anything else, and refuses a schema it
cannot fully enforce: a validator that ignored a rule would report an answer valid under a schema it
never applied. Use of an unsupported keyword is a typed `SCHEMA_ERROR` naming the keyword and its
path — never a silent skip.

| Keyword | Status | What the answer is checked against |
|---|---|---|
| `type` | enforced | the declared type; a union such as `["string", "null"]` is enforced like any other |
| `properties` | enforced | each declared field's own sub-schema, recursively |
| `required` | enforced | every listed key must be present in the answer |
| `additionalProperties: false` | enforced | a key the schema does not declare is a violation |
| `items` | enforced | every element of an array, recursively |
| `enum` | enforced | the value must be one of the listed literals |
| `minItems` | enforced | the array's minimum length |
| `title`, `description`, `default` | annotation only | carried, not enforced — where a rule would be lost, it belongs in the prompt |

The same mapping is the answer's grammar at the provider (`format` on Ollama, a `json_schema` on a
hosted API) and the validator of the parsed answer afterwards, so a response is generated *and*
checked against one document. Violations name the path they were found at (`$.iva: …`) — "the
response was invalid" is not a usable verdict.

**The absent value is the real `null`.** Every schema that admits an absent value types the field
`["string", "null"]`, and an enum that admits one lists the `null` literal itself
(`tipo_comprobante`, `categoria_gasto`, `condicion_impositiva_dominante`). The string `"null"` is
never the answer.

## The extraction schemas — the two media, one shape per step

| Schema | Medium | Fields | `required` | Notes |
|---|---|---|---|---|
| `extraction/invoice` | text | 7 | all 7 | `additionalProperties: false` |
| `extraction/invoice_vision` | page image | 7 | all 7 | byte-identical to `extraction/invoice` |
| `extraction/invoice_detection` | text | 3 | all 3 | gate; the template is spelled `deteccion` |
| `extraction/invoice_vision_detection` | page image | 3 | all 3 | byte-identical to `extraction/invoice_detection` |
| `extraction/invoice_desglose` | text | 10 | all 10 | tax breakdown |
| `extraction/invoice_vision_desglose` | page image | 10 | all 10 | byte-identical to `extraction/invoice_desglose` |
| `extraction/invoice_clasificacion` | text | 4 | all 4 | line of business |
| `extraction/invoice_vision_clasificacion` | page image | 4 | all 4 | byte-identical to `extraction/invoice_clasificacion` |
| `extraction/invoice_rubro` | text | 3 | all 3 | conditional quantity |
| `extraction/invoice_vision_rubro` | page image | 3 | all 3 | byte-identical to `extraction/invoice_rubro` |

Every extraction schema is `"type": "object"` with `additionalProperties: false`, so the answer
carries exactly the declared fields and nothing beside them.

**The vision schema is a copy, and that is the point.** Each vision schema is byte-identical to its
text twin: the duplication is the *identifier convention*, not a different format — a vision step
resolves its schema under its own name, so `extraction/invoice_vision` has to exist even though its
content equals `extraction/invoice`. Changing one half of a pair without the other is a divergence
this table is meant to surface.

### Which fields are nullable, and which values an enum admits

| Schema | Nullable (`["string", "null"]`) | Non-nullable `string` | Enum |
|---|---|---|---|
| `invoice` | `tipo_comprobante`, `razon_social_emisor`, `cuit_emisor`, `fecha_emision`, `nro_comprobante`, `notas` | `moneda` | `tipo_comprobante`: `A` \| `B` \| `C` \| `090` \| `099` \| `null`; `moneda`: `ARS` \| `USD` |
| `invoice_detection` | `motivo_rechazo` | `indicios_detectados`, `comprobante_valido` | `comprobante_valido`: `"true"` \| `"false"` (strings, not booleans) |
| `invoice_desglose` | `condicion_impositiva_dominante` | the nine fields from `analisis_condicion_iva` to `alicuotas_detectadas` | `condicion_impositiva_dominante`: `Responsable Inscripto` \| `Monotributo` \| `Exento` \| `No Categorizado` \| `Consumidor Final` \| `null` |
| `invoice_clasificacion` | `categoria_gasto`, `centro_de_costo` | `analisis_evidencia_rubro`, `descripcion` | `categoria_gasto`: `Restaurante` \| `Supermercado` \| `Hospedaje` \| `Combustible` \| `Movilidad/Pasajes` \| `Peajes` \| `Herramientas` \| `Otros` \| `null` |
| `invoice_rubro` | `cantidad_comensales_personas`, `cantidad_litros` | `analisis_rubro_aplica` | — |

Two things the table makes visible:

- **Money is text.** Every amount field of `invoice_desglose` is a `string`, because the value is
  returned exactly as printed (`"12.345,60"`); only the enum field is nullable, and the "no tax"
  answer is the string `"0"`, not `null`.
- **`moneda` is the only field of the base reading whose type is a bare `string`** — every other
  field of `invoice` can be a real `null`. That is the format; that a reading should prefer `USD`
  only when the page shows it is the template's rule.

## The review schemas — no field is extracted, every field is judged

A review answer is a verdict per field of another model's answer, so all five review schemas share
one shape: `field_verdicts`, an array of objects that are `additionalProperties: false` and require
`field`, `reason`, `verdict` and `suggested_value`.

| Schema | Medium judged | `minItems` | `field` |
|---|---|---|---|
| `review/invoice` | document text | 7 | enum — the seven base-reading field names |
| `review/invoice_vision` | page image | 7 | enum — the seven base-reading field names (byte-identical to `review/invoice`) |
| `review/invoice_desglose` | document text | 10 | enum — the ten tax-breakdown field names |
| `review/invoice_vision_desglose` | page image | 10 | enum — the ten tax-breakdown field names (byte-identical to `review/invoice_desglose`) |
| `review/general` | document text | — | any string: the schema-agnostic reviewer |

| Verdict field | Type · values |
|---|---|
| `field` | `string` — the key's name, as in the proposal being judged |
| `reason` | `string` — one short line supporting the verdict |
| `verdict` | `string` · `agree` \| `disagree` \| `uncertain` \| `ignored` |
| `suggested_value` | `["string", "null"]` — the correction when the verdict is `disagree`, otherwise `null` |

`review/general` is the only review schema that does not pin `field` to an enum and the only one
without a `minItems`: it audits any step, against whatever contract it is handed. A pinned schema
and a `minItems` equal to the audited step's field count are what stop a review from silently
answering a shorter array than the proposal it judged.

The reviewed step's own schema travels to the reviewer as `<extra:contract>` — that is what makes
the reviewer the extractor's judge rather than a second opinion, and it is why these files are read
twice: once as the shape of an answer, once as the standard that answer is audited against.

## Known mismatches to keep in mind

- **`deteccion` vs `detection`**: the gate's template is `extraction/invoice_deteccion` (Spanish)
  while its schema is `extraction/invoice_detection` (English). It is the one step whose two
  identifiers do not match, and a mismatched pair is a `DEPENDENCY_ERROR`, not a fallback.
- **`review/invoice_vision` states one key fewer than it enforces**: its prompt describes the
  verdict object as `field` + `verdict` + `suggested_value`, while `review/invoice_vision.schema.json`
  also requires `reason`. The schema is what the answer is validated against.
- **`centro_de_costo` is declared nullable but is always `null` at extraction** — a later
  classification step fills it. That is a rule, and it lives in the template, not in the schema.
