# Procesador Orquestador

## Objetivo

El módulo `procesador-orquestador` tiene como responsabilidad exclusiva **coordinar el workflow documental completo**.

Debe decidir:

* qué procesador ejecutar;
* en qué orden;
* con qué artefactos;
* qué fuente documental utilizar;
* cuándo ejecutar OCR;
* cuándo utilizar visión;
* cuándo invocar el procesador LLM;
* cómo manejar errores y fallbacks entre procesadores;
* cómo consolidar resultados por página y por documento.

El orquestador **no implementa lógica interna de PDF, imagen, OCR o LLM**.

Su responsabilidad empieza cuando recibe un documento y termina cuando devuelve un resultado documental consolidado.

---

# Principio de diseño

El orquestador responde:

> **“¿Qué debe hacerse con este documento o página y qué procesador debe ejecutarse a continuación?”**

No responde:

> **“¿Cómo funciona internamente cada procesador?”**

Por lo tanto:

```text
procesador-orquestador
    = qué hacer

procesador-pdf
procesador-image
procesador-ocr
procesador-llm-call
    = cómo hacerlo
```

---

# Flujo principal

* Recibir una entrada.
* Detectar si es:

  * PDF;
  * imagen;
  * formato no soportado.
* Crear el contexto global del documento.
* Si es PDF:

  * ejecutar `procesador-pdf`;
  * registrar páginas y artefactos generados.
* Si es imagen:

  * crear una página lógica única.
* Procesar cada página independientemente.
* Evaluar qué artefactos existen:

  * texto nativo;
  * imagen;
  * imagen normalizada;
  * OCR.
* Ejecutar `procesador-image` cuando sea necesario.
* Ejecutar `procesador-ocr` cuando corresponda.
* Seleccionar la fuente documental más adecuada.
* Construir un `LLMInput` cuando el workflow requiera inferencia.
* Invocar `procesador-llm-call`.
* Registrar resultados y decisiones.
* Consolidar páginas.
* Consolidar documento.
* Devolver `DocumentResult`.

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
   logical page

        ↓
    process_page()
        ↓
  inspect artifacts
        ↓
  image processing?
        │
        ▼
 procesador-image
        ↓
   image result
        ↓
       OCR?
        │
        ▼
  procesador-ocr
        ↓
    OCR result
        ↓
   select_source()
        ↓
   LLM required?
        │
        ▼
   build_llm_input()
        ↓
procesador-llm-call
        ↓
    LLMResult
        ↓
consolidate_page()
        ↓
consolidate_document()
```

---

# Contrato del módulo

## Entrada

```text
DocumentRequest
├── input_path
├── input_type
├── workflow
├── policies
├── options
└── metadata
```

Ejemplo:

```json
{
  "input_path": "document.pdf",
  "workflow": "invoice_extraction",

  "options": {
    "parallel_pages": true
  },

  "policies": {
    "allow_ocr": true,
    "allow_vlm": true
  }
}
```

---

# Salida

```text
DocumentResult
├── document_id
├── input
├── pages[]
├── status
├── decisions[]
├── errors[]
├── metadata
└── final_result
```

---

# Estado global

El orquestador es el único dueño del estado global del documento.

```text
DocumentContext
├── document_id
├── input
├── input_type
├── workflow
├── policies
├── pages[]
├── decisions[]
├── errors[]
├── status
└── final_result
```

---

# Estado por página

Cada página debe mantener su propio contexto.

```text
PageContext
├── page_number
├── artifacts
│   ├── page_pdf
│   ├── page_image
│   ├── native_text
│   ├── normalized_image
│   ├── ocr_text
│   └── ocr_markdown
│
├── results
│   ├── pdf_result
│   ├── image_result
│   ├── ocr_result
│   └── llm_result
│
├── selected_source
├── extraction_strategy
├── decisions[]
├── errors[]
└── status
```

El orquestador mantiene este estado.

Cada procesador únicamente devuelve su propio resultado.

---

# 1. Primitivas

El orquestador debe tener pocas primitivas.

Se utilizan para administrar:

* contexto;
* estado;
* artefactos;
* decisiones;
* invocación de procesadores.

## Contexto

* `create_document_context(request)`
* `create_page_context(page_number)`
* `load_document_context(path)`
* `save_document_context(context)`

## Estado

* `update_document_state(context, data)`
* `update_page_state(page_context, data)`
* `set_document_status(context, status)`
* `set_page_status(page_context, status)`

## Artefactos

* `register_artifact(context, artifact_type, path)`
* `register_page_artifact(page_context, artifact_type, path)`
* `get_artifact(context, artifact_type)`
* `has_artifact(context, artifact_type)`

## Trazabilidad

* `register_decision(context, decision)`
* `register_error(context, error)`

## Procesadores

* `get_processor(name)`
* `execute_processor(processor, request)`

Estas funciones no deben implementar lógica interna de los procesadores.

---

# 2. Utilitarios

## `process_document(request)`

Función principal.

Debe:

* validar entrada;
* crear `DocumentContext`;
* detectar tipo;
* ejecutar procesamiento inicial;
* crear páginas;
* procesar páginas;
* consolidar resultados;
* devolver `DocumentResult`.

```text
process_document()
      ↓
detect_input_type()
      ↓
initialize_document()
      ↓
prepare_pages()
      ↓
process_pages()
      ↓
consolidate_document_result()
      ↓
DocumentResult
```

---

## `detect_input_type(input_path)`

Determina:

```text
PDF
IMAGE
UNSUPPORTED
```

No analiza semánticamente el contenido.

---

## `prepare_pdf_document(context)`

Debe:

* construir request para `procesador-pdf`;
* ejecutar el procesador;
* registrar `PDFResult`;
* crear `PageContext` para cada página.

No debe:

* renderizar directamente;
* extraer texto;
* extraer imágenes.

---

## `prepare_image_document(context)`

Debe:

* crear una única página lógica;
* registrar la imagen como artefacto de entrada;
* derivarla al workflow común de página.

---

## `process_pages(context)`

Debe:

* iterar páginas;
* permitir ejecución secuencial o paralela;
* llamar a `process_page()` para cada una;
* preservar orden lógico.

---

## `process_page(page_context, workflow, policies)`

Función central del routing documental.

Debe:

1. inspeccionar artefactos disponibles;
2. determinar si necesita procesamiento de imagen;
3. ejecutar imagen si corresponde;
4. determinar si necesita OCR;
5. ejecutar OCR si corresponde;
6. seleccionar fuente;
7. definir estrategia de extracción;
8. construir `LLMInput` si corresponde;
9. ejecutar procesador LLM;
10. consolidar resultado de página.

Flujo:

```text
process_page()
      ↓
inspect_page()
      ↓
should_process_image()
      ↓
run_image_processing()
      ↓
should_run_ocr()
      ↓
run_ocr()
      ↓
select_source()
      ↓
select_extraction_strategy()
      ↓
should_run_llm()
      ↓
build_llm_input()
      ↓
run_llm()
      ↓
consolidate_page_result()
```

---

# 3. Invocación de procesadores

## `run_image_processing(page_context)`

Debe:

* localizar imagen de entrada;
* construir request;
* invocar `procesador-image`;
* registrar `ImageResult`;
* registrar artefactos nuevos.

No procesa la imagen directamente.

---

## `run_ocr(page_context)`

Debe:

* localizar imagen normalizada;
* construir `OCRRequest`;
* invocar `procesador-ocr`;
* registrar `OCRResult`;
* registrar artefactos OCR.

No ejecuta Docling directamente.

---

## `run_llm(page_context, llm_input)`

Debe:

* enviar `LLMInput` ya preparado;
* invocar `procesador-llm-call`;
* registrar `LLMResult`.

No debe:

* renderizar templates;
* ejecutar retries LLM;
* validar schemas internamente;
* decidir nodos del grafo LLM.

Eso pertenece a `procesador-llm-call`.

---

# 4. Decisores documentales

Los decisores pertenecen al orquestador porque determinan el routing entre procesadores.

## `should_process_image(page_context, policy)`

Puede evaluar:

* existencia de imagen;
* clasificación PDF;
* necesidad de normalización;
* workflow solicitado.

Devuelve:

```text
true / false
```

---

## `should_run_ocr(page_context, policy)`

Puede decidir OCR cuando:

* no existe texto nativo;
* el texto nativo es insuficiente;
* la página es predominantemente imagen;
* el workflow requiere OCR;
* se necesita una segunda fuente textual.

---

## `should_run_vlm(page_context, policy)`

Puede determinar si la entrada LLM debe incluir imagen cuando:

* hay contenido visual relevante;
* la página es `MIXED`;
* OCR no representa toda la información;
* el workflow requiere visión.

Importante:

`should_run_vlm()` **no ejecuta el modelo**.

Solo determina si la imagen debe incluirse en `LLMInput`.

---

## `should_run_llm(page_context, workflow)`

Determina si la página requiere una etapa LLM.

Devuelve:

```text
true / false
```

---

# 5. Selección de fuente

## `select_source(page_context, policy)`

Debe seleccionar la representación documental a utilizar.

Posibles fuentes:

```text
NATIVE_TEXT
OCR_TEXT
IMAGE
NATIVE_TEXT + IMAGE
OCR_TEXT + IMAGE
```

Ejemplo:

```json
{
  "source": "OCR_TEXT",
  "reason": "native_text_empty"
}
```

La decisión debe registrarse.

---

# 6. Estrategia de extracción

## `select_extraction_strategy(page_context, workflow, policy)`

Puede devolver:

```text
TEXT_ONLY
OCR_ONLY
VLM_ONLY
TEXT_PLUS_VLM
OCR_PLUS_VLM
```

Esta función define **qué información será enviada** al siguiente procesador.

No ejecuta inferencia.

---

# 7. Construcción del input LLM

## `build_llm_input(page_context, strategy, workflow)`

Debe transformar artefactos ya seleccionados en:

```text
LLMInput
├── task
├── template
├── document
├── images[]
├── extra_context
├── schema
├── options
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

El orquestador decide **qué enviar**.

`procesador-llm-call` decide **cómo enviarlo al modelo**.

---

# 8. Políticas

Las decisiones de routing deberían estar desacopladas del código.

Ejemplo:

```yaml
image:
  enabled: true

ocr:
  enabled: true
  when:
    - native_text_empty
    - image_page
    - native_text_low_density

vlm:
  enabled: true
  when:
    - mixed_page
    - visual_content
    - workflow_requires_visual_context

llm:
  enabled: true
```

Las políticas determinan comportamiento sin modificar procesadores.

---

# 9. Manejo de errores entre procesadores

El orquestador administra errores a nivel workflow.

Puede decidir:

```text
retry processor
fallback processor
continue partial
stop page
review required
```

Estados posibles:

```text
PENDING
PROCESSING
SUCCESS
PARTIAL
FAILED
REVIEW_REQUIRED
```

---

## `handle_processor_error(error, context, policy)`

Ejemplo:

```text
OCR FAILED
    ↓
¿VLM permitido?
   ┌─┴─┐
  yes  no
   │    │
image  REVIEW_REQUIRED
to VLM
```

---

# Diferencia con retry LLM

El orquestador puede reintentar un **procesador completo**:

```text
procesador-ocr
      ↓
ERROR
      ↓
retry / fallback
```

`procesador-llm-call` administra retries internos como:

```text
LLM request
      ↓
invalid JSON
      ↓
retry LLM
```

Los dos niveles no deben mezclarse.

---

# 10. Comparación de fuentes documentales

Si se necesita comparar:

```text
native text
vs
OCR text
```

o:

```text
OCR
vs
resultado visual
```

esa comparación pertenece al nivel documental.

Funciones posibles:

* `compare_document_sources()`
* `detect_source_conflicts()`
* `select_best_source()`

Estas funciones no deben comparar múltiples respuestas LLM.

Eso pertenece a `procesador-llm-call`.

---

# 11. Consolidación

## `consolidate_page_result(page_context)`

Debe reunir:

* artefactos;
* fuente seleccionada;
* estrategia;
* OCR;
* LLM;
* decisiones;
* errores.

Devuelve:

```text
PageResult
```

---

## `consolidate_document_result(document_context)`

Debe:

* ordenar páginas;
* reunir resultados;
* conservar referencias a artefactos;
* consolidar extracción final;
* generar `DocumentResult`.

No debe alterar los resultados originales de los procesadores.

---

# 12. Reprocesamiento

El orquestador debe permitir ejecutar nuevamente solo una etapa.

Ejemplos:

* `reprocess_page(page_number)`
* `reprocess_image(page_number)`
* `reprocess_ocr(page_number)`
* `reprocess_llm(page_number)`

Debe reutilizar artefactos existentes siempre que sigan siendo válidos.

---

# 13. Paralelización

Las páginas deben poder procesarse independientemente.

```text
document.pdf
     ↓
procesador-pdf
     ↓
 ┌────┬────┬────┬────┐
 ▼    ▼    ▼    ▼    ▼
P1   P2   P3   P4   P5
 │    │    │    │    │
 ▼    ▼    ▼    ▼    ▼
process_page()
```

El orquestador controla:

* concurrencia;
* estado;
* fallos;
* orden final.

---

# 14. Helpers

## Estado

* `get_page_context(context, page_number)`
* `set_page_status(page, status)`
* `set_document_status(context, status)`

## Artefactos

* `get_artifact(page, artifact_type)`
* `has_artifact(page, artifact_type)`
* `register_page_artifact(page, type, path)`
* `get_best_available_text(page)`
* `get_best_available_image(page)`

## Routing

* `evaluate_condition(condition, context)`
* `match_policy(context, policy)`
* `resolve_next_processor(context, workflow)`

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

Eliminar cualquier implementación directa de:

```text
extract_text_from_pdf()
render_pdf_page()
extract_pdf_images()

deskew_image()
calculate_blur()
resize_image()

run_docling()
extract_ocr_text()

render_prompt()
build_provider_payload()
generate_text()
generate_multimodal()
validate_llm_schema()
retry_llm_request()
select_next_llm_node()
compare_llm_outputs()
execute_llm_graph()
```

Cada una pertenece a su procesador específico.

---

# Separación con `procesador-llm-call`

## Orquestador

Decide:

```text
¿Necesito LLM?
¿Qué fuente documental uso?
¿Incluyo imagen?
¿Qué task ejecutar?
¿Qué template/schema corresponde al workflow?
¿Qué hago si falla el procesador LLM completo?
```

Genera:

```text
LLMInput
```

---

## Procesador LLM

Recibe:

```text
LLMInput
```

Y decide internamente:

```text
¿Cómo renderizo el prompt?
¿Cómo construyo mensajes?
¿Cómo llamo al provider?
¿Cómo valido el schema?
¿Reintento una inferencia?
¿Qué nodo LLM sigue?
¿Cómo comparo outputs LLM?
```

Devuelve:

```text
LLMResult
```

---

# Dos grafos separados

## Grafo documental

Propiedad del orquestador:

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

## Grafo de inferencia

Propiedad de `procesador-llm-call`:

```text
classify
   ↓
 ┌─┴──────────┐
 ▼            ▼
extract_a   extract_b
 └─────┬──────┘
       ↓
    compare
       ↓
    validate
       ↓
     result
```

Estos grafos no deben compartir responsabilidad.

---

# Integración completa

```text
                    INPUT
                      ↓
             procesador-orquestador
                      ↓
                 detect type
               ┌──────┴──────┐
               ▼             ▼
              PDF          IMAGE
               │             │
               ▼             │
        procesador-pdf       │
               │             │
               └──────┬──────┘
                      ▼
                 PageContext
                      ↓
              routing documental
                      ↓
             procesador-image
                      ↓
                  ImageResult
                      ↓
                 ¿OCR?
                      ↓
              procesador-ocr
                      ↓
                   OCRResult
                      ↓
                select_source
                      ↓
                build_llm_input
                      ↓
             procesador-llm-call
                      ↓
                   LLMResult
                      ↓
             procesador-orquestador
                      ↓
                  consolidate
                      ↓
                DocumentResult
```

---

# Independencia

El orquestador depende de los **contratos públicos** de los procesadores, no de sus implementaciones internas.

Por ejemplo:

```text
PDFRequest → PDFResult
ImageRequest → ImageResult
OCRRequest → OCRResult
LLMInput → LLMResult
```

Esto permite reemplazar:

* Poppler;
* OpenCV;
* Docling;
* Ollama;

sin modificar el flujo general, siempre que se mantenga el contrato.

---

# Regla arquitectónica final

`procesador-orquestador`:

> **Recibe un documento, administra su estado y decide qué procesador debe ejecutarse en cada etapa.**

Es dueño de:

* workflow documental;
* routing entre procesadores;
* selección de fuentes;
* políticas;
* estado global;
* fallbacks;
* consolidación.

No es dueño de:

* implementación PDF;
* implementación de imagen;
* implementación OCR;
* inferencia LLM;
* grafo interno LLM.

En términos simples:

```text
ORQUESTADOR
    = coordina el sistema

PROCESADORES
    = ejecutan capacidades específicas
```
