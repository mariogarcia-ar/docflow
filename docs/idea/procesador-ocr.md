# Procesador OCR

## Objetivo

El módulo `procesador-ocr` tiene como responsabilidad exclusiva **extraer una representación textual y estructurada desde una imagen preparada**, utilizando Docling como motor principal de OCR y análisis documental.

Debe recibir una imagen lista para procesamiento y devolver:

* texto plano;
* Markdown estructurado;
* representación JSON;
* bloques;
* tablas;
* layout;
* orden de lectura;
* métricas;
* metadata técnica;
* estado de la extracción.

El módulo:

* no procesa PDFs;
* no selecciona páginas;
* no normaliza imágenes;
* no decide si OCR debe ejecutarse;
* no selecciona la fuente documental final;
* no llama a LLM/VLM;
* no compara OCR contra otras fuentes;
* no controla el workflow documental.

Su responsabilidad empieza cuando recibe:

```text
OCRRequest
```

y termina cuando devuelve:

```text
OCRResult
```

---

# Principio de diseño

`procesador-ocr` responde:

> **“Dada esta imagen preparada y esta configuración, ¿qué contenido textual y estructural puedo extraer de ella?”**

No responde:

> **“¿Debo ejecutar OCR sobre esta página?”**

ni:

> **“¿Debo usar este OCR o el texto nativo?”**

ni:

> **“¿Debo enviar esta información a un LLM?”**

Esas decisiones pertenecen al `procesador-orquestador`.

---

# Separación de responsabilidades

```text
procesador-orquestador
    =
decide si OCR debe ejecutarse
+ selecciona input
+ controla estado
+ idempotencia
+ stop/resume
+ skip/force
+ fallback

procesador-image
    =
prepara técnicamente la imagen

procesador-ocr
    =
extrae contenido

procesador-llm-call
    =
realiza inferencia
```

---

# Flujo principal

1. Recibir `OCRRequest`.
2. Validar imagen de entrada.
3. Normalizar configuración OCR.
4. Configurar Docling.
5. Ejecutar procesamiento.
6. Extraer:

   * texto;
   * párrafos;
   * títulos;
   * bloques;
   * tablas;
   * layout;
   * orden de lectura;
   * metadata.
7. Convertir resultado a una representación intermedia estable.
8. Construir:

   * `text.txt`;
   * `document.md`;
   * `document.json`;
   * tablas individuales.
9. Analizar métricas.
10. Validar técnicamente la extracción.
11. Persistir artefactos.
12. Generar metadata.
13. Devolver `OCRResult`.

---

# Flujo general

```text
OCRRequest
    ↓
validate_ocr_input()
    ↓
configure_ocr()
    ↓
Docling
    ↓
extract_structured_content()
    ↓
normalize result
    ↓
 ┌─────────┬────────────┬─────────────┐
 ▼         ▼            ▼             ▼
TEXT     MARKDOWN       JSON        TABLES
    └─────────┬────────────┬──────────┘
              ↓
      analyze_ocr_result()
              ↓
      validate_ocr_result()
              ↓
       persist artifacts
              ↓
           OCRResult
```

---

# Contrato del módulo

## Entrada

```text
OCRRequest
├── image_path
├── output_dir
├── options
└── context
```

Ejemplo:

```json
{
  "image_path": "image/normalized.png",

  "output_dir": "page_001/ocr",

  "options": {
    "ocr": true,
    "layout": true,
    "tables": true,
    "reading_order": true
  },

  "context": {
    "document_id": "doc_001",
    "page_number": 1,
    "workflow_run_id": "run_001"
  }
}
```

El `context` es solamente metadata de correlación.

El módulo no debe modificar estado global utilizando ese contexto.

---

# Salida

```text
OCRResult
├── text
├── markdown
├── structured_document
├── tables[]
├── blocks[]
├── layout
├── metrics
├── artifacts
├── validation
├── metadata
└── status
```

Ejemplo:

```json
{
  "text_path": "ocr/text.txt",
  "markdown_path": "ocr/document.md",
  "json_path": "ocr/document.json",

  "tables": [
    "ocr/tables/table_001.md"
  ],

  "metrics": {
    "characters": 3245,
    "words": 518,
    "blocks": 42,
    "tables": 1,
    "text_density": 0.68
  },

  "validation": {
    "status": "VALID"
  },

  "status": "success"
}
```

---

# Estructura de salida

Cada ejecución OCR escribe exclusivamente dentro de su namespace.

```text
ocr/
├── text.txt
├── document.md
├── document.json
├── tables/
│   ├── table_001.md
│   └── table_002.md
└── metadata.json
```

Dentro de una página:

```text
page_001/
├── source/
│   ├── page.pdf
│   └── page.png
│
├── native_text/
│   └── text.txt
│
├── image/
│   ├── normalized.png
│   └── metadata.json
│
├── ocr/
│   ├── text.txt
│   ├── document.md
│   ├── document.json
│   ├── tables/
│   └── metadata.json
│
└── llm/
```

Regla:

> **El procesador OCR solamente escribe dentro de `ocr/`.**

Nunca debe modificar:

```text
source/
native_text/
image/
llm/
```

---

# Relación con idempotencia

La idempotencia completa pertenece al orquestador.

El módulo OCR no decide:

```text
REUSE
SKIP
FORCE
RESUME
```

El orquestador determina previamente si la etapa debe ejecutarse.

Ejemplo:

```text
OCR stage
   ↓
orchestrator
   ↓
 ┌───────────┬───────────┬─────────┐
 ▼           ▼           ▼
REUSE       SKIP       EXECUTE
                         ↓
                  procesador-ocr
```

Si `procesador-ocr` recibe un `OCRRequest`, debe asumir:

> **La ejecución fue autorizada y debe realizarse.**

---

# Determinismo técnico

Aunque el módulo no controla la idempotencia global, debe favorecer resultados técnicamente reproducibles.

Dadas:

```text
misma imagen
+ misma versión del motor
+ mismas opciones
```

debe intentar producir:

```text
misma estructura lógica de salida
```

Esto requiere:

* normalizar opciones;
* mantener formatos estables;
* ordenar bloques de forma determinística;
* preservar orden de tablas;
* normalizar JSON;
* evitar timestamps dentro de contenido funcional;
* mantener versionado técnico en metadata.

---

# Metadata de ejecución

`metadata.json` debería incluir:

```text
OCRMetadata
├── engine
├── engine_version
├── processor_version
├── options
├── input
├── metrics
├── validation
├── timing
├── transformations
└── context
```

Ejemplo:

```json
{
  "engine": "docling",
  "engine_version": "x.y.z",
  "processor_version": "1.0.0",

  "input": {
    "image_path": "image/normalized.png"
  },

  "options": {
    "ocr": true,
    "layout": true,
    "tables": true
  },

  "validation": {
    "status": "VALID"
  }
}
```

El `processing_key` puede ser calculado por el orquestador utilizando esta información.

---

# 1. Primitivas

Funciones de bajo nivel que encapsulan Docling y librerías auxiliares.

---

## Pipeline

```text
load_docling_pipeline(options)

configure_image_pipeline(options)

enable_ocr(pipeline, enabled=True)

enable_table_detection(pipeline, enabled=True)

enable_layout_analysis(pipeline, enabled=True)
```

---

## Ejecución

```text
convert_image_with_docling(image_path, options)
```

---

## Extracción

```text
extract_docling_text(result)

extract_docling_markdown(result)

extract_docling_tables(result)

extract_docling_blocks(result)

extract_docling_layout(result)

extract_docling_metadata(result)
```

---

## Exportación

```text
export_docling_text(...)

export_docling_markdown(...)

export_docling_json(...)

export_docling_tables(...)
```

Las primitivas conocen Docling.

No conocen:

* PDF workflow;
* image workflow;
* LLM;
* routing;
* selección de fuentes.

---

# 2. Procesamiento principal

## `process_ocr_image(request)`

Función principal del módulo.

Debe:

1. validar request;
2. validar imagen;
3. preparar output temporal;
4. configurar Docling;
5. ejecutar OCR;
6. extraer contenido estructurado;
7. construir representaciones normalizadas;
8. procesar tablas;
9. calcular métricas;
10. validar extracción;
11. persistir resultados;
12. generar metadata;
13. publicar artefactos finales;
14. devolver `OCRResult`.

```text
process_ocr_image()
        ↓
validate_ocr_request()
        ↓
validate_ocr_input()
        ↓
configure_ocr()
        ↓
run_ocr_engine()
        ↓
extract_structured_content()
        ↓
build outputs
        ↓
analyze_ocr_result()
        ↓
validate_ocr_result()
        ↓
persist
        ↓
OCRResult
```

---

# 3. Wrapper para páginas

## `process_ocr_from_page(...)`

Wrapper opcional para páginas provenientes de un PDF.

Debe:

* recibir explícitamente la imagen;
* mantener `page_number`;
* conservar `document_id`;
* construir `OCRRequest`;
* llamar internamente a `process_ocr_image()`.

```text
process_ocr_from_page()
        ↓
build OCRRequest
        ↓
process_ocr_image()
```

No debe:

```text
leer page.pdf
renderizar PDF
seleccionar page.png
buscar normalized.png automáticamente
```

El orquestador entrega la imagen correcta.

---

# 4. Configuración OCR

## `configure_ocr(options)`

Normaliza exclusivamente configuración técnica.

Puede definir:

```text
OCR enabled
layout enabled
table detection
reading order
structure extraction
language
engine parameters
```

No debe decidir:

```text
si OCR es necesario
si usar OCR o texto nativo
si usar VLM
```

---

# Configuración normalizada

Es conveniente convertir:

```json
{
  "tables": true,
  "ocr": true,
  "layout": true
}
```

a una representación ordenada y estable:

```text
NormalizedOCROptions
├── ocr
├── layout
├── tables
├── reading_order
├── language
└── engine_options
```

Esto facilita reproducibilidad e idempotencia externa.

---

# 5. Representación intermedia

## `extract_structured_content(result)`

La salida nativa de Docling debe convertirse a una representación común.

```text
OCRDocument
├── text
├── paragraphs[]
├── titles[]
├── blocks[]
├── tables[]
├── layout
├── reading_order[]
└── metadata
```

El resto del sistema no debería depender directamente de estructuras internas de Docling.

Esta capa permite reemplazar Docling en el futuro manteniendo el contrato.

---

# 6. Texto

## `build_ocr_text(result)`

Genera una representación textual simple.

Salida:

```text
text.txt
```

Debe priorizar:

* legibilidad;
* orden lógico;
* estabilidad;
* ausencia de metadata innecesaria.

---

# 7. Markdown

## `build_ocr_markdown(result)`

Genera Markdown estructurado.

Debe preservar cuando sea posible:

* títulos;
* párrafos;
* listas;
* tablas;
* jerarquías;
* orden de lectura.

Salida:

```text
document.md
```

---

# 8. JSON estructurado

## `build_ocr_json(result)`

Genera una representación destinada a consumo programático.

Ejemplo:

```text
document
├── blocks[]
├── tables[]
├── layout
├── reading_order[]
└── metadata
```

Salida:

```text
document.json
```

El formato debería permanecer estable entre versiones compatibles del procesador.

---

# 9. Tablas

## `process_tables(result, output_dir)`

Debe:

* detectar tablas;
* conservar orden;
* normalizar filas;
* normalizar columnas;
* preservar celdas;
* conservar referencias al layout;
* exportar representaciones individuales.

Ejemplo:

```text
tables/
├── table_001.md
├── table_001.json
├── table_002.md
└── table_002.json
```

Si inicialmente solo se requiere Markdown, JSON puede permanecer opcional.

---

# 10. Layout

La extracción de layout puede incluir:

```text
blocks
bounding boxes
page dimensions
block types
reading order
table regions
text regions
```

Las coordenadas deberían normalizarse a una representación independiente del motor cuando sea posible.

Ejemplo:

```text
bbox
├── x
├── y
├── width
└── height
```

---

# 11. Análisis del resultado

## `analyze_ocr_result(result)`

Debe producir:

```text
OCRMetrics
├── characters
├── words
├── blocks
├── tables
├── paragraphs
├── text_density
├── empty
└── structure_detected
```

Puede utilizarse posteriormente por el orquestador para decidir calidad o estrategia.

El OCR únicamente calcula las métricas.

No interpreta qué debe hacerse con ellas.

---

# 12. Validación técnica

## `validate_ocr_result(result, metrics)`

Debe verificar exclusivamente calidad técnica de la extracción.

Puede detectar:

```text
VALID
EMPTY
LOW_CONTENT
INCOMPLETE
PARSE_ERROR
ERROR
```

Ejemplos:

### `VALID`

Existe contenido estructurado suficiente y la ejecución terminó correctamente.

### `EMPTY`

No se extrajo contenido textual.

### `LOW_CONTENT`

Existe contenido, pero es escaso.

### `INCOMPLETE`

Parte del pipeline produjo resultados parciales.

### `PARSE_ERROR`

El motor ejecutó, pero alguna representación no pudo construirse correctamente.

### `ERROR`

La ejecución OCR falló.

---

# La validación no decide routing

Un resultado:

```text
LOW_CONTENT
```

no implica automáticamente:

```text
usar VLM
```

ni:

```text
repetir OCR
```

ni:

```text
revisión manual
```

El procesador devuelve:

```text
LOW_CONTENT
```

y el orquestador decide qué hacer.

---

# 13. Errores

Los errores deberían clasificarse técnicamente.

Ejemplo:

```text
INVALID_INPUT
UNSUPPORTED_IMAGE
ENGINE_ERROR
OCR_ERROR
LAYOUT_ERROR
TABLE_EXTRACTION_ERROR
EXPORT_ERROR
IO_ERROR
INTERNAL_ERROR
```

El resultado puede incluir:

```text
OCRError
├── type
├── message
├── recoverable
└── metadata
```

El módulo puede indicar si técnicamente considera el error recuperable.

No decide el fallback documental.

---

# Retry

Por defecto, los retries de la **etapa OCR completa** pertenecen al orquestador.

Ejemplo:

```text
procesador-ocr
      ↓
ENGINE_ERROR
      ↓
OCRResult FAILED
      ↓
orchestrator
      ↓
retry / fallback / review
```

El módulo solo puede realizar retries internos de operaciones estrictamente técnicas y transparentes si son parte del funcionamiento normal del motor.

No debe crear un segundo workflow OCR por su cuenta.

---

# 14. Persistencia

El módulo debe persistir sus propios artefactos.

Nunca debe considerar un archivo válido antes de finalizar su escritura.

Ejemplo:

```text
document.json.tmp
        ↓
write
        ↓
validate
        ↓
atomic rename
        ↓
document.json
```

Aplicar la misma lógica cuando corresponda a:

```text
text.txt
document.md
document.json
metadata.json
tables/*
```

---

# Publicación de resultados

Una práctica recomendable es construir temporalmente:

```text
ocr/.tmp/
```

y publicar solamente al terminar correctamente:

```text
ocr/
```

Conceptualmente:

```text
execute
   ↓
temporary artifacts
   ↓
validate
   ↓
commit
   ↓
OCRResult
```

Esto evita resultados parcialmente escritos.

---

# 15. Artefactos existentes

El módulo no debe utilizar la mera existencia de:

```text
ocr/document.json
```

como criterio para evitar ejecución.

Eso pertenece al orquestador mediante:

```text
processing_key
artifact validation
stage state
```

Si el orquestador decidió llamar nuevamente a OCR, el procesador debe ejecutar.

---

# 16. Stop / Resume

El `procesador-ocr` no administra el `stop/resume` del workflow.

Esto pertenece al orquestador.

Ejemplo:

```text
ORCHESTRATOR

OCR READY
   ↓
execute
   ↓
OCR RUNNING
   ↓
OCR SUCCESS
   ↓
persist context
```

Si se solicita stop mientras OCR está ejecutándose:

* el orquestador no inicia nuevas etapas;
* la ejecución OCR actual puede finalizar;
* o puede cancelarse si el motor soporta cancelación segura.

El módulo no conserva un workflow parcial propio salvo que el motor OCR soporte explícitamente procesamiento incremental.

---

# Granularidad de Resume

A diferencia de `procesador-llm-call`, el OCR normalmente se trata como una operación atómica:

```text
IMAGE
   ↓
OCR
   ↓
OCRResult
```

Por lo tanto:

```text
resume OCR stage
```

generalmente significa:

```text
REUSE resultado completo
```

o:

```text
EXECUTE OCR nuevamente
```

No es necesario implementar un subgrafo de resume interno salvo que en el futuro el motor permita etapas costosas recuperables de forma independiente.

---

# 17. Concurrencia

El módulo debe poder ejecutarse simultáneamente sobre imágenes distintas.

Ejemplo:

```text
page_001 → procesador-ocr
page_002 → procesador-ocr
page_003 → procesador-ocr
```

No debe compartir estado mutable entre páginas.

El control de concurrencia global pertenece al orquestador.

---

# Aislamiento

Cada ejecución recibe:

```text
OCRRequest
```

y escribe exclusivamente dentro del:

```text
output_dir
```

asignado.

No debe asumir directorios globales compartidos.

---

# 18. Helpers

## Archivos

```text
create_ocr_directory()

build_ocr_output_paths()

ensure_directory()

write_text_atomic()

write_json_atomic()

read_json()
```

---

## Configuración

```text
normalize_docling_options()

should_enable_tables()

should_enable_layout()

should_enable_ocr()

should_enable_reading_order()
```

Estas funciones interpretan configuración explícita.

No toman decisiones de workflow.

---

## Texto

```text
count_ocr_characters()

count_ocr_words()

clean_ocr_text()

normalize_ocr_text()

is_ocr_empty()
```

---

## Markdown

```text
normalize_markdown()

merge_ocr_blocks()

preserve_reading_order()
```

---

## Tablas

```text
count_tables()

normalize_table()

table_to_markdown()

table_to_json()
```

---

## Layout

```text
count_blocks()

calculate_ocr_text_density()

normalize_bbox()

normalize_layout()
```

---

## Metadata

```text
build_ocr_metadata()

merge_ocr_metadata()

get_engine_version()

get_processor_version()
```

---

## Validación

```text
validate_ocr_request()

validate_ocr_input()

validate_ocr_result()

validate_output_artifacts()
```

---

# 19. Responsabilidades que NO pertenecen a este módulo

Eliminar del alcance cualquier función similar a:

```text
process_ocr_pdf()

select_ocr_mode()

should_run_ocr()

select_source()

select_primary_source()

compare_ocr_with_native_text()

compare_ocr_with_vlm()

build_llm_context_from_ocr()

send_to_llm()

run_vlm()

retry_document_stage()

resume_document()

skip_stage()

force_stage()

invalidate_downstream()
```

---

# `process_ocr_pdf()`

No pertenece al OCR.

El PDF debe haber sido procesado previamente por:

```text
procesador-pdf
```

OCR trabaja exclusivamente con imágenes.

---

# `select_ocr_mode()`

Si significa:

```text
¿debo ejecutar OCR?
```

pertenece al orquestador.

Si significa:

```text
¿cómo configuro técnicamente Docling?
```

pertenece al módulo OCR.

---

# `compare_ocr_with_native_text()`

La comparación entre fuentes pertenece al nivel documental.

El OCR no debe conocer:

```text
native_text
```

como fuente competidora.

---

# `compare_ocr_with_vlm()`

El módulo OCR no debe conocer resultados VLM.

---

# `build_llm_context_from_ocr()`

Convertir:

```text
ocr/document.md
```

en:

```text
<doc>
```

o:

```text
<extra>
```

pertenece al orquestador o al procesador LLM.

---

# Skip / Force

El módulo tampoco debe conocer:

```text
skip OCR
force OCR
reuse OCR
```

Estas son decisiones del `StageExecution` mantenido por el orquestador.

---

# 20. Integración con `procesador-image`

El input normal es:

```text
procesador-image
      ↓
normalized.png
      ↓
procesador-orquestador
      ↓
OCRRequest
      ↓
procesador-ocr
```

El procesador OCR no modifica:

```text
normalized.png
```

Debe tratarlo como input inmutable.

---

# Imagen específica para OCR

Si el módulo de imagen genera:

```text
image/ocr_ready.png
```

el orquestador puede seleccionarla como input.

Ejemplo:

```text
procesador-image
      ↓
ocr_ready.png
      ↓
orchestrator
      ↓
procesador-ocr
```

OCR no decide cuál variante utilizar.

---

# 21. Integración con `procesador-pdf`

Flujo esperado:

```text
procesador-pdf
      ↓
page.png
      ↓
procesador-image
      ↓
normalized.png
      ↓
procesador-orquestador
      ↓
procesador-ocr
```

OCR nunca debe:

```text
abrir page.pdf
renderizar page.pdf
extraer texto PDF
```

---

# 22. Integración con `procesador-llm-call`

OCR produce:

```text
text.txt
document.md
document.json
```

El orquestador puede seleccionar alguno como fuente.

Ejemplo:

```text
OCRResult
    ↓
orchestrator
    ↓
select_source()
    ↓
build_llm_input()
    ↓
procesador-llm-call
```

El OCR no conoce:

* prompts;
* templates;
* schemas LLM;
* providers;
* modelos;
* grafos LLM.

---

# 23. Integración completa

```text
                PDF / IMAGE
                     ↓
             procesador-orquestador
                     ↓
               procesador-pdf
                     ↓
                  page.png
                     ↓
              procesador-image
                     ↓
               normalized.png
                     ↓
             procesador-orquestador
                     ↓
                 OCRRequest
                     ↓
               procesador-ocr
                     ↓
          ┌──────────┼─────────────┐
          ▼          ▼             ▼
       text.txt  document.md   document.json
                     │
                     └──────┬──────┘
                            ↓
                       OCRResult
                            ↓
                  procesador-orquestador
                            ↓
                     source selection
                            ↓
                  procesador-llm-call
```

---

# 24. Independencia del módulo

El módulo debe funcionar completamente aislado:

```text
normalized.png
      ↓
OCRRequest
      ↓
procesador-ocr
      ↓
OCRResult
```

Esto permite:

* pruebas unitarias;
* benchmarking;
* evaluación de Docling;
* comparar motores OCR;
* cambiar Docling en el futuro;
* reprocesar OCR independientemente;
* probar diferentes configuraciones;
* medir performance;
* validar calidad de extracción.

---

# 25. Reemplazo del motor OCR

El resto del sistema no debería depender directamente de Docling.

La arquitectura deseada es:

```text
OCRRequest
     ↓
procesador-ocr
     ↓
OCRDocument
     ↓
OCRResult
```

Internamente hoy puede existir:

```text
Docling
```

mañana:

```text
otro motor OCR
```

sin alterar:

```text
OCRRequest
OCRResult
```

---

# 26. Métricas de ejecución

Además de métricas del contenido, puede registrar:

```text
timing
├── setup_time
├── inference_time
├── extraction_time
├── export_time
└── total_time
```

También:

```text
resource_usage
├── cpu
├── memory
└── gpu
```

cuando esa información esté disponible y resulte útil.

El módulo solo mide.

El orquestador decide cómo utilizar esas métricas.

---

# Regla arquitectónica final

`procesador-ocr`:

> **Recibe una imagen preparada y devuelve una representación textual y estructural estable de su contenido.**

Es dueño de:

```text
configuración técnica OCR

Docling

extracción de texto

extracción de estructura

layout

reading order

tablas

normalización del resultado OCR

métricas OCR

validación técnica OCR

persistencia de artefactos OCR

metadata OCR
```

No es dueño de:

```text
PDF

normalización de imagen

selección del input documental

decisión de ejecutar OCR

idempotencia del workflow

stop/resume documental

skip/force

reprocesamiento documental

fallbacks

comparación de fuentes

selección de fuente

VLM

LLM

consolidación documental
```

En términos simples:

```text
procesador-orquestador
    =
decide si OCR debe ejecutarse
y qué hacer con su resultado

procesador-image
    =
prepara la imagen

procesador-ocr
    =
lee y estructura la imagen

procesador-llm-call
    =
interpreta mediante inferencia
```

La regla operativa fundamental es:

> **OCR transforma una imagen en información estructurada; no decide el workflow que la rodea.**

Y respecto de reutilización:

> **El procesador OCR no decide si un resultado previo puede reutilizarse. Si recibe un `OCRRequest`, ejecuta la extracción. La decisión de evitar esa ejecución costosa pertenece al orquestador.**
