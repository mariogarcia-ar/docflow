# Estrategia de Procesamiento Inteligente de Documentos (IDP) sobre Ollama

**Versión 4 · fase de análisis (sin código).** Ingesta por página (`pdftotext` / `pdftoppm` / Docling OCR) y, en cada vía (texto y visión), una etapa de **extracción** y una de **revisión**, con **modelos, prompts y schemas distintos** en cada etapa. **Alcance:** facturas y tickets (PDF o imagen) procesados con modelos 100 % locales. **Runtime:** Ollama.

---

## 1. Resumen ejecutivo

Primero, una **etapa de ingesta** decide página por página si el texto se extrae directo del PDF (`pdftotext`) o por OCR (Docling sobre la imagen). Luego el documento recorre dos vías independientes. En cada una, un modelo **extrae** y otro **revisa** el resultado, con un prompt y un schema propios. Un **árbitro determinista** valida las revisiones, cruza las dos vías y emite el resultado final con **confianza** y **procedencia** por campo. Lo que no se puede validar se deriva a revisión humana (`needs_review`).

Ningún dato llega al resultado porque "un modelo lo dijo": tiene que superar reglas de negocio (aritmética, formato, anclaje al texto) y, además, ser confirmado por un segundo modelo que no es el que lo extrajo.

## 2. Arquitectura y preprocesamiento

### 2.1 Etapa 0: ingesta y enrutamiento por página

Antes de las dos vías, cada archivo pasa por una etapa de ingesta que produce, **por página**, un texto y (cuando hace falta) una imagen.

```
[Entrada] ─┬─ PDF (se evalúa cada página)
           │     ├─ con texto ──> pdftotext ───────────────────────────> texto nativo
           │     └─ sin texto ──> pdftoppm ──> imagen ─┐
           │                                           ├─> Docling (OCR) ──> texto OCR
           └─ Imagen (JPG / PNG) ──────────────────────┘
```

| Entrada | Decisión | Herramienta | Para la vía texto | Para la vía visión |
| --- | --- | --- | --- | --- |
| Página de PDF **con texto** | Caracteres ≥ umbral | `pdftotext` en modo layout (conserva columnas) | Texto nativo | Imagen con `pdftoppm` a 200 dpi, solo cuando se activa la vía visión |
| Página de PDF **sin texto** | Caracteres \< umbral | `pdftoppm` a 200 dpi → Docling OCR | Texto OCR | La misma imagen |
| **Archivo de imagen** | No aplica | Docling OCR | Texto OCR | La misma imagen (orientación corregida y reescalada) |

Un mismo PDF puede mezclar páginas de ambos tipos. El texto de todas las páginas se concatena con marcadores de página que indican su origen (texto nativo u OCR), y ese origen se conserva para el árbitro.

### 2.2 Cómo se decide si una página tiene texto

| Criterio | Regla |
| --- | --- |
| **Regla principal** | Extraer la página con `pdftotext`; si tiene menos de \~40 caracteres alfanuméricos, es imagen. El umbral se calibra con el set dorado. |
| **Texto basura** | Si aparecen secuencias `(cid:` o el carácter de reemplazo `U+FFFD`, o casi no hay caracteres legibles, tratar la página como imagen. |
| **Escaneo con capa OCR incrustada** | Pasa como "con texto", pero su calidad es la del OCR de quien generó el PDF. Si falla el anclaje o la ecuación, la cascada activa la vía visión, que lee la imagen. |
| **Página mixta** (foto pegada bajo un encabezado de texto) | `pdftotext` solo captura el encabezado, así que faltan los totales y la validación falla: la cascada activa la vía visión. |

### 2.3 Notas de la ingesta

- **Herramientas:** las utilidades de poppler (`pdftotext`, `pdftoppm`) y Docling.
- **Texto nativo vs OCR:** `pdftotext` devuelve el texto incrustado sin errores de reconocimiento; el OCR de Docling puede equivocarse. Por eso el origen pesa en el anclaje y en la confianza (§8).
- **Independencia de las vías:** en páginas escaneadas ambas vías parten de la misma imagen, pero la vía visión la lee directamente y no depende del OCR, así que sigue verificando de forma independiente.
- **Tablas:** el modo layout de `pdftotext` conserva las columnas pero no genera tablas Markdown como Docling. Si T1 pierde ítems en PDFs con texto, evaluar Docling también sobre ellos.
- **Fotos de entrada:** corregir la orientación y reescalar la imagen que va al VLM a \~2400 px de lado mayor (equivalente a una A4 a 200 dpi). Los tickets muy largos se envían por franjas.

### 2.4 Las cuatro etapas de extracción y revisión

```
                  ┌─ VÍA TEXTO ───────────────────────────────────────────────────────────┐
[Etapa 0] ────────┤ Texto por página ─> [T1 Extracción] ─> JSON A ─> [T2 Revisión] ─> A'  │
(texto + imágenes)│                                                                       ├─> [Árbitro] ─> RESULTADO FINAL
                  │ VÍA VISIÓN ───────────────────────────────────────────────────────────┤
                  │ Imagen por página ─> [V1 Extracción] ─> JSON B ─> [V2 Revisión] ─> B' │
                  └───────────────────────────────────────────────────────────────────────┘
```

| Etapa | Rol | Entrada | Salida |
| --- | --- | --- | --- |
| **T1** | Extrae datos del texto | Texto por página (`pdftotext` u OCR de Docling) | JSON A (extracción de texto) |
| **T2** | Verifica A contra el texto | Texto por página + JSON A | Revisión de texto |
| **V1** | Extrae datos de la imagen | Imágenes de las páginas (`pdftoppm` o archivo original) | JSON B (extracción de visión) |
| **V2** | Verifica B contra la imagen | Imágenes + JSON B | Revisión de visión |

## 3. Principios de diseño

1. **Un modelo distinto por etapa.** Cuatro modelos, de al menos tres familias. El revisor nunca es el mismo modelo que extrajo, así no comparte sus sesgos.
2. **Un prompt distinto por etapa.** El extractor transcribe; el revisor audita. Mezclar ambos roles en un mismo prompt hace que el modelo confirme lo que ya escribió.
3. **Un schema distinto por etapa.** La extracción devuelve datos; la revisión devuelve veredictos con evidencia.
4. **El revisor no reescribe.** Solo emite veredictos. Quien aplica correcciones es el árbitro, y solo si superan las validaciones deterministas.
5. **Lectura independiente primero.** En el schema de revisión, el valor observado va antes que el veredicto: con salida estructurada los campos se generan en orden, así el revisor lee el dato por su cuenta antes de compararlo con la extracción.
6. **Evidencia obligatoria.** Todo veredicto cita su evidencia (cita literal en texto; zona y valor leído en visión).
7. **Texto nativo antes que OCR.** Si la página tiene texto incrustado se usa tal cual; el OCR queda para las imágenes y las páginas escaneadas.

## 4. Modelos por etapa

| Etapa | Modelo recomendado | Tag Ollama | Tamaño Q4 | Familia | Licencia |
| --- | --- | --- | --- | --- | --- |
| **T1** Extracción texto | Gemma 3 12B | `gemma3:12b` | 8,1 GB | Google | Gemma Terms |
| **T2** Revisión texto | Qwen3.5 9B | `qwen3.5:9b` | 6,6 GB | Alibaba | Apache 2.0 |
| **V1** Extracción visión | Qwen3-VL 8B | `qwen3-vl:8b` | 6,1 GB | Alibaba | Apache 2.0 |
| **V2** Revisión visión | Ministral 3 8B | `ministral-3:8b` | 6,0 GB | Mistral | Apache 2.0 |

**Por qué estos:**

- **T1 Gemma 3 12B:** muy sólido en español y buen seguimiento de schema.
- **T2 Qwen3.5 9B:** el mejor equilibrio calidad/tamaño del catálogo y de otra familia que T1.
- **V1 Qwen3-VL 8B:** OCR de primer nivel (32 idiomas), sucesor de Qwen2.5-VL.
- **V2 Ministral 3 8B:** multimodal, de una familia distinta a V1. **Es la elección menos probada para OCR de facturas en español**: validarla en el set dorado (§10) antes de fijarla.

### 4.1 Alternativas

| Etapa | Alternativa | Cuándo |
| --- | --- | --- |
| T1 | `granite4.1:8b` (5,3 GB, Apache 2.0) | Si el cliente exige licencia permisiva o hay 8 GB |
| T2 | `ministral-3:8b` o `granite4.1:8b` | Si se prefiere otra familia que T1 |
| V2 | `qwen2.5vl:7b` (6,0 GB) | Ya probado en facturas, pero misma familia que V1 |
| V2 | `gemma3:12b` (multimodal, 8,1 GB) | Otra familia, pero repite el modelo de T1 |

> Confirmar los tags exactos con `ollama list` o en la Ollama Library antes de fijarlos.

### 4.2 Descartados

Phi-4 (16K de contexto), Llama 3.2 Vision (imagen+texto solo en inglés), modelos de razonamiento tipo DeepSeek R1 (lentos y no mejoran la transcripción), Aya Expanse (no comercial) y cuantizaciones Q3 (degradan la extracción estructurada).

### 4.3 VRAM y orden de carga

Cada modelo pesa entre 6 y 8 GB, así que **con 12 GB corre uno a la vez** y con 16 GB o más pueden convivir dos. Para no recargar modelos en cada documento, **procesar por lotes por etapa**: pasar todos los documentos por T1, luego todos por T2, y así sucesivamente.

## 5. Schemas (descripción de campos)

Las dos extracciones comparten un **núcleo común** para que el árbitro pueda cruzarlas campo a campo. Cada vía agrega solo sus campos propios. Los schemas de revisión son distintos de los de extracción y distintos entre sí.

### 5.1 Extracción (T1 y V1)

| Grupo | Campos del núcleo común |
| --- | --- |
| Identificación | Tipo de comprobante (A, B, C, M, ticket), punto de venta, número, fecha |
| Emisor | CUIT, razón social |
| Autorización | CAE, vencimiento del CAE |
| Importes | Neto gravado, no gravado, exento, IVA por alícuota (lista de alícuota + importe), otros tributos, descuentos, total |
| Ítems | Por línea: descripción, cantidad, precio unitario, alícuota de IVA, importe |

| Etapa | Campos propios (además del núcleo) |
| --- | --- |
| **T1** | Lista de campos no encontrados en el texto |
| **V1** | Lista de campos ilegibles; observaciones visuales (borroso, sello, tachadura, torcido) |

### 5.2 Revisión (T2 y V2)

Cada revisión contiene un veredicto por campo y hallazgos globales. **El orden importa:** primero la lectura independiente del revisor, al final su comparación.

| Elemento | T2 (revisión de texto) | V2 (revisión de visión) |
| --- | --- | --- |
| Por campo, 1.º | Nombre del campo | Nombre del campo |
| Por campo, 2.º | Valor observado por el revisor | Valor observado por el revisor |
| Por campo, 3.º | Cita literal del texto | Zona de la página donde lo leyó |
| Por campo, 4.º | — | Si es legible (sí / no) |
| Por campo, último | Veredicto | Veredicto |
| Globales | Ítems omitidos, ítems sobrantes, hallazgos | Legibilidad global (buena / regular / mala), ítems omitidos, ítems sobrantes, hallazgos |

**Veredictos posibles:** `confirmado`, `discrepa`, `no_verificable`.

## 6. Prompts por etapa

| Etapa | Rol del prompt | Instrucciones clave | Restricciones |
| --- | --- | --- | --- |
| **T1** | Extractor de comprobantes fiscales argentinos | Leer el texto por páginas (texto nativo u OCR); copiar valores tal como figuran; fechas ISO; importes con punto decimal y sin separador de miles; si falta un dato, `null` y registrarlo como no encontrado | No calcular, no inferir, no completar |
| **T2** | Auditor del texto | Para cada campo: 1) leer el valor en el texto por cuenta propia, 2) citar el fragmento literal, 3) recién entonces comparar con la extracción; además listar líneas de ítems omitidas o sobrantes | No reescribir el JSON, no recalcular totales, no asumir que la extracción es correcta |
| **V1** | Lector de imágenes de comprobantes | Igual que T1, más campos ilegibles y observaciones visuales; usar jerarquía y posición de los bloques para ubicar totales | No adivinar lo ilegible: `null` y registrarlo |
| **V2** | Auditor visual | Para cada campo: localizar la zona, leer el valor, indicar si es legible, luego comparar; revisar ítems omitidos o sobrantes | Mismas que T2; ante duda, `no_verificable` |

**Contraste entre roles:** los prompts de extracción piden transcribir fielmente y declarar lo que falta; los de revisión piden leer primero, citar evidencia y recién después comparar, sin asumir que la extracción es correcta. El texto final de los cuatro prompts se redacta y afina con documentos reales (§12).

## 7. Flujo de ejecución

| Modo | Secuencia | Llamadas por documento |
| --- | --- | --- |
| **Cascada (recomendado)** | Etapa 0 → T1 → T2 → validación determinista. Si pasa, se emite el resultado. Si falla (ecuación, CUIT, anclaje o disputa), se rasterizan las páginas que aún no tengan imagen y se ejecutan V1 → V2; el árbitro cruza ambas vías. | 2 (típico), 4 (si se activa visión) |
| **Paralelo** | Etapa 0 → T1 → T2 y V1 → V2 siempre; el árbitro cruza. | 4 |

Medir qué porcentaje de documentos activa la vía visión antes de decidir si el modo paralelo vale su costo.

## 8. El árbitro

### 8.1 Aplicación de las revisiones (dentro de cada vía)

| Veredicto del revisor | Acción del árbitro | Procedencia |
| --- | --- | --- |
| `confirmado` | Se conserva el valor | `extraido_y_confirmado` |
| `discrepa` y solo el valor observado pasa las validaciones | Se corrige | `corregido_por_revision` |
| `discrepa` y ambos valores pasan las validaciones | No se decide | `en_disputa` |
| `discrepa` y ninguno pasa | Se deriva | `needs_review` |
| `no_verificable` | Se conserva sin aumentar confianza | `sin_verificar` |

El revisor **nunca modifica un campo por sí solo**: toda corrección pasa antes por las validaciones de §8.2.

### 8.2 Validaciones deterministas (Argentina)

| Campo | Regla |
| --- | --- |
| CUIT | 11 dígitos con dígito verificador (módulo 11) |
| Punto de venta / Nº comprobante | 4–5 y 8 dígitos |
| CAE | 14 dígitos; vencimiento no anterior a la fecha del comprobante |
| Tipo de comprobante | A/B/C/M coherente con el IVA discriminado (en B y C no se discrimina) |
| Alícuotas | 0 %, 2,5 %, 5 %, 10,5 %, 21 %, 27 % |
| Ecuación | Neto gravado + No gravado + Exento + IVA (por alícuota) + Otros tributos − Descuentos = Total, tolerancia ±0,01 por línea |
| Ítems | La suma de los ítems coincide con el subtotal |
| Anclaje | Cada número del resultado debe aparecer literalmente en el texto de la vía texto (`pdftotext` u OCR de Docling); un anclaje en texto nativo pesa más que uno en OCR |

### 8.3 Cruce entre vías

Con los resultados ya revisados de cada vía (A′ y B′):

- **Texto / IDs:** prioridad a la vía texto, siempre sujeta a validación.
- **Numéricos:** si divergen, gana la vía que cumpla la ecuación. Si ambas la cumplen con valores distintos, o ninguna, `needs_review`.
- **Tablas:** alinear ítems por similitud de texto y usar los ítems omitidos de ambos revisores como pista.

### 8.4 Salida

Cada campo del resultado final incluye valor, **confianza** (0–1) y **procedencia**. La confianza es máxima cuando ambas vías coinciden y ambos revisores confirman, y cae cuando el valor depende de un solo modelo o de una corrección. Además, un valor anclado en texto nativo (`pdftotext`) tiene más confianza que uno anclado en OCR, porque no hay error de reconocimiento. Los umbrales de `needs_review` se calibran con el set dorado.

## 9. Parámetros de Ollama por etapa

| Etapa | Salida estructurada | Temperatura | Modo thinking | Contexto (`num_ctx`) |
| --- | --- | --- | --- | --- |
| T1 | Schema de extracción de texto | 0 | Desactivado | Documento + schema (8192–16384) |
| T2 | Schema de revisión de texto | 0 | Opcional: probar con y sin | Documento + JSON A + schema (más alto que T1) |
| V1 | Schema de extracción de visión | 0 | Desactivado | Tokens de imagen + schema (≥ 8192) |
| V2 | Schema de revisión de visión | 0 | Desactivado | Tokens de imagen + JSON B + schema |

- Una A4 a 200 dpi son \~3.800 tokens visuales en Qwen3-VL (usa 32×32 px por token; Qwen2.5-VL usa 28×28). En Ministral 3 medir el consumo real.
- Las páginas se envían juntas si entran en el contexto; si no, en tandas de páginas. Los tickets muy largos van por franjas.
- Con 12 GB de VRAM se mantiene un solo modelo cargado a la vez; con 16 GB o más pueden convivir dos.

## 10. Evaluación

- **Set dorado de 50 a 100 documentos** con casos difíciles: tickets térmicos, fotos torcidas, multipágina.
- Medir **precisión por campo**, no solo por documento.
- **Enrutamiento:** incluir PDFs mixtos (páginas de texto y escaneadas), escaneos con capa de texto OCR incrustada y fotos pegadas dentro de un PDF; medir el % de páginas mal clasificadas y calibrar el umbral de caracteres.
- **Errores inyectados:** incluir documentos con valores deliberadamente erróneos en el JSON candidato para medir cuántos detecta cada revisor (recall) y cuántas falsas alarmas genera. Un revisor que confirma todo no aporta nada.
- Métricas clave: % de documentos que activan la vía visión, % en `needs_review`, aporte de cada revisor (correcciones válidas) y errores que pasan el árbitro sin ser detectados.
- Validar V2 (Ministral 3) frente a `qwen2.5vl:7b` y `gemma3:12b` como revisor visual.

## 11. Licencias

| Modelo | Licencia | Nota |
| --- | --- | --- |
| Qwen3.5, Qwen3-VL, Ministral 3, Granite 4.1 | Apache 2.0 | Sin restricciones relevantes |
| Gemma 3 | Gemma Terms | Tiene condiciones de uso: revisar antes de proyectos con clientes; alternativa `granite4.1:8b` |

## 12. Pendientes de análisis y validación

1. Confirmar GPU/VRAM y fijar los tags de los cuatro modelos.
2. Definir el umbral de enrutamiento por página con muestras reales.
3. Cerrar el contenido final de los cuatro prompts y los cuatro schemas.
4. Armar el set dorado con errores inyectados y PDFs mixtos, y medir la línea base (cascada vs. paralelo).
5. Calibrar umbrales de confianza, tamaño de contexto y dpi con los resultados.
6. Pasar a implementación (ingesta, árbitro, prompts) una vez cerradas las decisiones anteriores.