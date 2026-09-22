# Procesador Orquestador

## Objetivo

El módulo `procesador-orquestador` tiene como responsabilidad exclusiva **coordinar, persistir y controlar el workflow documental completo**.

Debe decidir:

* qué procesador ejecutar;
* en qué orden;
* con qué artefactos;
* qué fuente documental utilizar;
* cuándo ejecutar procesamiento de imagen;
* cuándo ejecutar OCR;
* cuándo utilizar visión;
* cuándo invocar el procesador LLM;
* cuándo reutilizar resultados existentes;
* cuándo omitir una etapa;
* cuándo forzar su reprocesamiento;
* cómo detener y reanudar una ejecución;
* cómo manejar errores y fallbacks;
* cómo invalidar resultados dependientes;
* cómo controlar concurrencia;
* cómo consolidar resultados por página y documento.

El orquestador **no implementa lógica interna de PDF, imagen, OCR o LLM**.

Su responsabilidad empieza cuando recibe un documento o recupera una ejecución existente y termina cuando:

* devuelve un `DocumentResult`;
* deja el workflow pausado de forma recuperable;
* o marca la ejecución como fallida o pendiente de revisión.

---

# Principio de diseño

El orquestador responde:

> **“¿Qué debe hacerse ahora con este documento o página, utilizando qué artefactos y qué resultados existentes pueden reutilizarse?”**

No responde:

> **“¿Cómo funciona internamente cada procesador?”**

Por lo tanto:

```text
procesador-orquestador
    = decidir
    + coordinar
    + administrar estado
    + controlar ejecución

procesador-pdf
procesador-image
procesador-ocr
procesador-llm-call
    = ejecutar capacidades específicas
```

---

# Principios operativos

El orquestador debe cumplir cinco propiedades fundamentales:

```text
1. separación de responsabilidades
2. idempotencia
3. resumibilidad
4. trazabilidad
5. control de costo
```

La regla central es:

> **Una etapa exitosa no debe ejecutarse nuevamente salvo que haya sido invalidada, forzada o sus entradas/configuración hayan cambiado.**

---

# Flujo principal

1. Recibir un `DocumentRequest`.
2. Identificar el documento.
3. Crear o recuperar `DocumentContext`.
4. Crear un `workflow_run_id`.
5. Detectar tipo de entrada.
6. Construir el plan de ejecución.
7. Inspeccionar estados y artefactos existentes.
8. Determinar por etapa:

```text
SKIP
REUSE
EXECUTE
RESUME
RETRY
FORCE
STOP
```

9. Si es PDF:

   * invocar `procesador-pdf` cuando corresponda;
   * registrar páginas y artefactos.

10. Si es imagen:

    * crear una página lógica.

11. Procesar cada página independientemente.

12. Para cada etapa:

    * resolver dependencias;
    * calcular identidad de procesamiento;
    * determinar si existe un resultado reutilizable;
    * ejecutar solamente cuando sea necesario.

13. Seleccionar fuente documental.

14. Construir `LLMInput` si corresponde.

15. Invocar `procesador-llm-call`.

16. Registrar decisiones, estados y artefactos.

17. Consolidar páginas.

18. Consolidar documento.

19. Persistir `DocumentContext`.

20. Devolver `DocumentResult`.

---

# Flujo general

```text
INPUT
  ↓
ORCHESTRATOR
  ↓
load/create context
  ↓
build execution plan
  ↓
detect_input_type()
  │
  ├── PDF
  │    ↓
  │ resolve_stage(PDF)
  │    ↓
  │ procesador-pdf / REUSE
  │    ↓
  │ pages[]
  │
  └── IMAGE
       ↓
     logical page

           ↓
      process_page()
           ↓
     resolve IMAGE stage
      │
      ├── REUSE
      ├── SKIP
      └── EXECUTE
              ↓
       procesador-image

           ↓
      resolve OCR stage
      │
      ├── REUSE
      ├── SKIP
      └── EXECUTE
              ↓
        procesador-ocr

           ↓
      select_source()

           ↓
      resolve LLM stage
      │
      ├── REUSE
      ├── SKIP
      └── EXECUTE
              ↓
     procesador-llm-call

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
├── execution
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
  },

  "execution": {
    "resume": true,
    "reuse_successful": true,
    "retry_failed": true,
    "invalidate_downstream": true
  }
}
```

---

# Política de ejecución

Las decisiones operativas deben estar separadas de las políticas documentales.

```text
ExecutionPolicy
├── resume
├── reuse_successful
├── retry_failed
├── skip_stages[]
├── force_stages[]
├── stop_after_stage
├── start_from_stage
├── invalidate_downstream
├── dry_run
└── parallel_pages
```

Ejemplo:

```yaml
execution:

  resume: true

  reuse_successful: true

  retry_failed: true

  invalidate_downstream: true

  skip_stages: []

  force_stages:
    - OCR

  stop_after_stage: null

  start_from_stage: null

  dry_run: false
```

---

# Salida

```text
DocumentResult
├── document_id
├── workflow_run_id
├── input
├── pages[]
├── status
├── execution_summary
├── decisions[]
├── errors[]
├── metadata
└── final_result
```

---

# Identidades del sistema

Se deben diferenciar tres identificadores.

## `document_id`

Identifica el documento lógico.

Debe permanecer estable entre múltiples ejecuciones del mismo documento.

---

## `workflow_run_id`

Identifica una ejecución concreta del workflow.

```text
document_id
    │
    ├── workflow_run_001
    ├── workflow_run_002
    └── workflow_run_003
```

---

## `processing_key`

Identifica determinísticamente una operación.

Conceptualmente:

```text
processing_key =
    hash(
        processor
        + processor_version
        + input_hashes
        + normalized_options
    )
```

La regla es:

```text
mismas entradas
+ misma configuración
+ misma versión
────────────────────
mismo processing_key
```

El `processing_key` permite decidir si un resultado existente continúa siendo reutilizable.

---

# Estado global

El orquestador es el único dueño del estado documental global.

```text
DocumentContext
├── document_id
├── workflow_run_id
├── input
├── input_hash
├── input_type
├── workflow
├── policies
├── execution_policy
├── pages[]
├── stages[]
├── decisions[]
├── errors[]
├── status
├── stop_requested
└── final_result
```

Los procesadores no modifican directamente `DocumentContext`.

---

# Estado por página

Cada página mantiene su propio contexto.

```text
PageContext
├── page_number
│
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
├── stages
│   ├── image
│   ├── ocr
│   └── llm
│
├── selected_source
├── extraction_strategy
├── decisions[]
├── errors[]
└── status
```

Cada procesador únicamente recibe una solicitud y devuelve su propio resultado.

---

# Estado de etapa

La unidad básica de control operativo es:

```text
document
   ↓
page
   ↓
stage
```

Cada etapa debe tener un registro independiente.

```text
StageExecution
├── stage_id
├── stage
├── processor
├── processor_version
├── status
├── processing_key
├── input_artifacts[]
├── output_artifacts[]
├── options_hash
├── attempts
├── started_at
├── finished_at
├── skip_reason
├── force_reason
├── error
└── metadata
```

---

# Estados posibles

```text
NOT_STARTED
READY
RUNNING
SUCCESS
FAILED
PARTIAL
SKIPPED
REUSED
INVALIDATED
PAUSED
CANCELLED
REVIEW_REQUIRED
```

Diferenciar `SKIPPED` de `REUSED` es importante.

```text
SKIPPED
    = la etapa deliberadamente no debe ejecutarse

REUSED
    = la etapa no se ejecuta porque existe un resultado válido
```

---

# Artefactos

Cada artefacto debería poder describirse mediante:

```text
ArtifactDescriptor
├── artifact_id
├── artifact_type
├── path
├── content_hash
├── processing_key
├── producer
├── producer_version
├── input_artifacts[]
├── workflow_run_id
├── status
└── metadata
```

Los procesadores continúan utilizando archivos físicos.

El orquestador mantiene además información que permite determinar:

* quién produjo el artefacto;
* a partir de qué inputs;
* mediante qué configuración;
* si continúa siendo válido.

---

# Ownership de artefactos

Cada procesador escribe exclusivamente en su propio namespace.

```text
page_001/

├── source/
├── native_text/
├── render/

├── image/
├── ocr/
└── llm/
```

Regla:

```text
PDF
    → source/
    → render/
    → native_text/

IMAGE
    → image/

OCR
    → ocr/

LLM
    → llm/
```

Un procesador nunca debe sobrescribir artefactos pertenecientes a otro procesador.

---

# 1. Primitivas

El orquestador debe mantener pocas primitivas.

---

## Contexto

```text
create_document_context(request)
load_document_context(path)
save_document_context(context)

create_page_context(page_number)
get_page_context(context, page_number)
```

---

## Estado

```text
update_document_state(context, data)
update_page_state(page_context, data)

set_document_status(context, status)
set_page_status(page_context, status)

get_stage_execution(page_context, stage)
set_stage_status(stage_execution, status)
```

---

## Artefactos

```text
register_artifact(...)
register_page_artifact(...)

get_artifact(...)
has_artifact(...)

calculate_artifact_hash(...)
validate_artifact(...)
```

---

## Identidad

```text
calculate_input_hash(...)
calculate_options_hash(...)
calculate_processing_key(...)
```

---

## Ejecución

```text
get_processor(name)
execute_processor(processor, request)

claim_stage(stage_execution)
release_stage(stage_execution)
```

---

## Trazabilidad

```text
register_decision(...)
register_error(...)

append_workflow_trace(...)
build_decision_record(...)
```

Las primitivas no implementan lógica interna de los procesadores.

---

# 2. Procesamiento principal

## `process_document(request)`

Función principal.

Debe:

1. validar entrada;
2. identificar documento;
3. crear o cargar contexto;
4. crear `workflow_run_id`;
5. aplicar `ExecutionPolicy`;
6. construir plan de ejecución;
7. ejecutar o simular etapas;
8. consolidar resultado;
9. persistir estado.

```text
process_document()
      ↓
initialize_or_resume()
      ↓
build_execution_plan()
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

# 3. Plan de ejecución

## `build_execution_plan(context)`

Debe analizar todo el workflow antes de realizar operaciones costosas.

Para cada etapa determina:

```text
EXECUTE
REUSE
SKIP
FORCE
WAIT
BLOCKED
```

Ejemplo:

```text
PAGE 1

PDF      REUSE
IMAGE    REUSE
OCR      FORCE
LLM      INVALIDATED → EXECUTE
```

El plan debe poder generarse sin ejecutar el workflow.

---

# Dry Run

Cuando:

```text
dry_run = true
```

el orquestador:

* carga contexto;
* inspecciona artefactos;
* calcula `processing_key`;
* evalúa dependencias;
* evalúa skips;
* evalúa forces;
* calcula invalidaciones;
* construye el plan;

pero **no ejecuta procesadores**.

Ejemplo:

```text
ExecutionPlan

Page 1
PDF     REUSE
IMAGE   REUSE
OCR     EXECUTE
LLM     EXECUTE

Page 2
PDF     REUSE
IMAGE   REUSE
OCR     REUSE
LLM     REUSE
```

Esto permite inspeccionar previamente operaciones potencialmente costosas.

---

# 4. Procesamiento de documentos

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

* construir `PDFRequest`;
* resolver estado de la etapa;
* reutilizar `PDFResult` cuando sea válido;
* ejecutar `procesador-pdf` cuando corresponda;
* registrar artefactos;
* crear `PageContext`.

No debe:

* renderizar PDF directamente;
* extraer texto;
* extraer imágenes.

---

## `prepare_image_document(context)`

Debe:

* crear una página lógica;
* registrar imagen original;
* derivarla al workflow normal de página.

---

# 5. Procesamiento de páginas

## `process_pages(context)`

Debe:

* procesar páginas independientemente;
* permitir ejecución secuencial o paralela;
* respetar stop requests;
* preservar orden lógico;
* mantener aislamiento de estado.

---

## `process_page(page_context, workflow, policies)`

Función central de routing documental.

Debe:

1. inspeccionar artefactos;
2. evaluar estado;
3. resolver procesamiento de imagen;
4. resolver OCR;
5. seleccionar fuente;
6. seleccionar estrategia;
7. resolver LLM;
8. consolidar página.

```text
process_page()
      ↓
inspect_page()
      ↓
resolve_stage(IMAGE)
      ↓
resolve_stage(OCR)
      ↓
select_source()
      ↓
select_extraction_strategy()
      ↓
resolve_stage(LLM)
      ↓
consolidate_page_result()
```

---

# 6. Resolución de etapas

## `resolve_stage(stage, context, policy)`

Es una de las funciones principales del orquestador.

Debe decidir:

```text
SKIP
FORCE
REUSE
EXECUTE
WAIT
```

Orden recomendado:

```text
explicit_skip?
      ↓ yes
    SKIP

      no
      ↓
explicit_force?
      ↓ yes
   EXECUTE

      no
      ↓
valid reusable result?
      ↓ yes
    REUSE

      no
      ↓
   EXECUTE
```

---

# Skip

Un skip debe ser explícito y persistente.

Puede existir:

```text
SKIPPED_EXPLICIT
SKIPPED_BY_POLICY
```

Ejemplo:

```text
stage: OCR
status: SKIPPED
reason: explicit_skip
```

Un resultado reutilizado no debe registrarse como skip.

Debe registrarse:

```text
status: REUSED
reason: valid_existing_result
```

---

# Force

`force` obliga a ejecutar una etapa incluso si existe un resultado válido.

Ejemplo:

```text
force:
    page: 3
    stage: OCR
```

Resultado:

```text
PDF     REUSE
IMAGE   REUSE
OCR     EXECUTE
LLM     INVALIDATE
```

---

# Niveles de Force

Se pueden soportar:

```text
force_document
force_page
force_stage
```

Ejemplo:

```text
force_document=true
```

fuerza el documento completo.

```text
force_page=3
```

fuerza las etapas correspondientes a la página.

```text
force_stage:
    page: 3
    stage: OCR
```

fuerza una etapa concreta.

---

# 7. Idempotencia

Una operación es reutilizable cuando:

```text
input_hash
      +
processor_version
      +
options_hash
      ↓
processing_key
```

coincide con una ejecución exitosa existente.

## `is_stage_reusable(stage_execution, current_inputs)`

Debe comprobar:

```text
status == SUCCESS

processing_key == current_processing_key

output artifacts exist

output artifact hashes valid
```

Si todas las condiciones se cumplen:

```text
REUSE
```

---

# Regla de idempotencia

> **La existencia física de un archivo no implica que el resultado sea válido.**

Ejemplo incorrecto:

```text
ocr/document.json exists
        ↓
      reuse
```

Ejemplo correcto:

```text
ocr/document.json exists
        ↓
processing_key match?
        ↓
artifact valid?
        ↓
      REUSE
```

---

# 8. Dependencias e invalidación

Cada etapa debe declarar sus dependencias.

Ejemplo:

```text
PDF
 ↓
IMAGE
 ↓
OCR
 ↓
LLM
```

Si cambia una etapa upstream, las dependencias downstream deben invalidarse.

Ejemplo:

```text
IMAGE processing_key cambia
          ↓
OCR INVALIDATED
          ↓
LLM INVALIDATED
```

---

## `invalidate_downstream(stage, page_context)`

Debe:

* encontrar etapas dependientes;
* marcar sus resultados como `INVALIDATED`;
* conservar artefactos históricos;
* impedir su reutilización;
* registrar causa.

Ejemplo:

```text
OCR
status = INVALIDATED
reason = upstream_image_changed
```

---

# 9. Stop

El sistema debe poder detener una ejecución de forma segura.

## `request_stop(context)`

Debe registrar:

```text
stop_requested = true
```

No debe iniciar nuevas etapas.

La operación actualmente en ejecución debe:

* terminar normalmente;
* o cancelarse mediante mecanismos seguros del procesador cuando existan.

Luego debe persistirse el estado.

```text
RUNNING
   ↓
STOP REQUEST
   ↓
finish current atomic stage
   ↓
persist
   ↓
PAUSED
```

---

# Stop seguro

La regla es:

> **Stop no significa destruir el workflow. Significa dejarlo en un estado consistente desde el cual pueda continuar.**

Ejemplo:

```text
PDF      SUCCESS
IMAGE    SUCCESS
OCR      SUCCESS
LLM      NOT_STARTED

DOCUMENT PAUSED
```

---

# Stop After Stage

Debe poder configurarse:

```text
stop_after_stage
```

Ejemplo:

```text
stop_after_stage = OCR
```

Produce:

```text
PDF
 ↓
IMAGE
 ↓
OCR
 ↓
PAUSE
```

Esto permite revisar resultados antes de ejecutar operaciones costosas posteriores.

---

# 10. Resume

## `resume_document(document_id)`

Resume una ejecución existente.

Debe:

1. cargar `DocumentContext`;
2. inspeccionar etapas;
3. validar artefactos;
4. revisar estados incompletos;
5. reconstruir plan;
6. continuar desde donde corresponde.

No significa volver a ejecutar todo.

---

# Comportamiento de Resume

```text
SUCCESS
    → REUSE

REUSED
    → REUSE

SKIPPED
    → mantener skip

INVALIDATED
    → EXECUTE

FAILED
    → RETRY según policy

NOT_STARTED
    → EXECUTE

RUNNING
    → evaluar recuperación
```

---

# Recuperación de RUNNING

Si una ejecución anterior terminó abruptamente dejando:

```text
status = RUNNING
```

el orquestador debe detectar que no existe un worker activo.

Entonces puede convertir:

```text
RUNNING
   ↓
INTERRUPTED
   ↓
READY
```

y decidir retry según política.

---

# 11. Start From

También puede permitirse:

```text
start_from_stage
```

Ejemplo:

```text
start_from_stage = LLM
```

El orquestador debe verificar primero todas las dependencias.

```text
required OCR valid?
required IMAGE valid?
selected source valid?
```

Si faltan dependencias:

```text
BLOCKED
```

No debe regenerarlas automáticamente salvo que la política lo permita.

---

# 12. Invocación de procesadores

## `run_image_processing(page_context)`

Debe:

* localizar input;
* construir `ImageRequest`;
* resolver `processing_key`;
* invocar `procesador-image`;
* validar resultado;
* registrar `ImageResult`;
* registrar artefactos.

No procesa imágenes directamente.

---

## `run_ocr(page_context)`

Debe:

* localizar imagen seleccionada;
* construir `OCRRequest`;
* resolver `processing_key`;
* invocar `procesador-ocr`;
* validar resultado técnico;
* registrar `OCRResult`;
* registrar artefactos.

No ejecuta Docling directamente.

---

## `run_llm(page_context, llm_input)`

Debe:

* recibir `LLMInput` ya preparado;
* resolver estado de etapa;
* invocar `procesador-llm-call`;
* registrar `LLMResult`.

No debe:

* renderizar templates;
* construir payload del provider;
* ejecutar retries internos LLM;
* validar schemas internamente;
* decidir nodos internos del grafo LLM.

Eso pertenece a `procesador-llm-call`.

---

# 13. Decisores documentales

Los decisores pertenecen al orquestador porque determinan routing entre procesadores.

---

## `should_process_image(page_context, policy)`

Puede evaluar:

* existencia de imagen;
* clasificación PDF;
* calidad;
* necesidad de normalización;
* workflow.

---

## `should_run_ocr(page_context, policy)`

Puede decidir OCR cuando:

* no existe texto nativo;
* texto nativo insuficiente;
* página predominantemente imagen;
* workflow requiere OCR;
* se necesita segunda fuente.

---

## `should_run_vlm(page_context, policy)`

Puede decidir incluir imagen cuando:

* existe información visual relevante;
* página `MIXED`;
* OCR no representa todo el contenido;
* workflow requiere visión.

No ejecuta inferencia.

---

## `should_run_llm(page_context, workflow)`

Determina si la página requiere inferencia.

---

# 14. Selección de fuente

## `select_source(page_context, policy)`

Fuentes posibles:

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

La decisión debe quedar registrada.

---

# 15. Estrategia de extracción

## `select_extraction_strategy(page_context, workflow, policy)`

Valores posibles:

```text
TEXT_ONLY
OCR_ONLY
VLM_ONLY
TEXT_PLUS_VLM
OCR_PLUS_VLM
```

Define qué artefactos se enviarán al siguiente procesador.

No ejecuta inferencia.

---

# 16. Construcción del LLMInput

## `build_llm_input(page_context, strategy, workflow)`

Construye:

```text
LLMInput
├── task
├── provider
├── model
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

El orquestador decide:

```text
qué enviar
```

`procesador-llm-call` decide:

```text
cómo ejecutar la inferencia
```

---

# 17. Políticas documentales

Las decisiones de routing deben estar desacopladas del código.

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

---

# 18. Manejo de errores

El orquestador administra errores a nivel workflow.

Puede decidir:

```text
retry processor
fallback processor
continue partial
stop page
pause document
review required
```

---

## `handle_processor_error(error, context, policy)`

Ejemplo:

```text
OCR FAILED
    ↓
¿retry permitido?
    │
   yes
    ↓
 retry OCR

    no
    ↓
¿VLM permitido?
   ┌─┴─┐
  yes  no
   │    │
  VLM REVIEW_REQUIRED
```

---

# Diferencia con retry LLM

El orquestador puede reintentar un procesador completo:

```text
procesador-ocr
      ↓
ERROR
      ↓
retry processor
```

`procesador-llm-call` administra retries internos:

```text
LLM request
      ↓
invalid JSON
      ↓
retry inference
```

Los dos niveles no deben mezclarse.

---

# 19. Comparación de fuentes documentales

Comparaciones como:

```text
native text
vs
OCR text
```

o:

```text
OCR
vs
visual result
```

pertenecen al nivel documental.

Funciones posibles:

```text
compare_document_sources()
detect_source_conflicts()
select_best_source()
```

La comparación entre múltiples inferencias pertenece a `procesador-llm-call`.

---

# 20. Reprocesamiento

Reprocesar no implica necesariamente ejecutar nuevamente.

Ejemplo:

```text
reprocess_ocr(page)
        ↓
calculate processing_key
        ↓
same key?
   ┌────┴────┐
  YES       NO
   │         │
 REUSE    EXECUTE
```

Funciones posibles:

```text
reprocess_document()
reprocess_page()
reprocess_image()
reprocess_ocr()
reprocess_llm()
```

---

# 21. Paralelización y concurrencia

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
* límites;
* fallos;
* stop;
* orden final.

---

# Claim de etapas

Antes de ejecutar una etapa:

```text
claim_stage(stage)
```

debe realizar una transición atómica:

```text
READY
   ↓
RUNNING
```

Solo un worker debe poder adquirir la etapa.

Si otro worker encuentra:

```text
RUNNING
```

debe:

```text
WAIT
```

o abandonar según política.

Esto evita ejecuciones duplicadas costosas.

---

# 22. Persistencia atómica

Los artefactos críticos no deben considerarse válidos mientras están siendo escritos.

Ejemplo:

```text
document.json.tmp
       ↓
write
       ↓
validate
       ↓
atomic rename
       ↓
document.json
```

La misma regla puede aplicarse a:

```text
metadata.json
normalized.png
OCR outputs
LLM outputs
DocumentContext
```

---

# 23. Consolidación

## `consolidate_page_result(page_context)`

Debe reunir:

* artefactos;
* stage executions;
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
* conservar artefactos;
* registrar etapas reutilizadas;
* registrar etapas omitidas;
* registrar ejecuciones realizadas;
* consolidar extracción final;
* generar `DocumentResult`.

No debe alterar resultados originales.

---

# 24. Helpers

## Estado

```text
get_page_context()
get_stage_execution()

set_page_status()
set_document_status()
set_stage_status()
```

---

## Idempotencia

```text
calculate_input_hash()
calculate_options_hash()
calculate_processing_key()

is_stage_reusable()
validate_stage_outputs()
```

---

## Dependencias

```text
get_stage_dependencies()
get_downstream_stages()
invalidate_stage()
invalidate_downstream()
```

---

## Artefactos

```text
get_artifact()
has_artifact()
register_page_artifact()

get_best_available_text()
get_best_available_image()
```

---

## Routing

```text
evaluate_condition()
match_policy()
resolve_next_processor()
resolve_stage()
```

---

## Stop / Resume

```text
request_stop()
should_stop()
resume_document()
recover_interrupted_stage()
```

---

## Concurrencia

```text
claim_stage()
release_stage()
is_stage_running()
```

---

## Errores

```text
build_error_record()
is_recoverable_error()
should_retry_processor()
```

---

## Trazabilidad

```text
build_workflow_run_id()
append_workflow_trace()
build_decision_record()
```

---

# 25. Responsabilidades que NO pertenecen al orquestador

No debe implementar directamente:

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

Cada operación pertenece a su procesador específico.

---

# 26. Separación con `procesador-llm-call`

## Orquestador

Decide:

```text
¿Necesito LLM?

¿Qué fuente documental uso?

¿Incluyo imagen?

¿Qué task ejecutar?

¿Qué template/schema corresponde?

¿Existe un resultado reutilizable?

¿La etapa está invalidada?

¿Debe omitirse?

¿Debe forzarse?

¿Qué hago si falla el procesador?
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

Decide internamente:

```text
¿Cómo renderizo el prompt?

¿Cómo construyo mensajes?

¿Cómo llamo al provider?

¿Cómo valido schema?

¿Reintento la inferencia?

¿Qué nodo LLM sigue?

¿Cómo comparo outputs LLM?
```

Devuelve:

```text
LLMResult
```

---

# 27. Dos grafos separados

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

Cada nodo puede resultar:

```text
EXECUTE
REUSE
SKIP
FORCE
INVALIDATED
```

---

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

Ambos grafos no deben compartir responsabilidad.

---

# Integración completa

```text
                          INPUT
                            ↓
                  procesador-orquestador
                            ↓
                    load/create state
                            ↓
                   build execution plan
                            ↓
                      detect type
                   ┌────────┴────────┐
                   ▼                 ▼
                  PDF              IMAGE
                   │                 │
                   ▼                 │
             resolve PDF stage       │
                   │                 │
             execute / reuse         │
                   │                 │
                   └────────┬────────┘
                            ▼
                       PageContext
                            ↓
                      process_page
                            ↓
                    resolve IMAGE
                   ┌────────┴────────┐
                   │                 │
                 REUSE            EXECUTE
                                     ↓
                              procesador-image
                                     ↓
                                 ImageResult

                            ↓
                      resolve OCR
                   ┌────────┴────────┐
                   │                 │
                 REUSE            EXECUTE
                                     ↓
                               procesador-ocr
                                     ↓
                                  OCRResult

                            ↓
                       select_source
                            ↓
                       resolve LLM
                   ┌────────┴────────┐
                   │                 │
                 REUSE            EXECUTE
                                     ↓
                           procesador-llm-call
                                     ↓
                                  LLMResult

                            ↓
                         consolidate
                            ↓
                       DocumentResult
```

---

# Independencia

El orquestador depende exclusivamente de los contratos públicos:

```text
PDFRequest   → PDFResult

ImageRequest → ImageResult

OCRRequest   → OCRResult

LLMInput     → LLMResult
```

Los procesadores:

* no conocen `resume`;
* no conocen `skip`;
* no conocen `force`;
* no conocen el workflow completo;
* no deciden si su resultado debe reutilizarse.

Reciben:

```text
request
```

Ejecutan:

```text
capability
```

Devuelven:

```text
result
```

El orquestador decide cuándo y por qué invocarlos.

---

# Regla arquitectónica final

`procesador-orquestador`:

> **Recibe o recupera un documento, administra el estado persistente del workflow y decide qué procesador debe ejecutarse, reutilizarse, omitirse, forzarse o invalidarse en cada etapa.**

Es dueño de:

```text
workflow documental

routing

estado global

estado de etapas

idempotencia

stop / resume

skip / force

dependencias

invalidación downstream

concurrencia

selección de fuentes

políticas

fallbacks

reprocesamiento

consolidación
```

No es dueño de:

```text
implementación PDF

procesamiento interno de imagen

implementación OCR

inferencia LLM

retry interno LLM

grafo interno LLM
```

En términos simples:

```text
ORQUESTADOR
    =
decide
+ coordina
+ recuerda
+ reutiliza
+ controla

PROCESADORES
    =
ejecutan capacidades específicas
```

La regla operativa fundamental es:

> **No volver a ejecutar trabajo válido sin una razón explícita.**

Una etapa solamente debe ejecutarse nuevamente cuando:

```text
no existe resultado

o

resultado inválido

o

inputs cambiaron

o

configuración cambió

o

versión cambió

o

force fue solicitado
```

Todo lo demás debe resolverse mediante:

```text
REUSE
```
