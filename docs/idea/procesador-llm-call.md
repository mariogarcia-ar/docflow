# Procesador de Llamadas LLM

## Objetivo

El módulo `procesador-llm-call` tiene como responsabilidad exclusiva **preparar, ejecutar y validar llamadas a modelos LLM/VLM**.

Debe recibir entradas ya preparadas por otros módulos y transformarlas en solicitudes estructuradas al modelo.

Este módulo **no procesa PDFs**, **no normaliza imágenes**, **no ejecuta OCR** y **no decide qué fuente documental usar**. Esa coordinación pertenece al `workflow/orchestrator`.

---

# Flujo principal

* Recibir una solicitud LLM ya definida.
* Preparar:

  * prompt;
  * template;
  * variables;
  * texto;
  * imágenes;
  * contexto adicional;
  * schema de salida.
* Construir el payload requerido por el proveedor.
* Ejecutar la llamada al modelo.
* Capturar:

  * respuesta;
  * metadata;
  * tokens;
  * tiempo;
  * errores.
* Parsear la salida.
* Validar la respuesta contra el schema esperado.
* Persistir el resultado.
* Permitir reutilizar la salida como entrada de otro nodo.
* Permitir:

  * retries;
  * comparación de resultados;
  * múltiples modelos;
  * múltiples prompts;
  * ejecución paralela.
* Mantener trazabilidad completa de cada llamada.

---

# Contrato del módulo

## Entrada

El módulo debería recibir una estructura similar a:

```text id="5ybng9"
LLMRequest
├── model
├── provider
├── template
├── variables
├── text
├── images[]
├── extra_context
├── schema
├── options
└── metadata
```

Ejemplo conceptual:

```json id="haipcc"
{
  "provider": "ollama",
  "model": "qwen2.5-vl",

  "template": "extract_invoice",

  "variables": {
    "doc": "document.md",
    "extra": "business_rules.json"
  },

  "images": [
    "normalized.png"
  ],

  "schema": "invoice.schema.json",

  "options": {
    "temperature": 0,
    "max_tokens": 4096
  }
}
```

---

## Salida

```text id="8f8k2a"
LLMResult
├── request_id
├── model
├── provider
├── raw_response
├── parsed_response
├── schema_valid
├── validation_errors[]
├── usage
├── timing
├── status
└── metadata
```

Ejemplo:

```json id="f84h0c"
{
  "request_id": "run_001",

  "model": "qwen2.5-vl",
  "provider": "ollama",

  "parsed_response": {
    "document_type": "invoice",
    "invoice_number": "0001-12345"
  },

  "schema_valid": true,

  "validation_errors": [],

  "status": "success"
}
```

---

# 1. Primitivas

Funciones de bajo nivel que encapsulan proveedores y librerías externas como:

* `ollama`;
* APIs compatibles con OpenAI;
* SDKs específicos;
* `pydantic`;
* JSON Schema.

## Modelos

* `list_models()`
* `check_model_available(model_name)`
* `get_model_info(model_name)`

## Llamadas

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

## Tokens / modelo

* `count_tokens(model, content)`
* `get_context_window(model)`

## Persistencia básica

* `save_llm_response(response, path)`

Las primitivas deben conocer el proveedor, pero no el flujo documental completo.

---

# 2. Utilitarios

Funciones que combinan primitivas y representan operaciones completas de la capa LLM.

## `process_prompt(template, variables, schema=None)`

Responsable de construir el prompt final.

Debe:

* cargar template;
* resolver variables;
* inyectar `<doc>`;
* inyectar `<extra>`;
* inyectar `<schema>`;
* sanitizar contenido;
* validar variables requeridas;
* devolver el prompt final.

---

## `process_template(template_path, context)`

Debe:

* cargar el template;
* identificar variables;
* verificar variables faltantes;
* renderizar el contenido;
* devolver el template hidratado.

---

## `process_schema(schema_path, response)`

Debe:

* cargar schema;
* extraer JSON;
* parsear respuesta;
* validar tipos;
* validar campos requeridos;
* devolver:

  * resultado;
  * errores;
  * estado de validación.

---

## `process_text_input(text, model, options=None)`

Prepara texto para una llamada LLM.

Debe:

* normalizar contenido;
* verificar tamaño;
* contar tokens;
* truncar o rechazar según configuración;
* devolver representación lista para el request.

---

## `process_image_input(image_path, model, options=None)`

Prepara una imagen ya normalizada.

Debe:

* validar existencia;
* validar formato soportado por el modelo;
* generar payload;
* devolver representación multimodal.

No debe:

* rotar;
* redimensionar;
* mejorar;
* aplicar OCR.

Eso pertenece a otros módulos.

---

## `process_llm_request(request)`

Función central del módulo.

Debe:

* validar `LLMRequest`;
* procesar template;
* preparar texto;
* preparar imágenes;
* cargar schema;
* construir mensajes;
* construir payload;
* ejecutar modelo;
* capturar respuesta;
* parsear salida;
* validar schema;
* persistir metadata;
* devolver `LLMResult`.

Flujo:

```text id="v54b1x"
LLMRequest
     ↓
process_prompt()
     ↓
prepare inputs
     ↓
build messages
     ↓
LLM primitive
     ↓
parse response
     ↓
validate schema
     ↓
LLMResult
```

---

## `process_llm_node(node_config, state)`

Ejecuta una llamada LLM dentro de un grafo.

Debe:

* leer inputs requeridos desde `state`;
* construir `LLMRequest`;
* llamar a `process_llm_request()`;
* almacenar la salida en `state`;
* devolver el resultado del nodo.

No debe decidir qué página, OCR o texto nativo debe procesarse.

Ese input debe venir ya definido por el orquestador.

---

## `compare_outputs(outputs, fields=None)`

Compara salidas de múltiples llamadas.

Puede comparar:

* igualdad exacta;
* campos individuales;
* valores numéricos;
* estructura JSON;
* similitud semántica cuando corresponda.

Devuelve:

```text id="jbyzu1"
ComparisonResult
├── matches
├── conflicts
├── agreement
└── metadata
```

---

## `calculate_consensus(outputs)`

Calcula acuerdo entre múltiples salidas.

Puede trabajar:

* por documento;
* por campo;
* por valor.

No debe decidir acciones de negocio posteriores.

Solo devuelve métricas de consenso.

---

## `retry_llm_request(request, validation_errors, retry_config)`

Permite repetir una llamada cuando:

* el JSON es inválido;
* falla el schema;
* faltan campos;
* existe una condición explícita de retry.

Debe generar un nuevo request conservando trazabilidad del intento anterior.

---

## `execute_llm_graph(graph, initial_state)`

Ejecuta únicamente el **subgrafo LLM**.

Puede contener nodos como:

```text id="9dsy7v"
classify
   ↓
extract_a ─┐
           ├─ compare
extract_b ─┘
           ↓
validate
           ↓
consolidate
```

Este grafo conoce:

* prompts;
* modelos;
* schemas;
* resultados LLM.

No conoce:

* procesamiento PDF;
* procesamiento de imagen;
* OCR;
* estructura física de páginas.

---

# 3. Helpers

Funciones pequeñas y reutilizables.

## Mensajes y requests

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

## Contexto

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
* `append_trace(trace_path, event)`
* `build_request_metadata(request)`
* `build_response_metadata(response)`
* `write_json(path, data)`
* `read_json(path)`

---

# Responsabilidades que NO pertenecen a este módulo

Eliminar del alcance cualquier función similar a:

```text id="h7ypgh"
process_page()
process_pdf()
process_document()
run_ocr()
normalize_image()
select_document_source()
select_ocr_or_vlm()
```

Tampoco debe hacer:

```text id="pnp56a"
if page.type == IMAGE:
    run_ocr()
```

Esa lógica pertenece al orquestador.

---

# Separación entre Orquestador y LLM Graph

Es importante distinguir los dos niveles.

## Workflow documental

Responsabilidad del orquestador:

```text id="qdaglg"
PDF
 ↓
page
 ↓
image
 ↓
OCR
 ↓
selección de fuente
 ↓
LLM
```

## Workflow LLM

Responsabilidad de `procesador-llm-call`:

```text id="ub2s0y"
Prepared Input
      ↓
 classify
      ↓
 ┌────┴────┐
 ▼         ▼
extract_A extract_B
 └────┬────┘
      ↓
   compare
      ↓
   validate
      ↓
   result
```

El segundo puede existir independientemente del primero.

---

# Integración con el sistema

El orquestador prepara algo como:

```text id="ry4bif"
PreparedDocumentInput
├── document
├── images[]
├── extra_context
└── metadata
```

y lo transforma en:

```text id="df45ou"
LLMRequest
```

A partir de ahí:

```text id="crwzgu"
ORCHESTRATOR
      ↓
prepared input
      ↓
procesador-llm-call
      ↓
LLM Graph
      ↓
LLMResult
      ↓
ORCHESTRATOR
```

---

# Principio de diseño

`procesador-llm-call` debe cumplir una regla simple:

> **Recibe información preparada, ejecuta una o varias operaciones LLM y devuelve resultados estructurados y trazables.**

No conoce Poppler.

No conoce Docling.

No procesa imágenes con OpenCV.

No decide qué representación del documento utilizar.

No coordina el pipeline documental.

Sí puede conocer y orquestar un **grafo interno de llamadas LLM**, porque esa es parte de su responsabilidad específica.
