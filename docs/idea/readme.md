# Document Processing Pipeline

Pipeline modular para procesar documentos PDF e imágenes mediante extracción nativa, preparación visual, OCR e inferencia con LLM/VLM.

La idea principal es simple:

> Cada procesador realiza una única tarea y devuelve un resultado.
> El `procesador-orquestador` decide cómo, cuándo y en qué orden utilizarlos.

```text
INPUT
  ↓
ORCHESTRATOR
  ↓
PDF / IMAGE
  ↓
IMAGE PREPARATION
  ↓
OCR cuando corresponda
  ↓
SOURCE SELECTION
  ↓
LLM / VLM
  ↓
VALIDATION
  ↓
RESULT
```

El objetivo es mantener los componentes **independientes, reutilizables, idempotentes y reanudables**, evitando repetir operaciones costosas innecesariamente.

---

## Arquitectura

El sistema está dividido en cinco componentes:

```text
procesador-orquestador
procesador-pdf
procesador-image
procesador-ocr
procesador-llm-call
```

Cada uno tiene una responsabilidad específica:

| Módulo                   | Responsabilidad                                 |
| ------------------------ | ----------------------------------------------- |
| `procesador-orquestador` | Coordinar el workflow                           |
| `procesador-pdf`         | Extraer estructura y artefactos nativos del PDF |
| `procesador-image`       | Analizar y preparar imágenes                    |
| `procesador-ocr`         | Extraer texto y estructura desde imágenes       |
| `procesador-llm-call`    | Ejecutar inferencias LLM/VLM                    |

La separación original propone exactamente este modelo: PDF para estructura física, Image para preparación visual, OCR para extracción desde imagen y LLM para inferencia, dejando la coordinación en una quinta capa de workflow/orchestrator.

---

# Principio fundamental

Cada procesador debe cumplir:

```text
INPUT
  ↓
PROCESSOR
  ↓
RESULT
```

Por ejemplo:

```text
PDFRequest
    ↓
procesador-pdf
    ↓
PDFResult
```

No debe ocurrir:

```text
procesador-pdf
    ↓
decide ejecutar OCR
    ↓
procesador-ocr
```

La regla es:

> Un procesador produce información. El orquestador decide qué hacer con ella.

---

# Flujo general

```text
                         INPUT
                           ↓
                  procesador-orquestador
                           ↓
                     detect type
                  ┌────────┴────────┐
                  ▼                 ▼
                 PDF              IMAGE
                  │                 │
                  ▼                 │
           procesador-pdf           │
                  │                 │
                  └────────┬────────┘
                           ↓
                   procesador-image
                           ↓
                      ImageResult
                           ↓
                   ¿requiere OCR?
                           │
                           ▼
                    procesador-ocr
                           ↓
                       OCRResult
                           ↓
                    select_source()
                           ↓
                   build_llm_input()
                           ↓
                procesador-llm-call
                           ↓
                       LLMResult
                           ↓
                     consolidate
                           ↓
                    DocumentResult
```

---

# 1. Procesador Orquestador

## Responsabilidad

`procesador-orquestador` es el único componente que conoce el workflow documental completo.

Decide:

* qué procesador ejecutar;
* en qué orden;
* qué artefactos utilizar;
* si ejecutar OCR;
* si utilizar imagen en una inferencia;
* qué fuente documental seleccionar;
* qué estrategia de extracción utilizar;
* cuándo reutilizar resultados;
* cuándo forzar reprocesamiento;
* cuándo omitir una etapa;
* cómo reanudar una ejecución;
* cómo manejar errores y fallbacks;
* cómo consolidar resultados.

También administra:

```text
estado
idempotencia
stop / resume
skip / force
dependencias
invalidación
concurrencia
reprocesamiento
```

---

## Estados de ejecución

Cada etapa puede encontrarse en:

```text
NOT_STARTED
READY
RUNNING
SUCCESS
FAILED
REUSED
SKIPPED
INVALIDATED
PAUSED
```

Esto permite reanudar un documento sin ejecutar nuevamente etapas ya completadas.

Ejemplo:

```text
PDF      SUCCESS
IMAGE    SUCCESS
OCR      SUCCESS
LLM      NOT_STARTED
```

Al hacer `resume`:

```text
PDF      REUSE
IMAGE    REUSE
OCR      REUSE
LLM      EXECUTE
```

---

# 2. Procesador PDF

## Responsabilidad

`procesador-pdf` recibe un PDF y extrae sus artefactos nativos.

Puede producir:

```text
page.pdf
page.png
native_text/text.txt
native_text/blocks.json
embedded_images/
metadata.json
```

Por cada página puede calcular:

* cantidad de texto;
* cantidad de imágenes;
* cobertura textual;
* cobertura visual;
* dimensiones;
* metadata técnica.

También puede clasificar la composición como:

```text
TEXT
IMAGE
MIXED
```

Esta clasificación es descriptiva.

No decide:

```text
TEXT  → usar LLM
IMAGE → ejecutar OCR
MIXED → ejecutar VLM
```

Eso corresponde al orquestador.

El diseño original ya define que el PDF debe dividir páginas, generar PDF individual, render, texto e imágenes embebidas y describir si predomina texto o imagen.

---

## Contrato

```text
PDFRequest
├── pdf_path
├── output_dir
├── options
└── context
```

Salida:

```text
PDFResult
├── metadata
├── pages[]
├── artifacts
├── validation
└── status
```

Cada página:

```text
PDFPageResult
├── page_number
├── page_pdf
├── page_image
├── native_text
├── embedded_images[]
├── metrics
├── classification
└── metadata
```

---

# 3. Procesador Image

## Responsabilidad

`procesador-image` recibe una imagen y la analiza y prepara técnicamente.

Puede recibir:

```text
imagen original
render/page.png
imagen embebida
```

Analiza:

* resolución;
* dimensiones;
* blur;
* nitidez;
* brillo;
* contraste;
* ruido;
* orientación;
* skew;
* presencia de texto.

Puede producir:

```text
normalized.png
ocr_ready.png
vlm_ready.png
metadata.json
```

La idea original ya definía este módulo como responsable de nitidez, legibilidad, texto, rotación, resolución y optimización para procesamiento posterior.

---

## Variantes

```text
normalized.png
```

Representación general.

```text
ocr_ready.png
```

Optimizada para OCR.

```text
vlm_ready.png
```

Optimizada para modelos multimodales.

No debe asumirse:

```text
OCR image == VLM image
```

OCR puede necesitar:

```text
grayscale
deskew
binarización
contraste
```

Mientras un VLM puede necesitar preservar:

```text
color
layout
contexto visual
```

---

# 4. Procesador OCR

## Responsabilidad

`procesador-ocr` recibe una imagen preparada y extrae contenido estructurado.

Actualmente puede utilizar:

```text
Docling
```

Entrada típica:

```text
ocr_ready.png
```

Salida:

```text
OCRResult
```

Puede producir:

```text
ocr/
├── text.txt
├── document.md
├── document.json
├── tables/
└── metadata.json
```

Extrae:

* texto;
* bloques;
* párrafos;
* títulos;
* tablas;
* layout;
* orden de lectura;
* metadata.

El diseño original separa explícitamente OCR como extracción desde imagen y evita que el módulo decida cómo alimentar posteriormente al LLM.

---

# 5. Selección de fuente

Una misma página puede tener varias representaciones:

```text
native_text

OCR_TEXT

IMAGE

NATIVE_TEXT + IMAGE

OCR_TEXT + IMAGE
```

El orquestador selecciona cuál utilizar.

Ejemplos:

```text
native text válido
        ↓
NATIVE_TEXT
```

```text
native text vacío
        ↓
OCR_TEXT
```

```text
documento visual complejo
        ↓
OCR_TEXT + IMAGE
```

La selección de fuente ya estaba planteada en la idea original como una etapa independiente entre extracción y LLM.

---

# 6. Procesador LLM

## Responsabilidad

`procesador-llm-call` recibe una tarea de inferencia ya preparada.

Entrada:

```text
LLMInput
```

Puede incluir:

```text
task
provider
model
template
document
images[]
extra_context
schema
options
```

Salida:

```text
LLMResult
```

Se encarga de:

* renderizar templates;
* construir prompts;
* preparar mensajes;
* invocar providers;
* ejecutar LLM/VLM;
* parsear outputs;
* validar schemas;
* aplicar retries;
* comparar respuestas;
* calcular consenso.

La separación original ubica aquí específicamente templates, prompt, schema, texto, imágenes, contexto, ejecución y validación de outputs.

---

# Grafo LLM

El procesador puede coordinar un subgrafo exclusivamente de inferencia.

Ejemplo:

```text
classify
   ↓
 ┌─┴──────────┐
 ▼            ▼
extract_a   extract_b
 └─────┬──────┘
       ↓
    compare
       ↓
    validate
       ↓
   consolidate
```

Puede contener:

```text
classify
extract
verify
compare
consensus
validate
```

No puede contener:

```text
PDF
IMAGE PROCESSING
OCR
```

---

# Dos niveles de workflow

Existen dos grafos diferentes.

## Workflow documental

Controlado por:

```text
procesador-orquestador
```

```text
PDF
 ↓
IMAGE
 ↓
OCR
 ↓
SOURCE SELECTION
 ↓
LLM
```

---

## Workflow de inferencia

Controlado por:

```text
procesador-llm-call
```

```text
classify
   ↓
extract
   ↓
verify
   ↓
compare
   ↓
validate
```

Ambos niveles deben permanecer separados.

---

# Idempotencia

El sistema debe evitar repetir operaciones costosas.

Una etapa puede identificarse mediante:

```text
processing_key =
    hash(
        input_hash
        + processor
        + processor_version
        + options_hash
    )
```

Si:

```text
processing_key coincide
AND
status == SUCCESS
AND
artifacts válidos
```

entonces:

```text
REUSE
```

en lugar de:

```text
EXECUTE
```

---

# Skip y Force

El orquestador puede controlar explícitamente etapas.

## Skip

```text
skip OCR
```

Resultado:

```text
OCR → SKIPPED
```

---

## Force

```text
force OCR
```

Resultado:

```text
PDF     REUSE
IMAGE   REUSE
OCR     EXECUTE
LLM     INVALIDATED
```

Forzar una etapa invalida resultados downstream que dependían de su salida anterior.

---

# Stop / Resume

El workflow debe poder detenerse de forma segura.

Ejemplo:

```text
PDF       SUCCESS
IMAGE     SUCCESS
OCR       SUCCESS
LLM       NOT_STARTED

DOCUMENT  PAUSED
```

Luego:

```text
resume
```

produce:

```text
PDF       REUSE
IMAGE     REUSE
OCR       REUSE
LLM       EXECUTE
```

El objetivo es:

> No volver a pagar ni ejecutar trabajo válido.

---

# Procesamiento por página

Cada página debe funcionar como una unidad independiente.

```text
document.pdf
      ↓
procesador-pdf
      ↓

P1   P2   P3   P4   P5
```

Esto permite:

* paralelización;
* reprocesamiento aislado;
* recovery;
* debugging;
* resume parcial.

Ejemplo:

```text
P1 SUCCESS
P2 SUCCESS
P3 FAILED
P4 SUCCESS
P5 SUCCESS
```

Solo debe reprocesarse:

```text
P3
```

---

# Estructura de archivos

Ejemplo:

```text
document/
├── source/
│   └── document.pdf
│
├── metadata.json
│
├── page_001/
│   │
│   ├── source/
│   │   └── page.pdf
│   │
│   ├── render/
│   │   └── page.png
│   │
│   ├── native_text/
│   │   └── text.txt
│   │
│   ├── embedded_images/
│   │
│   ├── image/
│   │   ├── normalized.png
│   │   ├── ocr_ready.png
│   │   ├── vlm_ready.png
│   │   └── metadata.json
│   │
│   ├── ocr/
│   │   ├── text.txt
│   │   ├── document.md
│   │   ├── document.json
│   │   └── metadata.json
│   │
│   └── llm/
```

Cada procesador escribe exclusivamente dentro de su namespace.

---

# Ownership

```text
procesador-pdf
    ↓
source/
render/
native_text/
embedded_images/
```

```text
procesador-image
    ↓
image/
```

```text
procesador-ocr
    ↓
ocr/
```

```text
procesador-llm-call
    ↓
llm/
```

Ningún módulo debe sobrescribir archivos de otro.

---

# Persistencia atómica

Los outputs no deben publicarse mientras todavía están siendo generados.

Ejemplo:

```text
document.json.tmp
       ↓
write
       ↓
validate
       ↓
rename
       ↓
document.json
```

Esto evita que otro componente lea artefactos incompletos.

---

# Contratos entre módulos

La colaboración debe ocurrir exclusivamente mediante contratos públicos.

```text
PDFRequest
    ↓
procesador-pdf
    ↓
PDFResult
```

```text
ImageRequest
    ↓
procesador-image
    ↓
ImageResult
```

```text
OCRRequest
    ↓
procesador-ocr
    ↓
OCRResult
```

```text
LLMInput
    ↓
procesador-llm-call
    ↓
LLMResult
```

El orquestador consume estos resultados y decide el siguiente paso.

---

# Independencia

Cada procesador debe funcionar de forma aislada.

## PDF

```text
document.pdf
     ↓
procesador-pdf
     ↓
PDFResult
```

## Image

```text
image.png
    ↓
procesador-image
    ↓
ImageResult
```

## OCR

```text
ocr_ready.png
      ↓
procesador-ocr
      ↓
OCRResult
```

## LLM

```text
LLMInput
   ↓
procesador-llm-call
   ↓
LLMResult
```

Esto permite:

* testing independiente;
* benchmarking;
* reemplazo de librerías;
* debugging;
* reutilización en otros proyectos.

---

# Implementaciones reemplazables

La arquitectura no debe depender directamente de una implementación concreta.

Actualmente pueden utilizarse:

```text
PDF       → Poppler

Image     → OpenCV / Pillow

OCR       → Docling

LLM       → Ollama / vLLM / API
```

Mientras se mantengan los contratos:

```text
Request → Processor → Result
```

pueden reemplazarse las implementaciones internas sin modificar el workflow.

---

# Estructura del proyecto

```text
processors/
│
├── pdf/
│   ├── primitives
│   ├── utils
│   └── helpers
│
├── image/
│   ├── primitives
│   ├── utils
│   └── helpers
│
├── ocr/
│   ├── primitives
│   ├── utils
│   └── helpers
│
├── llm/
│   ├── primitives
│   ├── utils
│   └── helpers
│
└── workflow/
    ├── process_document()
    ├── process_page()
    ├── resolve_stage()
    ├── select_source()
    ├── select_extraction_strategy()
    ├── build_llm_input()
    ├── invalidate_downstream()
    ├── resume_document()
    └── execute_document_workflow()
```

Esta organización es consistente con la estructura propuesta originalmente para separar `pdf`, `image`, `ocr`, `llm` y `workflow`.

---

# Naming

Reservar nombres globales:

```text
process_document()

process_page()
```

para el orquestador.

Usar nombres específicos en cada procesador:

```text
process_pdf()

process_pdf_page()

process_image()

process_image_from_page()

process_ocr_image()

process_llm_request()

process_llm_node()
```

Así se diferencia claramente:

```text
procesar una página completa
```

de:

```text
ejecutar una capacidad sobre una página
```

---

# Resumen

```text
procesador-pdf
    =
extrae evidencia nativa

procesador-image
    =
prepara imágenes

procesador-ocr
    =
extrae texto y estructura

procesador-llm-call
    =
ejecuta inferencia

procesador-orquestador
    =
decide cómo colaboran
```

La arquitectura se basa en tres reglas:

1. **Cada procesador tiene una única responsabilidad.**
2. **Solo el orquestador conoce el workflow completo.**
3. **No se repite trabajo válido y costoso sin necesidad.**

En términos simples:

```text
PROCESSORS
    =
transform

ORCHESTRATOR
    =
decide + coordinate + reuse
```
