# Procesador de Imágenes

## Objetivo

El módulo `procesador-image` tiene como responsabilidad exclusiva **analizar, normalizar y preparar técnicamente imágenes para su consumo por otros procesadores**.

Debe poder trabajar con:

* imágenes recibidas directamente;
* imágenes renderizadas desde páginas PDF;
* imágenes embebidas extraídas previamente;
* regiones o recortes que le sean entregados explícitamente.

Su responsabilidad principal consiste en transformar:

```text
imagen de entrada
       ↓
análisis técnico
       ↓
normalización
       ↓
variantes preparadas
       ↓
ImageResult
```

Puede generar variantes optimizadas para distintos consumidores, por ejemplo:

```text
normalized.png

ocr_ready.png

vlm_ready.png
```

pero **no decide cuál de ellas debe utilizarse posteriormente**.

El módulo:

* no procesa PDFs;
* no ejecuta OCR;
* no llama a LLM/VLM;
* no selecciona la fuente documental;
* no decide si OCR es necesario;
* no decide si VLM es necesario;
* no coordina el workflow documental.

Su responsabilidad empieza cuando recibe:

```text
ImageRequest
```

y termina cuando devuelve:

```text
ImageResult
```

---

# Principio de diseño

`procesador-image` responde:

> **“Dada esta imagen y esta configuración técnica, ¿cómo puedo analizarla y prepararla para procesamiento posterior?”**

No responde:

> **“¿Qué debo hacer después con esta imagen?”**

Ni:

> **“¿Debo ejecutar OCR o VLM?”**

Estas decisiones pertenecen al `procesador-orquestador`.

---

# Separación de responsabilidades

```text
procesador-orquestador
    =
decide si procesar imagen
+ selecciona input
+ selecciona variante posterior
+ controla idempotencia
+ stop/resume
+ skip/force
+ fallbacks

procesador-image
    =
analiza
+ normaliza
+ prepara variantes técnicas

procesador-ocr
    =
extrae texto y estructura

procesador-llm-call
    =
ejecuta inferencia
```

---

# Flujo principal

1. Recibir `ImageRequest`.
2. Validar archivo.
3. Conservar referencia al input original.
4. Cargar imagen.
5. Analizar:

   * dimensiones;
   * resolución;
   * formato;
   * peso;
   * aspect ratio;
   * blur;
   * nitidez;
   * orientación;
   * skew;
   * contraste;
   * brillo;
   * ruido;
   * presencia estimada de texto;
   * cobertura estimada de texto.
6. Clasificar técnicamente la imagen.
7. Determinar transformaciones necesarias según configuración recibida.
8. Generar imagen normalizada.
9. Generar variantes técnicas solicitadas.
10. Validar artefactos generados.
11. Persistir outputs.
12. Generar `metadata.json`.
13. Devolver `ImageResult`.

---

# Flujo general

```text
ImageRequest
     ↓
validate_image_input()
     ↓
load_image()
     ↓
analyze_image()
     ↓
ImageMetrics
     ↓
normalize_image()
     ↓
normalized.png
     ↓
prepare requested variants
     │
     ├── ocr_ready.png
     └── vlm_ready.png
     ↓
classify_image()
     ↓
validate outputs
     ↓
persist
     ↓
ImageResult
```

---

# Contrato del módulo

## Entrada

```text
ImageRequest
├── image_path
├── output_dir
├── options
└── context
```

Ejemplo:

```json
{
  "image_path": "page_001/render/page.png",

  "output_dir": "page_001/image",

  "options": {
    "normalize": true,
    "prepare_for_ocr": true,
    "prepare_for_vlm": true,
    "correct_orientation": true,
    "deskew": true
  },

  "context": {
    "document_id": "doc_001",
    "page_number": 1,
    "workflow_run_id": "run_001"
  }
}
```

`context` se utiliza exclusivamente para:

* correlación;
* trazabilidad;
* metadata.

El procesador no debe modificar el estado documental global.

---

# Salida

```text
ImageResult
├── source
├── normalized
├── variants
│   ├── ocr_ready
│   └── vlm_ready
├── metrics
├── classification
├── transformations[]
├── validation
├── artifacts
├── metadata
└── status
```

Ejemplo:

```json
{
  "source_path": "render/page.png",

  "normalized_path": "image/normalized.png",

  "variants": {
    "ocr_ready": "image/ocr_ready.png",
    "vlm_ready": "image/vlm_ready.png"
  },

  "dimensions": {
    "width": 1600,
    "height": 2200
  },

  "quality": {
    "blur_score": 184.4,
    "sharpness_score": 0.82,
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
    "resize"
  ],

  "validation": {
    "status": "VALID"
  },

  "status": "success"
}
```

---

# Estructura de salida

El módulo escribe exclusivamente dentro de su namespace.

```text
image/
├── normalized.png
├── ocr_ready.png
├── vlm_ready.png
└── metadata.json
```

Las variantes son opcionales.

Si solamente se solicita normalización:

```text
image/
├── normalized.png
└── metadata.json
```

Dentro de una página:

```text
page_001/
├── source/
│   └── page.pdf
│
├── render/
│   └── page.png
│
├── native_text/
│   └── text.txt
│
├── image/
│   ├── normalized.png
│   ├── ocr_ready.png
│   ├── vlm_ready.png
│   └── metadata.json
│
├── ocr/
└── llm/
```

Regla:

> **`procesador-image` solamente escribe dentro de `image/`.**

Nunca debe modificar:

```text
source/
render/
native_text/
ocr/
llm/
```

---

# Input inmutable

La imagen recibida debe considerarse inmutable.

El procesador no debe modificar:

```text
image_path
```

en el lugar.

Siempre debe producir una nueva salida.

Ejemplo:

```text
render/page.png
       ↓
procesador-image
       ↓
image/normalized.png
```

Nunca:

```text
render/page.png
       ↓
sobrescribir
       ↓
render/page.png
```

---

# Relación con idempotencia

La idempotencia global pertenece al orquestador.

`procesador-image` no decide:

```text
REUSE
SKIP
FORCE
RESUME
```

Flujo:

```text
IMAGE stage
     ↓
orchestrator
     ↓
 ┌──────────┬──────────┬─────────┐
 ▼          ▼          ▼
REUSE      SKIP      EXECUTE
                       ↓
               procesador-image
```

Si el módulo recibe un `ImageRequest`, debe asumir:

> **La ejecución ya fue autorizada y debe producir nuevamente sus artefactos.**

---

# Determinismo técnico

Aunque no controla la idempotencia global, el módulo debe favorecer resultados reproducibles.

Idealmente:

```text
misma imagen
+
misma configuración
+
misma versión del procesador
──────────────────────────
misma transformación lógica
```

Para ello debe:

* normalizar opciones;
* utilizar criterios técnicos explícitos;
* registrar todas las transformaciones;
* evitar modificaciones implícitas;
* mantener nombres y formatos estables;
* registrar versiones del procesador y librerías relevantes.

---

# Metadata

`metadata.json` debería contener:

```text
ImageMetadata
├── processor
├── processor_version
├── libraries
├── input
├── input_metrics
├── output_metrics
├── classification
├── transformations[]
├── variants
├── validation
├── timing
└── context
```

Ejemplo:

```json
{
  "processor": "procesador-image",
  "processor_version": "1.0.0",

  "input": {
    "path": "render/page.png"
  },

  "classification": "TEXT_IMAGE",

  "transformations": [
    "deskew",
    "resize"
  ],

  "variants": {
    "normalized": "image/normalized.png",
    "ocr_ready": "image/ocr_ready.png"
  }
}
```

El orquestador puede utilizar:

```text
input hash
+
processor version
+
normalized options
```

para construir el `processing_key`.

---

# 1. Primitivas

Funciones de bajo nivel que encapsulan librerías como:

* OpenCV;
* Pillow;
* NumPy;
* otras librerías técnicas de imagen.

No conocen el workflow documental.

---

## Carga y almacenamiento

```text
load_image(path)

save_image(image, path)

get_image_metadata(path)

get_image_dimensions(image)
```

---

## Conversión

```text
convert_image_format(image, format)

resize_image(...)

compress_image(...)

convert_to_grayscale(image)
```

---

## Mejora

```text
normalize_contrast(image)

normalize_brightness(image)

denoise_image(image)

sharpen_image(image)

binarize_image(image)
```

---

## Calidad

```text
calculate_blur_score(image)

calculate_sharpness_score(image)

calculate_contrast_score(image)

calculate_brightness_score(image)

calculate_noise_score(image)
```

---

## Orientación

```text
detect_orientation(image)

detect_skew_angle(image)

rotate_image(image, angle)

deskew_image(image)
```

---

## Análisis visual

```text
detect_text_regions(image)

calculate_text_coverage(...)

crop_region(image, bbox)
```

Las primitivas no toman decisiones sobre OCR o LLM.

---

# 2. Procesamiento principal

## `process_image(request)`

Función principal.

Debe:

1. validar `ImageRequest`;
2. validar imagen;
3. crear directorio temporal;
4. cargar imagen;
5. analizar input;
6. normalizar imagen;
7. clasificar;
8. preparar variantes solicitadas;
9. analizar outputs;
10. validar resultados;
11. persistir artefactos;
12. generar metadata;
13. publicar outputs;
14. devolver `ImageResult`.

```text
process_image()
      ↓
validate_image_request()
      ↓
validate_image()
      ↓
load_image()
      ↓
analyze_image()
      ↓
normalize_image()
      ↓
classify_image()
      ↓
prepare_variants()
      ↓
validate_image_result()
      ↓
persist
      ↓
ImageResult
```

---

# 3. Wrapper para páginas PDF

## `process_image_from_page(...)`

Wrapper opcional para imágenes generadas por `procesador-pdf`.

Debe:

* recibir explícitamente `image_path`;
* preservar `page_number`;
* preservar `document_id`;
* construir `ImageRequest`;
* llamar internamente a `process_image()`.

```text
process_image_from_page()
        ↓
build ImageRequest
        ↓
process_image()
```

No debe:

```text
abrir PDF

renderizar PDF

extraer página

buscar automáticamente page.png
```

La imagen debe ser entregada por el orquestador.

---

# 4. Análisis

## `analyze_image(image)`

Calcula métricas sin modificar el input.

Debe analizar, cuando corresponda:

```text
dimensions
aspect_ratio
resolution
format
size

blur
sharpness
contrast
brightness
noise

orientation
skew

text_regions
text_coverage
```

Devuelve:

```text
ImageMetrics
```

---

# ImageMetrics

```text
ImageMetrics
├── dimensions
├── resolution
├── format
├── size
├── quality
│   ├── blur
│   ├── sharpness
│   ├── contrast
│   ├── brightness
│   └── noise
├── orientation
├── skew
├── text_regions[]
└── text_coverage
```

---

# 5. Normalización

## `normalize_image(image, metrics, options=None)`

Genera una representación técnica general.

Puede aplicar:

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

Debe aplicar únicamente transformaciones justificadas por:

```text
métricas
+
configuración explícita
```

Debe registrar todas las transformaciones realizadas.

---

# Regla de transformación

Evitar:

```text
aplicar todas las mejoras siempre
```

Preferir:

```text
analyze
   ↓
transformation required?
   │
 ┌─┴─┐
NO  YES
│    │
skip apply
```

Una transformación innecesaria también puede degradar información.

---

# 6. Clasificación

## `classify_image(metrics)`

Clasifica técnicamente la imagen.

Valores posibles:

```text
TEXT_IMAGE
VISUAL_IMAGE
MIXED_IMAGE
LOW_QUALITY
```

Esta clasificación describe características.

No implica routing.

Incorrecto:

```text
TEXT_IMAGE
    ↓
OCR
```

Correcto:

```text
TEXT_IMAGE
    ↓
metadata
    ↓
orchestrator decides
```

---

# 7. Variante normalizada

## `prepare_normalized_image(...)`

Produce la representación general del input.

Salida habitual:

```text
image/normalized.png
```

Debe buscar una imagen técnicamente limpia pero suficientemente fiel al original.

Esta variante sirve como representación base.

---

# 8. Variante para OCR

## `prepare_image_for_ocr(image, options=None)`

Genera una variante destinada técnicamente a motores OCR.

Puede aplicar:

* grayscale;
* contraste;
* denoise;
* deskew;
* resolución adecuada;
* sharpening controlado;
* binarización cuando corresponda.

Salida:

```text
image/ocr_ready.png
```

No ejecuta OCR.

No decide si debe utilizarse.

---

# 9. Variante para VLM

## `prepare_image_for_vlm(image, options=None)`

Genera una variante técnicamente adecuada para modelos multimodales.

Puede aplicar:

* resize manteniendo aspect ratio;
* compresión;
* conversión de formato;
* límites de resolución;
* reducción de peso;
* preservación de información visual relevante.

Salida:

```text
image/vlm_ready.png
```

No ejecuta ningún modelo.

No decide si VLM es necesario.

---

# Variantes independientes

Es importante no asumir que:

```text
imagen óptima para OCR
=
imagen óptima para VLM
```

Por ejemplo:

```text
OCR
    puede beneficiarse de grayscale
    binarización
    contraste fuerte

VLM
    puede necesitar color
    contexto visual
    composición completa
```

Por eso conviene permitir:

```text
normalized.png
ocr_ready.png
vlm_ready.png
```

como artefactos independientes.

---

# 10. Regiones y crops

El procesador puede generar regiones cuando se soliciten explícitamente.

Ejemplo:

```text
image/
├── normalized.png
└── regions/
    ├── region_001.png
    └── region_002.png
```

Puede utilizar:

```text
detect_text_regions()
crop_region()
```

Pero no debe decidir:

```text
qué región enviar al LLM
```

ni:

```text
qué región ejecutar con OCR
```

Esa selección pertenece al orquestador.

---

# 11. Validación

## `validate_image_result(result)`

Debe validar exclusivamente calidad técnica.

Estados posibles:

```text
VALID
LOW_QUALITY
INVALID_OUTPUT
UNSUPPORTED
ERROR
```

Puede evaluar:

* archivo generado;
* formato correcto;
* dimensiones;
* tamaño;
* corrupción;
* resolución mínima;
* legibilidad técnica.

---

# La validación no decide workflow

Ejemplo:

```text
LOW_QUALITY
```

no significa automáticamente:

```text
manual review
```

ni:

```text
skip OCR
```

ni:

```text
use VLM
```

El módulo devuelve:

```text
LOW_QUALITY
```

y el orquestador decide la acción posterior.

---

# 12. Errores

Los errores deben clasificarse técnicamente.

Ejemplo:

```text
INVALID_INPUT
UNSUPPORTED_FORMAT
DECODE_ERROR
TRANSFORMATION_ERROR
WRITE_ERROR
IO_ERROR
INTERNAL_ERROR
```

Puede devolver:

```text
ImageError
├── type
├── message
├── recoverable
└── metadata
```

El módulo puede indicar si considera técnicamente recuperable un error.

No decide el fallback del workflow.

---

# 13. Persistencia

Los outputs deben publicarse solamente cuando estén completos.

No conviene escribir directamente:

```text
normalized.png
```

mientras todavía está siendo producido.

Preferir:

```text
normalized.png.tmp
       ↓
write
       ↓
validate
       ↓
atomic rename
       ↓
normalized.png
```

La misma regla aplica a:

```text
ocr_ready.png

vlm_ready.png

metadata.json
```

---

# Directorio temporal

Puede utilizarse:

```text
image/.tmp/
```

durante la ejecución.

Conceptualmente:

```text
input
 ↓
processing
 ↓
temporary artifacts
 ↓
validation
 ↓
commit
 ↓
ImageResult
```

Esto evita que el orquestador detecte como válido un archivo parcialmente generado.

---

# 14. Stop / Resume

El módulo no administra el `stop/resume` del workflow.

Esto pertenece al orquestador.

Una ejecución de imagen normalmente debe tratarse como una operación atómica:

```text
ImageRequest
      ↓
process_image
      ↓
ImageResult
```

Por lo tanto, al reanudar:

```text
resultado válido
    → REUSE

resultado incompleto
    → EXECUTE
```

No es necesario implementar un subgrafo de resume interno.

---

# Stop durante procesamiento

Si se solicita stop:

* el orquestador no inicia nuevas etapas;
* la operación actual puede finalizar;
* o cancelarse si puede hacerse de forma segura.

Los artefactos temporales no deben considerarse resultados válidos.

---

# 15. Skip / Force

El procesador no debe conocer:

```text
skip image

force image

reuse image

resume image
```

Eso pertenece al `StageExecution` administrado por el orquestador.

Si recibe:

```text
ImageRequest
```

debe ejecutar el procesamiento solicitado.

---

# 16. Concurrencia

El módulo debe permitir procesar diferentes imágenes simultáneamente.

Ejemplo:

```text
page_001 → procesador-image

page_002 → procesador-image

page_003 → procesador-image
```

Cada ejecución:

* recibe su propio `ImageRequest`;
* escribe en su propio `output_dir`;
* no comparte estado mutable;
* no modifica inputs.

La coordinación global pertenece al orquestador.

---

# 17. Reprocesamiento

`procesador-image` no debe decidir cuándo reprocesar.

El flujo correcto es:

```text
orchestrator
     ↓
processing_key
     ↓
¿resultado válido?
     │
 ┌───┴───┐
YES      NO
 │        │
REUSE   EXECUTE
          ↓
   procesador-image
```

Cambios en opciones como:

```text
deskew
resolution
contrast
compression
OCR preparation
VLM preparation
```

pueden producir un `processing_key` diferente y provocar una nueva ejecución.

---

# 18. Dependencias downstream

El módulo tampoco invalida:

```text
OCR
LLM
```

directamente.

Ejemplo:

```text
normalized.png cambia
       ↓
ImageResult cambia
       ↓
orchestrator
       ↓
invalidate OCR
       ↓
invalidate LLM
```

La invalidación pertenece a la capa superior.

---

# 19. Helpers

## Archivos

```text
create_image_directory()

build_image_output_paths()

ensure_directory()

copy_source_image()

write_json_atomic()

read_json()
```

---

## Dimensiones

```text
calculate_image_area()

calculate_bbox_area()

calculate_coverage()

calculate_aspect_ratio()

calculate_resize_dimensions()
```

---

## Calidad

```text
calculate_blur_score()

calculate_sharpness_score()

calculate_contrast_score()

calculate_brightness_score()

calculate_noise_score()
```

---

## Validaciones

```text
validate_image_request()

validate_image()

validate_image_format()

validate_image_result()

validate_output_artifacts()

is_resolution_valid()

is_blur_acceptable()

is_rotation_required()

is_text_present()
```

---

## Metadata

```text
build_image_metadata()

merge_image_metadata()

get_processor_version()

get_library_versions()
```

---

# 20. Responsabilidades que NO pertenecen a este módulo

Eliminar cualquier lógica similar a:

```text
select_image_pipeline()

should_run_ocr()

should_run_vlm()

send_to_ocr()

send_to_vlm()

compare_ocr_with_vlm()

process_llm_image()

select_document_source()

select_extraction_strategy()

resume_document()

skip_stage()

force_stage()

invalidate_downstream()
```

---

# `select_image_pipeline()`

Si significa:

```text
¿qué procesador ejecutar después?
```

pertenece al orquestador.

El módulo sí puede decidir internamente:

```text
qué transformaciones técnicas aplicar
```

según la configuración recibida.

---

# `send_to_ocr()`

No pertenece a imagen.

El módulo únicamente puede producir:

```text
ocr_ready.png
```

El orquestador decide si invoca:

```text
procesador-ocr
```

---

# `send_to_vlm()`

No pertenece a imagen.

Puede producir:

```text
vlm_ready.png
```

pero no invocar modelos.

---

# `compare_ocr_with_vlm()`

No pertenece al módulo porque exige conocimiento de resultados externos.

---

# 21. Integración con `procesador-pdf`

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

El módulo de imagen no debe:

```text
abrir PDF
renderizar PDF
separar páginas
extraer texto PDF
```

---

# 22. Integración con `procesador-ocr`

Puede producir:

```text
ocr_ready.png
```

Flujo:

```text
procesador-image
      ↓
ImageResult
      ↓
orchestrator
      ↓
select image variant
      ↓
OCRRequest
      ↓
procesador-ocr
```

OCR no debe buscar automáticamente la variante.

El orquestador debe seleccionarla explícitamente.

---

# 23. Integración con `procesador-llm-call`

Puede producir:

```text
vlm_ready.png
```

Flujo:

```text
procesador-image
      ↓
ImageResult
      ↓
orchestrator
      ↓
select_source()
      ↓
build_llm_input()
      ↓
procesador-llm-call
```

El procesador de imagen no conoce:

* prompts;
* templates;
* schemas;
* providers;
* modelos;
* grafos LLM.

---

# 24. Integración completa

```text
                   PDF / IMAGE
                        ↓
                procesador-orquestador
                        ↓
             ┌──────────┴──────────┐
             ▼                     ▼
       procesador-pdf          direct image
             │                     │
             ▼                     │
        render/page.png             │
             └──────────┬───────────┘
                        ↓
                   ImageRequest
                        ↓
                procesador-image
                        ↓
                   ImageResult
                        ↓
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
    normalized     ocr_ready      vlm_ready
          │             │             │
          └─────────────┼─────────────┘
                        ↓
                 procesador-orquestador
                        ↓
               routing documental
                  ┌─────┴─────┐
                  ▼           ▼
                 OCR         LLM/VLM
```

---

# 25. Independencia del módulo

Debe poder funcionar de manera aislada:

```text
image.jpg
    ↓
ImageRequest
    ↓
procesador-image
    ↓
ImageResult
```

Esto permite:

* tests unitarios;
* benchmarking;
* experimentar con OpenCV/Pillow;
* cambiar algoritmos;
* comparar configuraciones;
* evaluar normalización;
* medir calidad;
* probar preparación OCR;
* probar preparación VLM;
* procesar imágenes sin PDF.

---

# 26. Reemplazo de implementación

El resto del sistema no debe depender directamente de OpenCV o Pillow.

Arquitectura:

```text
ImageRequest
     ↓
procesador-image
     ↓
ImageResult
```

Internamente puede existir hoy:

```text
OpenCV
Pillow
NumPy
```

y mañana otra implementación.

Mientras se mantengan:

```text
ImageRequest
ImageResult
```

el resto del sistema no debería cambiar.

---

# 27. Métricas de ejecución

Puede registrar:

```text
timing
├── load_time
├── analysis_time
├── normalization_time
├── variant_time
├── write_time
└── total_time
```

También cuando resulte útil:

```text
resource_usage
├── cpu
├── memory
└── gpu
```

El módulo mide.

No toma decisiones globales de costo o scheduling.

---

# Regla arquitectónica final

`procesador-image`:

> **Recibe una imagen y devuelve representaciones técnicamente preparadas más información objetiva sobre ella.**

Es dueño de:

```text
análisis técnico

métricas de imagen

orientación

deskew

resize

contraste

brillo

denoise

sharpening

conversión

compresión

clasificación técnica

normalized image

OCR-ready image

VLM-ready image

validación técnica

metadata de imagen

persistencia de artefactos de imagen
```

No es dueño de:

```text
PDF

OCR

LLM/VLM

selección de fuente

routing documental

decisión OCR/VLM

estado global

idempotencia del workflow

stop/resume

skip/force

fallbacks

invalidación downstream

consolidación documental
```

En términos simples:

```text
procesador-pdf
    =
descompone el PDF

procesador-image
    =
prepara técnicamente la imagen

procesador-ocr
    =
lee la imagen

procesador-llm-call
    =
realiza inferencia

procesador-orquestador
    =
decide cómo colaboran
```

La regla operativa fundamental es:

> **Preparar no significa decidir.**

El módulo puede generar:

```text
normalized.png
ocr_ready.png
vlm_ready.png
```

pero solamente el orquestador decide:

```text
qué variante usar

para qué procesador

y en qué momento
```

Respecto de reutilización:

> **`procesador-image` no decide si un artefacto previo puede reutilizarse. Si recibe un `ImageRequest`, ejecuta la transformación solicitada. La decisión `REUSE / SKIP / FORCE / RESUME` pertenece al orquestador.**
