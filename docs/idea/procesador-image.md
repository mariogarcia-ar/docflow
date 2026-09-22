# flujo principal
* Dada una imagen, crear una **unidad de procesamiento propia** con original, versión normalizada y metadata.
* Evaluar **calidad, nitidez, resolución y orientación**.
* Corregir **rotación, deskew, tamaño, formato y compresión** cuando sea necesario.
* Detectar si contiene **texto, contenido visual o ambos**.
* Clasificarla como:

  * `TEXT_IMAGE`
  * `VISUAL_IMAGE`
  * `MIXED_IMAGE`
  * `LOW_QUALITY`
* Definir en `metadata.json` la **fuente optimizada** y el pipeline siguiente.
* Derivar imágenes con texto a **OCR/VLM** y las visuales a **Vision LLM**.
* Conservar siempre el **original y los artefactos derivados** para auditoría y reprocesamiento.


# funciones 
Podés mantener la misma separación en **primitivas, utilitarios y helpers**.

### 1. Primitivas

Funciones de bajo nivel que encapsulan `cv2`, `PIL`, `numpy`, etc.

* `load_image(path)`
* `save_image(image, path)`
* `get_image_metadata(path)`
* `get_image_dimensions(image)`
* `convert_image_format(image, format)`
* `resize_image(image, max_width=None, max_height=None)`
* `compress_image(image, quality=85)`
* `convert_to_grayscale(image)`
* `normalize_contrast(image)`
* `normalize_brightness(image)`
* `denoise_image(image)`
* `sharpen_image(image)`
* `calculate_blur_score(image)`
* `detect_orientation(image)`
* `detect_skew_angle(image)`
* `rotate_image(image, angle)`
* `deskew_image(image)`
* `detect_text_regions(image)`
* `crop_region(image, bbox)`
* `calculate_text_coverage(regions, image_size)`

### 2. Utilitarios

Funciones que combinan primitivas y representan operaciones completas del pipeline.

* `process_image(image_path, output_dir)`

  * crea la carpeta de procesamiento;
  * copia/conserva el original;
  * obtiene metadata;
  * llama a `analyze_image()`;
  * normaliza la imagen;
  * clasifica el contenido;
  * genera `metadata.json`.

* `process_page_image(image_path, page_number, output_dir)`

  * procesa una imagen proveniente de una página PDF;
  * mantiene la referencia al `page_number`;
  * aplica el mismo pipeline que una imagen nativa.

* `analyze_image(image)`

  * calcula blur;
  * orientación;
  * skew;
  * resolución;
  * regiones de texto;
  * cobertura de texto;
  * calidad general.

* `normalize_image(image)`

  * corrige orientación;
  * aplica deskew;
  * ajusta tamaño;
  * mejora contraste/nitidez cuando corresponda;
  * normaliza formato.

* `classify_image(image_metrics)`

  * devuelve:

    * `TEXT_IMAGE`
    * `VISUAL_IMAGE`
    * `MIXED_IMAGE`
    * `LOW_QUALITY`

* `optimize_image_for_ocr(image)`

  * prepara la imagen para OCR.

* `optimize_image_for_vlm(image)`

  * adapta resolución, formato y compresión para Vision LLM.

* `select_image_pipeline(metadata)`

  * decide:

    * OCR;
    * VLM;
    * ambos;
    * revisión.

### 3. Helpers

Funciones pequeñas y reutilizables.

* `create_image_directory(output_root, image_name)`
* `build_output_filename(name, suffix, extension)`
* `normalize_filename(filename)`
* `ensure_directory(path)`
* `copy_source_image(source, destination)`
* `write_json(path, data)`
* `read_json(path)`
* `calculate_image_area(width, height)`
* `calculate_bbox_area(bbox)`
* `calculate_coverage(bboxes, image_size)`
* `calculate_aspect_ratio(width, height)`
* `calculate_resize_dimensions(width, height, max_size)`
* `is_resolution_valid(width, height, min_size)`
* `is_blur_acceptable(score, threshold)`
* `is_rotation_required(angle, threshold)`
* `is_text_present(text_coverage, threshold)`
* `validate_image(path)`
* `validate_image_format(format)`

El flujo quedaría:

```text
process_image()
      ↓
analyze_image()
      ↓
┌──────────────────────────┐
│ Primitivas               │
│ blur / rotate / resize   │
│ text regions / normalize │
└────────────┬─────────────┘
             ↓
      normalize_image()
             ↓
      classify_image()
             ↓
   select_image_pipeline()
             ↓
 OCR / VLM / BOTH / REVIEW
```

La misma regla que para PDF: **las primitivas conocen `cv2`/PIL; los utilitarios conocen el flujo documental; los helpers resuelven cálculos, validaciones y manejo de archivos.**
