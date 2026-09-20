# Flujo de extracción de comprobantes fiscales (v2)

> Ningún modelo determina por sí solo la verdad del documento. La confianza surge de la
> combinación entre evidencia documental, validaciones determinísticas, consistencia
> entre fuentes independientes, y confirmación humana cuando hay ambigüedad real.

---

## 0. Artefactos de entrada (fijos, no dependen del documento puntual)

```
┌─────────────┐
│   prompt    │  qué buscar / cómo leerlo
└──────┬──────┘
┌─────────────┐
│   schema    │  qué forma tiene la respuesta
└──────┬──────┘
┌──────────────────┐
│  schema-visual    │  dónde debería estar cada campo — solo existe si el emisor ya fue aprendido
└───────────────────┘
```

El prompt y el schema los edita un humano. El schema-visual lo actualiza el propio
sistema (paso 8), solo a partir de extracciones confirmadas.

---

## 1. Flujo principal

```
documento
  → rutear (tipo de material + legibilidad)
  → clasificar (¿es comprobante?)
  → extraer campos
  → normalizar
  → validar campos
       ├─ confirmado                          → aprender
       ├─ resoluble con evidencia             → resolver → validar (loop) → aprender
       └─ no resoluble / material degradado   → escalar (cola) → [no aprende de esto todavía]
```

Cambios vs. v1: se agrega **normalizar** entre extraer y validar, y se renombra
**corregir → resolver** (ver §5).

---

## 2. Rutear

| Fuente | Confianza de partida |
|---|---|
| texto plano | alta |
| pdf con texto | alta |
| pdf sin texto (imagen) | media |
| imagen (foto/escaneo) | media |

Esta tabla es una heurística de **ruteo** (cuánto trabajo hacer, qué lecturas pedir),
no una afirmación de verdad — un PDF nativo con texto corrupto o un OCR sobre
documento perfecto son posibles en cualquier dirección. Quien arbitra la verdad son
los refutadores del paso 5, no este tier.

```
documento
  → ¿tiene capa de texto (o es texto plano)?
       ├─ sí  → texto_nativo
       └─ no  → convertir (pdf_imagen → imagen) → preprocesar (resize si DPI excesivo)
                 → chequear legibilidad
                      ├─ legible     → escaneado_ocr
                      └─ no legible  → degradado → escalar directo
```

Extracción de texto según fuente (sin modelo todavía):

| Fuente | Método |
|---|---|
| texto plano | ninguna operación |
| pdf con texto | `pdftotext -layout` o similar |
| imagen / pdf rasterizado | OCR (docling o similar) |

---

## 3. Clasificar (¿es comprobante?)

Gate barato antes de extraer campos:

```
texto_nativo   → reglas sobre el texto extraído
escaneado_ocr  → reglas sobre el texto OCR, o reglas de elementos visuales
       ├─ no es comprobante → descartar (fast-fail)
       └─ es comprobante    → sigue
```

---

## 4. Extraer campos

```
tier == texto_nativo
  → regexp para campos de formato fijo (CUIT, fecha, tipo, nro_comprobante)
  → LLM local → extract_A
  → LLM local otra vez, mismo texto, autorrevisión → extract_B
       ├─ extract_A == extract_B → extraction_consistent
       └─ difieren                → extraction_unstable → escalar
  → cruzar regexp vs. extraction_consistent en los campos que ambos cubren

tier == escaneado_ocr
  → LLM local sobre texto_ocr → extract_A / extract_B → extraction_consistent | unstable
  → (en paralelo) LLM local vision sobre el render → campos_vision
  salida: extraction_consistent (texto) + campos_vision, SIN fusionar
```

**Nota de terminología:** `extraction_consistent` describe que dos corridas del mismo
modelo sobre el mismo texto coinciden — es un chequeo de **estabilidad**, no de
**validación**. Ambas corridas pueden coincidir y estar igual de equivocadas, porque
comparten modelo y texto. La validación real ocurre en el paso 5, contra evidencia
externa al modelo.

Cada campo extraído se representa como objeto, no como valor suelto:

```json
{
  "field": "total",
  "raw_value": "$125.340,50",
  "source": "ocr",
  "evidence": { "page": 1, "bbox": [0.71, 0.82, 0.93, 0.88] },
  "extractor": "qwen2.5vl-local",
  "extractor_version": "v3"
}
```

Esto es lo que le permite a los refutadores (etiqueta↔evidencia, posición) operar
sobre algo más que el valor final.

---

## 5. Normalizar

Entre extraer y validar. Nunca pisa el valor impreso — lo acompaña:

```json
{
  "field": "cuit_emisor",
  "raw_value": "30-12345678-9",
  "normalized_value": "30123456789"
}
```

El comparador campo a campo (texto vs. vision, o contra lo aprendido del emisor)
opera sobre `normalized_value`. Lo que se reporta y se aprende conserva `raw_value`,
porque el prompt de extracción ya exige preservar el formato impreso.

---

## 6. Validar campos

```
→ refutadores mecánicos, sobre cada lectura por separado
    (etiqueta↔evidencia, trazabilidad al prompt, aritmética, ventana de contexto)
       ├─ alguna lectura con violación → esa lectura no vota
       └─ lecturas limpias → comparar (sobre normalized_value)
              ├─ coinciden → confirmado
              └─ difieren  → ¿algún refutador dirime cuál vale?
                     ├─ sí → resoluble → resolver
                     └─ no → severidad del campo en disputa
                            ├─ bajo/medio (ej. descripción) → aceptar la de mayor confianza, registrar
                            └─ alto/crítico (ej. total, IVA, CUIT, fecha) → escalar

si hay emisor conocido:
  → chequeo posicional adicional con schema-visual (bbox vs. zona esperada)
       ├─ coincide → suma a "confirmado"
       └─ no coincide → refutador disparado → resoluble / escalar
```

**Matriz de severidad por campo** (ejemplo, ajustable por proyecto):

| Campo | Severidad |
|---|---|
| total, IVA | crítica |
| CUIT, fecha | alta |
| razón social | media |
| descripción, categoría | baja |

Solo campos de severidad baja/media pueden resolverse por "mayor confianza" sin
evidencia que dirima; alta/crítica siempre requieren refutador que dirima o escalan.

---

## 7. Resolver (antes "corregir")

Renombrado a propósito: el sistema no pisa un valor en silencio, deriva un candidato
con traza completa:

```json
{
  "field": "total",
  "original": { "value": "12.300", "source": "ocr" },
  "resolved": { "value": "13.200", "reason": "arithmetic_validator", "rule": "VAL_TOTAL_002" },
  "evidence": "subtotal 10.900 + iva 2.290 = 13.190 ≈ 13.200"
}
```

Después de resolver, vuelve a pasar por "validar" (loop) antes de confirmarse — una
resolución no se acepta sin re-chequeo.

---

## 8. Verificación (frontier + HITL) — sin cambios de fondo vs. v1

```
escalar(doc, lecturas_en_disputa, motivo)
  → llm_frontier lee el documento original (multimodal)
      → campos_frontier + justificación por campo
  → refutadores mecánicos también sobre campos_frontier (frontier no está exento)
  → comparar contra las lecturas en disputa
       ├─ coincide con una          → candidato + evidencia → humano confirma con un click
       └─ no coincide con ninguna   → todas las lecturas + evidencia → decide el humano
  → humano resuelve → campos_confirmados

  → ¿motivo de escalamiento repetido N veces (mismo emisor/patrón)?
       ├─ sí → frontier propone regla candidata
       │        → backtest contra el histórico de campos_confirmados
       │        → si el backtest no rompe casos ya resueltos → pendiente de aprobación humana
       │        → aprobada → activar
       └─ no → se registra el caso, sin proponer regla todavía
```

Se agrega **backtest** antes de la aprobación humana: la regla candidata se corre
contra el histórico de confirmados antes de proponerse, para no promoverla en base a
un único caso.

---

## 9. Aprender

Solo con `campos_confirmados`. Actualiza: perfil del emisor, `schema-visual` del
emisor. Nunca a partir de una lectura cruda, de `campos_frontier` sin confirmar, ni
de un `resolved` que no volvió a pasar por validar.

---

## Notas / pendientes

- **Versionado transversal**: cada decisión debería poder reconstruirse — qué versión
  de prompt, schema, extractor y reglas produjo cada `campos_confirmados`. No es un
  paso del flujo, es un requisito de logging en cada paso que genera evidencia.
- **Tasa de escalamiento esperada al frontier** — sigue sin medirse; condiciona si el
  diseño de costos del paso 8 es sostenible a volumen.
- **Regla determinística para el blind spot emisor/receptor**: CUIT propio conocido →
  nunca es `cuit_emisor`. Candidata a refutador fijo desde el día uno, no depende de
  aprendizaje ni de schema-visual.
- Los "validadores" del paso 6 pueden tipificarse (sintácticos, aritméticos,
  de evidencia, de posición, de reglas de negocio) a medida que se agreguen — no hace
  falta la taxonomía completa desde el arranque, alcanza con que cada uno declare
  contra qué evidencia refuta.
