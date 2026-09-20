# Versión simplificada

**Idea central:** un valor solo se acepta solo si lo respalda evidencia *independiente*. Si no, lo decide un humano. Y el sistema solo aprende de lo que un humano confirmó.

```
documento → leer → extraer candidatos → validar con reglas → decidir
                                                              ├─ confirmado
                                                              └─ revisión humana
```

## Los 4 pasos

1. **Leer.** Si el PDF tiene texto, se usa. Si no, OCR y también lectura visual de la imagen.
2. **Extraer.** Cada campo sale de varias fuentes (regex, un LLM y, si existe, el QR de la factura). Un segundo modelo revisa el resultado buscando errores.
3. **Validar con reglas duras.** Checksum del CUIT, subtotal + IVA = total, el CUIT propio nunca es el emisor, la fecha existe. Si una regla falla, el valor se descarta, aunque todos los modelos coincidan.
4. **Decidir por campo.**
   - **Confirmado** si pasa las reglas o si dos lecturas *de material distinto* coinciden (texto vs. imagen), y no hay otro valor compitiendo de cerca.
   - **Dudoso** va a un humano, con un modelo más potente sugiriendo la respuesta.

## Lo único que hay que recordar

- **Dos modelos leyendo el mismo texto no son dos pruebas.** Solo cuentan las reglas determinísticas y el cruce texto/imagen.
- **Los campos críticos** (total, IVA, CUIT, fecha) exigen una de esas dos pruebas. Los menos importantes (razón social, descripción) aceptan una lectura bien anclada que el revisor no refute.
- **Un valor descartado por regla no se rescata por votos.**


# Flujo de extracción de comprobantes fiscales (v6)

> Ningún modelo determina por sí solo la verdad del documento. La confianza surge de la
> combinación entre evidencia documental, validaciones determinísticas, consistencia
> entre fuentes independientes, y confirmación humana cuando hay ambigüedad real.

---

## Invariantes de diseño

No son parámetros configurables. Una implementación que viole alguno deja de ser este diseño.

| # | Invariante | Se especifica en |
|---|---|---|
| I1 | **Independencia.** A y B del mismo lane nunca cuentan como fuente independiente. El +2 de independencia es solo para el cruce entre lanes (texto vs. vision). | §6.2 |
| I2 | **El score pertenece al candidato, no al campo.** Candidatos con igual `normalized_value` se fusionan *antes* de puntuar. | §5, §6 |
| I3 | **Veto.** Una refutación dura invalida el candidato; ningún puntaje la compensa. | §6.3 |
| I4 | **Sin doble conteo.** Máximo una señal por familia de evidencia. Una señal que fue *input* de un extractor (p. ej. el schema-visual usado como hint) no cuenta como corroboración de su *output*. | §6.2 |
| I5 | **B lee la fuente.** El revisor recibe el documento original, no solo el JSON de A. | §4.1 |
| I6 | **Score ≠ verdad.** Lo que confirma el motor es `SYSTEM_CONFIRMED`. Solo la confirmación humana es ground truth. | §9 |
| I7 | **Solo la confirmación humana activa lo aprendido.** Una señal de scoring aprendida (template de layout, perfil de emisor) se activa únicamente desde `HUMAN_CONFIRMED`. `SYSTEM_CONFIRMED` alimenta estadísticas en sombra sin efecto en el score ni en la calibración: un error sistemático de todos los modelos no puede enseñarse a sí mismo. | §9 |
| I8 | **Alcanzabilidad.** Todo par (campo, tier) tiene un camino a CONFIRMADO o una escalera de escalamiento explícita. Un test automático corre cada vez que cambian puntajes, umbrales, gates o señales disponibles, y **falla el build/la configuración** si algún par válido queda sin camino. | Anexo A |
| I9 | **Nada se pisa en silencio.** `resolver` deriva candidatos con traza y siempre vuelven al motor. | §7 |
| I10 | **La falta de información no es un error.** Todo validador responde `PASS` / `FAIL` / `UNKNOWN`. `UNKNOWN` no puntúa, no penaliza y nunca veta. | §6.2 |

---

## 0. Artefactos de entrada (fijos, no dependen del documento puntual)

Con el patrón A/B de §4, los artefactos se bifurcan por **rol** (extraer / revisar) y,
en el caso del prompt, también por **lane** (texto / vision). El schema de extracción
no se multiplica: es compartido entre A y B.

```
extraction_prompt_texto     ─┐
extraction_prompt_vision    ─┤→ qué buscar / cómo leerlo (uno por lane)
review_prompt_texto         ─┤→ buscar errores en campos_A, no re-extraer
review_prompt_vision        ─┘  (framing adversarial, ver §4.1)

extraction_schema            → qué forma tiene una factura (compartido texto/vision: invoice.json)
review_schema                → qué forma tiene un veredicto de B (no una factura)

schema-visual                → uno por (emisor, tipo_comprobante, layout_fingerprint)
                               Lo consume SOLO el chequeo posicional del motor (§6, señal
                               LAYOUT_HISTORY). No se inyecta en los prompts de A ni de B (I4).
```

Un mismo emisor puede tener Factura A, Factura B, notas de crédito, sucursales o
ERP antiguos y nuevos: con un schema por emisor, un layout legítimo distinto se lee
como anomalía. Por eso la clave incluye tipo y huella de layout (§9).

El prompt y los schemas los edita un humano. El schema-visual lo propone el propio sistema
en sombra (§9), pero un template solo entra en juego (señal `LAYOUT_HISTORY`) después de
confirmación humana (I7).

### `review_schema`

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

Cómo consume el motor cada veredicto (§6.2):

| Veredicto | Efecto |
|---|---|
| `agree` | cuenta como "B no refuta" (+1, familia `SAME_MATERIAL`) |
| `uncertain` | neutro: no suma ni resta |
| `disagree` | refutación blanda sobre el candidato de A (−2) |
| `suggested_value` | **candidato nuevo** que arranca su propio puntaje desde cero: no hereda los puntos de A ni gana por venir del revisor. Necesita un refutador mecánico que lo dirima antes de pasar a `resolver` (§7); la opinión de B por sí sola no alcanza para pisar a A, por la misma razón por la que la del frontier tampoco alcanza sola en §8. |

---

## 1. Flujo principal

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

**Cambios vs. v5:**

- Todos los validadores responden **PASS / FAIL / UNKNOWN**; `UNKNOWN` no puntúa ni veta (I10, §6.2).
- Un veto aritmético exige que la regla declare tener **todos sus componentes**; si no, es `UNKNOWN` (§6.3, §6.4).
- Se elimina la refutación blanda por "evidencia insuficiente": la falta de evidencia ya se
  expresa como puntos que no se cobran (§6.2).
- El QR pasa a describirse como **extracción determinística de una fuente embebida**, no
  como verdad del comprobante (§4.2, §6.2).
- El aprendizaje se separa en dos canales: **SYSTEM_CONFIRMED** solo alimenta estadísticas en
  sombra; templates, calibración y reglas solo desde **HUMAN_CONFIRMED**. Se agrega el ciclo
  de vida de templates (I7, §9).
- El loop resolver → motor solo reingresa si hay candidato o evidencia **nuevos** (§7).
- **Códigos de razón** estándar para cada decisión (§6.5).
- Auditoría por riesgo y métricas nuevas del revisor y de la independencia entre lanes (§9, Notas).
- El test de alcanzabilidad **falla el build** (I8, Anexo A).

---

## 2. Rutear

| Fuente | Confianza de partida |
|---|---|
| texto plano | alta |
| pdf con texto (íntegro) | alta |
| pdf sin texto (imagen) | media |
| imagen (foto/escaneo) | media |

Esta tabla es una heurística de **ruteo** (cuánto trabajo hacer, qué lecturas pedir),
no una afirmación de verdad. Quien arbitra la verdad es el motor de decisión (§6).

```
documento
  → ¿tiene capa de texto (o es texto plano)?
       ├─ sí  → chequear integridad de la capa de texto
       │          (caracteres de reemplazo / no imprimibles, mapeo de fuentes roto,
       │           ausencia de etiquetas esperadas)
       │          ├─ íntegra → texto_nativo
       │          └─ dudosa  → tratar como imagen (renderizar y seguir por la rama de abajo)
       └─ no  → convertir (pdf_imagen → imagen) → preprocesar (resize si DPI excesivo)
                 → chequear legibilidad
                      ├─ legible     → escaneado_ocr
                      └─ no legible  → degradado → escalar directo
```

El chequeo de integridad importa porque la ancla nativa (§6.5) solo vale como evidencia
fuerte sobre una capa de texto verificada como íntegra.

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
esa extracción, no que confirme si está bien. Framing adversarial, no confirmatorio:
un modelo al que le preguntás "¿está bien esto?" tiende a decir que sí más de lo que
debería.

**Condición no negociable (I5):** B tiene que leer la fuente (texto o imagen), no solo la
respuesta de A. Si B solo ve el JSON de A, es exactamente el patrón `judge` (K6) que ya
se descartó en `my_hitl_llm_frontier.md` por no poder detectar error de material.

Cada rol se versiona como objeto, no como nombre suelto (`deepseek-r1` puede significar
cosas muy distintas): `role`, `family`, `variant`, `quantization`, `runtime`,
`prompt_version`.

### 4.2 Extracción

```
tier == texto_nativo
  → regexp para campos de formato fijo (CUIT, fecha, tipo, nro_comprobante)  → candidatos
  → extract_A (deepseek-r1) sobre el texto → campos_A → candidatos
  → extract_B (gemma3), recibe texto + campos_A, prompt "buscá errores en esta
    extracción" → veredicto por campo (agree | disagree | uncertain)
  → cruzar regexp vs. campos_A en los campos que ambos cubren

tier == escaneado_ocr
  → mismo patrón (A deepseek-r1 / B gemma3 revisor) sobre texto_ocr
  → (en paralelo, mismo patrón) extract_A (qwen2.5vl) sobre el render → campos_vision_A
    extract_B (Granite-Vision 2B), recibe render + campos_vision_A, mismo framing adversarial

cualquier tier con render disponible
  → decodificar QR, si hay (ver abajo) → candidatos por extracción determinística

  salida: candidatos de cada lane con su veredicto de B, SIN fusionar entre lanes;
          eso lo resuelve el motor de decisión (§6)
```

**QR de comprobante electrónico (si los comprobantes son argentinos con CAE).** Las
facturas electrónicas traen un QR de ARCA cuyo payload incluye fecha, CUIT del emisor,
punto de venta, tipo y número de comprobante, importe, moneda, tipo y número de documento
del receptor, y código de autorización. Es una **extracción determinística de una fuente
embebida**: la decodificación es exacta y no depende de ningún LLM ni de OCR, pero eso no
vuelve al payload la verdad del comprobante (la autenticidad del CAE se valida con una
consulta a ARCA, ver Notas). Lo que aporta es una segunda lectura del mismo dato con modos
de falla distintos a los del OCR y los LLM; por eso su **coincidencia** con el valor
impreso puntúa como `DETERMINISTIC`, y por eso cubre justo los campos críticos y distingue
emisor de receptor por construcción. Un desacuerdo QR ↔ texto impreso **no se resuelve por
puntaje**: activa `conflicto_qr` y fuerza REVISAR o escalar. No es una discrepancia entre
modelos sino entre dos representaciones del documento (error de lectura, comprobante
inconsistente o alterado, QR incorrecto).

**Dos ejes de refutación, no uno solo:**
- **Dentro de cada lane** (A/B, mismo material, modelos distintos) → refuta errores de
  *razonamiento del modelo* sobre ese material.
- **Entre lanes** (texto vs. vision) → el único par que puede refutar un error de
  *OCR/material*. El chequeo A/B no lo reemplaza, lo complementa.

**Límite de la independencia entre lanes.** Ambas lanes parten del mismo documento y, por
defecto, del mismo render y preprocesado (§2). En escaneos degradados los errores pueden
estar correlacionados. Diseño recomendado: *mismo documento, pipelines de transformación
distintos, familias de modelo distintas*. Por ejemplo, OCR sobre imagen en escala de grises,
con deskew y DPI alto; vision sobre el render original o con un resize alternativo. La
suposición de independencia no se da por buena: se mide con `cross_modal_correlated_error_rate`
(Notas).

**Terminología:** `cross_model_agreement` reemplaza a `extraction_consistent`. Es más
fuerte que dos corridas del mismo modelo, pero sigue sin ser prueba: A y B comparten el
mismo material, así que un error de OCR o de render que ambos "vean" igual no es
detectable en este paso.

**Fallo de extracción:** un output que no parsea contra el schema (JSON constreñido) o
que se corta a mitad de generación se trata como fallo y reintenta, independientemente
del chequeo A/B.

Cada campo extraído se representa como objeto, con la evidencia dividida en **ubicación**
y **contenido**. Un bbox correcto no prueba que el valor leído sea el impreso:

```json
{
  "field": "total",
  "raw_value": "$125.340,50",
  "producer": "extractor_llm | regexp | vision | qr",
  "source": "ocr",
  "evidence": {
    "location": { "page": 1, "bbox": [0.71, 0.82, 0.93, 0.88] },
    "content": { "raw_text": "$125.340,50", "label": "Total", "verified": true }
  },
  "extractor": {
    "role": "vision_extractor", "family": "qwen2.5vl", "variant": "<completar>",
    "quantization": "<completar>", "runtime": "<completar>", "prompt_version": "<completar>"
  }
}
```

`verified` **lo calcula el sistema, no el modelo**: es el resultado de leer mecánicamente
el contenido en la ubicación declarada (offset en la capa de texto, o re-lectura del recorte
del bbox) y compararlo con `raw_value`. Un bbox autodeclarado sin verificar no puntúa.

---

## 5. Normalizar y agrupar candidatos

Entre extraer y decidir. Nunca pisa el valor impreso, lo acompaña:

```json
{
  "field": "cuit_emisor",
  "raw_value": "30-12345678-9",
  "normalized_value": "30123456789"
}
```

El comparador (texto vs. vision, o contra lo aprendido) opera sobre `normalized_value`. Lo
que se reporta y se aprende conserva `raw_value`.

**Agrupación (I2).** Todos los productores que llegan al mismo `normalized_value` para un
campo se fusionan en **un** candidato con múltiples señales. Sin esto, `"125.340,50"` y
`"125340.5"` aparecerían como competidores y el margen (§6.5) quedaría en cero.

```json
{
  "field": "total",
  "candidates": [
    {
      "normalized_value": "125340.50",
      "producers": ["extractor_llm_texto", "regexp", "vision_A"],
      "signals": [
        { "family": "DETERMINISTIC",    "rule": "VAL_TOTAL_002", "result": "PASS", "points": 3 },
        { "family": "DOCUMENT_CONTENT", "verified": true,       "result": "PASS", "points": 2 },
        { "family": "CROSS_MODAL",                              "result": "PASS", "points": 2 },
        { "family": "SAME_MATERIAL",    "detail": "B agree + regexp", "result": "PASS", "points": 1 }
      ],
      "hard_refutations": [],
      "score": 8
    },
    {
      "normalized_value": "125840.50",
      "producers": ["vision_B_sugerido"],
      "signals": [ { "family": "DOCUMENT_CONTENT", "verified": false, "result": "UNKNOWN", "points": 0 } ],
      "hard_refutations": [
        { "rule": "VAL_TOTAL_002", "result": "FAIL", "required_components_present": true,
          "reason": "combinación subtotal+IVA+total inconsistente" }
      ],
      "score": null,
      "status": "vetado"
    }
  ]
}
```

(`SAME_MATERIAL` suma +1 aunque coincidan B y regexp: tope por familia, §6.2. Cada señal registra
su `result`; las `UNKNOWN` se conservan en la traza con 0 puntos.)

---

## 6. Motor de decisión (consenso MoE)

Cada campo recibe candidatos y señales de varios expertos; el motor combina las señales
en un puntaje por candidato, en vez de contar votos.

### 6.1 Expertos

| Experto | Rol | De dónde sale |
|---|---|---|
| OCR / texto nativo | material base | §2 |
| Parser / regexp | **produce candidatos** de formato (nunca decide: puede encontrar varios CUIT) | §4.2 |
| Extractor LLM | produce candidatos semánticos | extract_A, §4 |
| Reviewer / Critic | refuta candidatos; sus `suggested_value` son candidatos nuevos | extract_B, §4 |
| Modelo visual | produce candidatos desde la imagen | extract_A vision, §4 |
| QR | produce candidatos por extracción determinística de una fuente embebida; su coincidencia con el valor impreso es señal `DETERMINISTIC` | §4.2 |
| Validadores determinísticos | apoyan o refutan | refutadores mecánicos |
| Histórico / schema-visual | contexto de posición por (emisor, tipo, layout) | §0, §9 |

### 6.2 Señales, familias y tope

**Regla I4:** dentro de una misma familia se toma **una** señal (la de mayor valor); no se
suman. Es la versión concreta de "no doble conteo indirecto": posición y contenido, o
regla fiscal e histórico que aprendió esa misma regla, no pueden inflar el score.

| Familia | Señal | Pts | Cuenta solo si |
|---|---|---|---|
| `DETERMINISTIC` | resultado `PASS` de una validación fuerte: aritmética (con tolerancia explícita, §7), checksum, regla fiscal, coincidencia con el QR | **+3** | la regla declara contra qué evidencia refuta **y que dispone de todos sus componentes**; si no, `UNKNOWN` |
| `DOCUMENT_CONTENT` | **ancla verificada**: el contenido en la ubicación coincide con `raw_value` y la etiqueta/contexto es compatible con el campo | **+2** | `verified: true` (§4.2); tener bbox no alcanza |
| `CROSS_MODAL` | texto-lane final y vision-lane final coinciden en `normalized_value` | **+2** | corrieron ambas lanes (distinto material, I1) |
| `SAME_MATERIAL` | B no refuta (`agree`) en el mismo lane; o regexp coincide con A | **+1** (tope 1 aunque ocurran ambas) | mismo lane: nunca puntúa como +2 |
| `LAYOUT_HISTORY` | posición coincide con un template **activo** (emisor + tipo + layout, §9) | **+1** | el template está activo; el schema-visual no fue input del extractor; no se apoya en la misma regla que ya dio +3 |
| Refutación blanda | reviewer `disagree`; layout `MISMATCH` contra un template **activo**; validador en `FAIL` que no está en la lista de vetos (§6.3) | **−2** | uno por familia |
| Evidencia directa en contra | el documento apunta a otro valor para ese campo | **−3** | verificada mecánicamente |

`uncertain` de B es neutro. Los puntajes son punto de partida, no medidos.

**Resultado de los validadores (I10).** Todo validador responde en tres estados. La falta
de información nunca se convierte en error:

| Estado | Efecto | Ejemplos |
|---|---|---|
| `PASS` | suma los puntos de su familia | checksum válido; la aritmética cierra; el QR coincide; el layout coincide con un template activo |
| `FAIL` | veto si está en la lista de §6.3; si no, refutación blanda (−2) | checksum inválido; la aritmética no cierra *con todos los componentes presentes*; el layout no coincide con un template activo |
| `UNKNOWN` | 0 puntos, sin penalización, nunca veta | aritmética sin todos los componentes; sin template activo; documento sin QR; capa de texto dudosa |

Cada validador puede exponer su vocabulario propio (MATCH / MISMATCH, MATCH / CONFLICT /
NOT_AVAILABLE) mapeado a estos tres estados. El `CONFLICT` del QR es un caso aparte: no
veta ni resta a ningún candidato, activa el flag `conflicto_qr` (§6.5). La ausencia de
evidencia se expresa como puntos que no se cobran, no como un −2 adicional; por eso v6
elimina la refutación por "evidencia insuficiente".

### 6.3 Refutaciones duras (veto)

Un candidato con refutación dura queda **vetado**: no puede ser ganador, no cuenta como
segundo candidato, y se conserva en la traza. Ninguna suma de señales lo rehabilita (I3).

Lista cerrada (todo lo que no esté acá es blando):

- CUIT con checksum inválido, o con largo/formato imposible.
- **CUIT propio como `cuit_emisor`** (regla fija desde el día uno, no depende de aprendizaje;
  requiere la lista de CUIT propios como configuración).
- Fecha inexistente, o valor que no parsea contra el schema.
- Inconsistencia aritmética fuera de la tolerancia declarada, **solo si la regla declara que
  dispone de todos los componentes** requeridos para esa clase de comprobante (ver 6.4). Si
  falta alguno, el resultado es `UNKNOWN`, no `FAIL`.

Si todos los candidatos de un campo quedan vetados → `resolver` (§7) o escalar.

### 6.4 Grupos de consistencia

Las reglas aritméticas no refutan un campo aislado sino una **combinación** de candidatos:
`{subtotal, IVA, otros tributos, total}`. El motor evalúa combinaciones; si exactamente una
es consistente, esa recibe el +3 y las demás quedan vetadas; si hay más de una consistente,
o ninguna, se escala (`ESC_NO_UNIQUE_ARITHMETIC_COMBINATION`).

**Precondición de completitud.** Cada regla declara sus `required_components` según el
`tipo_comprobante` (neto, IVA por alícuota, percepciones, retenciones, otros tributos,
bonificaciones, redondeo; una Factura C no discrimina IVA). Solo si todos están presentes
con candidato la regla puede dar `PASS` o `FAIL`. Si falta alguno, da `UNKNOWN`: no puntúa,
no veta, y el campo queda en la situación "sin determinístico aplicable" del Anexo A. Un
modelo de ecuación incompleto no puede producir un veto.

Los ítems de línea quedan fuera de alcance en esta versión, salvo como insumo de la suma
que valida el subtotal.

### 6.5 Decisión

```
por campo:
  candidatos = agrupar por normalized_value (§5), excluir vetados
  ganador    = argmax(score);  segundo = siguiente mejor (score 0 si no hay)

  CONFIRMADO   si:  ganador.score >= T_confirmar(severidad, tier)
                AND ganador.score - segundo.score >= margen(severidad)
                AND gate(severidad) satisfecho
                AND sin conflicto QR ↔ impreso
  ESCALAR      si:  ganador.score < 2, o todos los candidatos vetados
  REVISAR      en cualquier otro caso
```

| Severidad | Campos | T nativo | T OCR | Margen | Gate (evidencia fuerte, obligatoria) |
|---|---|---|---|---|---|
| crítica | total, IVA | 5 | 5 | ≥ 2 | `DETERMINISTIC` o `CROSS_MODAL` |
| alta | CUIT, fecha | 3 | 5 | ≥ 2 | `DETERMINISTIC`, `CROSS_MODAL` o **ancla nativa** |
| media | razón social | 3 | 4 | ≥ 1 | — |
| baja | descripción, categoría | 3 | 4 | ≥ 1 | — |

**Ancla nativa.** Vale como evidencia fuerte solo si se cumple todo:

1. tier `texto_nativo` con capa de texto íntegra (§2);
2. contenido verificado en la ubicación (`verified: true`);
3. la etiqueta pertenece a una lista blanca por campo (fecha: "Fecha de emisión" o equivalente,
   no "Vto." ni "Período"; CUIT: bloque del emisor);
4. **unicidad**: no hay otra ocurrencia con la misma etiqueta de rol y distinto valor.

En texto nativo no hay error de OCR que detectar; el riesgo restante es de razonamiento
del modelo o de confusión de etiqueta, y eso lo cubren A/B, regexp y los puntos 3 y 4. **No
vale para campos críticos**: en total/IVA hay ambigüedad de etiqueta (subtotal, total en
otra moneda) y el costo del error es mayor, así que exigen determinístico o cruce.

**Por qué el umbral OCR es más alto:** en OCR el `DOCUMENT_CONTENT` se verifica contra el
mismo pipeline que produjo el texto, así que prueba trazabilidad, no corrección. La
fuerza tiene que venir del cruce o de una regla determinística.

Los valores de T, margen y el corte de escalamiento (2) son **iniciales y no medidos**,
elegidos para que todo par (campo, tier) tenga camino a CONFIRMADO (Anexo A, I8).
Calibrar con el mecanismo de §9.

**Salida por campo:**

```
señales → vetos → ganador/margen → gate
   ├─ CONFIRMADO        → SYSTEM_CONFIRMED
   ├─ REVISAR/RESOLVER  → ¿algún refutador mecánico dirime?
   │                          ├─ sí → resolver (§7) → vuelve al motor
   │                          └─ no → ¿falta una lane?  sí → correrla a demanda → motor
   │                                                    no → escalar (§8)
   └─ ESCALAR           → escalar (§8), directo al frontier
```

**Códigos de razón.** Cada decisión de campo registra uno o más códigos estables. Son el
`motivo` de `escalar(...)` en §8 (el conteo de motivos repetidos por emisor/patrón sale de
acá) y la base de métricas, dashboards, análisis de escalamiento y explicación al humano.

| Código | Resultado | Cuándo |
|---|---|---|
| `CONF_SCORE_MARGIN_GATE` | CONFIRMADO | score ≥ T, margen y gate cumplidos |
| `REV_SCORE_MID` | REVISAR | score entre 2 y T |
| `REV_CLOSE_MARGIN` | REVISAR | margen insuficiente frente al segundo candidato |
| `REV_GATE_UNMET` | REVISAR | score suficiente pero sin evidencia fuerte |
| `REV_REVIEWER_CONFLICT` | REVISAR | B en `disagree` con `suggested_value` en disputa |
| `REV_QR_CONFLICT` | REVISAR | QR distinto del valor impreso |
| `ESC_LOW_SCORE` | ESCALAR | ganador con score < 2 |
| `ESC_ALL_VETOED` | ESCALAR | todos los candidatos vetados y `resolver` no aporta uno |
| `ESC_NO_UNIQUE_ARITHMETIC_COMBINATION` | ESCALAR | cero o más de una combinación aritmética consistente |
| `ESC_MISSING_STRONG_EVIDENCE` | ESCALAR | tras correr la lane a demanda sigue sin cumplirse el gate |
| `ESC_QR_CONFLICT` | ESCALAR | el conflicto con el QR persiste tras resolver |
| `ESC_NO_NEW_EVIDENCE` | ESCALAR | `resolver` no cambió candidatos ni señales (§7) |
| `ESC_LOOP_LIMIT` | ESCALAR | se agotaron las 2 vueltas |
| `ESC_DEGRADED_MATERIAL` | ESCALAR | material no legible (§2) |

El objetivo no es sumar modelos, es combinar expertos con errores poco correlacionados.
Un tercer LLM que lee el mismo texto no mueve el score en ninguna categoría de +2;
solo el cruce texto/vision y las reglas determinísticas mueven la aguja.

---

## 7. Resolver (antes "corregir")

El sistema no pisa un valor en silencio: deriva un candidato con traza.

```json
{
  "field": "total",
  "original": { "value": "12.700,00", "source": "ocr" },
  "resolved": {
    "value": "12.100,00",
    "reason": "arithmetic_validator",
    "rule": "VAL_TOTAL_002",
    "tolerance": "0.01"
  },
  "evidence": "subtotal 10.000,00 + iva 21% 2.100,00 = 12.100,00 (exacto)"
}
```

Reglas:

- **Tolerancia explícita.** Ningún validador aritmético acepta "≈". La tolerancia por
  defecto es de un centavo; cualquier redondeo mayor (p. ej. por líneas) debe declararse
  en la regla. Una tolerancia laxa convertiría el +3 en un sello para valores errados.
- El valor resuelto es un **candidato nuevo** (I9): arranca su propio puntaje y depende de
  que subtotal e IVA tengan su propio respaldo (§6.4). Si hay más de una combinación
  consistente, se escala.
- El loop resolver → motor solo reingresa si **cambió el conjunto de candidatos o el de
  señales** (comparados por `normalized_value` y por (familia, resultado)). Si no cambió
  nada, escala directo (`ESC_NO_NEW_EVIDENCE`): repetir el motor sobre la misma evidencia no
  puede dar un resultado distinto. Además tiene tope de **2 vueltas** (`ESC_LOOP_LIMIT`).

---

## 8. Verificación (frontier + HITL)

```
escalar(doc, lecturas_en_disputa, motivo)     # motivo = código de razón (§6.5)
  → (si falta una lane y el motivo es material: correrla a demanda antes de subir)
  → llm_frontier lee el documento original (multimodal)
      → campos_frontier + justificación por campo
  → refutadores mecánicos también sobre campos_frontier (frontier no está exento)
  → comparar contra las lecturas en disputa
       ├─ coincide con una          → candidato + evidencia → humano confirma con un click
       └─ no coincide con ninguna   → todas las lecturas + evidencia → decide el humano
  → humano resuelve → HUMAN_CONFIRMED

  → ¿motivo de escalamiento repetido N veces (mismo emisor/patrón)?
       ├─ sí → frontier propone regla candidata
       │        → backtest contra el histórico HUMAN_CONFIRMED
       │        → si el backtest no rompe casos ya resueltos → pendiente de aprobación humana
       │        → aprobada → activar
       └─ no → se registra el caso, sin proponer regla todavía
```

El backtest corre la regla candidata contra el histórico antes de proponerla, para no
promoverla a partir de un único caso. Decidir qué datos fiscales pueden salir del
perímetro hacia un frontier externo es una decisión de diseño pendiente (ver Notas).

---

## 9. Aprender

**Dos estados de confirmación:**

| Estado | Origen | Uso |
|---|---|---|
| `SYSTEM_CONFIRMED` | el motor lo confirmó (§6.5) | procesamiento automático y estadísticas en sombra; **no es ground truth** |
| `HUMAN_CONFIRMED` | resolvió un humano (§8) o una muestra de auditoría | ground truth: activa lo aprendido, calibra umbrales, entrena cualquier meta-modelo futuro |

**Dos canales de aprendizaje separados (I7):**

| Canal | Qué alimenta | Fuente permitida |
|---|---|---|
| Estadísticas operativas **en sombra** | frecuencias por emisor/tipo, posiciones observadas, conteos, distribución de scores, detección de drift | `SYSTEM_CONFIRMED` y `HUMAN_CONFIRMED`. **Sin efecto en el score.** |
| Aprendizaje **con efecto** | templates activos, perfil de emisor usado como señal, umbrales, reglas candidatas (§8), meta-modelos | solo `HUMAN_CONFIRMED` |

La razón: bloquear que el histórico confirme lo que él mismo enseñó no alcanza. Si todos los
modelos leen mal el mismo campo de un template y el documento supera el umbral sin usar
layout, esa lectura entraría como aprendizaje, y `LAYOUT_HISTORY` reforzaría el error en los
documentos siguientes. Un error sistemático y correlacionado solo lo detecta un humano.

Nunca se aprende de una lectura cruda, de `campos_frontier` sin confirmar, ni de un
`resolved` que no volvió a pasar por el motor.

**Clave del schema-visual:** `(emisor, tipo_comprobante, layout_fingerprint)`. El fingerprint
es una huella tolerante de posiciones normalizadas de etiquetas ancla y logo.

**Ciclo de vida de un template:**

```
shadow → active → stale → retired
```

| Estado | Condición | Efecto en el score |
|---|---|---|
| `shadow` | se vio un fingerprint nuevo; se acumulan estadísticas en sombra. Sus primeros documentos entran a auditoría con prioridad (inicial: los primeros 3) para acelerar la activación | ninguno |
| `active` | k observaciones `HUMAN_CONFIRMED` consistentes entre sí y con las estadísticas en sombra (k inicial = 3, sin medir) | `LAYOUT_HISTORY`: MATCH +1; MISMATCH −2 |
| `stale` | no visto en N días (a definir), o mismatches recientes que un humano confirmó como layout nuevo | señal `UNKNOWN`: nunca MISMATCH, hasta re-confirmar |
| `retired` | reemplazado por un template nuevo del mismo emisor, o descartado | ninguno |

Cada template guarda `first_seen`, `last_seen`, `sample_count_human`, `sample_count_shadow`
y `state`. Un layout nuevo de un emisor conocido no es una anomalía: mientras no haya
template activo coincidente, la señal es `UNKNOWN`, ni positiva ni negativa. Un decaimiento
continuo de confianza queda como mejora posible; con estados discretos alcanza para empezar.
Como `LAYOUT_HISTORY` vale solo +1 y el Anexo A se sostiene sin ella, exigir activación
humana cuesta poco score y evita el error sistemático.

**Calibración y auditoría por riesgo:** el backtest y los umbrales se calibran con
`HUMAN_CONFIRMED` más una **muestra aleatoria auditada de los `SYSTEM_CONFIRMED`**. Sin esa
muestra la calibración es circular: se mediría el motor contra sus propias confirmaciones y
no habría forma de estimar la tasa de falsos confirmados. La tasa de auditoría se define por
severidad, por campo confirmado (valores iniciales, a reducir cuando haya evidencia):

| Severidad | Tasa inicial de auditoría |
|---|---|
| crítica | 20 % |
| alta | 10 % |
| media | 5 % |
| baja | 2 % |

Estratificar además por tier y por template (`shadow` o emisor nuevo), porque los errores se
concentran ahí.

---

## Notas / pendientes

- **Versionado transversal**: cada decisión debe poder reconstruirse: versión de prompt,
  schema, reglas y, por cada extractor, el objeto completo de modelo (`role`, `family`,
  `variant`, `quantization`, `runtime`, `prompt_version`). No es un paso del flujo, es un
  requisito de logging en cada paso que genera evidencia.
- **Tasa de escalamiento esperada al frontier**: sigue sin medirse; condiciona si el diseño
  de costos de §8 es sostenible a volumen. El Anexo A muestra qué caminos existen, no
  cuánto tráfico los toma.
- **Umbrales y puntajes sin calibrar** (§6): la métrica objetivo es la **tasa de falsos
  confirmados por campo** sobre la muestra auditada, con meta cercana a cero en campos
  críticos. Optimizar por costo del error, no por accuracy global.
- **Métricas del revisor B** (requieren `HUMAN_CONFIRMED`):
  `critic_disagreement_rate`; `critic_useful_disagreement_rate` (A estaba mal y B tenía
  razón); `critic_false_alarm_rate` (B disputa un A correcto); y
  **`critic_missed_error_rate`** (A estaba mal y B dijo `agree`), probablemente la más
  importante: mide cuánto vale realmente el +1 de `SAME_MATERIAL`. B es más débil que A en
  ambos lanes (gemma3 vs. deepseek-r1; Granite 2B vs. qwen2.5vl): vigilar que no genere ruido
  que sature REVISAR.
- **Independencia entre lanes**: `cross_modal_correlated_error_rate`, la proporción de casos
  en que texto y vision coinciden en un valor que `HUMAN_CONFIRMED` marca como incorrecto.
  Si es alta, el +2 de `CROSS_MODAL` está sobrevalorado y hay que diversificar más los
  pipelines (§4.2).
- **Tamaño de la muestra de auditoría**: con cero errores en n muestras auditadas, la cota
  superior al 95 % de la tasa de falsos confirmados es aproximadamente 3/n (regla del tres).
  Para sostener una meta cercana a 1 % en un campo crítico hacen falta del orden de 300
  campos auditados sin error, antes de bajar la tasa de auditoría.
- **Trade-off aceptado en el patrón A/B (§4):** que B vea la respuesta de A introduce
  sesgo de anclaje. Es más barato que una segunda extracción a ciegas, pero más débil. Si
  en producción B rara vez discrepa (posible rubber-stamping), medir cuánto cambia el
  comportamiento si B extrae primero sin ver a A.
- **Validadores determinísticos** que alimentan el +3 y los vetos: pueden tipificarse
  (sintácticos, aritméticos, de evidencia, de posición, de reglas de negocio) a medida que
  se agreguen; alcanza con que cada uno declare contra qué evidencia refuta.
- **Fuentes determinísticas opcionales**: constatación del comprobante contra ARCA
  (validador a nivel documento; responde si el comprobante es auténtico, no si se leyó
  bien, que es lo que mide el QR) y consulta de razón social por CUIT en el padrón (daría a
  un campo de severidad media una señal `DETERMINISTIC`). Ambas dependen de conectividad y
  credenciales.
- **Frontier y datos sensibles**: definir qué campos o documentos pueden salir del
  perímetro local. Los modelos de extracción son locales; §8 introduce un componente que
  quizá no lo sea.
- **Ítems de línea**: fuera de alcance de esta versión (§6.4); definir cómo se puntúan si se
  necesitan como salida.
- **Siguiente entregable**: este documento cierra el diseño del flujo. Lo que falta es el
  contrato de datos de runtime: `FieldCandidate`, `EvidenceSignal` (con `result`),
  `FieldDecision` (con códigos de razón) y `DecisionTrace`, más el pseudocódigo exacto del
  Decision Engine. El modelo de datos sale casi literal de §5 y §6.5.

---

## Anexo A. Alcanzabilidad de CONFIRMADO (verificación de I8)

Máximo score posible, con **todas** las señales positivas aplicables presentes y sin
señales negativas. "Emisor nuevo" = sin template **activo**; "template" = con `LAYOUT_HISTORY`.
`CROSS_MODAL` solo existe si corrieron ambas lanes. Como los templates se activan por
confirmación humana (§9), la columna "emisor nuevo" es la que rige al comienzo y para todo
emisor con pocos documentos confirmados.

| Campo | Tier | ¿Determinístico aplicable? | T | Máx. emisor nuevo | Máx. con template | ¿Alcanza? |
|---|---|---|---|---|---|---|
| total, IVA | texto_nativo | sí (aritmética completa / QR) | 5 | 6 | 7 | sí |
| total, IVA | texto_nativo | no (aritmética `UNKNOWN`, sin QR) | 5 | 3 | 4 | **no** → lane vision a demanda |
| total, IVA | nativo + vision a demanda | no | 5 | 5 | 6 | sí |
| total, IVA | escaneado_ocr | sí | 5 | 8 | 9 | sí |
| total, IVA | escaneado_ocr | no | 5 | 5 | 6 | sí |
| CUIT | texto_nativo | sí (checksum) | 3 | 6 | 7 | sí |
| CUIT | escaneado_ocr | sí (checksum) | 5 | 8 | 9 | sí |
| fecha | texto_nativo | no (salvo QR) | 3 | 3 | 4 | sí (vía ancla nativa) |
| fecha | escaneado_ocr | no (salvo QR) | 5 | 5 | 6 | sí |
| razón social | texto_nativo | no | 3 | 3 | 4 | sí |
| razón social | escaneado_ocr | no | 4 | 5 | 6 | sí |
| descripción, categoría | texto_nativo | no | 3 | 3 | 4 | sí |
| descripción, categoría | escaneado_ocr | no | 4 | 5 | 6 | sí |

"Aplicable" significa que la regla tiene todos sus componentes (resultado `PASS`/`FAIL`, no
`UNKNOWN`, §6.4) o que hay QR. La única celda inalcanzable es intencional: total/IVA en texto
nativo *sin* ningún determinístico aplicable (componentes faltantes y sin QR) no puede confirmarse con una sola
lane; la escalera corre la lane vision a demanda antes de subir al frontier.

**Por qué existe este anexo.** Con los parámetros de v4 (umbral 6 para todo, sin
cruce de lanes en texto nativo) razón social, descripción y categoría en `texto_nativo`
tenían techo 4 y **no podían confirmarse nunca**, y `fecha` no podía pasar el gate por
falta de una validación "fuerte". Esta tabla debe regenerarse, como test automático, cada
vez que cambien puntajes, umbrales o el conjunto de señales.

---

## Anexo B. Lecciones de la implementación

Lo que enseñó construir el flujo en `scripts/poc-flow/` (`flow/report.py`,
`flow/progress.py`, `flow/persist.py`, `flow/run.py`). No son decisiones nuevas: donde una
lección contradiga un §, manda el §. Son el registro de qué costó, para no volver a
pagarlo.

### B.1 Trazabilidad: dos audiencias, dos salidas

El primer error fue volcar el JSON del motor a stdout. El JSON es el contrato de la
máquina—`FieldResult`: decisiones, traza de candidatos, confirmados, notas—y **no es un
reporte**. Un operador tenía que deducir de él por dónde había pasado el flujo y qué
archivo abrir, que son justo las dos preguntas que el JSON no está hecho para contestar.

| Audiencia | Salida | Contenido |
|---|---|---|
| Persona | stdout | `path` (por dónde pasó), decisiones por resultado, `read next`, `notes` |
| Programa | stdout con `--json` | el `FieldResult` completo, con la traza de señales |

Tres reglas que salieron de ahí:

1. **El reporte no recalcula nada.** Lee `FieldResult` y el trace; si puntuara sus propios
   candidatos sería un segundo motor, y los dos podrían discrepar.
2. **El reporte no nombra un archivo que no se escribió.** Una ruta listada es una
   instrucción; una inventada es una instrucción falsa. Por eso el reporte deriva
   `read next` de los artefactos que los steps registraron, no de una lista fija.
3. **La traza es del runtime, no del reporte.** Cada step registra su resultado y sus
   archivos como dato (`StepTrace`), y el reporte los imprime. Guardar el resultado en el
   mismo lugar donde se genera es lo que evita que los dos se desincronicen.

### B.2 Los stages son la unidad, no un detalle de implementación

`read → extract → decide → hitl` como funciones separadas no fue cosmética: es lo que hace
posible reanudar, correr un solo stage, y nombrar el archivo de cada etapa.

| Stage | Entradas (`STAGE_DEPENDENCIES`) | Artefacto declarado (`STAGE_ARTIFACTS`) |
|---|---|---|
| `read` | — | `material.json`, `images/` |
| `extract` | `read` | `extraction.json` |
| `decide` | `extract` | `decision.json` |
| `hitl` | `decide` | `pending.json` (+ `resolution.json`, `confirmed.json`) |

Todo stage declara lo mismo en **un** lugar (`STAGE_DEPENDENCIES`, `STAGE_ARTIFACTS` en
`persist.py`). Nada de lo que hace el stage está escrito dos veces; y el nombre del
artefacto vive en un solo sitio. Si el journal, el reporte y el guardado llevan cada uno su
propia lista, tarde o temprano el reporte nombra un archivo que se llama distinto.

### B.3 `ran` no es `reused`

Un run reanudado se lee igual que uno completo si el reporte no lo distingue. Importa para
lo único que importa en un PoC de modelos locales: saber si la respuesta que estás leyendo
la produjo una llamada de hoy o un artefacto de la semana pasada. Por eso cada paso del
`path` dice `ran` o `reused`, y un stage reusado no se atribuye el trabajo del que lo
antecede.

### B.4 El progreso en vivo va a stderr

El `verbose` no es diagnóstico decorativo: es la única traza en vivo, y en un flujo con OCR
y generaciones locales el silencio de un minuto no se distingue de un cuelgue.

- **La respuesta va a stdout, el progreso a stderr.** Una nota de reanudación impresa en
  stdout corrompería el reporte; es la misma razón por la que `announce()` escribe a stderr.
- **Un solo dueño del switch.** El módulo de progreso configura la verbosidad una vez y
  todos los stages emiten por él; un stage que imprimiera por su cuenta rompería el
  contrato sin que nadie lo note.
- **La traza se registra siempre**, con o sin `--verbose`: el `path` del reporte no es un
  extra de la verbosidad, es la respuesta a "¿por dónde pasó?".
- Un `emit` apagado es un **no-op**, no un buffer que alguien vacía después.

### B.5 Reanudar: cuatro reglas, cada una por un fallo

| Regla | Sin ella |
|---|---|
| Un stage se marca `done` **después** de escribir su artefacto | una excepción a mitad de camino dejaría el stage marcado como hecho |
| Toda escritura es temp + rename | un `kill` en el medio dejaría un artefacto truncado y creíble |
| El journal lleva el sha256 del documento | editar el PDF reusaría la lectura de la versión anterior |
| La firma cubre los diales, los CUIT propios y un digest de cada prompt y schema | cambiar un prompt reusaría la extracción del prompt viejo |

Dos detalles que sólo aparecen al implementarlo:

- **Invalidar no es borrar.** Re-correr un stage intermedio marca como no-hechos ese stage y
  todos los posteriores, pero deja los archivos: el journal deja de confiar en ellos. Si el
  proceso muere justo después, el próximo arranque no lee estado a medio invalidar.
- **Al fingerprintear, los conjuntos se ordenan.** El orden de iteración de un `set` o
  `frozenset` depende de la aleatorización de hashes: una firma construida sobre un conjunto
  sin ordenar cambiaría en cada corrida y descartaría el journal **siempre**. Es un bug
  silencioso: parece que el journal no funciona, no que la firma está mal.

### B.6 Formatear es una decisión de audiencia, no de estilo

El mismo dato necesita **dos** serializaciones, y confundirlas rompe algo:

| Serialización | Para quién | Cómo | Si se confunde |
|---|---|---|---|
| La firma (`work_signature`) | la máquina | canónica: `sort_keys`, sin indentar | el journal se descarta en cada corrida |
| El artefacto (`decision.json`, …) | la persona | `indent=2`, `ensure_ascii=False` | un archivo de una sola línea que nadie lee ni puede `diff`ear |

Un `decision.json` compacto no es un artefacto: es un volcado. `pending.json` es la cola que
un humano abre para trabajar; si está en una línea, no se abre.

Y en el reporte: **cabe en 80 columnas**. El valor largo se corta con `…`, y la explicación
del motor va en una línea indentada `why:` debajo de la fila. Una fila que se envuelve deja
de ser una tabla.
### B.7 Lo que mostró una corrida real (`texto_nativo`, smoke run)

Documento `tests/fixtures/casos/66cd35e9-…pdf`, tier `texto_nativo`, una página: 2
`CONFIRMED` (CUIT por checksum, fecha por regla de fecha), el resto repartido entre
`REVIEW` y `ESCALATE`. Vale registrar por qué, porque cada caso es una lección:

- **El número de campos no es constante** (15 o 16 entre corridas, con el mismo documento y
  el mismo prompt): cambia lo que el modelo devuelve, no el documento. Una métrica sobre
  "campos extraídos" mide al modelo tanto como al comprobante; la que importa es la de
  confirmados por campo.
- **`importe_total_facturado` e `iva` quedaron en `REV_GATE_UNMET`**, no en escalamiento:
  score 2 ≥ piso, pero sin `DETERMINISTIC` ni `CROSS_MODAL`. Es **la celda inalcanzable del
  Anexo A apareciendo en la práctica**: sin lane vision y sin aritmética aplicable, un campo
  crítico en `texto_nativo` no confirma. La lane a demanda de §6.5 no es una optimización,
  es la condición para que ese par (campo, tier) tenga camino.
- **`iva` volvió `"21,0%"`** y el validador aritmético contestó `UNKNOWN` ("a component is
  not a plain amount"). Es lo correcto (§6.4: sin todos los componentes no hay `FAIL`, y sin
  `FAIL` no hay veto), pero muestra que **un componente de una regla tiene contrato de
  forma**: la aritmética necesita importes, y una alícuota no lo es. Va con
  `required_components`.
- **La lane B no devolvió veredictos** ("text lane B produced no review verdicts"). Sin
  `SAME_MATERIAL`, los campos de severidad baja quedan con techo 2 (`DOCUMENT_CONTENT`) y no
  alcanzan T=3. Un lane que no corre se reporta como nota; nunca como un cero silencioso.
- **Campos de severidad baja con un solo productor y ninguna señal `PASS`** puntúan 0 y
  escalan (`ESC_LOW_SCORE`): un valor sin ninguna evidencia que lo respalde no es un
  candidato débil, es un candidato sin evidencia.
- **El modelo contestó con la descripción del schema.** `tipo_comprobante` volvió
  `"A | B | C | 090 | 099"` y `condicion_impositiva_dominante` `"21 | 10_5 | 27 | 2_5 |
  exento_no_gravado | null"`: ese texto es, literalmente, el `description` de cada campo en
  `extraction.json`, porque ahí las opciones se declaran como texto libre y no como `enum`.
  Es un **artefacto de parseo, no una lectura**. Arreglo: declarar el `enum` de verdad, o
  descartar en el productor todo valor idéntico a la descripción del campo. Nota que el
  motor igual hizo lo correcto — el candidato no tiene ninguna señal `PASS`, así que escaló
  en vez de confirmar basura.

La conclusión de la corrida es a favor del diseño, no en contra: el motor no confirmó nada
que no pudiera sostener, y los campos que no confirmó son exactamente los que no tenían
evidencia fuerte disponible. Lo que falta no es un umbral más bajo, es la escalera de §6.5.

### B.8 Convenciones que pagaron

- **La librería es el entregable; el CLI es un cliente.** `myflow.py` parsea argumentos e
  imprime; todo lo demás es una llamada a la librería.
- **Un solo dueño por nombre de campo.** `SUBTOTAL_FIELD` / `IVA_FIELD` / `TOTAL_FIELD`
  existen una vez, porque el schema y el motor tienen que nombrar lo mismo.
- **Una negativa es una nota, no una excepción.** Un modelo que no contesta, una lane sin
  configurar: se registran en `notes` y el flujo sigue. Lo que no se hace nunca es
  sustituir la respuesta por un valor por defecto.
- **El reporte no importa `docflow`.** Es lo que permite ejercitarlo con valores
  construidos, sin adapters ni modelos.
- **Las gates corren sobre este árbol aunque `pytest` no lo colecte**: `ruff check`,
  `ruff format --check` y `pylint` sobre `scripts/poc-flow/` son parte del cierre, y los
  módulos puros (`route`, `validators`, `fields`, `engine`, `report`, `progress`) no
  necesitan un modelo para probarse.
