# Flujo de extracción de comprobantes fiscales (v4)

> Ningún modelo determina por sí solo la verdad del documento. La confianza surge de la
> combinación entre evidencia documental, validaciones determinísticas, consistencia
> entre fuentes independientes, y confirmación humana cuando hay ambigüedad real.

---

## 0. Artefactos de entrada (fijos, no dependen del documento puntual)

Con el patrón A/B de §4, los artefactos se bifurcan por **rol** (extraer / revisar) y,
en el caso del prompt, también por **lane** (texto / vision). El schema de extracción
y el schema-visual **no** se multiplican — siguen siendo compartidos entre A y B.

```
extraction_prompt_texto     ─┐
extraction_prompt_vision    ─┤→ qué buscar / cómo leerlo (uno por lane, ya existían)
review_prompt_texto         ─┤→ NUEVO: buscar errores en campos_A, no re-extraer
review_prompt_vision        ─┘  (framing adversarial, ver §4.1)

extraction_schema            → qué forma tiene una factura (compartido texto/vision,
                                 no cambia: invoice.json)
review_schema                → NUEVO: qué forma tiene un veredicto de B (no una factura)

schema-visual (por emisor)   → sin cambios: uno solo, lo consumen A y B por igual
```

El prompt y los dos schemas los edita un humano. El schema-visual lo actualiza el
propio sistema (paso 8), solo a partir de extracciones confirmadas.

### `review_schema` (nuevo)

```json
{
  "type": "object",
  "properties": {
    "reviewer": { "type": "string" },
    "extractor_reviewed": { "type": "string" },
    "field_verdicts": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "field": { "type": "string" },
          "verdict": { "type": "string", "enum": ["agree", "disagree", "uncertain"] },
          "reason": { "type": ["string", "null"] },
          "suggested_value": { "type": ["string", "null"] }
        },
        "required": ["field", "verdict"]
      }
    }
  },
  "required": ["reviewer", "extractor_reviewed", "field_verdicts"]
}
```

`suggested_value` es un candidato, no un reemplazo automático — como cualquier
desacuerdo entre lecturas, necesita un refutador mecánico que lo dirima antes de
pasar a `resolver` (§7); la opinión de B por sí sola no alcanza para pisar el valor
de A, por la misma razón por la que la opinión del frontier tampoco alcanza sola en
§8.


---

## 1. Flujo principal

```
documento
  → rutear (tipo de material + legibilidad)
  → clasificar (¿es comprobante?)
  → extraer campos (expertos generan candidatos + evidencia)
  → normalizar
  → motor de decisión (consenso MoE, §6)
       ├─ confirmado                          → aprender
       ├─ revisar/resolver con evidencia      → resolver → motor de decisión (loop) → aprender
       └─ escalar (score bajo / material degradado) → cola (§8) → [no aprende de esto todavía]
```

Cambios vs. v3: "validar campos" se reemplaza por el **motor de decisión** (§6) —
en vez de branches fijos, cada candidato acumula puntaje según la evidencia que lo
respalda, con un gate aparte para campos críticos que el puntaje solo no puede saltar.

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
documento perfecto son posibles en cualquier dirección. Quien arbitra la verdad es
el motor de decisión (§6), no este tier.

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

### 4.1 Modelos por lane (primario / alternativo)

| Lane | Primario (extract_A) | Alternativo (extract_B, revisor) |
|---|---|---|
| texto (razonamiento) | deepseek-r1 | gemma3 |
| vision | qwen2.5vl | Granite-Vision (2B) |

El rol de A y B **no es simétrico**: A extrae desde cero; B recibe el texto/imagen
original **más** la extracción de A, y se le pide explícitamente que busque errores en
esa extracción — no que confirme si está bien. Framing adversarial, no confirmatorio:
un modelo al que le preguntás "¿está bien esto?" tiende a decir que sí más de lo que
debería; uno al que le pedís "encontrá qué está mal" discrepa con más facilidad
cuando corresponde.

**Condición no negociable:** B tiene que leer la fuente (texto o imagen), no solo la
respuesta de A. Si B solo ve el JSON de A sin volver a mirar el documento, es
exactamente el patrón `judge` (K6) que ya se descartó en `my_hitl_llm_frontier.md`
por no poder detectar error de material — calificar la transcripción no es lo mismo
que calificar contra la evidencia.

### 4.2 Extracción

```
tier == texto_nativo
  → regexp para campos de formato fijo (CUIT, fecha, tipo, nro_comprobante)
  → extract_A (deepseek-r1) sobre el texto → campos_A
  → extract_B (gemma3), recibe texto + campos_A, prompt "buscá errores en esta
    extracción" → veredicto por campo
       ├─ B no señala errores → cross_model_agreement
       └─ B señala discrepancia en algún campo → discrepancia_señalada (por campo)
  → cruzar regexp vs. campos_A en los campos que ambos cubren

tier == escaneado_ocr
  → mismo patrón (extract_A deepseek-r1 / extract_B gemma3 revisor) sobre texto_ocr
  → (en paralelo, mismo patrón) extract_A (qwen2.5vl) sobre el render → campos_vision_A
    extract_B (Granite-Vision 2B), recibe render + campos_vision_A, mismo framing
    adversarial → cross_model_agreement | discrepancia_señalada

  salida: (campos_A texto, con su veredicto de B) + (campos_vision_A, con su veredicto de B),
          SIN fusionar entre lanes — eso sigue siendo responsabilidad de "validar"
```

**Dos ejes de refutación, no uno solo:**
- **Dentro de cada lane** (A/B, mismo material, modelos distintos) → refuta errores de
  *razonamiento del modelo* sobre ese material.
- **Entre lanes** (texto final vs. vision final, distinto material) → sigue siendo el
  único par que puede refutar un error de *OCR/material*, porque comparte solo el
  documento. El chequeo A/B no reemplaza esto — lo complementa.

**Nota de terminología:** `cross_model_agreement` reemplaza a `extraction_consistent`.
Es una señal más fuerte que la versión anterior (dos modelos con pesos distintos, no
el mismo modelo dos veces), pero sigue sin ser prueba definitiva: A y B comparten el
mismo material (mismo texto u mismo render), así que un error de OCR o de render que
ambos "vean" igual sigue sin ser detectable en este paso — para eso está el cruce
entre lanes.

**Qué reemplaza a la detección de inestabilidad de v2:** ya no depende de correr el
mismo modelo dos veces — un output que no parsea contra el `schema` (formato JSON
constreñido) o que se corta a mitad de generación se trata como fallo de
extracción y reintenta, independientemente del chequeo A/B.

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

## 6. Motor de decisión (consenso MoE)

Reemplaza los branches ad-hoc de v3 por un mecanismo explícito y calibrable. Cada
campo recibe candidatos y señales de varios expertos; un motor de decisión combina
esas señales en un puntaje, en vez de contar votos.

**Expertos, mapeados a lo que ya existe en el flujo:**

| Experto | De dónde sale en este documento |
|---|---|
| OCR / texto nativo | §2, extracción de texto por fuente |
| Extractor LLM | extract_A, §4 |
| Reviewer / Critic | extract_B, §4 |
| Modelo visual | extract_A vision, §4 |
| Validadores determinísticos | refutadores mecánicos ya usados en v1-v3 |
| Histórico / schema-visual | §0, chequeo posicional por emisor |

**Puntaje por candidato:**

| Señal | Puntos |
|---|---|
| Validación determinística fuerte (aritmética, checksum, regla fiscal) | +3 |
| Evidencia directa en el documento (bbox/posición localizada) | +2 |
| Coincidencia de fuente **independiente** — únicamente texto-lane final vs. vision-lane final (distinto material) | +2 |
| Reviewer/Critic (B) no logra refutar el candidato de A, mismo lane | +1 |
| Coincide con patrón histórico / schema-visual del emisor | +1 |
| Falta evidencia suficiente | −2 |
| Contradicción determinística o evidencia directa en contra | −3 |

**Regla que no es negociable, porque es la que evita el doble conteo:** una
coincidencia entre extract_A y extract_B **dentro del mismo lane** nunca puntúa como
el +2 de "fuente independiente" — eso está reservado para el cruce entre lanes
(texto vs. vision), el único par que comparte solo el documento. A/B compartiendo
lane solo puede sumar el +1 de revisor-no-refuta. Si esta distinción no queda fija
en el motor, el score reintroduce en silencio el mismo problema de independencia que
todo este diseño existe para evitar.

Cuando B discrepa y propone `suggested_value` (§0), ese valor es un candidato nuevo
que arranca su propio puntaje desde cero — no hereda los puntos de A, ni gana por
default por venir del revisor.

**Umbrales** (punto de partida, no medido todavía — calibrar contra el histórico de
`campos_confirmados` con el mismo mecanismo de backtest de §8):

```text
score >= 6     → CONFIRMADO
score 3 a 5    → REVISAR / RESOLVER
score < 3      → ESCALAR
```

**Gate adicional para campos de severidad alta/crítica** (mismo criterio de v2, ahora
expresado sobre el score): el puntaje solo no alcanza para confirmar `total`, `IVA`,
`CUIT` o `fecha` — necesitan además al menos una evidencia fuerte independiente
(+2 cruce de lanes) o una validación determinística (+3), aunque el score total ya
supere 6. Esto evita que un campo crítico se confirme solo porque acumuló varios +1
(revisor + histórico), que son señales débiles por separado.

| Campo | Severidad | Requisito extra sobre el score |
|---|---|---|
| total, IVA | crítica | +2 cruce de lanes o +3 determinístico, obligatorio |
| CUIT, fecha | alta | +2 cruce de lanes o +3 determinístico, obligatorio |
| razón social | media | score solo alcanza |
| descripción, categoría | baja | score solo alcanza |

**Salida del motor, por campo:**

```
score + gate de severidad
   ├─ CONFIRMADO         → aprender
   ├─ REVISAR/RESOLVER   → ¿algún refutador dirime cuál candidato vale?
   │                            ├─ sí → resolver (§7) → vuelve al motor (recalcula score)
   │                            └─ no → escalar (§8)
   └─ ESCALAR            → escalar (§8), directo a modelo de mayor capacidad (frontier)
```

El objetivo no es sumar modelos — es combinar expertos con errores poco
correlacionados. Agregar un tercer LLM que lee el mismo texto no mueve el score en
ninguna categoría de +2; solo el cruce texto/vision y las reglas determinísticas
mueven la aguja de verdad.



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

Después de resolver, vuelve a pasar por el motor de decisión (loop) antes de
confirmarse — una resolución no se acepta sin recalcular el score.

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
- Los validadores determinísticos que alimentan el +3/−3 del motor de decisión
  pueden tipificarse (sintácticos, aritméticos, de evidencia, de posición, de reglas
  de negocio) a medida que se agreguen — no hace falta la taxonomía completa desde
  el arranque, alcanza con que cada uno declare contra qué evidencia refuta.
- **Umbrales del motor de decisión (§6) sin calibrar**: `6 / 3-5 / <3` es un punto de
  partida razonable, no un resultado medido. Usar el mismo histórico de
  `campos_confirmados` que ya alimenta el backtest de reglas (§8) para ajustar los
  cortes antes de confiar en ellos en producción.
- **Trade-off aceptado en el patrón A/B (§4):** que B vea la respuesta de A antes de
  opinar introduce sesgo de anclaje — es más barato que una segunda extracción a
  ciegas, pero es una validación más débil que una verdaderamente independiente. Se
  acepta por costo; si en producción se mide que B rara vez discrepa (posible señal
  de que está rubber-stampeando en vez de revisando), vale la pena medir cuánto
  cambia el comportamiento si a B se le pide extraer primero sin ver a A, y comparar
  después — más caro, pero sin el sesgo de anclaje.
