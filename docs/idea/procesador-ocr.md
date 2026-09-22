# flujo principal
* Incorporar **Docling como capa OCR estructurada** para páginas o imágenes donde el texto nativo no sea suficiente.
* Recibir como entrada la **imagen ya normalizada**: rotación, deskew, resolución y calidad corregidas.
* Configurar el OCR según el tipo de documento:

  * texto;
  * layout;
  * tablas;
  * estructura documental.
* Extraer:

  * texto;
  * párrafos y bloques;
  * títulos;
  * tablas;
  * orden de lectura.
* Convertir el resultado a un **formato intermedio común**, preferentemente Markdown estructurado.
* Usar la salida OCR como:

  * `<doc>` cuando sea la fuente principal;
  * `<extra>` cuando funcione como contexto de validación para un VLM.
* Permitir combinar **OCR + Vision LLM** para comparar o validar resultados.
* Integrar Docling dentro del decisor general:

  * texto nativo PDF;
  * OCR Docling;
  * Vision LLM;
  * combinación de fuentes.
* Conservar siempre la salida OCR y su metadata para **auditoría, comparación y reprocesamiento**.


# funciones 
Podés mantener exactamente la misma separación en **primitivas, utilitarios y helpers**, ahora para la capa OCR/Docling.

### 1. Primitivas

Funciones de bajo nivel que encapsulan `docling` y librerías auxiliares.

* `load_docling_pipeline(options)`
* `configure_image_pipeline(options)`
* `configure_pdf_pipeline(options)`
* `enable_ocr(pipeline, enabled=True)`
* `enable_table_detection(pipeline, enabled=True)`
* `convert_image_with_docling(image_path, options)`
* `convert_pdf_with_docling(pdf_path, options)`
* `extract_docling_text(result)`
* `extract_docling_markdown(result)`
* `extract_docling_tables(result)`
* `extract_docling_blocks(result)`
* `extract_docling_layout(result)`
* `extract_docling_metadata(result)`
* `export_docling_markdown(result, output_path)`
* `export_docling_json(result, output_path)`
* `export_docling_tables(result, output_dir)`
* `save_docling_result(result, output_path)`

### 2. Utilitarios

Funciones que combinan primitivas y representan operaciones completas del pipeline OCR.

* `process_ocr_image(image_path, output_dir)`

  * recibe imagen normalizada;
  * ejecuta Docling;
  * extrae texto, tablas y layout;
  * genera Markdown;
  * guarda metadata.

* `process_ocr_page(page_dir)`

  * toma `page.png` o `normalized.png`;
  * ejecuta OCR;
  * almacena resultados dentro de la carpeta de página.

* `process_ocr_pdf(pdf_path, output_dir)`

  * procesa PDF completo cuando corresponda;
  * deriva los resultados a cada página.

* `analyze_ocr_result(result)`

  * calcula cantidad de texto;
  * bloques;
  * tablas;
  * estructura detectada;
  * calidad del resultado.

* `extract_structured_content(result)`

  * unifica texto, tablas y bloques.

* `build_ocr_markdown(result)`

  * genera la representación intermedia común.

* `process_tables(result, output_dir)`

  * extrae y normaliza tablas detectadas.

* `select_ocr_mode(page_metadata)`

  * decide configuración:

    * OCR simple;
    * OCR + layout;
    * OCR + tablas;
    * procesamiento completo.

* `validate_ocr_result(ocr_result)`

  * verifica que exista contenido útil;
  * detecta salida vacía o inconsistente.

* `compare_ocr_with_native_text(ocr_text, native_text)`

  * compara OCR contra texto nativo PDF.

* `compare_ocr_with_vlm(ocr_result, vlm_result)`

  * detecta discrepancias entre OCR y Vision LLM.

* `build_llm_context_from_ocr(ocr_result)`

  * prepara salida para `<doc>` o `<extra>`.

### 3. Helpers

Funciones pequeñas y reutilizables.

* `create_ocr_directory(page_dir)`
* `build_ocr_output_paths(output_dir)`
* `normalize_docling_options(options)`
* `should_enable_tables(metadata)`
* `should_enable_ocr(metadata)`
* `should_use_full_layout(metadata)`
* `count_ocr_characters(text)`
* `count_ocr_words(text)`
* `count_tables(tables)`
* `count_blocks(blocks)`
* `is_ocr_empty(result)`
* `calculate_ocr_text_density(result)`
* `normalize_markdown(markdown)`
* `clean_ocr_text(text)`
* `normalize_table(table)`
* `table_to_markdown(table)`
* `merge_ocr_blocks(blocks)`
* `preserve_reading_order(blocks)`
* `build_ocr_metadata(result)`
* `write_json(path, data)`
* `write_text(path, content)`
* `read_json(path)`

El flujo quedaría:

```text
process_page()
      ↓
select_ocr_mode()
      ↓
process_ocr_page()
      ↓
Docling primitive
      ↓
texto + layout + tablas
      ↓
extract_structured_content()
      ↓
build_ocr_markdown()
      ↓
validate_ocr_result()
      ↓
OCR output
      ↓
<doc> / <extra> / comparación con VLM
```

La separación conceptual sería:

* **Primitivas:** conocen Docling.
* **Utilitarios:** conocen el flujo OCR/documental.
* **Helpers:** resuelven normalización, métricas, validación, archivos y transformación de resultados.
