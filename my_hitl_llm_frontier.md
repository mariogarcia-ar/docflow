# Validación cruzada: construir la extracción real, y en qué orden

Todo lo de acá está medido en `scripts/poc/`, no propuesto. Caso de trabajo:
`var/run/pdf_escaneados/9b7a423c-…-p1.png` (factura A, La Anónima), donde el modelo
local falló de tres formas distintas y el frontier acertó.

---

## La tesis, en una línea

**Una sola lectura segura no es evidencia de nada.** Un error silencioso solo lo detecta
**otra lectura que no comparta con la primera más que el documento**.

> **La independencia es una propiedad del prefijo compartido, no del paso.**

Dos lecturas del mismo texto OCR no son independientes: comparten el error de OCR. Si el
OCR se comió una línea, las dos leen un documento incompleto y **coincidir se reporta
como "verificado"**.

De ahí el corolario que decide el diseño:

> **`judge` no puede detectar un error de OCR.** Califica la transcripción, y la
> transcripción *es* la salida del OCR. Medido por introspección:
> `inspect.signature(FrontierEngine.judge)` no tiene parámetro `images`. Califica un guion.

La comparación con poder de refutación es entonces **campos derivados del texto (OCR) ×
campos derivados de los píxeles (vision)**: comparten solo el documento, y todo lo demás
—ruteo, DPI, motor, modelo, tokenizador— es distinto.

Cada paso tiene que dejar un artefacto legible por el siguiente, y `batch_*.py` replica el
árbol de carpetas (espejo) para que emparejar dos corridas sea una ruta relativa y no una
heurística de nombres. Y un archivo *saltado* se escribe `<stem>.skipped.json`, **nunca**
`<stem>.json`: contarlo como extracción infla el denominador.

---

## La secuencia, ordenada por poder de refutación por dólar

```
   PDF con imagen ──┬─ 0. el harness arranca        (gratis)
   (una página)     ├─ 1. etiqueta ↔ evidencia      (gratis)
                    ├─ 2. valor trazable al prompt  (gratis)  ← el mejor retorno
                    ├─ 3. aritmética del comprobante(gratis)
                    ├─ 4. el prompt entró completo  (gratis)
                    ├─ 5. estabilidad: N corridas del local        (barato)
                    ├─ 6. cross-modelo sobre el MISMO texto        (medio)
                    ├─ 7. local-vision sobre el píxel              (caro)
                    └─ 8. FRONTIER-VISION sobre el píxel           (el más caro)
                           └─ × local-texto → comparte solo el documento
                                 ├─ coinciden → confirmado
                                 └─ difieren  → escalar a HITL
```

**Por qué este orden.** Los pasos 0–4 no cuestan nada y juntos habrían atrapado, sin un
dólar, las fabricaciones del local: pagar primero por el frontier para descubrir que el
local copió el prompt es pagar por información que ya se tenía. El 6 va antes que el 7
porque es más barato y ya aísla el modelo. El 8 va al final porque es el único que comparte
solo el documento, o sea el único que puede refutar un error de OCR.

**Qué aísla cada par:**

| Par | Comparte | Aísla |
|---|---|---|
| local-texto × local-texto (N veces) | todo | inestabilidad del **modelo** |
| local-texto × frontier-texto | el texto OCR | el **modelo** |
| local-texto × local-vision | el documento | el **material** (OCR/ruteo) |
| **local-texto × frontier-vision** | **solo el documento** | **todo a la vez** |
| cualquiera × `judge` | el material | **nada del material** |

**Los costos que justifican el orden:** refutadores mecánicos → milisegundos, costo cero;
OCR ~8–10 s por llamada (recarga ONNX, no hay camino caliente); local texto ~4–11 s; local
vision ~3 s; **frontier ~180–300 s por lectura, 20 700 tokens para dos campos** — dos
órdenes de magnitud más que todo lo demás junto.

---

## Los refutadores mecánicos (sin modelo, costo ≈ 0)

Van primero, siempre. Refutan gratis lo que un modelo cobraría por descubrir. El más
rentable no necesita ningún modelo:

```python
# ¿el valor está en el prompt y NO en el documento?
v in texto_del_prompt and v not in texto_del_documento
```

Medido con `deepseek-r1:1.5b`: `cuit_emisor="20-1"` (el ejemplo de la regla 3),
`razon_social_emisor="ROSARI0"` (regla 2), `importe_total="17.898,30"` (regla 4),
`tipo_comprobante="A | B | C | 090 | 099"` (la lista de claves leída como valor). **El
modelo recibió el prompt y devolvió el prompt.** Un chequeo de "¿es plausible?" no lo ve:
`"20-1"` es un CUIT plausible.

Los otros tres:

- **Etiqueta ↔ evidencia.** Un `reason.code` que no coincide con su `evidence` es defecto
  del *adaptador*, no del documento. Medido: página en blanco devuelve `value=None` con
  `reason=blank_page` **pero** `evidence.observed["shape"] == "blank"` — *en blanco* y *no
  medible* son dos afirmaciones distintas, y leer la forma solo cuando hay valor las
  colapsa.
- **Aritmética.** El único lector independiente que no es un modelo. Medido: Σ 9 ítems
  `60 535.54`, ×21% `12 712.46`, +percepciones `75 306.21`, todo exacto. Cuando cierra,
  valida el **documento** y refuta por aritmética cualquier campo que lo contradiga *sin
  gastar un token*; cuando no cierra, el sospechoso puede ser el **OCR**.
- **Ventana de contexto.** Detector por llamada: `evaluated_tokens >= num_ctx * 0.5`.
  Medido: 5 945 caracteres → 2 249 tokens contra 2 048, `done_reason: 'stop'`, valor
  plausible, **y nada en la respuesta lo dice**. `deepseek-r1:1.5b` falla ruidosamente
  (HTTP 400) ante un prompt oversize; `smollm2` lo **descarta en silencio**. Arreglo:
  `DOCFLOW_OLLAMA_NUM_CTX=8192` → `truncated 0`.

Antes de comparar dos árboles hay que probar que **contestan lo mismo**: la firma de
`_mirror.Resume` cubre modelo, esquema y **texto del prompt**, y está hasheada por eso
mismo — comparar corridas con prompts distintos parece un desacuerdo y es un cambio de
instrumento.

Y el paso 0 es **validar el validador**: un harness que no arranca reporta silencio, y el
silencio se lee "limpio". Medido en `batch_llm_frontier.py`: declaraba `--out` dos veces (no
arrancaba nunca, así que no había nada que verificar) y `gates()` exigía *todos* los nombres
de credencial, que son **alternativas** — anunciaba *"no credential: dry run"* en la misma
corrida donde acababa de evaluar el documento.

---

## El caso del ticket: tres lecturas, tres resultados

| Campo | local-texto (1.5B) | local-vision (qwen2.5vl) | frontier-texto (v4-pro) | Verdad |
|---|---|---|---|---|
| `cuit_emisor` | `"20-1"` ← *del prompt* | `30582215703` ← **el del cliente** | `30-50673003-8` | `30-50673003-8` |
| `razon_social_emisor` | `"ROSARI0"` ← *del prompt* | `CVC SOCIEDAD ANONIMA` ← **el cliente** | `LA ANONIMA …` | `LA ANONIMA …` |
| `importe_total_facturado` | `"17.898,30"` ← *del prompt* | `$ 12712.46` (el IVA) | `75306.21` | `75 306.21` |
| `fecha_emision` | `10/07/1996` ← **inicio de actividad** | `2026-08-29` (vence el CAE) | `19-08-26` | `19-08-26` |
| `comprobante_valido` | `"comprobante_valido"` ← *el nombre del campo* | `"S"` | `true` | `true` |

1. **El local no falla por un motivo, falla por tres.** Copia el prompt, elige la fecha
   equivocada y devuelve el nombre del campo como valor. Tres corridas, tres respuestas.
   **Un validador de "¿es plausible?" aprueba los tres errores.**
2. **El vision local no es una segunda opinión gratuita.** Trae la *misma* confusión
   emisor/receptor que el texto y devuelve el CUIT del cliente. **Coincidir en el error no
   es coincidir**: por eso la independencia tiene que estar en el material, no en la
   herramienta.
3. **El frontier acierta y es estable:** dos corridas, 14 de 15 campos idénticos, y los
   valores son los que la aritmética predice.

**El límite semántico, que ningún modelo arregla.** El comprobante imprime *su* CUIT
(`30-50673003-8`) y el del cliente (`CVC SOCIEDAD ANONIMA`, `30582215703`). Ambos modelos
devolvieron el del cliente. No es error de OCR ni de modelo: **el prompt no distingue emisor
de receptor** y no hay un `cuit_receptor` donde poner el segundo. Ninguna validación cruzada
lo detecta, porque **las dos lecturas se equivocan igual**. Es el techo del método, y hay
que decirlo en vez de esconderlo detrás de "2 de 2 coinciden".

**Y el caso sin diagnóstico automático, medido:** un fixture escaneado (`3ac5a2ec`) que el
OCR lee como `blank` **en todos los DPI** aunque tiene tinta. La medición que lo discrimina
es `span_x` (fracción de columnas con tinta): `0.28` en el que falla, contra **0.75–1.00** en
los cuatro que leen bien — y uno que *sí* lee tiene **menos** tinta (`0.0055` vs `0.0112`):
es la *concentración*, no la cantidad. "El OCR no devolvió nada" no siempre es un defecto
del documento.

---

## La restricción que cambia la secuencia

**`deepseek` tiene `supports_vision: False` y lo dice antes de la llamada**, con un
`unsupported_format` tipado: `--mode vision` con DeepSeek **se rehúsa, no falla**, y eso es
lo correcto — una respuesta plausible a una pregunta que no puede contestar es peor que una
negativa.

Consecuencia práctica: **si el único proveedor configurado es DeepSeek, el paso 8 no
existe**, y la garantía más fuerte alcanzable es *material × modelo*, **no** *solo
documento*. La estrategia tiene que declarar cuál de las dos está dando, no asumir la más
fuerte.

---

## Qué escala a HITL, y qué no

**Escala:** un campo donde las lecturas independientes **difieren** y **ningún refutador
mecánico disparó**. Ahí hay una decisión que ningún programa puede tomar.

**No escala:** un campo ya refutado por un refutador mecánico (el programa sabe la
respuesta); un campo donde las lecturas **coinciden en el error** (falta una regla, no una
revisión); un documento donde falló el paso 0–4 (es un defecto del harness: se arregla, no
se revisa a mano).

**`review.json` tiene que registrar cuál de las dos lecturas produjo cada valor, y con qué
modelo.** Un veredicto sin el registro de quién lo produjo es una afirmación que nadie puede
revisar.

---

## El documento, en pseudocódigo (lenguaje natural)

```text
# ─────────────────────────────────────────────────────────────────────────────
# 0. Validar el validador — gratis, y va primero.
#    Un harness que no arranca reporta SILENCIO, y el silencio se lee "limpio".
# ─────────────────────────────────────────────────────────────────────────────
verificar_harness():
    asegurar( el driver arranca )            # un --out declarado dos veces = error en CADA invocación
    asegurar( gates() no miente )            # los nombres de credencial son ALTERNATIVAS, no un AND
    asegurar( ambas corridas respondieron la MISMA pregunta )
        # firma de _mirror.Resume = modelo + esquema + TEXTO DEL PROMPT, hasheada por eso mismo

def procesar_documento(doc):

    # === 1. Confianza de partida, antes de cualquier LLM ===
    tier, material = rutear(doc)          # texto_nativo | rasterizado | escaneado
    # La confianza no se declara ni se elige: se deriva del tier y la refutan los pasos de abajo.

    if tier != TEXTO_NATIVO:
        legible = chequear_legibilidad(material)   # sharpness vs umbral, y span_x si el OCR no devuelve nada
        if not legible:
            return encolar(doc, motivo="material_degradado", fields=None)
            # no tiene sentido cross-validar algo que ya se sabe poco confiable

    # === 2. Extracción(es) según el tier ===
    texto = obtener_texto(material, tier)     # texto nativo del PDF, u OCR si no lo es

    fields_texto, corridas = correr_local_estable(prompt=PROMPT_EXTRACCION, texto=texto, n=2)
    estable = corridas_coinciden(corridas)
    # este par aísla solo la INESTABILIDAD DEL MODELO, no el material:
    # descarta ruido antes de sospechar del modelo

    # === 3. Refutadores mecánicos, corren siempre, cuestan ~0 ===
    violaciones = []
    violaciones += chequear_etiqueta_evidencia(fields_texto, material)
        # un reason.code que no coincide con evidence es defecto del ADAPTADOR:
        # en blanco y no-medible no son lo mismo

    violaciones += chequear_trazabilidad_al_prompt(fields_texto, PROMPT_EXTRACCION, texto)
        # EL MÁS RENTABLE, sin ningún modelo:  v in prompt  AND  v not in documento
        # el modelo recibió el prompt y devolvió el prompt

    violaciones += chequear_aritmetica(fields_texto)
        # Σítems == subtotal · subtotal×alícuota == IVA · subtotal+IVA+percepciones == total
        # el único lector independiente que no es un modelo

    violaciones += chequear_ventana_contexto(texto, PROMPT_EXTRACCION, NUM_CTX)
        # evaluated_tokens >= num_ctx * PROMPT_WINDOW_SHARE(0.5); done_reason 'stop' no lo delata

    if violaciones:
        return encolar(doc, motivo="refutador_disparado", fields=fields_texto, detalle=violaciones)
        # fabricación o inconsistencia detectada gratis: no pagues vision para confirmar
        # algo que ya está refutado

    # === 4. Si el material puede fallar por OCR, buscá el par que lo aísla ===
    if tier == TEXTO_NATIVO:
        # no hay frontera OCR que refutar: texto×texto + refutadores ya alcanza
        if estable:
            fields_final = fields_texto
        else:
            return encolar(doc, motivo="inestable_sin_frontera_ocr", fields=fields_texto)
    else:
        # 4.a cross-modelo sobre el MISMO texto: aísla el MODELO, y va antes por barato.
        #     No puede refutar un error de OCR: comparte el texto.
        # 4.b el par decisivo: local-texto × vision, que comparte SOLO el documento.
        fields_vision = correr_local_vision(material)      # qwen2.5vl:3b → aísla el MATERIAL
        # ...y frontier-vision si hay proveedor con supports_vision=True (DeepSeek lo tiene en False)

        diffs = comparar_campo_a_campo(fields_texto, fields_vision)

        if not diffs and estable:
            fields_final = fields_texto   # coinciden compartiendo solo el documento
        else:
            return encolar(doc, motivo="texto_vs_vision_difieren",
                           fields={"texto": fields_texto, "vision": fields_vision},
                           detalle=diffs)
            # acá, y solo acá, frontier/humano son recursos de la cola —
            # no un paso automático del camino feliz

    # === 5. Regla explícita para el blind spot conocido (emisor/receptor) ===
    fields_final = corregir_si_es_receptor_conocido(fields_final, CUITS_PROPIOS)
    # gratis y determinístico: no depende de que ninguna validación cruzada lo note,
    # porque ambas lecturas se equivocan igual y nunca lo iban a notar

    return CONFIRMADO(fields_final, tier=tier, estable=estable)


# ─────────────────────────────────────────────────────────────────────────────
# Lo que NO entra en el camino decisivo
# ─────────────────────────────────────────────────────────────────────────────
judge(fields, guion):
    # NO valida el material y no puede: califica la transcripción, y la transcripción
    # ES la salida del OCR. Sirve para consistencia INTERNA y fabricaciones.
    # Defecto abierto: GRADE_SCHEMA declara `supported` y el modelo devolvió `plausible`
    # → leer `supported` da None × 23 y se reporta "sin refutaciones" EN SILENCIO.
    normalizar_clave(veredicto) antes de consumir

emparejar(a, b):                            # el espejo de batch_*.py
    # emparejar por RUTA RELATIVA, nunca por heurística de nombres;
    # contar <stem>.skipped.json APARTE: un salto no es una extracción vacía

localizar_el_problema(fields_texto, fields_cross, fields_vision):
    # cuando el par decisivo difiere, el cross-modelo dice DÓNDE mirar:
    if fields_texto coincide_con fields_cross:
        → el material está bien; el problema es el PÍXEL o el MODELO DE VISIÓN
          → revisar DPI efectivo, legibilidad, qwen2.5vl
    else:
        → el problema es el MODELO o el TEXTO → revisar el prompt y el OCR


def encolar(doc, motivo, fields, detalle=None):
    # registro auditable: qué lectura(s) produjeron cada valor y con qué modelo,
    # para que la cola sea revisable y no una afirmación sin respaldo
    return HITL_Queue.push({
        "doc": doc, "motivo": motivo, "fields_por_fuente": fields,
        "detalle": detalle, "asistencia_disponible": ["frontier_vision", "humano"]
    })

escala_a_hitl():
    SÍ  → un campo donde las lecturas independientes DIFIEREN y ningún refutador disparó
    NO  → un campo ya refutado por un refutador mecánico
    NO  → un campo donde las lecturas COINCIDEN EN EL ERROR (falta una regla, no una revisión)
    NO  → un documento donde falló el paso 0–4 (defecto del harness: se arregla)
```

**El orden es la política de costos:** todo lo refutable sin el frontier se refuta antes de
tocarlo.
