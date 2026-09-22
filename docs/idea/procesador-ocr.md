# Procesador OCR

## Objetivo

El módulo `procesador-ocr` tiene como responsabilidad exclusiva **extraer contenido estructurado desde imágenes mediante OCR**, utilizando Docling como motor principal.

Debe recibir imágenes ya preparadas por `procesador-image` y devolver texto, layout, tablas y metadata de extracción.

Este módulo **no procesa PDFs**, **no normaliza imágenes**, **no llama a LLM/VLM** y **no decide qué fuente utilizar después**. Esa coordinación pertenece al `workflow/orchestrator`.

---

# Flujo principal

* Recibir una imagen ya normalizada.
* Configurar Docling según las necesidades de extracción.
* Ejecutar OCR.
* Extraer:

  * texto;
  * párrafos;
  * bloques;
  * títulos;
  * tablas;
  * orden de lectura;
  * layout.
* Convertir el resultado a un formato intermedio común.
* Generar preferentemente:

  * texto plano;
  * Markdown estructurado;
  * JSON estructurado;
  * tablas separadas cuando corresponda.
* Validar que la extracción tenga contenido útil.
* Generar metadata OCR.
* Persistir todos los artefactos.
* Devolver un resultado estructurado al orquestador.

El módulo no debe decidir si la salida OCR se utilizará como:

* `<doc>`;
* `<extra>`;
* fuente principal;
* fuente secundaria;
* validación contra VLM.

Eso corresponde al orquestador.

---

# Estructura de salida

Ejemplo:

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

Cada módulo mantiene sus propios archivos y evita sobrescribir artefactos generados por otros procesadores.

---

# Contrato del módulo

## Entrada

```text
OCRRequest
├── image_path
├── options
└── context
```

El contexto puede incluir:

* `document_id`;
* `page_number`;
* `source_type`;
* metadata previa.

Ejemplo conceptual:

```json
{
  "image_path": "image/normalized.png",

  "options": {
    "ocr": true,
    "layout": true,
    "tables": true
  },

  "context": {
    "document_id": "doc_001",
    "page_number": 1
  }
}
```

---

## Salida

```text
OCRResult
├── text
├── markdown
├── structured_document
├── tables[]
├── blocks[]
├── layout
├── metadata
└── status
```

Ejemplo conceptual:

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
    "tables": 1
  },

  "status": "success"
}
```

---

# 1. Primitivas

Funciones de bajo nivel que encapsulan Docling y librerías auxiliares.

## Pipeline

* `load_docling_pipeline(options)`
* `configure_image_pipeline(options)`
* `enable_ocr(pipeline, enabled=True)`
* `enable_table_detection(pipeline, enabled=True)`
* `enable_layout_analysis(pipeline, enabled=True)`

## Ejecución

* `convert_image_with_docling(image_path, options)`

## Extracción

* `extract_docling_text(result)`
* `extract_docling_markdown(result)`
* `extract_docling_tables(result)`
* `extract_docling_blocks(result)`
* `extract_docling_layout(result)`
* `extract_docling_metadata(result)`

## Exportación

* `export_docling_text(result, output_path)`
* `export_docling_markdown(result, output_path)`
* `export_docling_json(result, output_path)`
* `export_docling_tables(result, output_dir)`

Las primitivas conocen Docling, pero no conocen el pipeline documental completo.

---

# 2. Utilitarios

Funciones que combinan primitivas y representan operaciones completas de OCR.

## `process_ocr_image(image_path, output_dir, options=None, context=None)`

Función principal del módulo.

Debe:

* validar entrada;
* crear estructura OCR;
* configurar Docling;
* ejecutar OCR;
* extraer contenido;
* construir texto;
* construir Markdown;
* construir JSON estructurado;
* extraer tablas;
* analizar resultado;
* validar resultado;
* persistir artefactos;
* generar `metadata.json`;
* devolver `OCRResult`.

Flujo:

```text
process_ocr_image()
        ↓
validate_ocr_input()
        ↓
configure_ocr()
        ↓
Docling
        ↓
extract_structured_content()
        ↓
build outputs
        ↓
validate_ocr_result()
        ↓
OCRResult
```

---

## `process_ocr_from_page(image_path, page_number, output_dir, options=None)`

Wrapper para páginas provenientes de un PDF.

Debe:

* mantener referencia a `page_number`;
* conservar referencia al documento;
* llamar internamente a `process_ocr_image()`.

```text
process_ocr_from_page()
        ↓
process_ocr_image()
```

No debe leer directamente `page.pdf` ni decidir qué archivo de página utilizar.

El orquestador debe entregarle la imagen correcta.

---

## `configure_ocr(options)`

Normaliza las opciones necesarias para Docling.

Puede definir:

* OCR;
* layout;
* tablas;
* estructura documental.

Devuelve una configuración lista para ejecutar.

---

## `extract_structured_content(result)`

Agrupa en una representación común:

* texto;
* bloques;
* párrafos;
* títulos;
* tablas;
* layout;
* orden de lectura.

No realiza lógica LLM.

---

## `build_ocr_text(result)`

Genera una representación textual simple.

Salida:

```text
text.txt
```

---

## `build_ocr_markdown(result)`

Genera la representación Markdown estructurada.

Debe preservar cuando sea posible:

* títulos;
* párrafos;
* listas;
* tablas;
* orden de lectura.

Salida:

```text
document.md
```

---

## `build_ocr_json(result)`

Genera una representación estructurada para consumo programático.

Puede incluir:

```text
document
├── blocks[]
├── tables[]
├── layout
└── metadata
```

Salida:

```text
document.json
```

---

## `process_tables(result, output_dir)`

Procesa exclusivamente las tablas detectadas.

Debe:

* identificar tablas;
* normalizar estructura;
* conservar filas y columnas;
* exportar cada tabla;
* devolver referencias a los artefactos generados.

---

## `analyze_ocr_result(result)`

Calcula métricas como:

* cantidad de caracteres;
* cantidad de palabras;
* cantidad de bloques;
* cantidad de tablas;
* densidad textual;
* contenido vacío;
* estructura detectada.

Devuelve:

```text
OCRMetrics
```

---

## `validate_ocr_result(result, metrics)`

Verifica que la extracción sea técnicamente válida.

Puede detectar:

* salida vacía;
* muy poco texto;
* ausencia de bloques;
* errores de parsing;
* extracción incompleta.

Debe devolver un estado, no decidir el siguiente workflow.

Ejemplo:

```text
VALID
EMPTY
LOW_CONTENT
ERROR
```

---

# 3. Helpers

Funciones pequeñas y reutilizables.

## Archivos

* `create_ocr_directory(output_dir)`
* `build_ocr_output_paths(output_dir)`
* `ensure_directory(path)`
* `write_text(path, content)`
* `write_json(path, data)`
* `read_json(path)`

## Configuración

* `normalize_docling_options(options)`
* `should_enable_tables(options)`
* `should_enable_layout(options)`
* `should_enable_ocr(options)`

Estas funciones evalúan configuración explícita, no toman decisiones de workflow.

---

## Texto

* `count_ocr_characters(text)`
* `count_ocr_words(text)`
* `clean_ocr_text(text)`
* `normalize_ocr_text(text)`
* `is_ocr_empty(text)`

## Markdown

* `normalize_markdown(markdown)`
* `merge_ocr_blocks(blocks)`
* `preserve_reading_order(blocks)`

## Tablas

* `count_tables(tables)`
* `normalize_table(table)`
* `table_to_markdown(table)`

## Layout

* `count_blocks(blocks)`
* `calculate_ocr_text_density(result)`
* `normalize_bbox(bbox)`

## Metadata

* `build_ocr_metadata(metrics, options, status)`
* `merge_ocr_metadata(base_metadata, new_metadata)`

---

# Responsabilidades que NO pertenecen a este módulo

Eliminar del alcance funciones similares a:

```text
process_ocr_pdf()
select_ocr_mode()
compare_ocr_with_native_text()
compare_ocr_with_vlm()
build_llm_context_from_ocr()
send_to_llm()
select_primary_source()
```

## Motivo

### `process_ocr_pdf()`

El PDF ya debe ser dividido y procesado por `procesador-pdf`.

OCR trabaja sobre imágenes.

---

### `select_ocr_mode()`

Si significa decidir **si debe ejecutarse OCR**, pertenece al orquestador.

El módulo OCR sí puede configurar **cómo ejecutar OCR** una vez solicitado.

---

### `compare_ocr_with_native_text()`

La comparación entre fuentes pertenece a una capa superior de validación/orquestación.

---

### `compare_ocr_with_vlm()`

El OCR no debe conocer el VLM.

---

### `build_llm_context_from_ocr()`

Transformar la salida OCR en `<doc>` o `<extra>` pertenece al orquestador o a la capa LLM.

---

# Integración con el sistema

El flujo esperado es:

```text
procesador-pdf
      ↓
   page.png
      ↓
procesador-image
      ↓
normalized.png
      ↓
   ORCHESTRATOR
      ↓
procesador-ocr
      ↓
text.txt
document.md
document.json
tables/
metadata.json
      ↓
   ORCHESTRATOR
```

El orquestador puede después decidir utilizar:

```text
native_text/text.txt
```

o:

```text
ocr/document.md
```

o:

```text
image/normalized.png
```

o una combinación.

El módulo OCR no participa de esa decisión.

---

# Independencia del módulo

También debe poder funcionar de manera aislada:

```text
normalized.png
      ↓
procesador-ocr
      ↓
OCRResult
```

Esto permite:

* test unitario independiente;
* benchmarking de Docling;
* cambiar de motor OCR;
* reprocesar OCR sin volver a ejecutar PDF o imagen;
* comparar motores en el futuro.

---

# Principio de diseño

`procesador-ocr` debe cumplir una regla simple:

> **Recibe una imagen preparada y devuelve una representación textual y estructurada de su contenido.**

Conoce Docling.

No conoce Poppler.

No modifica imágenes con OpenCV.

No conoce Ollama.

No construye prompts.

No decide si ejecutar un VLM.

No selecciona la fuente documental final.

No coordina el workflow completo.

Su salida debe ser suficientemente estructurada y estable para que cualquier capa posterior pueda consumirla sin depender directamente de Docling.
