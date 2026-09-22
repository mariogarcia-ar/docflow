# Procesador PDF

## Objetivo

El módulo `procesador-pdf` tiene como responsabilidad exclusiva **descomponer, inspeccionar y extraer artefactos nativos de un archivo PDF**.

Debe recibir un PDF y producir una estructura organizada por páginas con:

* PDF de página individual;
* render de página;
* texto nativo;
* imágenes embebidas;
* metadata técnica.

Este módulo **no normaliza imágenes**, **no ejecuta OCR**, **no llama a LLM/VLM** y **no decide el workflow posterior**. Esa coordinación pertenece al `workflow/orchestrator`.

---

# Flujo principal

* Recibir un PDF.
* Validar que el archivo sea procesable.
* Crear una carpeta principal para el documento.
* Obtener metadata general:

  * cantidad de páginas;
  * dimensiones;
  * información básica del documento.
* Dividir conceptualmente el procesamiento por página.
* Para cada página:

  * generar un PDF individual;
  * renderizar la página a imagen;
  * extraer texto nativo preservando layout;
  * extraer imágenes embebidas;
  * calcular métricas básicas de composición;
  * clasificar técnicamente la página como:

    * `TEXT`
    * `IMAGE`
    * `MIXED`
  * generar `metadata.json`.
* Conservar todos los artefactos generados.
* Devolver al orquestador la estructura resultante.

La clasificación sirve como **metadata descriptiva**.

El módulo no debe decidir directamente:

* ejecutar OCR;
* ejecutar VLM;
* usar texto nativo;
* usar imagen;
* combinar fuentes.

Eso pertenece al orquestador.

---

# Estructura de salida

Ejemplo para un PDF de 10 páginas:

```text id="gd90e4"
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
│   │   └── text.txt
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

Cada página debe funcionar como una **unidad autocontenida de procesamiento**.

---

# Contrato del módulo

## Entrada

```text id="68v7dq"
PDFRequest
├── pdf_path
├── output_dir
└── options
```

Opciones posibles:

```json id="1awz7j"
{
  "render": true,
  "extract_text": true,
  "extract_images": true,
  "layout": true,
  "dpi": 200
}
```

---

## Salida

```text id="yvppxs"
PDFResult
├── document_id
├── source_path
├── metadata
├── pages[]
└── status
```

Cada página devuelve:

```text id="vf3wru"
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

Ejemplo conceptual:

```json id="pl3xg4"
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

  "classification": "TEXT"
}
```

---

# 1. Primitivas

Funciones de bajo nivel que encapsulan:

* Poppler;
* `python-poppler`;
* Poppler CLI;
* utilidades auxiliares de PDF.

## Documento

* `get_pdf_metadata(pdf_path)`
* `get_page_count(pdf_path)`
* `get_page_dimensions(pdf_path, page_number)`

## Separación y unión

* `extract_page(pdf_path, page_number, output_path)`
* `split_pdf(pdf_path, output_dir)`
* `merge_pdfs(pdf_paths, output_path)`

## Render

* `render_page_to_image(pdf_path, page_number, output_path, dpi=200)`

## Texto nativo

* `extract_text_from_page(pdf_path, page_number, layout=True)`
* `get_text_blocks(pdf_path, page_number)`

## Imágenes embebidas

* `extract_images_from_page(pdf_path, page_number, output_dir)`
* `get_image_blocks(pdf_path, page_number)`

Las primitivas conocen Poppler y operaciones PDF, pero no conocen OCR, OpenCV ni LLM.

---

# 2. Utilitarios

Funciones que combinan primitivas para resolver operaciones completas sobre PDFs.

## `process_pdf(pdf_path, output_dir, options=None)`

Función principal del módulo.

Debe:

* validar PDF;
* crear estructura del documento;
* conservar el PDF original;
* obtener metadata;
* obtener cantidad de páginas;
* iterar sobre todas las páginas;
* llamar a `process_pdf_page()`;
* consolidar resultados;
* generar `metadata.json`;
* devolver `PDFResult`.

Flujo:

```text id="z1ks0v"
process_pdf()
     ↓
validate_pdf()
     ↓
get_pdf_metadata()
     ↓
iterate pages
     ↓
process_pdf_page()
     ↓
PDFResult
```

---

## `process_pdf_page(pdf_path, page_number, output_dir, options=None)`

Procesa exclusivamente una página PDF.

Debe:

* crear carpeta de página;
* generar `page.pdf`;
* generar `page.png`;
* extraer texto nativo;
* extraer imágenes embebidas;
* calcular métricas;
* clasificar técnicamente la página;
* generar metadata;
* devolver `PDFPageResult`.

```text id="m77pk1"
process_pdf_page()
       ↓
extract_page()
       ↓
render_page_to_image()
       ↓
extract_text_from_page()
       ↓
extract_images_from_page()
       ↓
analyze_pdf_page()
       ↓
classify_pdf_page()
       ↓
PDFPageResult
```

---

## `analyze_pdf_page(page_data)`

Calcula métricas sobre la composición nativa del PDF.

Puede analizar:

* cantidad de caracteres;
* cantidad de palabras;
* cantidad de bloques de texto;
* cantidad de imágenes;
* área de texto;
* área de imágenes;
* cobertura de texto;
* cobertura de imágenes;
* imagen dominante.

Devuelve:

```text id="rbtgpp"
PDFPageMetrics
```

---

## `classify_pdf_page(metrics)`

Clasifica la composición de la página.

Posibles valores:

```text id="4g4syb"
TEXT
IMAGE
MIXED
```

Ejemplo conceptual:

```text id="nr8vd7"
TEXT
- contenido nativo predominantemente textual

IMAGE
- poco o ningún texto nativo
- imagen dominante sobre la página

MIXED
- combinación relevante de texto e imágenes
```

Esta función **solo describe la composición PDF**.

No debe interpretar:

```text id="xltr9v"
TEXT  → usar LLM texto
IMAGE → ejecutar OCR
MIXED → ejecutar VLM
```

Esas decisiones pertenecen al orquestador.

---

## `reprocess_pdf_page(pdf_path, page_number, output_dir)`

Permite regenerar los artefactos de una página concreta sin reprocesar todo el documento.

Útil para:

* errores de extracción;
* cambios de DPI;
* cambios de parámetros;
* debugging.

---

## `rebuild_pdf(page_pdfs, output_path)`

Reconstruye un PDF a partir de páginas PDF.

No debe tomar artefactos de OCR ni LLM.

---

# 3. Helpers

Funciones pequeñas y reutilizables.

## Directorios y archivos

* `create_document_directory(pdf_path, output_root)`
* `create_page_directory(document_dir, page_number)`
* `build_page_filename(page_number, extension)`
* `normalize_filename(filename)`
* `ensure_directory(path)`
* `copy_source_pdf(source, destination)`
* `write_text(path, content)`
* `write_json(path, data)`
* `read_json(path)`

## Métricas de página

* `calculate_page_area(width, height)`
* `calculate_bbox_area(bbox)`
* `calculate_text_coverage(text_blocks, page_size)`
* `calculate_image_coverage(image_blocks, page_size)`
* `calculate_largest_image_ratio(image_blocks, page_size)`
* `count_characters(text)`
* `count_words(text)`

## Validaciones

* `validate_pdf(path)`
* `validate_page_number(page_number, total_pages)`
* `is_text_empty(text)`
* `has_embedded_images(images)`

## Metadata

* `build_pdf_metadata(pdf_info, page_count)`
* `build_pdf_page_metadata(metrics, classification, artifacts)`
* `merge_pdf_metadata(base_metadata, new_metadata)`

---

# Responsabilidades que NO pertenecen a este módulo

Eliminar del alcance cualquier función similar a:

```text id="banhhn"
normalize_image()
deskew_image()
calculate_blur_score()

run_ocr()
process_ocr_page()

send_to_llm()
process_llm_request()

select_primary_source()
select_extraction_strategy()
select_ocr_or_vlm()
```

---

# Diferencia entre extracción y decisión

El módulo puede producir simultáneamente:

```text id="3tw6cz"
page.pdf
page.png
text.txt
embedded_images/
metadata.json
```

aunque una página tenga texto nativo suficiente.

No debe eliminar artefactos según clasificación.

La regla es:

> **Extraer primero, decidir después.**

Esto permite que el orquestador pueda posteriormente elegir entre:

* texto nativo;
* imagen normalizada;
* OCR;
* VLM;
* combinación de fuentes.

---

# Integración con `procesador-image`

El PDF produce un render:

```text id="el24j5"
procesador-pdf
      ↓
page.png
```

Ese archivo puede ser entregado por el orquestador a:

```text id="4i3qb0"
procesador-image
```

para:

* evaluar calidad;
* detectar rotación;
* corregir skew;
* generar `normalized.png`.

`procesador-pdf` no debe hacer ese trabajo.

---

# Integración con `procesador-ocr`

El PDF puede producir:

```text id="14mgho"
native_text/text.txt
```

pero si el orquestador determina que el texto nativo no es suficiente, puede utilizar:

```text id="ucws9f"
render/page.png
      ↓
procesador-image
      ↓
normalized.png
      ↓
procesador-ocr
```

El módulo PDF no conoce esa decisión.

---

# Integración con `procesador-llm-call`

El módulo PDF nunca llama directamente al LLM.

El flujo correcto es:

```text id="tj2p0j"
procesador-pdf
      ↓
PDFPageResult
      ↓
ORCHESTRATOR
      ↓
prepared input
      ↓
procesador-llm-call
```

---

# Integración con el sistema

El flujo completo puede ser:

```text id="5t4g67"
                 PDF
                  ↓
          procesador-pdf
                  ↓
            PDFPageResult
                  ↓
             ORCHESTRATOR
            ┌─────┼──────┐
            ▼     ▼      ▼
         native  image   ...
          text     │
                   ▼
           procesador-image
                   ↓
             normalized
                   ↓
             ORCHESTRATOR
                   ↓
             procesador-ocr
                   ↓
              OCRResult
                   ↓
             ORCHESTRATOR
                   ↓
          procesador-llm-call
```

---

# Independencia del módulo

`procesador-pdf` también debe poder utilizarse de forma aislada:

```text id="wkl9mh"
document.pdf
     ↓
procesador-pdf
     ↓
PDFResult
```

Esto permite:

* testear Poppler independientemente;
* extraer páginas sin OCR;
* obtener texto nativo sin LLM;
* cambiar posteriormente el procesador de imágenes;
* reprocesar páginas individuales;
* utilizarlo en otros proyectos sin depender del resto del pipeline.

---

# Principio de diseño

`procesador-pdf` debe cumplir una regla simple:

> **Recibe un PDF y devuelve sus artefactos nativos organizados por página.**

Conoce Poppler.

Conoce la estructura interna del PDF.

Puede extraer texto nativo.

Puede extraer imágenes embebidas.

Puede renderizar páginas.

No conoce OpenCV como pipeline de optimización.

No conoce Docling.

No conoce Ollama.

No construye prompts.

No ejecuta OCR.

No decide qué fuente utilizar.

No coordina el workflow completo.

Su trabajo termina cuando entrega un `PDFResult` consistente, reproducible y autocontenido.
