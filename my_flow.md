# Flujo de extracción de comprobantes fiscales (v5)

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
| I7 | **El histórico no se confirma a sí mismo.** Una observación no alimenta el schema-visual si solo se confirmó gracias al schema-visual. | §9 |
| I8 | **Alcanzabilidad.** Todo par (campo, tier) tiene un camino a CONFIRMADO o una escalera de escalamiento explícita. Se verifica automáticamente cada vez que cambian puntajes o umbrales. | Anexo A |
| I9 | **Nada se pisa en silencio.** `resolver` deriva candidatos con traza y siempre vuelven al motor. | §7 |

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

El prompt y los schemas los edita un humano. El schema-visual lo actualiza el propio
sistema (§9), solo desde observaciones que cumplan I6 e I7.

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
       ├─ CONFIRMADO        → SYSTEM_CONFIRMED → aprender (solo bajo I6/I7)
       ├─ REVISAR/RESOLVER  → resolver (§7) → motor (loop, máx. 2 vueltas)
       │                        └─ sin refutador → lane faltante a demanda → motor
       │                                             └─ sigue sin cerrar → frontier (§8)
       └─ ESCALAR (score bajo / todo vetado / material degradado) → frontier (§8)
                                                  └→ humano → HUMAN_CONFIRMED → aprender
```

**Cambios vs. v4:**

- Se agregan los **invariantes** y las **familias de evidencia** con tope por familia (§6.2).
- El **gate de campos críticos** pasa de "cruce de lanes o determinístico" a un concepto
  de *evidencia fuerte* por severidad, para no escalar PDFs nativos perfectos (§6.5).
- **Refutaciones duras** (veto) separadas de las blandas (§6.3).
- **Margen** entre primer y segundo candidato además del score absoluto (§6.5).
- **Umbrales por severidad y tier**, elegidos para ser alcanzables (Anexo A).
- Evidencia dividida en **ubicación** y **contenido**; el +2 exige verificación mecánica (§4.2).
- `regexp` y **QR** entran como productores de candidatos (§4.2, §6.1).
- **schema-visual** por emisor + tipo + layout (§0, §9).
- **SYSTEM_CONFIRMED vs. HUMAN_CONFIRMED** (§9).
- Escalera con **lane a demanda** antes del frontier (§1, §8).
- Ejemplo aritmético corregido y **tolerancia explícita** (§7).

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
  → decodificar QR, si hay (ver abajo) → candidatos + señal determinística

  salida: candidatos de cada lane con su veredicto de B, SIN fusionar entre lanes;
          eso lo resuelve el motor de decisión (§6)
```

**QR de comprobante electrónico (si los comprobantes son argentinos con CAE).** Las
facturas electrónicas traen un QR de ARCA cuyo payload incluye fecha, CUIT del emisor,
punto de venta, tipo y número de comprobante, importe, moneda, tipo y número de documento
del receptor, y código de autorización. Decodificarlo es determinístico y no depende de
ningún LLM ni de OCR: cubre justo los campos críticos y distingue emisor de receptor por
construcción. Un desacuerdo QR ↔ texto impreso **no se resuelve por puntaje**: fuerza
REVISAR o escalar (puede ser un error de lectura o un comprobante inconsistente).

**Dos ejes de refutación, no uno solo:**
- **Dentro de cada lane** (A/B, mismo material, modelos distintos) → refuta errores de
  *razonamiento del modelo* sobre ese material.
- **Entre lanes** (texto vs. vision) → el único par que puede refutar un error de
  *OCR/material*. El chequeo A/B no lo reemplaza, lo complementa.

**Límite de la independencia entre lanes.** Ambas lanes parten del mismo render y del
mismo preprocesado (§2). En escaneos degradados los errores pueden estar correlacionados.
Mitigación recomendada: que la lane vision use una resolución o preprocesado distinto al
del OCR, o al menos que el chequeo de legibilidad sea estricto.

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
        { "family": "DETERMINISTIC",    "rule": "VAL_TOTAL_002", "points": 3 },
        { "family": "DOCUMENT_CONTENT", "verified": true,       "points": 2 },
        { "family": "CROSS_MODAL",                              "points": 2 },
        { "family": "SAME_MATERIAL",    "detail": "B agree + regexp", "points": 1 }
      ],
      "hard_refutations": [],
      "score": 8
    },
    {
      "normalized_value": "125840.50",
      "producers": ["vision_B_sugerido"],
      "signals": [ { "family": "DOCUMENT_CONTENT", "verified": false, "points": 0 } ],
      "hard_refutations": [ { "rule": "VAL_TOTAL_002", "reason": "combinación subtotal+IVA+total inconsistente" } ],
      "score": null,
      "status": "vetado"
    }
  ]
}
```

(`SAME_MATERIAL` suma +1 aunque coincidan B y regexp: tope por familia, §6.2.)

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
| QR | produce candidatos y señal determinística | §4.2 |
| Validadores determinísticos | apoyan o refutan | refutadores mecánicos |
| Histórico / schema-visual | contexto de posición por (emisor, tipo, layout) | §0, §9 |

### 6.2 Señales, familias y tope

**Regla I4:** dentro de una misma familia se toma **una** señal (la de mayor valor); no se
suman. Es la versión concreta de "no doble conteo indirecto": posición y contenido, o
regla fiscal e histórico que aprendió esa misma regla, no pueden inflar el score.

| Familia | Señal | Pts | Cuenta solo si |
|---|---|---|---|
| `DETERMINISTIC` | validación fuerte: aritmética (con tolerancia explícita, §7), checksum, regla fiscal, coincidencia con QR | **+3** | la regla declara contra qué evidencia refuta |
| `DOCUMENT_CONTENT` | **ancla verificada**: el contenido en la ubicación coincide con `raw_value` y la etiqueta/contexto es compatible con el campo | **+2** | `verified: true` (§4.2); tener bbox no alcanza |
| `CROSS_MODAL` | texto-lane final y vision-lane final coinciden en `normalized_value` | **+2** | corrieron ambas lanes (distinto material, I1) |
| `SAME_MATERIAL` | B no refuta (`agree`) en el mismo lane; o regexp coincide con A | **+1** (tope 1 aunque ocurran ambas) | mismo lane: nunca puntúa como +2 |
| `LAYOUT_HISTORY` | posición coincide con un template conocido (emisor + tipo + layout) | **+1** | el template existe; el schema-visual no fue input del extractor; no se apoya en la misma regla que ya dio +3 |
| Refutación blanda | reviewer `disagree`, mismatch de layout contra template conocido, evidencia insuficiente | **−2** | uno por familia |
| Evidencia directa en contra | el documento apunta a otro valor para ese campo | **−3** | verificada mecánicamente |

`uncertain` de B es neutro. Los puntajes son punto de partida, no medidos.

### 6.3 Refutaciones duras (veto)

Un candidato con refutación dura queda **vetado**: no puede ser ganador, no cuenta como
segundo candidato, y se conserva en la traza. Ninguna suma de señales lo rehabilita (I3).

Lista cerrada (todo lo que no esté acá es blando):

- CUIT con checksum inválido, o con largo/formato imposible.
- **CUIT propio como `cuit_emisor`** (regla fija desde el día uno, no depende de aprendizaje;
  requiere la lista de CUIT propios como configuración).
- Fecha inexistente, o valor que no parsea contra el schema.
- Inconsistencia aritmética fuera de la tolerancia declarada (ver 6.4).

Si todos los candidatos de un campo quedan vetados → `resolver` (§7) o escalar.

### 6.4 Grupos de consistencia

Las reglas aritméticas no refutan un campo aislado sino una **combinación** de candidatos:
`{subtotal, IVA, otros tributos, total}`. El motor evalúa combinaciones; si exactamente una
es consistente, esa recibe el +3 y las demás quedan vetadas; si hay más de una consistente,
o ninguna, se escala. El `tipo_comprobante` determina qué campos se esperan (una Factura C
no discrimina IVA). Los ítems de línea quedan fuera de alcance en v5, salvo como insumo de
la suma que valida el subtotal.

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
- El loop resolver → motor tiene tope de **2 vueltas**; después escala.

---

## 8. Verificación (frontier + HITL)

```
escalar(doc, lecturas_en_disputa, motivo)
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
| `SYSTEM_CONFIRMED` | el motor lo confirmó (§6.5) | procesamiento automático; **no es ground truth** |
| `HUMAN_CONFIRMED` | resolvió un humano (§8) o una muestra de auditoría | ground truth; dataset de calibración |

**Qué alimenta el aprendizaje** (perfil del emisor y schema-visual):

- Siempre desde `HUMAN_CONFIRMED`.
- Desde `SYSTEM_CONFIRMED` solo si el candidato **habría alcanzado el umbral sin la señal
  `LAYOUT_HISTORY`** (I7). Así el histórico nunca refuerza un patrón que él mismo confirmó.
- Nunca desde una lectura cruda, desde `campos_frontier` sin confirmar, ni desde un
  `resolved` que no volvió a pasar por el motor.

**Clave del schema-visual:** `(emisor, tipo_comprobante, layout_fingerprint)`. El
fingerprint es una huella tolerante de posiciones normalizadas de etiquetas ancla y logo.
Sin template coincidente no hay señal `LAYOUT_HISTORY` (ni positiva ni negativa): un
layout nuevo de un emisor conocido no es una anomalía. Un mismatch cuenta −2 solo cuando
el fingerprint coincide con un template conocido pero la posición difiere. Un template
nuevo se crea a partir de confirmaciones humanas.

**Calibración:** el backtest y los umbrales se calibran con `HUMAN_CONFIRMED` más una
**muestra aleatoria auditada por un humano de los `SYSTEM_CONFIRMED`** (tasa inicial alta,
p. ej. 10–20 %, a reducir con evidencia). Sin esa muestra la calibración es circular: se
mediría el motor contra sus propias confirmaciones y no habría forma de estimar la tasa de
falsos confirmados.

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
  razón); tasa de falsa alarma (B disputa un A correcto). B es más débil que A en ambos
  lanes (gemma3 vs. deepseek-r1; Granite 2B vs. qwen2.5vl): vigilar que no genere ruido
  que sature REVISAR.
- **Trade-off aceptado en el patrón A/B (§4):** que B vea la respuesta de A introduce
  sesgo de anclaje. Es más barato que una segunda extracción a ciegas, pero más débil. Si
  en producción B rara vez discrepa (posible rubber-stamping), medir cuánto cambia el
  comportamiento si B extrae primero sin ver a A.
- **Validadores determinísticos** que alimentan el +3 y los vetos: pueden tipificarse
  (sintácticos, aritméticos, de evidencia, de posición, de reglas de negocio) a medida que
  se agreguen; alcanza con que cada uno declare contra qué evidencia refuta.
- **Fuentes determinísticas opcionales**: constatación del comprobante contra ARCA
  (validador a nivel documento) y consulta de razón social por CUIT en el padrón (daría a
  un campo de severidad media una señal `DETERMINISTIC`). Ambas dependen de conectividad y
  credenciales.
- **Frontier y datos sensibles**: definir qué campos o documentos pueden salir del
  perímetro local. Los modelos de extracción son locales; §8 introduce un componente que
  quizá no lo sea.
- **Ítems de línea**: fuera de alcance de v5 (§6.4); definir cómo se puntúan si se
  necesitan como salida.

---

## Anexo A. Alcanzabilidad de CONFIRMADO (verificación de I8)

Máximo score posible, con **todas** las señales positivas aplicables presentes y sin
señales negativas. "Emisor nuevo" = sin template de layout; "template" = con `LAYOUT_HISTORY`.
`CROSS_MODAL` solo existe si corrieron ambas lanes.

| Campo | Tier | ¿Determinístico disponible? | T | Máx. emisor nuevo | Máx. con template | ¿Alcanza? |
|---|---|---|---|---|---|---|
| total, IVA | texto_nativo | sí (aritmética / QR) | 5 | 6 | 7 | sí |
| total, IVA | texto_nativo | no | 5 | 3 | 4 | **no** → lane vision a demanda |
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

La única celda inalcanzable es intencional: total/IVA en texto nativo *sin* ningún
determinístico aplicable (sin subtotal, ítems ni QR) no puede confirmarse con una sola
lane; la escalera corre la lane vision a demanda antes de subir al frontier.

**Por qué existe este anexo.** Con los parámetros de v4 (umbral 6 para todo, sin
cruce de lanes en texto nativo) razón social, descripción y categoría en `texto_nativo`
tenían techo 4 y **no podían confirmarse nunca**, y `fecha` no podía pasar el gate por
falta de una validación "fuerte". Esta tabla debe regenerarse, como test automático, cada
vez que cambien puntajes, umbrales o el conjunto de señales.
