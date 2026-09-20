# Flujo de extracción de comprobantes fiscales

## 0. Artefactos de entrada (fijos, no dependen del documento puntual)

```
┌─────────────┐
│   prompt    │  qué buscar / cómo leerlo (reglas de negocio, correcciones de OCR)
└──────┬──────┘
       │
┌─────────────┐
│   schema    │  qué forma tiene la respuesta (campos, tipo, formato, reglas de validación)
└──────┬──────┘
       │
┌──────────────────┐
│  schema-visual    │  dónde debería estar cada campo — CONDICIONAL:
│  (por emisor)     │  solo existe si el emisor ya fue aprendido
└───────────────────┘
```

El prompt y el schema los edita un humano. El schema-visual lo actualiza el propio sistema (paso 7, "aprender"), pero solo a partir de extracciones ya confirmadas.

---

## 1. Flujo principal (vista de alto nivel)

```
documento
  → rutear (tipo de material + legibilidad)
  → clasificar (¿es comprobante?)
  → extraer campos
  → validar campos
       ├─ ok                                  → confirmar → aprender
       ├─ corregible con evidencia            → corregir → validar (loop) → confirmar → aprender
       └─ no corregible / material degradado  → escalar (cola) → [no aprende de esto todavía]
```

---

## 2. Rutear

### 2.1 Tipo de fuente → confianza de partida

| Fuente          | Confianza | Por qué |
|---|---|---|
| texto plano     | alta      | es el string real, no hay interpretación de por medio |
| pdf con texto   | alta      | la capa de texto es el string real del PDF |
| pdf sin texto (imagen) | media | depende de OCR |
| imagen (foto/escaneo)  | media | depende de OCR |

### 2.2 Gate

```
documento
  → ¿tiene capa de texto (o es texto plano)?
       ├─ sí  → texto_nativo    (confianza alta, sin OCR de por medio)
       └─ no  → ¿es imagen o PDF sin texto?
                 → convertir: si es pdf_imagen, exportar a imagen
                 → preprocesar: ¿es pesada / DPI excesivo? → redimensionar
                 → chequear legibilidad (sharpness)
                      ├─ legible     → escaneado_ocr   (confianza media)
                      └─ no legible  → degradado        → escalar directo
```

*Cuidado ya señalado: "¿tiene capa de texto?" no es lo mismo que "el texto sirve" — un PDF con texto vacío o de una sola línea de metadata debería caer a `escaneado_ocr`, no clasificarse como `texto_nativo` solo por tener algo en la capa.*

### 2.3 Extracción de texto (según fuente, sin modelo todavía)

| Fuente | Método |
|---|---|
| texto plano | ninguna operación |
| pdf con texto | `pdftotext -layout` o similar |
| imagen / pdf rasterizado | OCR (docling o similar) |

---

## 3. Clasificar (¿es comprobante?)

Gate barato, corre **antes** de gastar en extracción de campos completa:

```
texto_nativo      → reglas sobre el texto extraído (pdftotext) para determinar si es comprobante
escaneado_ocr     → reglas sobre el texto del OCR, o reglas de elementos visuales, para determinar si es comprobante
       │
       ├─ no es comprobante → descartar (fast-fail, no llega a "extraer campos")
       └─ es comprobante    → sigue el flujo
```

---

## 4. Extraer campos

```
tier == texto_nativo
  → extraer campos con regexp donde el formato es fijo
      (CUIT, fecha, tipo de comprobante, nro_comprobante)
  → correr LLM local sobre el texto → campos_A
  → correr LLM local otra vez sobre el mismo texto,
    pidiéndole que revise si sus propios campos son correctos → campos_B
       ├─ campos_A == campos_B → campos_texto
       └─ difieren               → inestable → escalar
  → cruzar campos por regexp vs. campos_texto en los campos que ambos cubren
      (refutador extra, gratis)
  # no hay lectura de vision acá: no hay frontera OCR que aislar

tier == escaneado_ocr
  → correr LLM local sobre texto_ocr → campos_A
  → correr LLM local otra vez, mismo texto_ocr, pidiendo autorrevisión → campos_B
       ├─ campos_A == campos_B → campos_texto
       └─ difieren               → inestable → escalar
  → (en paralelo) correr LLM local vision sobre el render → campos_vision

  salida: campos_texto + campos_vision, SIN fusionar
          (la fusión es responsabilidad de "validar", no de "extraer")
```

> **Nota abierta:** pedirle al mismo modelo, sobre el mismo texto, que revise si sus propios campos son correctos ("campos_B") es útil para detectar **inestabilidad** (el modelo se contradice a sí mismo), pero no es una validación independiente — comparte el mismo texto y el mismo modelo que campos_A, así que hereda cualquier error de lectura que ambos compartan. Vale la pena no llamarlo "1ª/2ª validación" para no confundirlo con los refutadores mecánicos o con el cruce texto×vision, que sí son independientes.

---

## 5. Validar campos

```
tier == texto_nativo
  campos_texto (ya estable)
  → refutadores mecánicos vs. documento
      (etiqueta↔evidencia, trazabilidad al prompt, aritmética, ventana de contexto)
       ├─ sin violaciones → confirmado
       └─ con violaciones → ¿la violación señala un valor correcto?
              ├─ sí → corregible → corregir
              └─ no → escalar

tier == escaneado_ocr
  campos_texto + campos_vision
  → refutadores mecánicos sobre cada lectura por separado
       ├─ ambas limpias → comparar campo a campo
       │      ├─ coinciden → confirmado
       │      └─ difieren  → ¿algún refutador dirime cuál vale?
       │             ├─ sí → corregible → corregir
       │             └─ no → escalar
       └─ una o ambas con violaciones → escalar
              (una lectura sucia no vota; no promedies con la limpia)

en ambos tiers, si hay emisor conocido:
  → chequeo posicional adicional con schema-visual
      ¿el token extraído está en la zona esperada para ESE emisor?
       ├─ sí → suma a "confirmado"
       └─ no → refutador disparado → corregible / escalar
```

---

## 6. Verificación (escalamiento: frontier + HITL)

```
escalar(doc, lecturas_en_disputa, motivo)
  → llm_frontier lee el DOCUMENTO ORIGINAL (multimodal — no el texto ya extraído)
      → campos_frontier + justificación por campo
  → refutadores mecánicos también sobre campos_frontier (frontier no está exento)

  → comparar campos_frontier contra las lecturas en disputa
       ├─ coincide con una         → mostrar al humano 1 candidato + evidencia (confirma con un click)
       └─ no coincide con ninguna  → mostrar todas las lecturas + evidencia; decide el humano

  → humano resuelve → campos_confirmados

  → ¿este motivo de escalamiento ya se repitió N veces (mismo emisor/patrón)?
       ├─ sí → llm_frontier propone una regla candidata → pendiente de aprobación humana
       └─ no → se registra el caso, sin proponer regla todavía
```

---

## 7. Aprender

Solo con `campos_confirmados` (post-refutadores o post-humano). Nunca con una lectura cruda o con `campos_frontier` sin confirmar.

Actualiza:
- el perfil del emisor (formato de campos esperado)
- el `schema-visual` del emisor (zona donde aparece cada campo)

---

## Notas / pendientes de definir

- **Umbral de comparación campo a campo** (paso 5): ¿diff exacto de string o tolerancia por campo? (ej. una fecha con formato distinto pero mismo valor no debería contar como diferencia).
- **Tasa de escalamiento esperada al frontier** — no medida todavía; condiciona si el diseño de costos del paso 6 es sostenible a volumen.
- **Regla determinística para el blind spot emisor/receptor**: si el CUIT/razón social devuelto coincide con un CUIT propio conocido, está en el campo equivocado — puede vivir como refutador mecánico fijo, sin depender de schema-visual ni de HITL.
