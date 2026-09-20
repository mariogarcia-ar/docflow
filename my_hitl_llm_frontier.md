# Validación cruzada por paso: cómo determinar la extracción real y en qué orden

Este documento responde dos preguntas:

1. **¿Cómo se determina la extracción real?** No eligiendo la respuesta que más confía,
   sino ubicando **en qué paso** se rompió la cadena, con evidencia.
2. **¿Cuál es la mejor secuencia?** La que refuta más por menos dinero, y que deja el
   paso caro (vision del frontier) para cuando ya sirve para algo.

Todo lo que sigue está medido en `scripts/poc/`, no propuesto. El caso de trabajo es
`var/run/pdf_escaneados/9b7a423c-…-p1.png` (factura A, La Anónima), donde el modelo
local falló de tres formas distintas y el frontier acertó.

---

## 0. La tesis, en una línea

**Una sola lectura segura no es evidencia de nada.** Lo único que detecta un error
silencioso son **dos lecturas que no comparten nada** y que se contradicen
(`prd.md`, `sad.md` §4). Por eso la estrategia no es "sumar validadores": es
**construir lecturas independientes y conservar la independencia**.

### La regla que se deriva, y que es la que decide el diseño

> **La independencia es una propiedad del prefijo compartido, no del paso.**

Dos lecturas que parten del mismo texto OCR **no son independientes**: comparten el
error de OCR. Si el OCR se comió una línea, las dos leen un documento incompleto y
las dos coinciden — y coincidir se reporta como "verificado".

Corolario, y es el motivo por el que el paso caro existe:

> **`judge` NO PUEDE detectar un error de OCR**, porque califica la transcripción, y
> la transcripción **es** la salida del OCR. Medido por introspección:
> `inspect.signature(FrontierEngine.judge)` no tiene parámetro `images`, su cuerpo no
> nombra `images`, y delega en `structured`. Califica un guion.

Así que la comparación que sí tiene poder de refutación es:

**campos derivados del texto (OCR) × campos derivados de los píxeles (vision).**

Ese par comparte **solo el documento**. Todo lo demás — ruteo, DPI, motor de OCR,
modelo, tokenizador — es distinto. Esa es la comparación que el usuario propuso, y es
la correcta. El resto de este documento es cómo llegar ahí sin gastar de más y cómo
**localizar** el problema cuando aparece.

---

## 1. Qué artefacto deja cada paso

Cada frontera tiene que dejar un artefacto, porque una validación que no puede leer
lo que el paso anterior produjo no valida nada.

| # | Paso | Operación | Artefacto | Aísla |
|---|---|---|---|---|
| 1 | Cortar / contar | K2 `probe` | `page_count` (en `measurements`) | — |
| 2 | Clasificar por página | K2 `classify` | `shape` ∈ {text, image, mixed, blank} | — |
| 3 | Rutear | `pdf.route_page` / `decide.decide` | nombre de ruta + razón | la decisión |
| 4a | Texto | K2 `layout_text` | `.txt` con `\f` por página | motor de texto |
| 4b | Píxeles | K2 `render` | `.png` | DPI efectivo |
| 5 | OCR | K4 `layout` (texto) + `read` (censo) | `.txt` + `.ocr.json` | motor de OCR |
| 6 | Legibilidad | K3 `legibility` | `sharpness` vs umbral | calidad de imagen |
| 7 | Campos desde texto | K5 `structured` | `<stem>.fields.json` | el **modelo** |
| 8 | Campos desde píxeles | K5 `vision` (`qwen2.5vl`) | `<stem>.fields.json` | el **ruteo/OCR** |
| 9 | Campos desde píxeles (frontier) | K6 `vision` | ver §3 | modelo + material |
| 10 | Veredicto sobre los campos | K6 `judge` | `<stem>.frontier.json` | consistencia **interna** |
| 11 | Contraste mecánico | `hitl.py` | `review.json` | emparejamiento |

Los pasos 4b→5 y 7→8 son las dos fronteras donde nace un error silencioso. Todo lo
demás es barato.

**El espejo es la infraestructura que hace posible comparar**: `batch_*.py` replica la
estructura de carpetas, así que emparejar dos corridas es una operación de ruta
relativa, no una heurística de nombres. Sin espejo, comparar es adivinar.

**Trampa medida:** un archivo *saltado* se escribe `<stem>.skipped.json`, **nunca**
`<stem>.json`. Un registro de salto no es una extracción vacía, y un consumidor que
haga glob de `*.json` leería "saltado" como "no encontró nada". Al comparar, contar las
dos cosas por separado.

---

## 2. Los refutadores mecánicos (sin modelo, costo ≈ 0)

Estos van **primero**, siempre. Refutan gratis lo que un modelo cobraría por descubrir.

### 2.1 El número contradice su propia etiqueta

Un `reason.code` que no coincide con el `evidence` es un defecto del adaptador, no del
documento. Caso medido: `pdf.classify` de una página en blanco devuelve `value=None`
con `reason=blank_page`, **pero** `evidence.observed["shape"] == "blank"`. Leer la
forma solo cuando hay valor colapsa *en blanco* con *no medible* — dos afirmaciones
distintas.

Y al revés: `blank_page` en un **archivo de imagen** es un defecto del motor. Medido:
K2 abre un `.jpg` como documento de 1 página, y `page.get_images()` devuelve **0**
mientras `get_image_info()` devuelve **1**. Dos APIs del mismo motor se contradicen
dentro de una sola medición.

### 2.2 El valor es trazable al prompt, no al documento

**El refutador más rentable que encontramos, y no necesita ningún modelo.**

Implementación: para cada valor devuelto `v`, comprobar
`v in texto_del_prompt and v not in texto_del_documento`.

Medido en este ticket con `deepseek-r1:1.5b` y el prompt del registry:

| Campo | Valor devuelto | Origen real |
|---|---|---|
| `cuit_emisor` | `"20-1"` | el ejemplo de la **regla 3** del prompt |
| `razon_social_emisor` | `"ROSARI0"` | el ejemplo de la **regla 2** |
| `tipo_comprobante` | `"A \| B \| C \| 090 \| 099"` | la **lista de claves** leída como valor |
| `importe_total_facturado` | `"17.898,30"` | el ejemplo de la **regla 4** |

Ninguna de esas cadenas está en el documento. **El modelo recibió el prompt y devolvió
el prompt.** Un verificador que solo mire "¿el valor es plausible?" no lo ve: `"20-1"`
es un CUIT plausible, `"17.898,30"` es un importe plausible.

Costo: `in` sobre dos cadenas. Refuta fabricaciones enteras sin tocar un proveedor.

### 2.3 La aritmética del comprobante

El lector independiente más barato que existe, y el único que no es un modelo.

```
Σ renglones impresos              == subtotal impreso
subtotal × alícuota_dominante     == IVA impreso
subtotal + IVA + percepciones     == total impreso
```

Medido en este ticket, cierra exacto:

| Chequeo | Calculado | Impreso |
|---|---|---|
| Σ 9 ítems | **60 535.54** | 60 535.54 |
| ×21% | **12 712.46** | 12 712.46 |
| +242.14 +1 816.07 | **75 306.21** | 75 306.21 |

Dos consecuencias, y son distintas:

- **Valida el documento**, no la extracción. Cuando cierra, *cualquier* campo que lo
  contradiga queda refutado por aritmética, sin gastar un token.
- **Cuando no cierra, el problema puede ser el OCR**, no el modelo. Un dígito mal
  reconocido rompe la suma y la cadena entera queda sospechosa desde el paso 4.

### 2.4 El prompt entró completo

Medido: el prompt del registry son ~2 400 caracteres; la llamada completa en este
ticket fue de **5 945 caracteres → 2 249 tokens evaluados contra un presupuesto de
2 048** (`num_ctx=4096`, el prompt toma la mitad). `done_reason: 'stop'`, valor
plausible, **y nada en la respuesta lo dice**.

- El detector es por llamada: `evaluated_tokens >= num_ctx * 0.5`
  (`PROMPT_WINDOW_SHARE` en `batch_llm_local.py`).
- Arreglo verificado: `DOCFLOW_OLLAMA_NUM_CTX=8192` → `truncated 0`.
- **Ojo con el modelo**: `deepseek-r1:1.5b` **falla ruidosamente** ante un prompt
  oversize (`HTTP 400 exceed_context_size_error`, con `n_prompt_tokens` y `n_ctx`);
  `smollm2` lo **descarta en silencio** con `done_reason: 'stop'`. La elección de
  modelo cambia qué es detectable: con `smollm2`, la única evidencia es el detector
  por llamada.

### 2.5 Ninguna corrida respondió una pregunta distinta

Antes de comparar dos árboles hay que probar que **contestan lo mismo**. La firma de
`_mirror.Resume` cubre modelo, esquema y **texto del prompt**, y está hasheada por eso
mismo: comparar una corrida con otro prompt es comparar dos preguntas, y el resultado
parece un desacuerdo cuando en realidad es un cambio de instrumento.

### 2.6 El harness arranca y no miente

Dos defectos reales encontrados hoy en `batch_llm_frontier.py`, y son la razón de que
este paso exista:

- **El driver no arrancaba**: declaraba `--out` dos veces → `argparse.ArgumentError` en
  *cada* invocación. Nunca se había podido correr, así que no había nada que verificar.
- **`gates()` mentía**: exigía que *todos* los nombres de credencial estuvieran seteados,
  y los nombres de credencial son **alternativas**. Con `DOCFLOW_FRONTIER_DEEPSEEK_KEY`
  configurada anunciaba *"no credential: dry run"* **en la misma corrida donde acababa
  de evaluar el documento**.

Un harness que no arranca reporta **silencio**, y el silencio se lee como "limpio".
Validar el validador es el paso 0.

---

## 3. Las lecturas independientes, y qué aísla cada par

| Par | Comparte | Aísla | Costo |
|---|---|---|---|
| local-texto × local-texto (N veces) | todo | **inestabilidad del modelo** | N × local |
| local-texto × frontier-texto | el **texto OCR** | **el modelo** | 1 × frontier |
| local-texto × local-vision | el **documento** | **el material** (OCR/ruteo) | 1 × local-vision |
| **local-texto × frontier-vision** | **solo el documento** | **todo a la vez** | 1 × frontier-vision |
| cualquiera × `judge` | el material | nada del material | 1 × frontier |

La última fila es la trampa: **`judge` se ve como la comparación definitiva y no lo
es.** Califica la consistencia de los campos contra un guion; un OCR incompleto le
llega como un guion consistente.

### El `judge` sigue sirviendo, para otra cosa

Detecta **inconsistencias internas y fabricaciones**: campos con formato imposible,
valores que son el nombre del campo, listas de opciones copiadas del prompt. Medido en
este ticket: 23 veredictos por campo, marcó exactamente los 7 que correspondían,
incluidos los tres que el refutador 2.2 había encontrado.

**Pero tiene un defecto abierto y grave:** `GRADE_SCHEMA` declara `supported` y
DeepSeek devolvió `plausible`. Un consumidor que lea `supported` obtiene `None` en los
23 campos y **concluye "ninguna refutación" en silencio**. Hay que fijar la clave con
el esquema o normalizarla antes de consumir el veredicto.

---

## 4. La secuencia óptima

Ordenada por **poder de refutación por dólar**, que es distinto de por poder de
refutación.

```
                        ┌─ 0. el harness arranca (gratis)
                        ├─ 1. etiqueta ↔ evidencia        (gratis)
                        ├─ 2. valor trazable al prompt    (gratis)  ← el mejor retorno
   PDF con imagen ──────┼─ 3. aritmética del comprobante  (gratis)
   (una página)         ├─ 4. el prompt entró completo    (gratis)
                        │
                        ├─ 5. estabilidad: N corridas del local      (barato)
                        ├─ 6. cross-modelo sobre el MISMO texto      (medio)
                        │      └─ local-texto × frontier-texto  → aísla el MODELO
                        │
                        ├─ 7. local-vision (qwen2.5vl) sobre el píxel (caro)
                        │      └─ × local-texto → aísla el MATERIAL
                        │
                        └─ 8. FRONTIER-VISION sobre el píxel         (el más caro)
                               └─ × local-texto  → comparte solo el documento
                                     ├─ coinciden    → extracción confirmada
                                     └─ difieren     → escalar a HITL
```

### Por qué este orden y no otro

- **Los pasos 0–4 no cuestan nada y refutan los errores que más nos costaron hoy.**
  Los cuatro juntos habrían atrapado las fabricaciones del local sin gastar un dólar.
  Pagar primero por el frontier para descubrir que el local copió el prompt es pagar
  por información que ya se tenía.
- **El paso 6 antes del 7** porque es más barato y ya aísla el modelo. Si el texto y el
  cross-modelo coinciden, el campo es sólido y el píxel no agrega nada.
- **El paso 8 al final porque es el único que comparte solo el documento**, y es lo
  único que puede refutar un error de OCR. Es el que compra la garantía real, y por eso
  se gasta solo cuando los baratos no cerraron el caso.

### La secuencia, sobre el caso concreto: PDF con imagen

```bash
# --- 1. Ruteo ---------------------------------------------------------
python scripts/poc/batch_pdf.py <carpeta> --out var/run
#   deja <stem>.pages.json  -> shape, route, measured_dpi, rendered_dpi
#   y <stem>-pN.png         -> el bitmap, con el DPI medido (nunca upscale)

# --- 2. OCR -----------------------------------------------------------
python scripts/poc/batch_ocr.py var/run/<sub> --lang es --out var/run2/<sub>
#   <stem>-pN.txt      -> texto ordenado (layout)
#   <stem>-pN.ocr.json -> censo por página (read/blank/unreadable)

# --- 3. Campos desde texto (local) ------------------------------------
DOCFLOW_OLLAMA_NUM_CTX=8192 python scripts/poc/batch_llm_local.py <texto> \
    --schema registry/schemas/extraction/invoice.json \
    --prompt "$(cat registry/prompts/extraction/invoice.txt)" \
    --out var/ticket/local
#   <stem>.fields.json

# --- 4. Campos desde píxeles (local vision) ---------------------------
DOCFLOW_OLLAMA_NUM_CTX=8192 python scripts/poc/batch_llm_local.py <imagen> \
    --mode vision --schema registry/schemas/extraction/invoice.json \
    --out var/ticket/local_vision

# --- 5. El frontier LEYENDO el píxel (el paso decisivo) ---------------
python scripts/poc/batch_llm_frontier.py <imagen> \
    --fields var/ticket/local --out var/ticket/frontier_vision --mode vision \
    --schema registry/schemas/extraction/invoice.json
#   OJO: exige un proveedor con supports_vision=True. DeepSeek lo tiene en False.

# --- 6. Contraste mecánico --------------------------------------------
python scripts/poc/hitl.py <carpeta> --out var/ticket
#   review.json -> diferencias, pareadas por ruta relativa
```

### La restricción que cambia la secuencia

**`deepseek` tiene `supports_vision: False` y lo dice antes de la llamada**, con un
`unsupported_format` tipado. Medido: `batch_llm_frontier.py --mode vision` con DeepSeek
**se rehúsa, no falla** — y eso es lo correcto (una respuesta plausible a una pregunta
que no puede contestar es peor que una negativa).

Consecuencia práctica: **si el único proveedor configurado es DeepSeek, el paso 8 no
existe**. El lector de píxeles disponible es `qwen2.5vl:3b` local, o sea el paso 7, que
comparte el ruteo con el paso 3. En esa configuración la garantía más fuerte alcanzable
es *material × modelo*, **no** *solo documento*. La estrategia tiene que decir cuál de
las dos está dando, no asumir la más fuerte.

---

## 5. Cómo localizar el problema cuando las lecturas difieren

Cuando el par decisivo (8 × 3) difiere, el paso 6 dice **dónde mirar**:

| paso 6 (texto vs texto, mismo material) | Diagnóstico | Qué revisar |
|---|---|---|
| **Coinciden entre sí** | el material está bien; el problema es el **píxel o el modelo de visión** | DPI, legibilidad, `qwen2.5vl` |
| **Difieren entre sí** | el problema es el **modelo** o el **texto** | el prompt (2.2/2.4), el OCR |

Si coinciden texto×texto pero el de píxeles difiere → **el OCR perdió o inventó algo**
y hay que ir al paso 4b/5: ¿el DPI pedido superó el medido? ¿la legibilidad estaba bajo
el umbral? ¿el censo dijo `blank` en alguna página?

**Y el caso que no tiene diagnóstico automático, medido:** hay un fixture escaneado
(`3ac5a2ec`) que el OCR lee como `blank` **en todos los DPI** aunque tiene tinta. La
medición que lo discrimina es `span_x` (fracción de columnas con tinta): `0.28` en el
que falla, contra **0.75–1.00** en los cuatro que leen bien. Nótese que un fixture que
sí lee tiene **menos** tinta (`0.0055` vs `0.0112`): es la *concentración*, no la
cantidad. Es decir: "el OCR no devolvió nada" **no siempre es un defecto del documento**,
y no se detecta mirando la salida del OCR.

---

## 6. El caso del ticket, con los errores que aparecieron

Tres lecturas, mismo documento, tres resultados distintos:

| Campo | local-texto (1.5B) | local-vision (qwen2.5vl) | frontier-texto (v4-pro) | Verdad |
|---|---|---|---|---|
| `cuit_emisor` | `"20-1"` ← *del prompt* | `30582215703` ← **el del cliente** | `30-50673003-8` | `30-50673003-8` |
| `razon_social_emisor` | `"ROSARI0"` ← *del prompt* | `CVC SOCIEDAD ANONIMA` ← **el cliente** | `LA ANONIMA S.A. …` | `LA ANONIMA …` |
| `importe_total_facturado` | `"17.898,30"` ← *del prompt* | `$ 12712.46` (el IVA) | `75306.21` | `75 306.21` |
| `subtotal` | `null` | `>60535.54` | `60535.54` | `60 535.54` |
| `tipo_comprobante` | `"A \| B \| C \| 090 \| 099"` ← *la lista* | `"FACTURA"` | `A` | `A` |
| `comprobante_valido` | `"comprobante_valido"` ← *el nombre del campo* | `"S"` | `true` | `true` |
| `nro_comprobante` | `04928-00054475` | `04928-00054475` | `04928-00054475` | `04928-00054475` |
| `fecha_emision` | `10/07/1996` ← **la fecha de inicio de actividad** | `2026-08-29` (el vencimiento del CAE) | `19-08-26` | `19-08-26` |

Lo que enseña, y son las tres razones por las que esta estrategia tiene la forma que
tiene:

1. **El local no falla por un motivo, falla por tres**: copia el prompt, elige la fecha
   equivocada (la de inicio de actividad en lugar de la de emisión) y devuelve el nombre
   del campo como valor. Tres corridas dieron tres respuestas distintas. **Un validador
   de "¿es plausible?" aprueba los tres errores.**
2. **El vision local no es una segunda opinión gratuita**: trae la *misma* confusión
   emisor/receptor que el texto — y el impacto es que devuelve el CUIT del cliente.
   Coincidir en el error no es coincidir. **Por eso la lectura tiene que ser
   independiente en el material, no solo en la herramienta.**
3. **El frontier acierta y es estable**: dos corridas, 14 de 15 campos idénticos, y los
   valores que devuelve son exactamente los que la aritmética predice. La única
   diferencia entre las dos corridas fue el orden de las palabras en la razón social.

### El límite semántico, que ningún modelo arregla

El comprobante imprime **su** CUIT (`30-50673003-8`) y **el del cliente**
(`CVC SOCIEDAD ANONIMA`, `30582215703`). Ambos modelos devolvieron el del cliente. No
es un error de OCR ni de modelo: **es que el prompt no distingue emisor de receptor**, y
la lista de campos no tiene un `cuit_receptor` donde poner el segundo.

Ninguna validación cruzada detecta esto, porque las lecturas no se contradicen: **las
dos se equivocan igual.** Es el techo del método, y hay que decirlo en vez de esconderlo
detrás de "2 de 2 coinciden".

---

## 7. El orden de los pasos es también la política de costos

Medido, para no elegir a ojo:

| Paso | Costo medido |
|---|---|
| Aritmética / trazabilidad al prompt / etiqueta↔evidencia | milisegundos, $0 |
| OCR (K4 `read`) | **~8–10 s cada llamada** (recarga ONNX; no hay camino caliente entre procesos) |
| Local texto (`deepseek-r1:1.5b`) | ~4–11 s |
| Local texto (`smollm2`) | 0.5–3.6 s, **pero corre desbocado 1 de 5 veces** |
| Local vision (`qwen2.5vl:3b`) | ~3 s, 1.79 M caracteres de prompt |
| **Frontier (DeepSeek v4-pro)** | **~180–300 s por lectura**, y gastó **20 700 tokens** para dos campos |

El frontier cuesta dos órdenes de magnitud más que todo lo demás junto. Un documento
deliberadamente razona antes de contestar; con `MAX_TOKENS=16384` **truncó** y no
contestó nada. **Cualquier cosa que se pueda refutar sin el frontier tiene que
refutarse antes.**

---

## 8. Qué escala a HITL, y qué no

**Escala:** un campo donde las lecturas independientes **difieren** y **ningún
refutador mecánico disparó**. Ahí hay una decisión que ningún programa puede tomar.

**No escala:**

- Un campo donde los refutadores mecánicos ya refutaron (2.2, aritmética) — el programa
  sabe la respuesta.
- Un campo donde las lecturas **coinciden en el error** (§6) — la cola no ayuda, porque
  lo que falta es una regla, no una revisión.
- Un documento donde el paso 0–4 falló — eso es un defecto del harness, se arregla, no
  se revisa a mano.

**Y la regla que hace que la cola signifique algo:** `review.json` tiene que registrar
**cuál de las dos lecturas** produjo cada valor, y con qué modelo. Un veredicto sin el
registro de quién lo produjo es una afirmación que nadie puede revisar — que es
exactamente lo que este proyecto existe para evitar.

---

## 9. Las cuatro trampas que ya nos costaron tiempo

1. **Comparar dos corridas hechas con prompts distintos.** Parece un desacuerdo entre
   modelos y es un cambio de instrumento. La firma de `Resume` cubre prompt, esquema y
   modelo: verificar que coincidan **antes** de comparar.
2. **Leer el veredicto con la clave equivocada.** `GRADE_SCHEMA` declara `supported`;
   el modelo devolvió `plausible`. Leer `supported` da `None` × 23 y se reporta
   *"sin refutaciones"*. Un resultado vacío y un resultado limpio se ven igual.
3. **Contar un `.skipped.json` como extracción.** Infla el denominador y hace que un
   documento no procesado participe del contraste.
4. **Creer que `judge` validó el material.** No lo hizo ni puede: califica la
   transcripción. Es un chequeo de consistencia interna presentado como chequeo de
   contenido, y es la trampa más cara de las cuatro porque *da la sensación de haber
   cerrado el circuito*.

---

## 10. Resumen ejecutivo

- La extracción real no se **elige**, se **construye**: una lectura desde el texto y
  otra desde los píxeles, que no compartan nada más que el documento.
- El orden es **gratis → barato → caro**: etiqueta, trazabilidad-al-prompt, aritmética,
  ventana; estabilidad; cross-modelo sobre el mismo texto; vision local; **vision del
  frontier al final**.
- `judge` **no** es la comparación decisiva: califica un guion.
- El refutador de mejor retorno es el más tonto: **¿este valor está en el prompt y no en
  el documento?** Atrapó las tres fabricaciones del modelo local sin gastar un token.
- La aritmética es el único lector independiente que no es un modelo, y además dice si
  el problema está aguas arriba (OCR) o aguas abajo (modelo).
- Con un solo proveedor sin visión configurado, **la garantía más fuerte es
  material × modelo, no solo-documento**. La estrategia tiene que declarar cuál está
  dando.
- Queda un error que ninguna validación cruzada detecta: **cuando las dos lecturas se
  equivocan igual** (emisor vs receptor). Eso no es un problema de validación, es una
  regla que falta.
