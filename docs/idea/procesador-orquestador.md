# Procesador Orquestador

## Objetivo

El módulo `procesador-orquestador` tiene como responsabilidad exclusiva **coordinar el flujo completo de procesamiento documental**.

Debe decidir:

* qué procesador ejecutar;
* en qué orden;
* con qué entrada;
* qué resultado reutilizar;
* cuándo continuar, bifurcar, reintentar o finalizar.

El orquestador **no implementa lógica específica de PDF, imagen, OCR o LLM**.

Su función es conectar módulos independientes mediante contratos claros y mantener el estado global del procesamiento.

---

# Principio de diseño

El orquestador debe cumplir una regla simple:

> **Coordina módulos, pero no reemplaza sus responsabilidades.**

Conoce:

* `procesador-pdf`;
* `procesador-image`;
* `procesador-ocr`;
* `procesador-llm-call`.

Pero no implementa internamente:

* Poppler;
* OpenCV;
* Docling;
* Ollama;
* OCR;
* procesamiento visual;
* extracción nativa de PDF.

---

# Flujo principal

* Recibir un documento.
* Detectar el tipo de entrada:

  * PDF;
  * imagen.
* Crear el contexto global del documento.
* Ejecutar el procesador correspondiente.
* Si es PDF:

  * llamar a `procesador-pdf`;
  * obtener las páginas;
  * procesar cada página independientemente.
* Para cada página:

  * analizar resultados disponibles;
  * decidir si utilizar:

    * texto nativo;
    * imagen;
    * OCR;
    * combinación de fuentes.
* Cuando corresponda:

  * llamar a `procesador-image`;
  * llamar a `procesador-ocr`;
  * preparar entrada para LLM;
  * llamar a `procesador-llm-call`.
* Mantener el estado de cada etapa.
* Registrar errores y decisiones.
* Consolidar resultados.
* Generar el resultado final del documento.

---

# Flujo general

```text
INPUT
  ↓
ORCHESTRATOR
  ↓
detect_input_type()
  │
  ├── PDF
  │    ↓
  │ procesador-pdf
  │    ↓
  │ pages[]
  │
  └── IMAGE
       ↓
   image input

        ↓
 process_page()
        ↓
 evaluate sources
        ↓
 ┌──────┼───────────┐
 ▼      ▼           ▼
native  image      OCR
text     │           │
         ▼           │
 procesador-image    │
         │           │
         └─────┬─────┘
               ↓
       select_source()
               ↓
       build_llm_input()
               ↓
   procesador-llm-call
               ↓
          LLMResult
               ↓
       consolidate_result()
```

---

# Contrato del módulo

## Entrada

```text
DocumentRequest
├── input_path
├── input_type
├── workflow
├── options
└── metadata
```

Ejemplo:

```json
{
  "input_path": "document.pdf",
  "workflow": "invoice_extraction",

  "options": {
    "allow_ocr": true,
    "allow_vlm": true,
    "parallel_pages": true
  }
}
```

---

## Salida

```text
DocumentResult
├── document_id
├── input
├── pages[]
├── workflow
├── status
├── errors[]
├── metadata
└── final_result
```

---

# Estado global

El orquestador debe ser el único responsable del estado global del documento.

Ejemplo:

```text
DocumentContext
├── document_id
├── input
├── document_type
├── pages[]
│   ├── page_number
│   ├── pdf_result
│   ├── image_result
│   ├── ocr_result
│   ├── llm_result
│   ├── selected_source
│   ├── status
│   └── errors[]
│
├── workflow_state
├── decisions[]
└── final_result
```

---

# Estado por página

Cada página debe mantener su propio estado.

Ejemplo:

```json
{
  "page_number": 1,

  "status": "processing",

  "artifacts": {
    "native_text": "native_text/text.txt",
    "page_image": "render/page.png",
    "normalized_image": "image/normalized.png",
    "ocr_markdown": "ocr/document.md"
  },

  "results": {
    "pdf": {},
    "image": {},
    "ocr": {},
    "llm": {}
  },

  "decision": {
    "selected_source": "ocr",
    "reason": "native_text_insufficient"
  }
}
```

---

# 1. Primitivas

El orquestador debería tener pocas primitivas.

No encapsula motores externos, sino operaciones básicas de estado y ejecución.

* `create_document_context(request)`
* `create_page_context(page_number)`
* `load_document_context(path)`
* `save_document_context(context)`
* `update_document_state(context, data)`
* `update_page_state(page_context, data)`
* `register_artifact(context, artifact)`
* `register_decision(context, decision)`
* `register_error(context, error)`
* `get_processor(name)`
* `execute_processor(processor, request)`

Las primitivas no deben contener reglas de negocio complejas.

---

# 2. Utilitarios

## `process_document(request)`

Función principal del orquestador.

Debe:

* validar entrada;
* crear contexto;
* detectar tipo;
* ejecutar pipeline correspondiente;
* procesar páginas;
* consolidar resultados;
* devolver `DocumentResult`.

Flujo:

```text
process_document()
      ↓
detect_input_type()
      ↓
initialize_document()
      ↓
process_pdf()
   o process_image()
      ↓
process_pages()
      ↓
consolidate_document()
      ↓
DocumentResult
```

---

## `detect_input_type(input_path)`

Debe determinar:

```text
PDF
IMAGE
UNSUPPORTED
```

No debe analizar el contenido interno.

Solo identifica el tipo de entrada.

---

## `process_pdf_document(context)`

Debe:

* construir `PDFRequest`;
* llamar a `procesador-pdf`;
* registrar `PDFResult`;
* crear un `PageContext` por página;
* derivar cada página a `process_page()`.

No debe implementar procesamiento PDF.

---

## `process_image_document(context)`

Debe:

* crear una página lógica para la imagen;
* construir `ImageRequest`;
* derivar a `process_page()`.

Esto permite que PDF e imagen converjan en el mismo pipeline.

---

## `process_page(page_context, workflow)`

Función central de coordinación por página.

Debe decidir qué módulos ejecutar según:

* artefactos disponibles;
* metadata;
* workflow;
* políticas configuradas.

Ejemplo:

```text
process_page()
     ↓
inspect_page_state()
     ↓
run_image_if_needed()
     ↓
run_ocr_if_needed()
     ↓
select_source()
     ↓
build_llm_input()
     ↓
run_llm_if_needed()
     ↓
finalize_page()
```

---

## `run_image_processing(page_context)`

Debe:

* localizar la imagen de entrada;
* construir request para `procesador-image`;
* ejecutar el módulo;
* registrar `ImageResult`.

No procesa la imagen directamente.

---

## `run_ocr(page_context)`

Debe:

* seleccionar la imagen normalizada;
* construir `OCRRequest`;
* ejecutar `procesador-ocr`;
* registrar `OCRResult`.

No ejecuta Docling directamente.

---

## `run_llm(page_context, workflow)`

Debe:

* construir entrada preparada;
* construir `LLMRequest`;
* llamar a `procesador-llm-call`;
* registrar `LLMResult`.

No construye internamente lógica específica de proveedor.

---

# 3. Decisores

Los decisores pertenecen al orquestador porque determinan el siguiente paso del workflow.

## `should_process_image(page_context)`

Puede evaluar:

* existencia de imagen;
* origen PDF;
* clasificación PDF;
* necesidad de normalización.

Devuelve:

```text
true / false
```

---

## `should_run_ocr(page_context, policy)`

Puede decidir OCR cuando:

* no existe texto nativo;
* el texto es insuficiente;
* la página está clasificada como `IMAGE`;
* el workflow exige OCR;
* se requiere validación adicional.

---

## `should_run_vlm(page_context, policy)`

Puede decidir utilizar imagen en un VLM cuando:

* existe contenido visual relevante;
* la página es `MIXED`;
* OCR no es suficiente;
* el workflow exige visión.

---

## `select_source(page_context, policy)`

Debe seleccionar entre:

```text
NATIVE_TEXT
OCR_TEXT
IMAGE
NATIVE_TEXT + IMAGE
OCR_TEXT + IMAGE
```

La selección debe quedar registrada junto con su motivo.

Ejemplo:

```json
{
  "source": "OCR_TEXT",
  "reason": "native_text_empty",
  "confidence": 0.95
}
```

---

## `select_extraction_strategy(page_context, workflow)`

Puede devolver:

```text
TEXT_ONLY
OCR_ONLY
VLM_ONLY
TEXT_PLUS_VLM
OCR_PLUS_VLM
```

Este decisor no ejecuta módulos.

Solo define la estrategia.

---

# 4. Preparación de entrada para LLM

## `build_llm_input(page_context, strategy)`

Debe construir una estructura común:

```text
PreparedLLMInput
├── document
├── images[]
├── extra_context
├── schema
└── metadata
```

Ejemplo:

```text
strategy = OCR_PLUS_VLM

document:
    ocr/document.md

images:
    image/normalized.png
```

---

## `build_document_context_for_llm(context)`

Permite agregar información de nivel documento:

* páginas anteriores;
* clasificación global;
* reglas de negocio;
* metadata;
* resultados ya consolidados.

---

# 5. Workflow

El workflow debe definir **qué se quiere lograr**, no cómo funciona cada procesador.

Ejemplo:

```yaml
workflow: invoice_extraction

steps:
  - prepare
  - extract
  - validate
  - consolidate
```

El orquestador traduce esas etapas en llamadas a módulos.

---

# Workflow por políticas

Conviene separar reglas del código.

Ejemplo:

```yaml
document:
  process_images: true

ocr:
  enabled: true
  when:
    - native_text_empty
    - image_page
    - low_text_density

vlm:
  enabled: true
  when:
    - mixed_page
    - visual_content
    - ocr_low_confidence
```

Así el comportamiento puede cambiar sin modificar los procesadores.

---

# 6. Consolidación

## `consolidate_page_result(page_context)`

Debe reunir:

* fuente seleccionada;
* OCR;
* LLM;
* validaciones;
* metadata;
* errores.

Devuelve:

```text
PageResult
```

---

## `consolidate_document_result(document_context)`

Debe combinar los resultados de todas las páginas.

Puede:

* mantener resultados separados;
* ordenar páginas;
* unir extracciones;
* generar resultado documental final.

No debe modificar los resultados originales de cada procesador.

---

# 7. Manejo de errores

El orquestador debe decidir qué hacer frente a errores.

Estados posibles:

```text
PENDING
PROCESSING
SUCCESS
PARTIAL
FAILED
REVIEW_REQUIRED
```

Ejemplo:

```text
OCR ERROR
    ↓
¿VLM permitido?
    │
 ┌──┴──┐
yes    no
 │      │
VLM   REVIEW_REQUIRED
```

---

## `handle_processor_error(error, context, policy)`

Puede decidir:

* retry;
* fallback;
* continuar parcialmente;
* detener página;
* marcar revisión manual.

---

# 8. Reprocesamiento

El diseño debe permitir reprocesar solamente una etapa.

Ejemplos:

```text
reprocess_page(page_id)
reprocess_image(page_id)
reprocess_ocr(page_id)
reprocess_llm(page_id)
```

El orquestador reutiliza los artefactos existentes y evita ejecutar etapas anteriores cuando no es necesario.

---

# 9. Paralelización

Cada página debe poder procesarse independientemente.

Ejemplo:

```text
document.pdf
     ↓
procesador-pdf
     ↓
 ┌────┼────┬────┐
 ▼    ▼    ▼    ▼
P1   P2   P3   P4
 │    │    │    │
 ▼    ▼    ▼    ▼
process_page()
```

El orquestador debe controlar:

* concurrencia;
* estado;
* errores;
* orden final.

---

# 10. Helpers

## Estado

* `get_page_context(context, page_number)`
* `set_page_status(page, status)`
* `set_document_status(context, status)`
* `get_artifact(page, artifact_type)`
* `has_artifact(page, artifact_type)`

## Routing

* `evaluate_condition(condition, context)`
* `match_policy(context, policy)`
* `resolve_next_step(state, workflow)`

## Artefactos

* `register_page_artifact(page, type, path)`
* `get_best_available_text(page)`
* `get_best_available_image(page)`

## Errores

* `build_error_record(exception, processor)`
* `is_recoverable_error(error)`
* `should_retry_processor(error, policy)`

## Trazabilidad

* `build_workflow_run_id()`
* `append_workflow_trace(event)`
* `build_decision_record(rule, result, reason)`

---

# Responsabilidades que NO pertenecen al orquestador

El orquestador no debe implementar:

```text
extract_text_from_pdf()
render_pdf()
deskew_image()
calculate_blur()
run_docling()
generate_text()
generate_multimodal()
parse_llm_json()
```

Debe llamar al procesador responsable.

---

# Relación entre módulos

```text
                   ORCHESTRATOR
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
  procesador-pdf  procesador-image  procesador-ocr
        │               │               │
        └───────────────┼───────────────┘
                        │
                        ▼
              procesador-llm-call
```

No debería existir:

```text
procesador-pdf
      ↓
procesador-image
      ↓
procesador-ocr
      ↓
procesador-llm-call
```

como dependencias internas entre módulos.

La relación correcta es:

```text
ORCHESTRATOR → procesador-pdf
ORCHESTRATOR → procesador-image
ORCHESTRATOR → procesador-ocr
ORCHESTRATOR → procesador-llm-call
```

---

# Separación entre Document Workflow y LLM Graph

El orquestador controla el workflow documental:

```text
PDF
 ↓
PAGE
 ↓
IMAGE
 ↓
OCR
 ↓
SOURCE SELECTION
 ↓
LLM
```

`procesador-llm-call` puede controlar internamente un grafo de inferencia:

```text
classify
   ↓
extract_a ─┐
           ├→ compare
extract_b ─┘
             ↓
          validate
             ↓
          result
```

Son dos niveles diferentes y deben mantenerse separados.

---

# Estructura recomendada

```text
orchestrator/
├── orchestrator.py
├── document.py
├── page.py
├── routing.py
├── policies.py
├── state.py
├── artifacts.py
├── errors.py
└── helpers.py
```

---

# Flujo final esperado

```text
                     INPUT
                       ↓
                  ORCHESTRATOR
                       ↓
                 detect type
                 ┌─────┴─────┐
                 ▼           ▼
                PDF        IMAGE
                 │           │
                 ▼           │
          procesador-pdf     │
                 │           │
                 └─────┬─────┘
                       ▼
                  PAGE CONTEXT
                       ↓
              procesador-image
                       ↓
                 IMAGE RESULT
                       ↓
                    DECISOR
             ┌─────────┼─────────┐
             ▼         ▼         ▼
        native text   OCR      image
             │         │         │
             │   procesador-ocr  │
             │         │         │
             └─────────┼─────────┘
                       ▼
                 select_source
                       ↓
                 build_llm_input
                       ↓
              procesador-llm-call
                       ↓
                    RESULT
                       ↓
                   consolidate
```

---

# Regla arquitectónica final

Cada procesador responde:

> **“Recibo X y produzco Y.”**

El orquestador responde:

> **“Según lo que recibí y los resultados disponibles, decido qué procesador ejecutar a continuación.”**

De esta forma:

* los módulos mantienen independencia;
* no existen dependencias circulares;
* los archivos no se pisan;
* cada etapa puede reprocesarse;
* se pueden cambiar motores sin afectar el resto;
* el pipeline puede crecer mediante nuevas políticas y nuevos procesadores.
