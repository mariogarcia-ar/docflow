# Flujo principal
* Dado un PDF, crear una **carpeta principal del documento**.
* Dividir el PDF en páginas y crear **una subcarpeta por página**.
* En cada subcarpeta guardar:

  * `page.pdf`: página individual.
  * `page.png`: render de la página.
  * `text.txt`: texto extraído preservando layout.
  * `images/`: imágenes embebidas extraídas.
  * `metadata.json`: métricas y clasificación.
* Clasificar cada página como:

  * `TEXT`
  * `IMAGE`
  * `MIXED`
* Definir en `metadata.json` cuál es la **fuente principal** para procesamiento posterior:

  * `TEXT` → `text.txt`
  * `IMAGE` → `page.png`
  * `MIXED` → texto + imagen.
* **Conservar siempre todos los artefactos**, aunque el decisor elija uno como fuente principal.
* Usar cada carpeta de página como una **unidad independiente de procesamiento**, facilitando paralelización, auditoría y reprocesamiento.

# funciones
Podés organizar las funciones en **tres capas**: primitivas, utilitarios y helpers.

### 1. Primitivas

Funciones de bajo nivel que encapsulan librerías externas como `python-poppler`, Poppler CLI, `Pillow`, etc.

* `get_pdf_metadata(pdf_path)`
* `get_page_count(pdf_path)`
* `split_pdf(pdf_path, output_dir)`
* `extract_page(pdf_path, page_number, output_path)`
* `merge_pdfs(pdf_paths, output_path)`
* `render_page_to_image(pdf_path, page_number, output_path, dpi=200)`
* `extract_text_from_page(pdf_path, page_number, layout=True)`
* `extract_images_from_page(pdf_path, page_number, output_dir)`
* `get_page_dimensions(pdf_path, page_number)`
* `get_text_blocks(pdf_path, page_number)`
* `get_image_blocks(pdf_path, page_number)`
* `save_image(image, output_path)`
* `convert_image_format(input_path, output_path)`
* `resize_image(input_path, output_path, size)`

### 2. Utilitarios

Funciones que combinan varias primitivas y representan operaciones completas del dominio.

* `process_pdf(pdf_path, output_dir)`

  * crea estructura del documento;
  * obtiene metadata;
  * itera todas las páginas;
  * llama a `process_page()`.

* `process_page(pdf_path, page_number, output_dir)`

  * crea carpeta de página;
  * genera `page.pdf`;
  * genera `page.png`;
  * extrae `text.txt`;
  * extrae imágenes;
  * analiza la página;
  * clasifica la página;
  * genera `metadata.json`.

* `analyze_page(page_data)`

  * calcula métricas de texto e imágenes.

* `classify_page(page_metrics)`

  * devuelve `TEXT`, `IMAGE` o `MIXED`.

* `select_primary_source(page_metadata)`

  * decide:

    * `text.txt`;
    * `page.png`;
    * ambos.

* `reprocess_page(page_dir)`

  * permite reprocesar una página sin procesar nuevamente todo el PDF.

* `rebuild_pdf(page_dirs, output_path)`

  * reconstruye un PDF a partir de páginas procesadas.

### 3. Helpers

Funciones pequeñas, reutilizables y sin demasiada lógica de negocio.

* `create_document_directory(pdf_path, output_root)`
* `create_page_directory(output_dir, page_number)`
* `build_page_filename(page_number, extension)`
* `normalize_filename(filename)`
* `ensure_directory(path)`
* `write_text(path, content)`
* `write_json(path, data)`
* `read_json(path)`
* `calculate_bbox_area(bbox)`
* `calculate_page_area(width, height)`
* `calculate_text_coverage(text_blocks, page_size)`
* `calculate_image_coverage(image_blocks, page_size)`
* `calculate_largest_image_ratio(image_blocks, page_size)`
* `count_characters(text)`
* `count_words(text)`
* `is_text_empty(text)`
* `validate_pdf(path)`
* `validate_page_number(page_number, total_pages)`

Conceptualmente quedaría:

```text
process_pdf()
    ↓
process_page()
    ↓
┌───────────────────────────────┐
│ Primitivas                    │
│ split / render / text / image │
└───────────────┬───────────────┘
                ↓
          analyze_page()
                ↓
         classify_page()
                ↓
     select_primary_source()
                ↓
         metadata.json
```

La regla que mantendría es: **las primitivas conocen las librerías; los utilitarios conocen el proceso de negocio; los helpers resuelven operaciones pequeñas y reutilizables.**
