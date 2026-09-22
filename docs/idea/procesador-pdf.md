# Procesador PDF

## Objetivo

El módulo `procesador-pdf` tiene como responsabilidad exclusiva **inspeccionar, descomponer y extraer los artefactos nativos de un archivo PDF**.

Debe recibir un PDF y producir una representación organizada del documento y de cada una de sus páginas.

Puede generar:

* PDF individual por página;
* render visual de cada página;
* texto nativo;
* bloques de texto;
* imágenes embebidas;
* métricas de composición;
* clasificación técnica;
* metadata del documento;
* metadata por página.

El módulo:

* no normaliza imágenes;
* no ejecuta OCR;
* no llama a LLM/VLM;
* no selecciona la fuente documental final;
* no decide si ejecutar OCR;
* no decide si ejecutar visión;
* no compara fuentes;
* no controla el workflow documental.

Su responsabilidad empieza cuando recibe:

```text
PDFRequest
```

y termina cuando devuelve:

```text
PDFResult
```

---

# Principio de diseño

`procesador-pdf` responde:

> **“¿Qué contiene nativamente este PDF y qué artefactos puedo extraer de cada página?”**

No responde:

> **“¿Qué debo hacer posteriormente con esos artefactos?”**

La regla fundamental es:

> **Extraer primero, decidir después.**

El procesador PDF describe el documento.

El orquestador decide cómo utilizarlo.

---

# Separación de responsabilidades

```text
procesador-orquestador
    =
decide si procesar PDF
+ administra estado
+ idempotencia
+ stop/resume
+ skip/force
+ routing
+ fallbacks
+ selección de fuentes

procesador-pdf
    =
inspecciona PDF
+ separa páginas
+ renderiza
+ extrae texto nativo
+ extrae imágenes embebidas
+ genera metadata

procesador-image
    =
prepara técnicamente renders o imágenes

procesador-ocr
    =
extrae contenido desde imágenes

procesador-llm-call
    =
realiza inferencia
```

---

# Flujo principal

1. Recibir `PDFRequest`.
2. Validar archivo.
3. Tratar el PDF original como input inmutable.
4. Obtener metadata global:

   * cantidad de páginas;
   * dimensiones;
   * versión PDF;
   * metadata disponible.
5. Crear estructura de salida.
6. Procesar cada página.
7. Para cada página:

   * generar `page.pdf`;
   * renderizar `page.png`;
   * extraer texto nativo;
   * extraer bloques;
   * extraer imágenes embebidas;
   * calcular métricas;
   * clasificar composición;
   * generar metadata.
8. Validar artefactos.
9. Consolidar páginas.
10. Persistir `metadata.json`.
11. Devolver `PDFResult`.

---

# Flujo general

```text
PDFRequest
    ↓
validate_pdf()
    ↓
inspect_pdf()
    ↓
PDF metadata
    ↓
iterate pages
    ↓
process_pdf_page()
    ↓
 ┌──────────┬──────────┬──────────────┬────────────────┐
 ▼          ▼          ▼              ▼
page.pdf   page.png   native text   embedded images
    └──────────┬──────────┬──────────────┘
               ↓
       analyze_pdf_page()
               ↓
      classify_pdf_page()
               ↓
       PDFPageResult
               ↓
        consolidate
               ↓
          PDFResult
```

---

# Contrato del módulo

## Entrada

```text
PDFRequest
├── pdf_path
├── output_dir
├── options
└── context
```

Ejemplo:

```json
{
  "pdf_path": "document.pdf",

  "output_dir": "document/",

  "options": {
    "extract_pages": true,
    "render": true,
    "extract_text": true,
    "extract_images": true,
    "layout": true,
    "dpi": 200
  },

  "context": {
    "document_id": "doc_001",
    "workflow_run_id": "run_001"
  }
}
```

`context` se utiliza exclusivamente para:

* correlación;
* trazabilidad;
* metadata.

El módulo no modifica el estado global del workflow.

---

# Salida

```text
PDFResult
├── source_path
├── metadata
├── pages[]
├── metrics
├── artifacts
├── validation
└── status
```

Cada página devuelve:

```text
PDFPageResult
├── page_number
├── page_pdf
├── page_image
├── native_text
├── text_blocks[]
├── embedded_images[]
├── metrics
├── classification
├── artifacts
├── validation
└── metadata
```

Ejemplo:

```json
{
  "page_number": 1,

  "page_pdf": "page_001/source/page.pdf",

  "page_image": "page_001/render/page.png",

  "native_text": "page_001/native_text/text.txt",

  "embedded_images": [
    "page_001/embedded_images/image_001.png"
  ],

  "metrics": {
    "characters": 2843,
    "words": 431,
    "text_coverage": 0.61,
    "image_coverage": 0.08,
    "largest_image_coverage": 0.05
  },

  "classification": "TEXT",

  "validation": {
    "status": "VALID"
  },

  "status": "success"
}
```

---

# Estructura de salida

Ejemplo:

```text
document/
├── source/
│   └── document.pdf
│
├── metadata.json
│
├── page_001/
│   ├── source/
│   │   └── page.pdf
│   │
│   ├── render/
│   │   └── page.png
│   │
│   ├── native_text/
│   │   ├── text.txt
│   │   └── blocks.json
│   │
│   ├── embedded_images/
│   │   ├── image_001.png
│   │   └── image_002.jpg
│   │
│   └── metadata.json
│
├── page_002/
│   └── ...
│
└── page_010/
    └── ...
```

Cada página debe funcionar como una **unidad autocontenida**.

---

# Ownership de artefactos

El procesador PDF es dueño únicamente de:

```text
source/
render/
native_text/
embedded_images/
metadata.json
```

No debe escribir dentro de:

```text
image/
ocr/
llm/
```

Esos namespaces pertenecen a otros procesadores.

---

# Input inmutable

El PDF original debe considerarse inmutable.

Nunca debe ser modificado en el lugar.

Ejemplo correcto:

```text
document.pdf
    ↓
procesador-pdf
    ↓
document/source/document.pdf
```

o simplemente conservar referencia al original cuando la política de almacenamiento así lo permita.

Nunca:

```text
document.pdf
    ↓
modificar
    ↓
document.pdf
```

---

# Relación con idempotencia

La idempotencia global pertenece al orquestador.

`procesador-pdf` no decide:

```text
REUSE
SKIP
FORCE
RESUME
```

El flujo correcto es:

```text
PDF stage
    ↓
orchestrator
    ↓
 ┌──────────┬──────────┬──────────┐
 ▼          ▼          ▼
REUSE      SKIP      EXECUTE
                       ↓
                procesador-pdf
```

Si recibe un `PDFRequest`, debe asumir:

> **La ejecución fue autorizada y debe realizarse según la configuración recibida.**

---

# Determinismo técnico

El módulo debe favorecer reproducibilidad.

Idealmente:

```text
mismo PDF
+
misma configuración
+
misma versión del procesador
──────────────────────────
mismos artefactos lógicos
```

Para ello debe:

* normalizar opciones;
* preservar orden de páginas;
* generar nombres determinísticos;
* mantener formatos estables;
* registrar versiones;
* evitar metadata volátil dentro del contenido funcional.

---

# Metadata global

`metadata.json` del documento puede contener:

```text
PDFMetadata
├── processor
├── processor_version
├── engine
├── engine_version
├── page_count
├── pdf_version
├── document_info
├── options
├── validation
├── timing
└── context
```

Ejemplo:

```json
{
  "processor": "procesador-pdf",

  "processor_version": "1.0.0",

  "engine": "poppler",

  "page_count": 10,

  "options": {
    "render": true,
    "extract_text": true,
    "extract_images": true,
    "dpi": 200
  }
}
```

---

# Metadata por página

Cada página puede registrar:

```text
PDFPageMetadata
├── page_number
├── dimensions
├── metrics
├── classification
├── artifacts
├── validation
└── timing
```

---

# 1. Primitivas

Funciones de bajo nivel que encapsulan:

* Poppler;
* `python-poppler`;
* Poppler CLI;
* otras librerías PDF auxiliares.

Las primitivas conocen PDF.

No conocen:

* OpenCV como pipeline de normalización;
* OCR;
* Docling;
* LLM;
* workflow documental.

---

## Documento

```text
get_pdf_metadata(pdf_path)

get_page_count(pdf_path)

get_page_dimensions(pdf_path, page_number)
```

---

## Separación y unión

```text
extract_page(pdf_path, page_number, output_path)

split_pdf(pdf_path, output_dir)

merge_pdfs(pdf_paths, output_path)
```

`merge_pdfs()` es una utilidad PDF genérica.

No debe utilizar resultados OCR o LLM.

---

## Render

```text
render_page_to_image(
    pdf_path,
    page_number,
    output_path,
    dpi=200
)
```

---

## Texto nativo

```text
extract_text_from_page(
    pdf_path,
    page_number,
    layout=True
)

get_text_blocks(
    pdf_path,
    page_number
)
```

---

## Imágenes embebidas

```text
extract_images_from_page(
    pdf_path,
    page_number,
    output_dir
)

get_image_blocks(
    pdf_path,
    page_number
)
```

---

# 2. Procesamiento principal

## `process_pdf(request)`

Función principal del módulo.

Debe:

1. validar `PDFRequest`;
2. validar PDF;
3. preparar output temporal;
4. obtener metadata;
5. obtener cantidad de páginas;
6. procesar páginas;
7. validar resultados;
8. consolidar `PDFResult`;
9. generar metadata;
10. publicar artefactos;
11. devolver resultado.

```text
process_pdf()
     ↓
validate_pdf_request()
     ↓
validate_pdf()
     ↓
inspect_pdf()
     ↓
iterate pages
     ↓
process_pdf_page()
     ↓
validate_pdf_result()
     ↓
commit artifacts
     ↓
PDFResult
```

---

# 3. Procesamiento por página

## `process_pdf_page(...)`

Procesa exclusivamente una página.

Debe:

1. validar número de página;
2. preparar directorio;
3. generar `page.pdf`;
4. renderizar `page.png` cuando se solicite;
5. extraer texto cuando se solicite;
6. extraer bloques;
7. extraer imágenes embebidas;
8. analizar composición;
9. clasificar;
10. validar artefactos;
11. generar metadata;
12. devolver `PDFPageResult`.

```text
process_pdf_page()
       ↓
extract_page()
       ↓
render_page_to_image()
       ↓
extract_text_from_page()
       ↓
get_text_blocks()
       ↓
extract_images_from_page()
       ↓
analyze_pdf_page()
       ↓
classify_pdf_page()
       ↓
validate_pdf_page_result()
       ↓
PDFPageResult
```

---

# Opciones por página

No todas las operaciones necesitan ejecutarse siempre.

Ejemplo:

```json
{
  "extract_pages": true,
  "render": true,
  "extract_text": true,
  "extract_images": false
}
```

El módulo ejecuta exactamente las capacidades solicitadas.

No decide cuáles necesita el workflow.

---

# 4. Inspección del documento

## `inspect_pdf(pdf_path)`

Agrupa información general.

Puede devolver:

```text
PDFDocumentInfo
├── page_count
├── pdf_version
├── metadata
├── encrypted
├── dimensions[]
└── technical_info
```

No interpreta semánticamente el documento.

---

# 5. Análisis de página

## `analyze_pdf_page(page_data)`

Calcula métricas nativas.

Puede analizar:

```text
characters

words

text_blocks

embedded_images

text_area

image_area

text_coverage

image_coverage

largest_image_coverage
```

Devuelve:

```text
PDFPageMetrics
```

---

# PDFPageMetrics

```text
PDFPageMetrics
├── characters
├── words
├── text_blocks
├── images
├── text_coverage
├── image_coverage
└── largest_image_coverage
```

Estas métricas pueden utilizarse posteriormente por el orquestador.

El módulo solamente las calcula.

---

# 6. Clasificación técnica

## `classify_pdf_page(metrics)`

Clasifica composición PDF.

Valores:

```text
TEXT

IMAGE

MIXED
```

Interpretación:

```text
TEXT
    contenido nativo predominantemente textual

IMAGE
    poco o ningún texto nativo
    y representación visual dominante

MIXED
    combinación relevante de texto e imágenes
```

Esta clasificación es exclusivamente descriptiva.

---

# Clasificación no implica routing

Incorrecto:

```text
TEXT
  ↓
usar LLM texto

IMAGE
  ↓
ejecutar OCR

MIXED
  ↓
ejecutar VLM
```

Correcto:

```text
classification
     ↓
PDFPageResult
     ↓
orchestrator
     ↓
routing decision
```

---

# 7. Texto nativo

El módulo puede extraer:

```text
native_text/text.txt
```

y opcionalmente:

```text
native_text/blocks.json
```

El texto debe preservar layout cuando sea posible según las opciones.

No debe:

* corregirse mediante LLM;
* mezclarse con OCR;
* reemplazarse por OCR;
* evaluarse semánticamente.

---

# Texto vacío

El módulo puede detectar:

```text
native_text_empty = true
```

pero solamente como metadata.

No debe interpretar:

```text
native_text_empty
       ↓
run OCR
```

Eso corresponde al orquestador.

---

# 8. Render de página

El render producido por PDF debe representar fielmente la página.

Salida:

```text
render/page.png
```

Debe ser suficiente para que posteriormente pueda procesarlo:

```text
procesador-image
```

El procesador PDF puede controlar parámetros técnicos propios del render:

```text
dpi
format
page dimensions
```

No debe:

* deskew;
* sharpen;
* denoise;
* ajustar contraste;
* preparar específicamente para OCR;
* preparar específicamente para VLM.

Eso corresponde a `procesador-image`.

---

# 9. Imágenes embebidas

El módulo puede extraer imágenes nativas del PDF.

Ejemplo:

```text
embedded_images/
├── image_001.png
├── image_002.jpg
└── image_003.png
```

Debe conservar cuando sea posible:

* formato;
* dimensiones;
* relación con la página;
* posición;
* identificador.

Puede registrar:

```text
EmbeddedImage
├── image_id
├── path
├── bbox
├── width
├── height
├── format
└── metadata
```

No debe decidir si una imagen embebida es relevante para OCR o VLM.

---

# 10. Validación

## `validate_pdf_result(result)`

Debe verificar calidad técnica.

Estados posibles:

```text
VALID
PARTIAL
INVALID
ERROR
```

Puede evaluar:

* PDF procesable;
* páginas esperadas;
* artefactos presentes;
* renders válidos;
* extracción completa;
* errores por página.

---

# Validación por página

## `validate_pdf_page_result(page_result)`

Puede devolver:

```text
VALID

PARTIAL

RENDER_ERROR

TEXT_EXTRACTION_ERROR

IMAGE_EXTRACTION_ERROR

ERROR
```

La validación describe qué ocurrió.

No decide el fallback posterior.

---

# 11. Errores

Errores posibles:

```text
INVALID_INPUT

UNSUPPORTED_PDF

ENCRYPTED_PDF

CORRUPTED_PDF

PAGE_EXTRACTION_ERROR

RENDER_ERROR

TEXT_EXTRACTION_ERROR

IMAGE_EXTRACTION_ERROR

IO_ERROR

INTERNAL_ERROR
```

Puede devolver:

```text
PDFError
├── type
├── page_number
├── message
├── recoverable
└── metadata
```

El módulo puede indicar si el error parece técnicamente recuperable.

El orquestador decide:

```text
retry
fallback
partial
stop
review
```

---

# 12. Persistencia

Los artefactos deben publicarse solamente después de completarse.

Ejemplo:

```text
page.png.tmp
      ↓
write
      ↓
validate
      ↓
atomic rename
      ↓
page.png
```

La misma regla aplica a:

```text
page.pdf
text.txt
blocks.json
metadata.json
embedded_images/*
```

---

# Directorios temporales

Puede utilizarse:

```text
document/.tmp/
```

o:

```text
page_001/.tmp/
```

durante procesamiento.

Flujo:

```text
processing
    ↓
temporary artifacts
    ↓
validate
    ↓
commit
    ↓
PDFPageResult
```

Esto evita exponer artefactos incompletos al orquestador.

---

# 13. Procesamiento parcial

El módulo debe soportar resultados parciales técnicamente válidos.

Ejemplo:

```text
page.pdf              SUCCESS
page.png              SUCCESS
native_text           ERROR
embedded_images       SUCCESS
```

La página puede devolver:

```text
status = PARTIAL
```

y preservar los artefactos válidos.

El procesador no decide si el workflow puede continuar.

---

# 14. Stop / Resume

El módulo no administra el `stop/resume` global.

Esto pertenece al orquestador.

Sin embargo, el procesamiento PDF tiene una particularidad:

> **Un PDF contiene múltiples páginas y cada página es una unidad natural de trabajo.**

Por eso el procesador debe permitir procesamiento aislado mediante:

```text
process_pdf_page()
```

Esto permite que el orquestador pueda reanudar trabajo a nivel de página sin volver a procesar el PDF completo.

---

# Resume a nivel documental

Ejemplo:

```text
page_001 SUCCESS
page_002 SUCCESS
page_003 FAILED
page_004 NOT_STARTED
```

El orquestador puede decidir:

```text
page_001 REUSE
page_002 REUSE
page_003 EXECUTE
page_004 EXECUTE
```

y llamar exclusivamente:

```text
process_pdf_page()
```

sobre las páginas necesarias.

El módulo PDF no decide cuáles reutilizar.

---

# Stop entre páginas

Cuando sea posible, una ejecución multipágina debe permitir que el caller deje de solicitar nuevas páginas.

Conceptualmente:

```text
P1 complete
 ↓
P2 complete
 ↓
stop requested by orchestrator
 ↓
do not start P3
```

El estado global de stop pertenece al orquestador.

---

# 15. Skip / Force

El módulo no debe conocer:

```text
skip PDF

force PDF

skip page 3

force page 4

reuse page
```

Estas decisiones pertenecen al orquestador.

Si recibe una llamada explícita a:

```text
process_pdf_page(page=3)
```

debe ejecutar la página solicitada.

---

# 16. Reprocesamiento

La función:

```text
reprocess_pdf_page()
```

no debería contener lógica de idempotencia propia.

Puede mantenerse como wrapper semántico:

```text
reprocess_pdf_page()
       ↓
process_pdf_page()
```

El orquestador decide previamente si realmente debe ejecutarse.

Flujo:

```text
orchestrator
     ↓
processing_key
     ↓
valid result?
   ┌────┴────┐
  YES       NO
   │         │
 REUSE    process_pdf_page()
```

---

# 17. Granularidad de processing key

Es recomendable permitir claves diferenciadas por documento y página.

Ejemplo:

```text
PDF_DOCUMENT_STAGE
```

puede depender de:

```text
pdf_hash
processor_version
global_options
```

Mientras cada página puede depender de:

```text
pdf_hash
page_number
processor_version
page_options
```

Conceptualmente:

```text
page_processing_key =
    hash(
        pdf_hash
        + page_number
        + processor_version
        + normalized_options
    )
```

El cálculo y validación pertenecen al orquestador.

---

# 18. Concurrencia

Las páginas son independientes y pueden procesarse en paralelo cuando la implementación lo permita.

Ejemplo:

```text
document.pdf
      ↓
 ┌────┬────┬────┬────┐
 ▼    ▼    ▼    ▼
P1   P2   P3   P4
```

Cada ejecución de página:

* escribe en su propio directorio;
* no modifica otras páginas;
* no comparte estado mutable;
* conserva `page_number`.

El control de concurrencia pertenece al orquestador.

---

# 19. Rebuild PDF

## `rebuild_pdf(page_pdfs, output_path)`

Puede reconstruir un PDF exclusivamente desde otros PDFs de página.

```text
page_001.pdf
page_002.pdf
page_003.pdf
      ↓
rebuild_pdf()
      ↓
document.pdf
```

No debe utilizar:

```text
OCR
normalized images
LLM results
```

Es una operación puramente PDF.

---

# 20. Helpers

## Directorios y archivos

```text
create_document_directory()

create_page_directory()

build_page_filename()

normalize_filename()

ensure_directory()

copy_source_pdf()

write_text_atomic()

write_json_atomic()

read_json()
```

---

## Documento

```text
get_pdf_metadata()

get_page_count()

get_page_dimensions()
```

---

## Página

```text
validate_page_number()

build_page_metadata()

build_page_artifact_paths()
```

---

## Métricas

```text
calculate_page_area()

calculate_bbox_area()

calculate_text_coverage()

calculate_image_coverage()

calculate_largest_image_ratio()

count_characters()

count_words()
```

---

## Validaciones

```text
validate_pdf_request()

validate_pdf()

validate_pdf_result()

validate_pdf_page_result()

validate_output_artifacts()

is_text_empty()

has_embedded_images()
```

---

## Metadata

```text
build_pdf_metadata()

build_pdf_page_metadata()

merge_pdf_metadata()

get_processor_version()

get_engine_version()
```

---

# 21. Responsabilidades que NO pertenecen a este módulo

Eliminar del alcance cualquier lógica similar a:

```text
normalize_image()

deskew_image()

calculate_blur_score()

prepare_image_for_ocr()

prepare_image_for_vlm()

run_ocr()

process_ocr_page()

send_to_llm()

process_llm_request()

select_primary_source()

select_extraction_strategy()

select_ocr_or_vlm()

compare_native_text_with_ocr()

resume_document()

skip_stage()

force_stage()

invalidate_downstream()
```

---

# Normalización de imagen

El PDF produce:

```text
render/page.png
```

La transformación técnica posterior pertenece a:

```text
procesador-image
```

---

# OCR

El módulo puede detectar que:

```text
native_text = empty
```

pero no debe ejecutar:

```text
procesador-ocr
```

La decisión pertenece al orquestador.

---

# LLM/VLM

El módulo nunca llama directamente modelos.

Tampoco construye:

```text
LLMInput
```

ni selecciona:

```text
TEXT_ONLY
OCR_ONLY
VLM_ONLY
TEXT_PLUS_VLM
OCR_PLUS_VLM
```

---

# 22. Diferencia entre extracción y decisión

El módulo puede generar simultáneamente:

```text
page.pdf

page.png

native_text/text.txt

native_text/blocks.json

embedded_images/

metadata.json
```

aunque finalmente solamente se utilice uno de esos artefactos.

No debe eliminar outputs por considerar que "no serán necesarios".

La regla permanece:

> **Extraer primero, decidir después.**

Esto permite al orquestador elegir posteriormente entre:

* texto nativo;
* render;
* imagen normalizada;
* OCR;
* VLM;
* combinación de fuentes.

---

# 23. Integración con `procesador-image`

Flujo:

```text
procesador-pdf
      ↓
render/page.png
      ↓
procesador-orquestador
      ↓
ImageRequest
      ↓
procesador-image
```

El procesador PDF no debe:

```text
detectar blur para corregirlo
deskew
denoise
sharpen
binarize
```

Puede producir métricas PDF, pero la calidad visual posterior pertenece al módulo de imagen.

---

# 24. Integración con `procesador-ocr`

Puede producir:

```text
native_text/text.txt
```

y:

```text
render/page.png
```

Si el orquestador determina que OCR es necesario:

```text
render/page.png
       ↓
procesador-image
       ↓
ocr_ready.png
       ↓
procesador-ocr
```

El módulo PDF no participa de esa decisión.

---

# 25. Integración con `procesador-llm-call`

El módulo nunca llama directamente a LLM.

Flujo correcto:

```text
procesador-pdf
       ↓
PDFPageResult
       ↓
procesador-orquestador
       ↓
select_source()
       ↓
build_llm_input()
       ↓
procesador-llm-call
```

---

# 26. Integración completa

```text
                        PDF
                         ↓
                 procesador-orquestador
                         ↓
                     PDFRequest
                         ↓
                  procesador-pdf
                         ↓
                    PDFResult
                         ↓
              ┌──────────┴──────────┐
              ▼                     ▼
       native_text              render/page
              │                     │
              │                     ▼
              │             procesador-image
              │                     ↓
              │              prepared images
              │                     │
              └──────────┬──────────┘
                         ↓
                 procesador-orquestador
                         ↓
                  routing documental
                   ┌─────┴─────┐
                   ▼           ▼
                  OCR         LLM/VLM
```

---

# 27. Independencia del módulo

`procesador-pdf` debe poder ejecutarse de forma aislada:

```text
document.pdf
     ↓
PDFRequest
     ↓
procesador-pdf
     ↓
PDFResult
```

Esto permite:

* tests unitarios;
* benchmarking de Poppler;
* extracción de texto nativo;
* separación de páginas;
* render independiente;
* extracción de imágenes embebidas;
* reprocesamiento de páginas;
* cambiar posteriormente el motor PDF;
* reutilizarlo fuera del workflow principal.

---

# 28. Reemplazo del motor PDF

El resto del sistema no debe depender directamente de Poppler.

La arquitectura debe ser:

```text
PDFRequest
    ↓
procesador-pdf
    ↓
PDFResult
```

Internamente puede utilizar actualmente:

```text
Poppler
python-poppler
CLI
```

y posteriormente reemplazarse por otra implementación.

Mientras se mantengan:

```text
PDFRequest
PDFResult
PDFPageResult
```

el resto del sistema no debería cambiar.

---

# 29. Métricas de ejecución

Puede registrar:

```text
timing
├── metadata_time
├── split_time
├── render_time
├── text_extraction_time
├── image_extraction_time
└── total_time
```

Por página:

```text
page_timing
├── extract_page
├── render
├── text
├── images
└── total
```

También, cuando resulte útil:

```text
resource_usage
├── cpu
├── memory
└── disk
```

El módulo mide.

No decide scheduling ni políticas de costo.

---

# 30. Estados técnicos

El procesador puede devolver:

```text
SUCCESS
PARTIAL
FAILED
```

A nivel página:

```text
SUCCESS
PARTIAL
FAILED
```

Los estados del workflow:

```text
REUSED
SKIPPED
INVALIDATED
PAUSED
```

pertenecen al orquestador.

Esta separación debe mantenerse explícita.

---

# Regla arquitectónica final

`procesador-pdf`:

> **Recibe un PDF y devuelve sus artefactos nativos, métricas y metadata organizados por página.**

Es dueño de:

```text
validación técnica PDF

metadata PDF

separación de páginas

page.pdf

render/page.png

texto nativo

bloques de texto

imágenes embebidas

métricas de composición

clasificación TEXT / IMAGE / MIXED

validación técnica por página

persistencia de artefactos PDF
```

No es dueño de:

```text
normalización de imágenes

OCR

LLM/VLM

selección de fuente documental

routing

decisión OCR/VLM

idempotencia del workflow

stop/resume global

skip/force

fallbacks

invalidación downstream

consolidación semántica
```

En términos simples:

```text
procesador-pdf
    =
descompone y describe el PDF

procesador-image
    =
prepara técnicamente sus imágenes

procesador-ocr
    =
lee las imágenes

procesador-llm-call
    =
realiza inferencia

procesador-orquestador
    =
decide cómo colaboran
```

La regla operativa fundamental es:

> **El PDF produce evidencia documental; no decide cómo interpretarla.**

Y respecto de reutilización:

> **`procesador-pdf` no decide si una página o un documento previo pueden reutilizarse. Si recibe un `PDFRequest` o una llamada explícita a `process_pdf_page()`, ejecuta la operación solicitada. La decisión `REUSE / SKIP / FORCE / RESUME` pertenece al orquestador.**
