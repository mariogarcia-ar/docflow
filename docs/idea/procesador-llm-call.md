# Procesador de Llamadas LLM

## Objetivo

El módulo `procesador-llm-call` tiene como responsabilidad exclusiva **preparar, ejecutar, validar, persistir y coordinar llamadas a modelos LLM/VLM**.

Recibe una tarea de inferencia ya definida mediante `LLMInput` y puede ejecutar:

* una llamada individual;
* múltiples llamadas secuenciales;
* llamadas paralelas;
* un subgrafo de inferencia;
* validaciones;
* retries;
* comparaciones;
* consenso;
* consolidación de resultados.

También debe poder **reanudar un subgrafo LLM parcialmente ejecutado sin repetir llamadas válidas y costosas**.

Este módulo no decide:

* qué documento procesar;
* si ejecutar OCR;
* qué fuente documental utilizar;
* si una página requiere visión;
* qué procesador documental ejecutar;
* cómo consolidar páginas;
* cómo manejar el workflow documental completo.

Su responsabilidad empieza cuando recibe:

```text
LLMInput
```

y termina cuando devuelve:

```text
LLMResult
```

---

# Principio de diseño

`procesador-llm-call` responde:

> **“Dada una tarea LLM ya definida, ¿cómo ejecuto su inferencia de forma estructurada, validada, trazable y reanudable?”**

No responde:

> **“¿Qué debo hacer con este documento o página?”**

Eso pertenece al `procesador-orquestador`.

---

# Dos niveles de orquestación

El sistema mantiene dos niveles claramente separados.

## Orquestador documental

Controla:

```text
PDF
 ↓
IMAGE
 ↓
OCR
 ↓
SOURCE SELECTION
 ↓
LLM
```

Decide si la etapa LLM debe:

```text
EXECUTE
REUSE
SKIP
FORCE
INVALIDATE
```

---

## Procesador LLM

Una vez iniciada la etapa LLM, puede controlar internamente:

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
   consolidate
```

Cada nodo puede a su vez:

```text
EXECUTE
REUSE
SKIP
FORCE
RETRY
INVALIDATE
```

La regla es:

> **El orquestador administra la etapa LLM completa. `procesador-llm-call` administra exclusivamente lo que ocurre dentro de esa etapa.**

---

# Flujo principal

1. Recibir `LLMInput`.
2. Validar contrato.
3. Crear o recuperar `LLMRun`.
4. Resolver configuración.
5. Cargar:

   * provider;
   * modelo;
   * template;
   * variables;
   * documento;
   * imágenes;
   * contexto adicional;
   * schema;
   * opciones.
6. Construir plan de inferencia.
7. Identificar llamadas o nodos ya ejecutados.
8. Reutilizar resultados válidos.
9. Ejecutar únicamente llamadas necesarias.
10. Renderizar prompts.
11. Preparar payloads.
12. Invocar modelos.
13. Capturar respuestas.
14. Parsear resultados.
15. Validar schemas.
16. Aplicar retries cuando corresponda.
17. Resolver ramas del grafo.
18. Comparar outputs cuando corresponda.
19. Consolidar resultado.
20. Persistir trazabilidad.
21. Devolver `LLMResult`.

---

# Flujo general

```text
LLMInput
   ↓
load/create LLMRun
   ↓
build inference plan
   ↓
resolve nodes
   ↓
 ┌───────────────┐
 │               │
REUSE          EXECUTE
                 ↓
          process_template()
                 ↓
           process_prompt()
                 ↓
           prepare inputs
                 ↓
          build_messages()
                 ↓
          provider request
                 ↓
             response
                 ↓
              parse
                 ↓
             validate
                 ↓
          retry if needed
                 ↓
            NodeResult
   │               │
   └───────┬───────┘
           ↓
    resolve next nodes
           ↓
      compare / merge
           ↓
       consolidate
           ↓
        LLMResult
```

---

# Contrato del módulo

## Entrada

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
├── graph
└── metadata
```

Ejemplo:

```json
{
  "task": "extract_invoice",

  "provider": "ollama",
  "model": "qwen2.5-vl",

  "template": "invoice-extraction.md",

  "document": "ocr/document.md",

  "images": [
    "image/normalized.png"
  ],

  "extra_context": {
    "document_type": "invoice"
  },

  "schema": "invoice.schema.json",

  "options": {
    "temperature": 0,
    "max_tokens": 4096
  },

  "metadata": {
    "document_id": "doc_001",
    "page_number": 1,
    "workflow_run_id": "run_001"
  }
}
```

El módulo no debe modificar la decisión de utilizar:

```text
native_text
OCR
IMAGE
OCR + IMAGE
NATIVE_TEXT + IMAGE
```

Tampoco decide si una imagen debería adjuntarse.

Estas decisiones ya vienen resueltas por el orquestador.

---

# Salida

```text
LLMResult
├── run_id
├── task
├── provider
├── model
├── graph_id
├── node_results{}
├── raw_response
├── parsed_response
├── schema_valid
├── validation_errors[]
├── attempts[]
├── comparisons{}
├── usage
├── timing
├── status
└── metadata
```

Ejemplo:

```json
{
  "run_id": "llm_run_001",

  "task": "extract_invoice",

  "provider": "ollama",
  "model": "qwen2.5-vl",

  "parsed_response": {
    "invoice_number": "0001-12345",
    "date": "2026-09-22",
    "total": 150000
  },

  "schema_valid": true,
  "validation_errors": [],

  "status": "success"
}
```

---

# Identidades internas

Deben distinguirse varios identificadores.

## `run_id`

Identifica una ejecución completa de `procesador-llm-call`.

```text
llm_run_001
```

---

## `graph_id`

Identifica el subgrafo de inferencia utilizado.

```text
invoice_extraction_v3
```

---

## `node_id`

Identifica lógicamente un nodo.

Ejemplo:

```text
classify
extract_a
extract_b
compare
validate
```

---

## `attempt_id`

Identifica una llamada concreta al provider.

```text
extract_a_attempt_01
extract_a_attempt_02
```

Un retry genera un nuevo `attempt_id`.

---

## `request_key`

Identifica determinísticamente una solicitud lógica al modelo.

Conceptualmente:

```text
request_key =
    hash(
        provider
        + model
        + model_version
        + rendered_prompt
        + input_hashes
        + schema_hash
        + normalized_options
    )
```

La regla es:

```text
misma solicitud lógica
        ↓
mismo request_key
```

Esto permite evitar repetir llamadas costosas.

---

# Idempotencia interna

La idempotencia existe en dos niveles.

## Nivel documental

Propiedad del `procesador-orquestador`.

Decide si debe ejecutar nuevamente:

```text
procesador-llm-call
```

completo.

---

## Nivel inferencia

Propiedad de `procesador-llm-call`.

Decide si un nodo interno debe ejecutar nuevamente una llamada.

Ejemplo:

```text
classify      SUCCESS
extract_a     SUCCESS
extract_b     FAILED
compare       NOT_STARTED
validate      NOT_STARTED
```

Al reanudar:

```text
classify      REUSE
extract_a     REUSE
extract_b     EXECUTE
compare       EXECUTE
validate      EXECUTE
```

No deben repetirse:

```text
classify
extract_a
```

si sus resultados siguen siendo válidos.

---

# Regla de idempotencia

> **Una llamada LLM válida no debe ejecutarse nuevamente solo porque el grafo fue reiniciado.**

Debe reutilizarse cuando:

```text
request_key coincide
AND
status == SUCCESS
AND
resultado persistido válido
```

---

# 1. Primitivas

Funciones de bajo nivel que encapsulan providers, SDKs y librerías.

Pueden conocer:

* Ollama;
* APIs compatibles con OpenAI;
* SDKs específicos;
* Pydantic;
* JSON Schema.

No conocen el workflow documental.

---

## Modelos

```text
list_models()
check_model_available(model_name)
get_model_info(model_name)
get_context_window(model_name)
```

---

## Ejecución

```text
generate_text(...)
generate_multimodal(...)
generate_structured(...)
stream_response(...)
```

---

## Payload

```text
build_provider_payload(...)
prepare_image_payload(...)
encode_image_base64(...)
```

---

## Schema

```text
load_schema(...)
validate_schema(...)
parse_json_response(...)
```

---

## Tokens

```text
count_tokens(...)
```

---

## Persistencia

```text
save_llm_response(...)
save_llm_state(...)
load_llm_state(...)
```

Las primitivas no toman decisiones sobre el workflow documental ni sobre qué fuente utilizar.

---

# 2. Procesamiento de una llamada

## `process_llm_request(llm_input)`

Función principal para una inferencia individual.

Debe:

1. validar `LLMInput`;
2. cargar template;
3. procesar variables;
4. preparar documento;
5. preparar imágenes;
6. cargar schema;
7. renderizar prompt;
8. calcular `request_key`;
9. construir mensajes;
10. construir payload;
11. ejecutar provider;
12. capturar respuesta;
13. parsear resultado;
14. validar schema;
15. registrar metadata;
16. devolver `LLMCallResult`.

Flujo:

```text
LLMInput
   ↓
process_template()
   ↓
process_prompt()
   ↓
prepare inputs
   ↓
calculate_request_key()
   ↓
build_messages()
   ↓
execute provider
   ↓
parse response
   ↓
validate
   ↓
LLMCallResult
```

---

# 3. Templates

## `process_template(template_path, context)`

Debe:

* cargar template;
* detectar variables;
* validar variables requeridas;
* renderizar contenido;
* devolver template procesado.

---

## `process_prompt(template, variables, schema=None)`

Debe:

* inyectar variables;
* resolver `<doc>`;
* resolver `<extra>`;
* resolver `<schema>`;
* sanitizar contenido;
* validar variables;
* devolver prompt final.

No debe seleccionar qué documento utilizar.

---

# 4. Inputs textuales

## `process_text_input(text, model, options=None)`

Debe:

* validar contenido;
* normalizar representación;
* contar tokens;
* verificar contexto disponible;
* preparar entrada.

No debe elegir entre:

```text
native_text
OCR
```

Eso ya viene definido por `LLMInput`.

---

# 5. Inputs visuales

## `process_image_input(image_path, model, options=None)`

Debe:

* validar existencia;
* validar formato compatible;
* preparar payload multimodal.

No debe:

* rotar;
* hacer deskew;
* aumentar resolución;
* mejorar contraste;
* comprimir según reglas documentales;
* ejecutar OCR.

La imagen debe llegar preparada.

---

# 6. Nodos LLM

## `process_llm_node(node_config, state)`

Ejecuta un nodo exclusivamente LLM.

Debe:

1. resolver inputs requeridos;
2. construir `LLMInput`;
3. calcular `request_key`;
4. consultar estado previo;
5. decidir:

   * `REUSE`;
   * `EXECUTE`;
   * `FORCE`;
   * `SKIP`.
6. ejecutar cuando corresponda;
7. validar resultado;
8. persistir resultado;
9. actualizar estado local;
10. devolver `LLMNodeResult`.

---

# LLMNodeResult

```text
LLMNodeResult
├── node_id
├── request_key
├── status
├── result
├── attempts[]
├── validation
├── usage
├── timing
└── metadata
```

---

# Estados de nodo

```text
NOT_STARTED
READY
RUNNING
SUCCESS
FAILED
SKIPPED
REUSED
INVALIDATED
PAUSED
```

Deben diferenciarse:

```text
SKIPPED
    = no debía ejecutarse

REUSED
    = existía un resultado válido
```

---

# 7. Grafo LLM

El módulo puede coordinar un **subgrafo de inferencia**.

Ejemplo:

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
   consolidate
```

Este grafo solamente contiene operaciones de inferencia y transformación asociadas a LLM.

Nunca debe contener:

```text
PDF
IMAGE NORMALIZATION
OCR
SOURCE SELECTION
```

---

## `execute_llm_graph(graph, initial_state)`

Debe:

* crear o recuperar `LLMGraphState`;
* resolver dependencias;
* determinar nodos preparados;
* reutilizar resultados válidos;
* ejecutar nodos pendientes;
* permitir ramas;
* permitir paralelización;
* manejar retries internos;
* manejar invalidaciones;
* persistir estado después de cada nodo;
* detenerse limpiamente cuando corresponda;
* consolidar resultado final.

---

# 8. Estado interno del grafo

```text
LLMGraphState
├── run_id
├── graph_id
├── graph_version
├── status
├── current_nodes[]
├── node_states{}
├── node_results{}
├── attempts{}
├── comparisons{}
├── errors[]
├── usage
├── stop_requested
└── final_result
```

Este estado pertenece exclusivamente al módulo LLM.

No reemplaza:

```text
DocumentContext
PageContext
StageExecution
```

del orquestador.

---

# 9. Dependencias

Cada nodo debe declarar dependencias.

Ejemplo:

```text
extract_a ─┐
           ├── compare
extract_b ─┘
```

Conceptualmente:

```yaml
compare:
  depends_on:
    - extract_a
    - extract_b
```

Un nodo solamente puede pasar a:

```text
READY
```

cuando todas sus dependencias requeridas están disponibles.

---

# 10. Invalidación interna

Si cambia o se fuerza un nodo upstream, sus descendientes deben invalidarse.

Ejemplo:

```text
force extract_a
       ↓
extract_a EXECUTE
       ↓
compare INVALIDATED
       ↓
validate INVALIDATED
       ↓
consolidate INVALIDATED
```

Función:

```text
invalidate_downstream_nodes(node_id, state)
```

No debe invalidar:

* OCR;
* ImageResult;
* PDFResult;
* otras etapas documentales.

Eso pertenece al orquestador.

---

# 11. Resume interno

El grafo debe ser reanudable.

## `resume_llm_graph(run_id)`

Debe:

1. cargar estado;
2. validar resultados persistidos;
3. detectar nodos completados;
4. detectar nodos interrumpidos;
5. reconstruir dependencias;
6. continuar exclusivamente desde nodos pendientes.

Ejemplo:

```text
classify       SUCCESS
extract_a      SUCCESS
extract_b      FAILED
compare        NOT_STARTED
validate       NOT_STARTED
```

Resume:

```text
classify       REUSE
extract_a      REUSE
extract_b      EXECUTE
compare        EXECUTE
validate       EXECUTE
```

---

# 12. Stop interno

Una solicitud de stop del orquestador debe poder propagarse al subgrafo.

El procesador debe evitar comenzar nuevas llamadas costosas cuando:

```text
stop_requested = true
```

Flujo:

```text
node A finished
      ↓
stop requested?
      │
     yes
      ↓
persist graph state
      ↓
PAUSED
```

No debe descartar nodos ya completados.

---

# Stop seguro

La regla es:

> **Detener el grafo entre llamadas siempre que sea posible, preservando todos los resultados válidos ya obtenidos.**

Si una llamada al provider ya comenzó:

* puede finalizar;
* puede cancelarse si el provider soporta cancelación segura;
* su resultado solamente se registra como válido si terminó correctamente.

---

# 13. Skip interno

Puede existir skip de nodos exclusivamente dentro del subgrafo LLM.

Ejemplo:

```text
skip_nodes:
    - verifier_b
```

Debe registrarse:

```text
status = SKIPPED
reason = explicit_skip
```

El grafo debe verificar que los nodos downstream toleren esa ausencia.

Un skip no puede romper silenciosamente una dependencia obligatoria.

---

# 14. Force interno

Puede forzarse un nodo específico:

```text
force_nodes:
    - extract_b
```

Aunque exista un resultado válido:

```text
extract_b → EXECUTE
```

Los nodos dependientes deben invalidarse.

```text
extract_b
   ↓
compare
   ↓
validate
```

se convierte en:

```text
extract_b    FORCE / EXECUTE
compare      INVALIDATED
validate     INVALIDATED
```

---

# 15. Dry Run del grafo

Debe poder construirse un plan sin invocar modelos.

Ejemplo:

```text
LLMGraphPlan

classify      REUSE
extract_a     REUSE
extract_b     EXECUTE
compare       EXECUTE
validate      EXECUTE
```

Esto permite conocer antes de ejecutar:

* cantidad de llamadas;
* modelos involucrados;
* nodos reutilizados;
* nodos forzados;
* dependencias invalidadas.

Especialmente útil cuando las inferencias son costosas.

---

# 16. Routing interno

El módulo puede realizar routing exclusivamente entre nodos LLM.

Ejemplo:

```text
classify
   ↓
document_type
   │
   ├── invoice → extract_invoice
   ├── receipt → extract_receipt
   └── unknown → generic_extract
```

Funciones:

```text
select_next_llm_node(...)
evaluate_llm_condition(...)
resolve_llm_branch(...)
```

No debe contener decisiones como:

```text
if page_is_image:
    run_ocr()
```

o:

```text
if native_text_empty:
    select_ocr()
```

---

# 17. Paralelización

El grafo puede ejecutar nodos independientes en paralelo.

Ejemplo:

```text
          classify
             ↓
      ┌──────┴──────┐
      ▼             ▼
 extract_a       extract_b
      │             │
      └──────┬──────┘
             ↓
          compare
```

El procesador debe controlar:

* dependencias;
* concurrencia;
* resultados;
* errores;
* orden lógico.

---

# Claim de nodo

Para impedir ejecuciones duplicadas:

```text
claim_node(node_id)
```

debe realizar una transición atómica:

```text
READY
  ↓
RUNNING
```

Solo un worker puede adquirir un nodo determinado dentro del mismo `run_id`.

Esto evita ejecutar dos veces la misma inferencia costosa por una condición de carrera.

---

# 18. Retry

## `retry_llm_request(...)`

Puede generar un nuevo intento cuando:

* JSON inválido;
* schema inválido;
* faltan campos;
* timeout;
* respuesta incompleta;
* error recuperable de provider;
* regla LLM explícita indica retry.

Cada retry debe mantener:

```text
run_id
node_id
attempt_id
previous_attempt_id
```

---

# Retry vs Re-execution

No deben confundirse.

## Retry

Pertenece a la misma ejecución lógica:

```text
request
   ↓
attempt 1
   ↓
invalid JSON
   ↓
attempt 2
```

---

## Force

Genera una nueva ejecución lógica del nodo:

```text
SUCCESS previo
   ↓
FORCE
   ↓
new execution
```

---

## Resume

Intenta reutilizar el resultado ya existente:

```text
SUCCESS previo
   ↓
RESUME
   ↓
REUSE
```

---

# 19. Historial de attempts

```text
LLMAttempt
├── attempt_id
├── node_id
├── request_key
├── provider
├── model
├── request_metadata
├── raw_response
├── parsed_response
├── validation
├── usage
├── timing
├── error
└── status
```

Los intentos anteriores nunca deben perderse cuando ocurre un retry.

---

# 20. Validación LLM

## `validate_llm_result(result, schema, rules=None)`

Puede validar:

* JSON;
* tipos;
* campos requeridos;
* enumeraciones;
* formatos;
* reglas simples ligadas al resultado de inferencia.

Devuelve:

```text
VALID
INVALID
RETRYABLE
```

No debe evaluar reglas documentales generales que excedan el scope LLM.

---

# 21. Comparación de outputs

## `compare_outputs(outputs, fields=None)`

Puede comparar:

* modelos diferentes;
* prompts diferentes;
* múltiples ejecuciones;
* ramas A/B;
* verificadores.

Puede evaluar:

* igualdad exacta;
* campos;
* números;
* listas;
* estructuras;
* similitud semántica.

Devuelve:

```text
ComparisonResult
├── matches
├── conflicts
├── agreement
└── metadata
```

---

# 22. Consenso

## `calculate_consensus(outputs)`

Puede calcular consenso:

* global;
* por campo;
* por valor.

Ejemplo:

```text
extract_a ─┐
extract_b ─┼── consensus
extract_c ─┘
```

El consenso se limita a outputs de inferencia.

No compara:

```text
native_text vs OCR
OCR vs imagen
OCR vs fuente documental
```

Eso pertenece a la capa documental.

---

# 23. Control de contexto

El módulo es responsable de verificar que la inferencia pueda ejecutarse dentro de la ventana del modelo.

Funciones:

```text
count_tokens()
calculate_available_tokens()
is_context_limit_exceeded()
truncate_to_token_limit()
```

La reducción de contexto debe ser:

* explícita;
* trazable;
* registrada en metadata.

No debe alterar silenciosamente el contenido.

---

# 24. Uso y costo

Cada llamada debe registrar cuando esté disponible:

```text
usage
├── input_tokens
├── output_tokens
├── total_tokens
├── cached_tokens
├── provider_usage
└── estimated_cost
```

Para modelos locales también puede registrar:

```text
timing
├── queue_time
├── load_time
├── inference_time
└── total_time
```

Esto permite al orquestador y a observabilidad conocer el costo real del subgrafo.

---

# 25. Persistencia

Los resultados deberían persistirse por ejecución.

Ejemplo:

```text
llm/
├── run_001/
│   ├── state.json
│   ├── graph.json
│   │
│   ├── classify/
│   │   ├── result.json
│   │   ├── metadata.json
│   │   └── attempts/
│   │
│   ├── extract_a/
│   ├── extract_b/
│   ├── compare/
│   └── final_result.json
```

Esto evita sobrescribir ejecuciones previas y facilita debugging.

---

# Persistencia atómica

Los resultados no deben marcarse como válidos hasta terminar de escribirse.

Ejemplo:

```text
result.json.tmp
      ↓
write
      ↓
validate
      ↓
atomic rename
      ↓
result.json
```

La misma regla debe aplicarse a:

```text
state.json
metadata.json
attempt.json
final_result.json
```

---

# 26. Helpers

## Requests

```text
build_messages()
build_llm_request()

build_run_id()
build_request_id()
build_node_id()
build_attempt_id()

calculate_request_key()
```

---

## Templates

```text
sanitize_prompt_input()
escape_xml_content()

inject_doc()
inject_extra()
inject_schema()

validate_template_variables()
```

---

## Contexto LLM

```text
build_node_context()
merge_contexts()

get_state_value()
set_state_value()
```

---

## Estado

```text
load_llm_state()
save_llm_state()

get_node_state()
set_node_status()

claim_node()
release_node()
```

---

## Resume / Stop

```text
resume_llm_graph()
request_graph_stop()
should_stop_graph()
recover_interrupted_node()
```

---

## Idempotencia

```text
calculate_request_key()
find_reusable_node_result()
validate_cached_result()
is_node_reusable()
```

---

## Dependencias

```text
get_node_dependencies()
get_downstream_nodes()
invalidate_node()
invalidate_downstream_nodes()
```

---

## Tokens

```text
truncate_to_token_limit()
calculate_available_tokens()
is_context_limit_exceeded()
```

---

## Responses

```text
normalize_llm_response()
extract_json_from_response()
is_valid_json()
normalize_structured_output()
```

---

## Comparación

```text
compare_field_values()
calculate_output_similarity()
detect_field_conflicts()
calculate_confidence()
```

---

## Retry

```text
should_retry()
build_retry_context()
increment_attempt()
```

---

## Trazabilidad

```text
append_llm_trace()

build_request_metadata()
build_response_metadata()

write_json()
read_json()
```

---

# 27. Manejo de errores

Los errores deben clasificarse.

Ejemplo:

```text
PROVIDER_ERROR
TIMEOUT
MODEL_UNAVAILABLE
CONTEXT_OVERFLOW
INVALID_RESPONSE
INVALID_JSON
SCHEMA_ERROR
DEPENDENCY_ERROR
INTERNAL_ERROR
```

El módulo debe decidir si el error es:

```text
RETRYABLE
NON_RETRYABLE
```

No debe decidir fallbacks documentales.

---

# Ejemplo correcto

```text
qwen request
    ↓
timeout
    ↓
retry qwen
```

---

# Ejemplo fuera de scope

```text
qwen failed
    ↓
run OCR again
```

La segunda decisión pertenece al orquestador.

---

# 28. Responsabilidades que NO pertenecen a este módulo

Eliminar cualquier lógica relacionada con:

```text
process_document()
process_page()

detect_input_type()

process_pdf()
process_image()
run_ocr()

should_run_ocr()
should_run_vlm()

select_document_source()
select_extraction_strategy()

build_document_context()
consolidate_document_result()
```

También debe evitar:

```text
if page.classification == IMAGE:
    run_ocr()
```

o:

```text
if native_text_empty:
    use_ocr()
```

o:

```text
if ocr_failed:
    use_image()
```

Estas decisiones pertenecen al `procesador-orquestador`.

---

# 29. Separación con procesador-orquestador

## Procesador Orquestador

Decide:

```text
¿Qué procesador ejecutar?

¿Qué fuente utilizar?

¿Necesito OCR?

¿Necesito visión?

¿La etapa LLM debe ejecutarse?

¿La etapa LLM puede reutilizarse?

¿La etapa LLM debe ser forzada?

¿La etapa LLM debe omitirse?

¿Qué hago si falla la etapa LLM completa?

¿Cómo proceso las páginas?

¿Cómo consolido el documento?
```

Produce:

```text
LLMInput
```

---

## Procesador LLM Call

Decide:

```text
¿Cómo ejecuto esta tarea LLM?

¿Qué template renderizo?

¿Cómo construyo mensajes?

¿Cómo construyo el payload?

¿Cómo llamo al provider?

¿Cómo valido el resultado?

¿Debo reintentar esta llamada?

¿Puedo reutilizar este nodo?

¿Qué nodos puedo ejecutar en paralelo?

¿Qué nodo sigue?

¿Qué nodos debo invalidar?

¿Cómo reanudo el subgrafo?

¿Cómo comparo outputs?

¿Cómo consolido el resultado LLM?
```

Produce:

```text
LLMResult
```

---

# 30. Stop / Resume: frontera entre ambos módulos

Esta frontera debe ser explícita.

## Stop del orquestador

Significa:

> No continuar el workflow documental.

Puede propagarse al `procesador-llm-call` activo.

---

## Stop del procesador LLM

Significa:

> No iniciar nuevos nodos LLM y persistir el subgrafo en un estado reanudable.

---

## Resume del orquestador

Determina si la etapa LLM completa debe:

```text
REUSE
o
RESUME
o
EXECUTE
```

---

## Resume del procesador LLM

Si recibe una etapa parcialmente ejecutada:

```text
resume existing LLMRun
```

debe reutilizar los nodos válidos y continuar únicamente con los pendientes.

---

# 31. Skip / Force: frontera entre ambos módulos

## Orquestador

Puede decidir:

```text
SKIP LLM STAGE
FORCE LLM STAGE
```

---

## Procesador LLM

Puede decidir o recibir:

```text
SKIP LLM NODE
FORCE LLM NODE
```

Nunca debe transformar un `FORCE NODE` en decisiones sobre OCR, PDF o imágenes.

---

# 32. Integración

```text
procesador-orquestador
          ↓
       LLMInput
          ↓
 procesador-llm-call
          ↓
     load LLMRun
          ↓
   build graph plan
          ↓
 ┌────────┴─────────┐
 │                  │
REUSE             EXECUTE
nodes              nodes
 │                  │
 └────────┬─────────┘
          ↓
   graph routing
          ↓
 retries / parallel
 compare / consensus
          ↓
      LLMResult
          ↓
procesador-orquestador
```

La interfaz entre ambos módulos debe permanecer explícita.

---

# Independencia del módulo

`procesador-llm-call` debe poder ejecutarse sin el pipeline documental.

Ejemplo:

```text
LLMInput
   ↓
procesador-llm-call
   ↓
LLMResult
```

Esto permite:

* probar modelos;
* probar prompts;
* comparar modelos;
* ejecutar benchmarks;
* evaluar schemas;
* probar retries;
* probar consenso;
* ejecutar grafos LLM;
* probar stop/resume;
* probar caching de nodos;
* cambiar providers;
* ejecutar inferencia sin PDF/OCR.

---

# Regla arquitectónica final

`procesador-llm-call`:

> **Recibe una tarea de inferencia ya preparada y administra su ejecución LLM interna hasta producir un resultado estructurado, validado y trazable.**

Es dueño de:

```text
templates

prompts

providers

model calls

schemas

parsing

retries internos

grafo LLM

routing LLM

estado del grafo LLM

nodos LLM

idempotencia por nodo

resume del grafo LLM

stop del grafo LLM

skip de nodos LLM

force de nodos LLM

invalidación entre nodos LLM

paralelización LLM

comparación

consenso

uso y timing

trazabilidad de inferencia
```

No es dueño de:

```text
workflow documental

PDF

procesamiento de imagen

OCR

selección de fuente documental

decisión OCR/VLM

estado global del documento

idempotencia documental

skip/force de procesadores documentales

consolidación documental
```

En términos simples:

```text
procesador-orquestador
    =
qué trabajo documental hacer
y qué etapas ejecutar

procesador-llm-call
    =
cómo ejecutar eficientemente
la inferencia solicitada
```

La regla operativa fundamental es:

> **No repetir una llamada LLM válida y costosa sin una razón explícita.**

Un nodo LLM debe volver a ejecutarse solamente cuando:

```text
no existe resultado

o

resultado inválido

o

inputs cambiaron

o

prompt cambió

o

schema cambió

o

modelo cambió

o

opciones cambiaron

o

nodo fue invalidado

o

force fue solicitado
```

En cualquier otro caso:

```text
REUSE
```
