# Procesador de Llamadas LLM

## Objetivo

El módulo `procesador-llm-call` tiene como responsabilidad exclusiva **preparar, ejecutar, validar y encadenar llamadas a modelos LLM/VLM**.

Recibe información ya preparada por el `procesador-orquestador` y la transforma en una o varias solicitudes al modelo.

Este módulo **no decide qué fuente documental utilizar**, **no procesa PDFs**, **no normaliza imágenes**, **no ejecuta OCR** y **no coordina el workflow documental completo**.

Su responsabilidad empieza cuando recibe un `LLMInput` ya definido y termina cuando devuelve un `LLMResult`.

---

# Principio de diseño

`procesador-llm-call` debe responder:

> **“Dada una tarea LLM ya definida, ¿cómo la ejecuto de forma estructurada, validada y trazable?”**

No debe responder:

> **“¿Qué debo hacer con esta página?”**

Esa decisión pertenece al `procesador-orquestador`.

---

# Flujo principal

* Recibir una tarea LLM preparada.
* Cargar:

  * modelo;
  * provider;
  * template;
  * variables;
  * texto;
  * imágenes;
  * contexto adicional;
  * schema.
* Renderizar el prompt.
* Preparar el payload.
* Ejecutar la llamada.
* Capturar la respuesta.
* Parsear salida.
* Validar contra schema.
* Registrar metadata.
* Aplicar retry cuando corresponda.
* Permitir encadenar múltiples llamadas LLM.
* Permitir ejecutar llamadas en paralelo.
* Comparar outputs cuando el workflow LLM lo requiera.
* Devolver resultado estructurado al orquestador.

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
  }
}
```

El módulo no debe modificar la decisión de usar:

```text
document = native_text
```

o:

```text
document = OCR
```

ni decidir si la imagen debe adjuntarse.

Eso ya viene resuelto por el orquestador.

---

# Salida

```text
LLMResult
├── run_id
├── task
├── provider
├── model
├── raw_response
├── parsed_response
├── schema_valid
├── validation_errors[]
├── attempts[]
├── usage
├── timing
├── status
└── metadata
```

Ejemplo:

```json
{
  "run_id": "llm_001",
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

# 1. Primitivas

Funciones de bajo nivel que encapsulan librerías y proveedores externos.

Pueden conocer:

* `ollama`;
* APIs compatibles con OpenAI;
* SDKs específicos;
* `pydantic`;
* JSON Schema.

## Modelos

* `list_models()`
* `check_model_available(model_name)`
* `get_model_info(model_name)`
* `get_context_window(model_name)`

## Ejecución

* `generate_text(model, messages, options=None)`
* `generate_multimodal(model, messages, images, options=None)`
* `generate_structured(model, messages, schema, options=None)`
* `stream_response(model, messages, options=None)`

## Payload

* `build_provider_payload(messages, images=None, schema=None, options=None)`
* `prepare_image_payload(image_path)`
* `encode_image_base64(image_path)`

## Schema

* `load_schema(path)`
* `validate_schema(data, schema)`
* `parse_json_response(response)`

## Tokens

* `count_tokens(model, content)`

## Persistencia

* `save_llm_response(response, output_path)`

Las primitivas conocen el proveedor, pero no conocen el workflow documental.

---

# 2. Utilitarios

## `process_llm_request(llm_input)`

Función principal del módulo.

Debe:

* validar `LLMInput`;
* cargar template;
* procesar variables;
* preparar texto;
* preparar imágenes;
* cargar schema;
* construir mensajes;
* construir payload;
* ejecutar modelo;
* capturar respuesta;
* parsear salida;
* validar schema;
* registrar metadata;
* devolver `LLMResult`.

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
build_messages()
   ↓
execute model
   ↓
parse response
   ↓
validate schema
   ↓
LLMResult
```

---

## `process_prompt(template, variables, schema=None)`

Debe:

* inyectar variables;
* resolver `<doc>`;
* resolver `<extra>`;
* resolver `<schema>`;
* sanitizar contenido;
* validar variables requeridas;
* devolver prompt final.

No debe seleccionar qué documento utilizar.

---

## `process_template(template_path, context)`

Debe:

* cargar template;
* detectar variables;
* validar variables requeridas;
* renderizar contenido;
* devolver template procesado.

---

## `process_schema(schema_path, response)`

Debe:

* cargar schema;
* extraer JSON;
* parsear respuesta;
* validar tipos;
* validar campos;
* devolver errores si corresponde.

---

## `process_text_input(text, model, options=None)`

Debe:

* normalizar contenido;
* contar tokens;
* validar tamaño;
* controlar límite de contexto;
* preparar entrada textual.

No debe seleccionar entre texto PDF u OCR.

---

## `process_image_input(image_path, model, options=None)`

Debe:

* validar existencia;
* validar formato compatible;
* preparar payload multimodal.

No debe:

* rotar;
* hacer deskew;
* redimensionar;
* mejorar calidad;
* ejecutar OCR.

La imagen ya debe llegar preparada.

---

# 3. Nodos LLM

## `process_llm_node(node_config, state)`

Ejecuta un nodo dentro de un grafo exclusivamente LLM.

Debe:

* obtener inputs del estado LLM;
* construir `LLMInput`;
* llamar a `process_llm_request()`;
* almacenar resultado en estado local;
* devolver resultado del nodo.

Ejemplo:

```text
classify_document
      ↓
LLMResult
```

---

# 4. Grafo LLM

El módulo puede coordinar un **subgrafo de inferencia LLM**.

Ejemplo:

```text
classify
   ↓
 ┌─┴─────────┐
 ▼           ▼
extract_a  extract_b
 └────┬──────┘
      ↓
   compare
      ↓
   validate
      ↓
 consolidate
```

Este grafo solo contiene operaciones relacionadas con LLM.

---

## `execute_llm_graph(graph, initial_state)`

Debe:

* inicializar estado LLM;
* ejecutar nodos;
* resolver dependencias;
* permitir ramas;
* ejecutar nodos en paralelo;
* capturar resultados;
* finalizar cuando el grafo termina.

No debe ejecutar:

```text
PDF → Image → OCR
```

Ese flujo pertenece al orquestador documental.

---

# 5. Routing interno del grafo LLM

El módulo puede tener routing interno, pero exclusivamente entre nodos LLM.

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

Funciones posibles:

* `select_next_llm_node(node_result, routing_rules)`
* `evaluate_llm_condition(condition, state)`
* `resolve_llm_branch(node_result, graph)`

No debe contener decisiones como:

```text
if page_is_image:
    run_ocr()
```

---

# 6. Comparación de outputs

## `compare_outputs(outputs, fields=None)`

Compara resultados de múltiples llamadas LLM.

Puede evaluar:

* igualdad exacta;
* campos;
* números;
* listas;
* estructuras JSON;
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

## `calculate_consensus(outputs)`

Calcula acuerdo entre:

* modelos distintos;
* prompts distintos;
* múltiples ejecuciones.

Puede calcular consenso:

* global;
* por campo;
* por valor.

No compara:

* texto nativo vs OCR;
* OCR vs imagen;
* fuentes documentales.

Eso pertenece a una capa superior.

---

# 7. Retry

## `retry_llm_request(request, validation_errors, retry_config)`

Debe poder ejecutar un nuevo intento cuando:

* el JSON es inválido;
* falla el schema;
* faltan campos;
* existe timeout;
* la respuesta está incompleta;
* una regla LLM explícita indica retry.

Debe conservar trazabilidad del intento anterior.

---

## Scope del retry

Este módulo puede hacer:

```text
LLM call
   ↓
schema invalid
   ↓
retry LLM call
```

No debe hacer:

```text
OCR falló
   ↓
usar VLM
```

Ese fallback pertenece al orquestador.

---

# 8. Validación LLM

## `validate_llm_result(result, schema, rules=None)`

Puede validar:

* estructura JSON;
* tipos;
* campos requeridos;
* enumeraciones;
* formatos;
* reglas simples asociadas al resultado LLM.

Debe devolver:

```text
VALID
INVALID
RETRYABLE
```

Las reglas de negocio documentales generales pueden mantenerse en otra capa si exceden el alcance de la inferencia.

---

# 9. Estado interno

El módulo puede mantener un estado propio para el grafo LLM.

Ejemplo:

```text
LLMGraphState
├── graph_id
├── current_nodes[]
├── node_results{}
├── attempts{}
├── comparisons{}
├── errors[]
└── final_result
```

Este estado debe permanecer encapsulado.

No debe reemplazar:

```text
DocumentContext
PageContext
```

del orquestador.

---

# 10. Helpers

## Requests

* `build_messages(system, user, images=None)`
* `build_llm_request(model, messages, schema=None)`
* `build_request_id()`
* `build_node_id()`

## Templates

* `sanitize_prompt_input(text)`
* `escape_xml_content(text)`
* `inject_doc(template, document)`
* `inject_extra(template, extra)`
* `inject_schema(template, schema)`
* `validate_template_variables(template, variables)`

## Contexto LLM

* `build_node_context(state, required_fields)`
* `merge_contexts(*contexts)`
* `get_state_value(state, key)`
* `set_state_value(state, key, value)`

## Tokens

* `truncate_to_token_limit(content, max_tokens)`
* `calculate_available_tokens(model, prompt_tokens)`
* `is_context_limit_exceeded(model, content)`

## Responses

* `normalize_llm_response(response)`
* `extract_json_from_response(response)`
* `is_valid_json(value)`
* `normalize_structured_output(data)`

## Comparación

* `compare_field_values(value_a, value_b)`
* `calculate_output_similarity(output_a, output_b)`
* `detect_field_conflicts(outputs)`
* `calculate_confidence(outputs)`

## Retry

* `should_retry(validation_result, retry_config)`
* `build_retry_context(errors, previous_output)`
* `increment_attempt(metadata)`

## Trazabilidad

* `build_run_id()`
* `append_llm_trace(event)`
* `build_request_metadata(request)`
* `build_response_metadata(response)`
* `write_json(path, data)`
* `read_json(path)`

---

# Responsabilidades que NO pertenecen a este módulo

Eliminar cualquier función o lógica relacionada con:

```text
process_document()
process_page()

detect_input_type()

process_pdf()
process_image()
run_ocr()

should_run_ocr()
should_run_vlm()

select_source()
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

Estas decisiones pertenecen al `procesador-orquestador`.

---

# Separación con `procesador-orquestador`

## Procesador Orquestador

Decide:

```text
¿Qué procesador ejecutar?
¿Qué fuente utilizar?
¿Necesito OCR?
¿Necesito VLM?
¿Qué hago si un procesador falla?
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
¿Cómo construyo el payload?
¿Cómo valido el schema?
¿Debo reintentar esta llamada?
¿Qué nodo LLM sigue dentro del grafo?
¿Cómo comparo múltiples outputs LLM?
```

Produce:

```text
LLMResult
```

---

# Integración

```text
procesador-orquestador
          ↓
       LLMInput
          ↓
procesador-llm-call
          ↓
      LLM Graph
          ↓
       LLMResult
          ↓
procesador-orquestador
```

La interfaz entre ambos debe ser explícita.

El orquestador no necesita conocer detalles como:

* formato específico de Ollama;
* mensajes del proveedor;
* parsing del JSON;
* retries de inferencia;
* estructura interna del grafo LLM.

Y `procesador-llm-call` no necesita conocer:

* páginas;
* PDF;
* OCR;
* selección de fuentes;
* estrategia documental.

---

# Independencia del módulo

Debe poder ejecutarse sin el resto del pipeline.

Ejemplo:

```text
LLMInput
   ↓
procesador-llm-call
   ↓
LLMResult
```

Esto permite:

* testear modelos independientemente;
* probar prompts;
* comparar modelos;
* ejecutar benchmarks;
* cambiar Ollama por otro proveedor;
* probar schemas;
* ejecutar workflows LLM sin documentos PDF.

---

# Regla arquitectónica final

`procesador-llm-call`:

> **Recibe una tarea LLM preparada y devuelve un resultado LLM estructurado.**

Puede orquestar **nodos LLM entre sí**.

No puede orquestar **procesadores documentales**.

En términos simples:

```text
procesador-orquestador
    = qué hacer

procesador-llm-call
    = cómo ejecutar la inferencia
```
