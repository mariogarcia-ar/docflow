# Quickstart — the flows of `my_flow.md`

One document, one run. The library is the deliverable; this CLI is one caller of it.

```bash
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<case> --verbose
```

Stdout is the operator report. Progress goes to stderr. `--json` / `--pretty` print the engine result instead.

A second run on the same `--work-root` **resumes**: finished stages show `reused`, the first unfinished stage runs. `--redo` ignores the journal.

---

## The main flow

This is `my_flow.md` §1. Every case below is a specialisation of it — never a second pipeline.

```
documento
  → rutear (tipo de material + legibilidad + integridad de la capa de texto)
  → clasificar (¿es comprobante?)
  → extraer (regexp, LLM, vision y QR producen candidatos + evidencia)
  → normalizar y agrupar candidatos (por normalized_value)
  → motor de decisión (§6: señales por familia, vetos, margen, gate)
       ├─ CONFIRMADO        → SYSTEM_CONFIRMED → estadísticas en sombra (§9)
       ├─ REVISAR/RESOLVER  → resolver (§7) → motor (solo si hay novedad; máx. 2 vueltas)
       │                        └─ sin refutador → lane faltante a demanda → motor
       │                                             └─ sigue sin cerrar → frontier (§8)
       └─ ESCALAR (score bajo / todo vetado / material degradado) → frontier (§8)
                                                  └→ humano → HUMAN_CONFIRMED → aprender
```

On disk that is four stages, always in this order:

| Stage | Artifact | What it answers |
|---|---|---|
| `read` | `material.json` (+ `images/` when pages were rendered) | What was read, which route, which tier |
| `extract` | `extraction.json` | Candidates, producers, notes (including “classified out”) |
| `decide` | `decision.json` | Per-field verdict, score, margin, gate, reason codes |
| `hitl` | `pending.json` | The fields a human must settle |

`CONFIRMADO` is a field verdict inside `decide`. `REVISAR` / `ESCALAR` become queue entries in `hitl`. The frontier and the human are **not** extra stages: they are `--resolve` and `--confirm` on a work root that already has a queue.

---

## The six canonical examples (proposed fixture matrix)

The intended set: one file per combination of **material** (text PDF / scanned PDF / image) × **outcome** (receipt / not a receipt).

| # | Label asked for | File | ext | `pdf_type` | Agrees? |
|---|---|---|---|---|---|
| 1 | pdf texto · sin comprobante | `negativos/neg_2026-06_correo_liquidacion.pdf` | pdf | `pdf_texto` | yes |
| 2 | pdf texto · con comprobante | `casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf` | pdf | `pdf_texto` | yes |
| 3 | pdf imagen · sin comprobante | `negativos/neg_2026-10_pantalla_aprobacion.pdf` | pdf | `pdf_escaneado` | yes |
| 4 | pdf imagen · con comprobante | `pdf_aptos_layout/36744cc6-2ed9-47e5-b4b8-66c31768164b.pdf` | pdf | **`pdf_texto`** | **no** |
| 5 | imagen · sin comprobante | `negativos/neg_2026-06_correo_liquidacion.pdf` | **pdf** | **`pdf_texto`** | **no** |
| 6 | imagen · con comprobante | `casos/66e6e0ea-e910-41f4-9037-13f0309812c1.jpg` | jpg | — (not a PDF) | yes |

Two rows do not match their label. Not resolved here — recorded, with the evidence:

- **Row 4.** `pdf_aptos_layout/` is the *text-layer* folder: all five of its PDFs are detected `pdf_texto`, and the fixture's own name says so. A scanned receipt lives in `pdf_escaneados/` instead (all five `pdf_escaneado`; `9b7a423c-189c-4b9b-8ab1-23b38d4518b4.pdf` carries an ARCA QR and is already used in Case 2). Using a text PDF here would make the "pdf imagen" row exercise Case 1 — the same branch as row 2.
- **Row 5** is the *same file as row 1* (a copy-paste slip, not a choice): it is a PDF, so it cannot be the "imagen" row. Image candidates in the negative folder: `neg_2026-11_foto_pizarra.jpg`, `neg_2026-03_dni_dorso.jpg`, `neg_2026-02_gastos_varios.png`.

Two facts about this table, kept apart on purpose:

- The `pdf_type` column is **measured** — it is the committed value in `tests/fixtures/manifest.json`, written by `voucherflow`'s detector (`build_manifest.py`), not a label copied from the folder name.
- The receipt / not-a-receipt half is the **curated folder naming** (`negativos/` = curated negative). It is *not* a `classify()` result: `classify` is a separate, weaker gate that runs inside `extract`, and its verdict for these files has not been measured here. A file can sit in `negativos/` and still pass `classify` — the folder is a human's judgement, `classify` is two cheap signals.

---

## How to read a run

```
path
  1. read      ran     read ran
  2. extract   ran     17 field(s) with candidates
  3. decide    ran     17 field(s) decided, 2 confirmed
  4. hitl      ran     15 field(s) pending

confirmed (…)
review (…)
escalate (…)

read next
  var/work/<case>/pending.json   — the fields a human must settle
  var/work/<case>/decision.json  — every decision, with the signals behind it

notes
  - …
```

`ran` vs `reused` is the only way to know whether today’s answer came from a model call or from last week’s artifact. `read next` names **only files that were written**.

Reason codes are the `motivo` of every branch (`my_flow.md` §6.5). The ones you will see first:

| Code | Branch |
|---|---|
| `CONF_SCORE_MARGIN_GATE` | CONFIRMADO |
| `REV_GATE_UNMET` | score enough, strong evidence missing |
| `REV_SCORE_MID` | score between 2 and T |
| `ESC_LOW_SCORE` | winner score &lt; 2 |
| `ESC_DEGRADED_MATERIAL` | `read` produced no text |

---

## Case 1 — PDF with a text layer (`texto_nativo`)

Routing heuristic (`my_flow.md` §2): a PDF whose text layer is `text` or `mixed` and intact is read as text. That is a routing claim, not a truth claim — the engine still decides per field.

```
PDF
  → ¿capa de texto íntegra?
       ├─ sí  → layout_text (pdftotext -layout) → tier texto_nativo
       │         → clasificar (reglas baratas sobre el texto)
       │              ├─ no es comprobante → extract vacío, nota "classified out"
       │              └─ es comprobante
       │                   → regexp (CUIT, fecha)
       │                   → lane A texto (deepseek-r1) + lane B texto (gemma3, adversarial)
       │                   → vision: no corre (read no renderizó páginas)
       │                   → motor
       │                        ├─ CONFIRMADO  (CUIT checksum, fecha existe, …)
       │                        ├─ REVISAR     (REV_GATE_UNMET en total/IVA: sin DETERMINISTIC ni CROSS_MODAL)
       │                        │                 → resolver: lane-on-demand *detecta* vision
       │                        │                 → render a demanda: todavía no  (# TODO: [MVP])
       │                        └─ ESCALAR     (score < 2)
       └─ dudosa → tratar como imagen (Case 2)
```

```bash
python scripts/poc-flow-v2/myflow.py \
  tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf \
  --work-root var/work/pdf-texto --verbose
```

What a real run of this fixture left on disk (`var/work/`):

- `material.json`: `kind=pdf`, `tier=texto_nativo`, `route=layout_text`, `pages_read=1`, `image_count=0`
- `cuit_emisor` **CONFIRMED** `CONF_SCORE_MARGIN_GATE` — producers `regexp + extractor_llm_texto`, signals `DOCUMENT_CONTENT` + `DETERMINISTIC` (checksum), score 5, gate closed
- `fecha_emision` **CONFIRMED** — regexp + date-exists rule
- most other fields **REVIEW** / **ESCALATE** — no vision lane, so `CROSS_MODAL` never fires; critical amounts stay at `REV_GATE_UNMET` unless arithmetic has every component

The smoke in `my_flow.md` B.7 (`tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf`) is the same branch: CUIT and date confirm; `importe_total_facturado` / `iva` land in `REV_GATE_UNMET`. That is Anexo A’s unreachable cell showing up in practice. The missing piece is not a lower threshold; it is the vision ladder (Case 2, and C6 below).

Inspect:

```bash
python -c "import json; m=json.load(open('var/work/pdf-texto/material.json')); print(m['tier'], m['route'], m.get('image_count'))"
```

---

## Case 2 — scanned PDF (`escaneado_ocr`)

No usable text layer (or a damaged one). The page is rendered, OCR’d, and the **pixels stay on the material**, so the vision lane can run.

```
PDF
  → ¿capa de texto? no / dudosa
       → render (DPI del piso, capped by the page) + OCR (Docling)
       → tier escaneado_ocr, images/ poblado
       → clasificar sobre texto OCR
       → extraer
            → regexp sobre texto_ocr
            → lane A/B texto (mismo patrón que Case 1)
            → lane A vision (qwen2.5vl) sobre el render
            → lane B vision (granite-vision:2b)  — si el modelo no está pulled: nota, no fake
            → QR: el módulo existe, extract no lo llama todavía (C3)
            → CROSS_MODAL cuando texto y vision coinciden en normalized_value
       → motor
            ├─ CONFIRMADO  (cruce texto/visión, o aritmética completa, o checksum)
            ├─ REVISAR / resolver
            └─ ESCALAR → --resolve → --confirm
```

```bash
python scripts/poc-flow-v2/myflow.py \
  tests/fixtures/pdf_escaneados/9b7a423c-189c-4b9b-8ab1-23b38d4518b4.pdf \
  --work-root var/work/pdf-scan --verbose
```

This is the only case where `CROSS_MODAL` can fire from the CLI today. A measured run of this fixture produced producers `regexp + extractor_llm_texto + vision` and `CROSS_MODAL` on date / IVA / currency (`plan/cierre-circuitos.md` C2). If `granite-vision:2b` is not pulled, lane B vision refuses with a **note** — never a stand-in verdict.

`SAME_MATERIAL` (+1) only appears when lane B returns `agree`. A missing review is a note (`text lane B produced no review verdicts`), never a silent zero.

---

## Case 3 — image file (`escaneado_ocr`)

A photo or scan that is already pixels. Routing is: legibility gate, then OCR. There is no text layer to prefer.

```
imagen (jpg/png/…)
  → chequear legibilidad
       ├─ no legible → tier degradado, text=None → extract no corre un modelo
       │                 → decide no tiene candidatos → hitl vacío / ESCALAR material
       └─ legible → OCR (Docling) → tier escaneado_ocr, route=ocr
                    → clasificar → extraer (regexp + lanes de texto)
                    → vision: no corre — read_material deja images=[] en archivos imagen
                    → motor (igual que Case 1: sin CROSS_MODAL)
```

```bash
python scripts/poc-flow-v2/myflow.py \
  tests/fixtures/casos/2926bed9-048a-4d72-9d41-8d65d290bfdb.jpeg \
  --work-root var/work/imagen --verbose
```

Blurred / illegible control (the pixel route is refused **before** OCR):

```bash
python scripts/poc-flow-v2/myflow.py \
  tests/fixtures/blur/f69d1898-40f7-4424-9c94-77a961677595.jpg \
  --work-root var/work/imagen-blur --verbose
```

Honest gap: attaching the source image as `material.images` so vision can run on a `.jpg` is not wired. Today an image file is OCR-only, same scoring ceiling as native text without a second lane.

---

## Case 4 — not a receipt (classify fast-fail)

`my_flow.md` §3. The gate runs **inside `extract`**, after `read`, before any model. Cheap rules: at least two independent fiscal signals (CUIT, amount, date, fiscal keyword). A lone keyword in prose is not a receipt.

```
documento → read (cualquier ruta) → clasificar
                                      ├─ proceeds → extraer
                                      └─ no → Extraction vacía, nota "classified out: …"
                                               decide no inventa campos
                                               hitl cola vacía
```

```bash
python scripts/poc-flow-v2/myflow.py \
  tests/fixtures/negativos/neg_2026-03_dni_dorso.jpg \
  --work-root var/work/no-comprobante --verbose
```

Look for `classified out:` in the report `notes` and in `extraction.json`. The model was not paid.

---

## After decide: the three exits

These are not extra CLIs. They are the same work root, continued.

### CONFIRMADO → `SYSTEM_CONFIRMED`

Already in the report under `confirmed`. Shadow statistics only (`my_flow.md` I6/I7). Nothing is learned from this channel.

### REVISAR / resolver → motor (max 2 loops)

`decide` already runs `resolver_loop`. Today the only resolver step is C6: *which critical fields still lack strong evidence*. If any do, a note is appended:

```
lane-on-demand deferred: importe_total_facturado, iva still lack strong evidence
```

and the loop stops — no new evidence was produced. Render-on-demand for a native-text PDF is `# TODO: [MVP]` (`flow/run.py`).

### ESCALAR → frontier → human

Needs `--work-root`. The suggestion is evidence, never a verdict (I6). Mechanical refuters still apply to frontier values.

```bash
# 1. produce the queue
python scripts/poc-flow-v2/myflow.py \
  tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf \
  --work-root var/work/pdf-texto

# 2. ask the frontier (writes resolution.json; no credential → note, queue survives)
python scripts/poc-flow-v2/myflow.py \
  tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf \
  --work-root var/work/pdf-texto --resolve

# 3. a human settles one pending field (writes confirmed.json)
python scripts/poc-flow-v2/myflow.py \
  tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf \
  --work-root var/work/pdf-texto --confirm fecha_emision=2026-07-07
```

`--confirm` on a field the engine already CONFIRMED is refused (I6). An empty value is not a decision. `--resolve` without `--work-root` is a no-op.

---

## Circuits vs this CLI

`plan/cierre-circuitos.md` closed C1–C9 in the library. Not every closed circuit is reachable from `myflow.py`. That is declared here so a missing signal is not read as a failed document.

| Circuit | From the CLI? | How you see it |
|---|---|---|
| C1 classify | yes | Case 4; note `classified out:` |
| C2 lanes A/B × texto/vision | **partial** | text A/B on every receipt-like document; vision A/B only when `material.images` is populated (Case 2). Image files and native-text PDFs skip vision |
| C3 QR | **no** | `flow/qr.py` is tested (`test_c3_*`); `extract()` never calls it. No `DETERMINISTIC` from QR, no `REV_QR_CONFLICT` on a real document yet |
| C4 `verified` | yes | `DOCUMENT_CONTENT` PASS only with digit-boundary presence in the text; otherwise UNKNOWN. Bbox re-read still `# TODO: [MVP]` |
| C5 arithmetic groups | yes, when amounts parse as amounts | unique consistent combo → +3; missing component → `UNKNOWN` (an alícuota `"21,0%"` is not an amount — B.7); 0 or more than one combo → `ESC_NO_UNIQUE_ARITHMETIC_COMBINATION` |
| C6 lane-on-demand | **detects, does not render** | note `lane-on-demand deferred: …`; Anexo A’s ladder is not walked for Case 1 |
| C7 resolver loop | yes | capped at 2; no new evidence → stop (the deferred note is that stop) |
| C8 frontier + HITL | yes | `--resolve` / `--confirm` (Case “After decide”) |
| C9 learn | **no** | `flow/learn.py` is tested (`SYSTEM_CONFIRMED` cannot activate a template). No store, no `LAYOUT_HISTORY` on a run. Activation stays `# TODO: [MVP]` in the caller |

---

## Resume, pause, stop

Same document, same work root:

```bash
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<case> --pause
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<case>          # resume
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<case> --stop
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<case> --redo
```

`path` then shows `reused` on finished stages. Invalidating a middle stage does **not** delete files; the journal stops trusting them.

---

## What this file is not

It is not a second specification. `my_flow.md` wins on invariants, scores, and reason codes. It is not the kernel bench (`scripts/poc/`). It is the operator map of **which branch of §1 a real file takes**, and which circuits you can actually watch from this CLI today.

