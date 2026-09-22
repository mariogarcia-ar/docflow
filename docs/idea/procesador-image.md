# Procesador de Imágenes

## Objetivo

El módulo `procesador-image` tiene como responsabilidad exclusiva el **análisis, normalización y preparación técnica de imágenes**.

Debe poder trabajar tanto con:

* imágenes nativas;
* imágenes generadas desde páginas de un PDF.

Este módulo **no ejecuta OCR**, **no llama a modelos LLM/VLM** y **no decide el workflow posterior**. Su función es producir una imagen normalizada y metadata suficiente para que el orquestador determine el siguiente paso.

---

# Flujo principal

* Recibir una imagen como entrada.
* Conservar siempre la imagen original.
* Crear una versión normalizada para procesamiento posterior.
* Evaluar:

  * dimensiones;
  * resolución;
  * formato;
  * peso;
  * nitidez;
  * blur;
  * orientación;
  * inclinación / skew;
  * presencia estimada de texto;
  * cobertura estimada de texto.
* Corregir cuando corresponda:

  * orientación;
  * rotación;
  * deskew;
  * tamaño;
  * resolución;
  * formato;
  * compresión;
  * contraste;
  * brillo;
  * ruido.
* Clasificar la imagen según sus características:

  * `TEXT_IMAGE`
  * `VISUAL_IMAGE`
  * `MIXED_IMAGE`
  * `LOW_QUALITY`
* Generar `metadata.json` con:

  * métricas;
  * clasificación;
  * transformaciones aplicadas;
  * paths de los artefactos generados.
* Entregar al orquestador:

  * imagen original;
  * imagen normalizada;
  * metadata.

El módulo no debe decidir si la imagen continúa hacia:

* OCR;
* Vision LLM;
* revisión manual;
* combinación de fuentes.

Esa decisión corresponde al `workflow/orchestrator`.

---

# Estructura de salida

Ejemplo:

```text
image/
├── source/
│   └── original.png
│
├── normalized/
│   └── normalized.png
│
└── metadata.json
```

Si la imagen proviene de una página PDF, debe mantenerse la referencia al origen:

```text
page_001/
├── source/
│   ├── page.pdf
│   └── page.png
│
├── image/
│   ├── normalized.png
│   └── metadata.json
│
├── native_text/
├── ocr/
└── llm/
```

---

# Contrato del módulo

## Entrada

```text
image_path
context opcional
```

El contexto puede incluir:

* `document_id`;
* `page_number`;
* `source_type`;
* metadata previa.

## Salida

```text
ImageResult
├── source_path
├── normalized_path
├── metadata
└── classification
```

Ejemplo conceptual:

```json
{
  "source_path": "source/page.png",
  "normalized_path": "image/normalized.png",

  "dimensions": {
    "width": 1600,
    "height": 2200
  },

  "quality": {
    "blur_score": 184.4,
    "is_legible": true
  },

  "orientation": {
    "rotation": 0,
    "skew": 1.2,
    "corrected": true
  },

  "content": {
    "has_text": true,
    "text_coverage": 0.72
  },

  "classification": "TEXT_IMAGE",

  "transformations": [
    "deskew",
    "resize",
    "compression"
  ]
}
```

---

# Funciones

## 1. Primitivas

Funciones de bajo nivel que encapsulan librerías externas como:

* `cv2`;
* `PIL`;
* `numpy`.

### Carga y almacenamiento

* `load_image(path)`
* `save_image(image, path)`
* `get_image_metadata(path)`
* `get_image_dimensions(image)`

### Conversión y transformación

* `convert_image_format(image, format)`
* `resize_image(image, max_width=None, max_height=None)`
* `compress_image(image, quality=85)`
* `convert_to_grayscale(image)`

### Mejora de imagen

* `normalize_contrast(image)`
* `normalize_brightness(image)`
* `denoise_image(image)`
* `sharpen_image(image)`

### Calidad

* `calculate_blur_score(image)`
* `calculate_sharpness_score(image)`

### Orientación

* `detect_orientation(image)`
* `detect_skew_angle(image)`
* `rotate_image(image, angle)`
* `deskew_image(image)`

### Análisis de contenido

* `detect_text_regions(image)`
* `crop_region(image, bbox)`
* `calculate_text_coverage(regions, image_size)`

Las primitivas no deben contener lógica de workflow ni dependencias con OCR o LLM.

---

# 2. Utilitarios

Funciones que combinan primitivas para resolver operaciones completas del dominio de imágenes.

## `process_image(image_path, output_dir, context=None)`

Responsabilidad principal del módulo.

Debe:

* validar la imagen;
* crear estructura de salida;
* conservar el original;
* cargar la imagen;
* analizarla;
* normalizarla;
* clasificarla;
* persistir `normalized.png`;
* generar `metadata.json`;
* devolver `ImageResult`.

Flujo:

```text
process_image()
      ↓
validate_image()
      ↓
analyze_image()
      ↓
normalize_image()
      ↓
classify_image()
      ↓
save artifacts
      ↓
ImageResult
```

---

## `process_image_from_page(image_path, page_number, output_dir)`

Wrapper para imágenes provenientes de un PDF.

Debe:

* mantener `page_number`;
* conservar referencia al documento original;
* llamar internamente a `process_image()`.

No debe implementar un pipeline diferente.

```text
process_image_from_page()
        ↓
process_image()
```

---

## `analyze_image(image)`

Calcula métricas sin modificar la imagen.

Debe analizar:

* dimensiones;
* aspect ratio;
* resolución;
* formato;
* tamaño;
* blur;
* nitidez;
* orientación;
* skew;
* regiones de texto;
* cobertura estimada de texto.

Devuelve:

```text
ImageMetrics
```

---

## `normalize_image(image, metrics, options=None)`

Aplica únicamente las transformaciones necesarias.

Puede realizar:

* corrección de orientación;
* deskew;
* resize;
* ajuste de resolución;
* normalización de contraste;
* normalización de brillo;
* reducción de ruido;
* sharpening;
* conversión de formato;
* compresión.

Debe registrar qué transformaciones fueron aplicadas.

---

## `classify_image(metrics)`

Clasifica la imagen según sus características.

Posibles valores:

```text
TEXT_IMAGE
VISUAL_IMAGE
MIXED_IMAGE
LOW_QUALITY
```

Esta función únicamente clasifica.

No debe seleccionar:

```text
OCR
VLM
BOTH
REVIEW
```

Esa lógica pertenece al orquestador.

---

## `prepare_image_for_ocr(image, options=None)`

Genera una variante técnica optimizada para OCR cuando el orquestador la solicite.

Puede aplicar:

* grayscale;
* contraste;
* denoise;
* resolución adecuada;
* binarización si corresponde.

No ejecuta OCR.

---

## `prepare_image_for_vlm(image, options=None)`

Genera una variante técnica optimizada para modelos multimodales.

Puede aplicar:

* resize manteniendo aspect ratio;
* compresión;
* conversión de formato;
* límites máximos de resolución;
* reducción de peso.

No llama al VLM.

---

# 3. Helpers

Funciones pequeñas y reutilizables.

### Archivos

* `create_image_directory(output_root, image_name)`
* `build_output_filename(name, suffix, extension)`
* `normalize_filename(filename)`
* `ensure_directory(path)`
* `copy_source_image(source, destination)`
* `write_json(path, data)`
* `read_json(path)`

### Dimensiones

* `calculate_image_area(width, height)`
* `calculate_bbox_area(bbox)`
* `calculate_coverage(bboxes, image_size)`
* `calculate_aspect_ratio(width, height)`
* `calculate_resize_dimensions(width, height, max_size)`

### Validaciones

* `validate_image(path)`
* `validate_image_format(format)`
* `is_resolution_valid(width, height, min_size)`
* `is_blur_acceptable(score, threshold)`
* `is_rotation_required(angle, threshold)`
* `is_text_present(text_coverage, threshold)`

### Metadata

* `build_image_metadata(metrics, transformations, classification)`
* `merge_image_metadata(base_metadata, new_metadata)`

---

# Responsabilidades que NO pertenecen a este módulo

Eliminar del alcance de `procesador-image` cualquier función similar a:

```text
select_image_pipeline()
send_to_ocr()
send_to_vlm()
compare_ocr_with_vlm()
process_llm_image()
```

El módulo de imagen debe terminar en:

```text
imagen original
      ↓
análisis
      ↓
normalización
      ↓
clasificación
      ↓
metadata + imagen normalizada
```

A partir de ahí, el `workflow/orchestrator` decide qué hacer.

---

# Integración con el resto del sistema

```text
procesador-pdf
      ↓
   page.png
      ↓
procesador-image
      ↓
normalized.png
+ metadata.json
      ↓
   ORCHESTRATOR
   ┌──────┼───────┐
   ▼      ▼       ▼
 native  OCR     VLM
 text
```

También debe aceptar imágenes directamente:

```text
image.jpg
    ↓
procesador-image
    ↓
normalized.png
+ metadata.json
    ↓
ORCHESTRATOR
```

---

# Principio de diseño

`procesador-image` debe cumplir una única regla:

> **Recibe una imagen y devuelve una imagen preparada más información objetiva sobre ella.**

No conoce Docling.

No conoce Ollama.

No conoce prompts.

No conoce schemas LLM.

No ejecuta workflows.

Esto permite mantener el módulo independiente y reutilizable, mientras el orquestador decide cómo combinarlo con PDF, OCR y LLM.
