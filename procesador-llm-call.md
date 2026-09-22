# flujo principal
* Definir cada llamada a LLM como un **nodo estándar** con entrada, procesamiento y salida estructurada.
* Cada nodo debe soportar:

  * prompts parametrizados;
  * texto;
  * imágenes;
  * contexto adicional;
  * esquema de salida JSON tipado.
* Implementar un **motor de templates** para inyectar dinámicamente:

  * `<doc>` → contenido principal;
  * `<extra>` → contexto adicional;
  * `<schema>` → estructura esperada de salida.
* Sanitizar y escapar el contenido inyectado para evitar que el documento rompa la estructura del prompt.
* Modelar el flujo como un **grafo/DAG** compuesto por nodos de:

  * clasificación;
  * extracción;
  * validación;
  * comparación;
  * consolidación.
* Permitir **enrutamiento condicional** según la salida de cada nodo.
* Permitir ejecutar **múltiples modelos o prompts en paralelo** sobre la misma entrada.
* Comparar resultados mediante:

  * consenso;
  * validaciones de esquema;
  * reglas de negocio;
  * análisis de discrepancias.
* Si existen diferencias o baja confianza, ejecutar:

  * retry;
  * nueva extracción;
  * nodo validador;
  * revisión manual.
* Persistir cada salida en el **estado del grafo** para que pueda ser utilizada por nodos posteriores.
* Mantener trazabilidad completa de:

  * prompt utilizado;
  * modelo;
  * input;
  * output;
  * validaciones;
  * retries;
  * decisión final.
* Flujo general: **entrada → template → LLM → salida estructurada → validación → comparación → decisión → resultado final**.

# funciones 
Podés mantener la misma arquitectura en **tres capas: primitivas, utilitarios y helpers**, pero ahora aplicada a la capa LLM/orquestación.

### 1. Primitivas

Funciones de bajo nivel que encapsulan `ollama`, SDKs de LLM, `pydantic`, motores de templates, etc.

* `load_model(model_name)`
* `check_model_available(model_name)`
* `list_models()`
* `generate_text(model, prompt, options=None)`
* `generate_multimodal(model, prompt, images, options=None)`
* `generate_structured(model, prompt, schema, options=None)`
* `stream_response(model, prompt, options=None)`
* `embed_text(model, text)`
* `count_tokens(model, content)`
* `load_prompt_template(path)`
* `render_template(template, variables)`
* `load_schema(path)`
* `validate_schema(data, schema)`
* `parse_json_response(response)`
* `encode_image_base64(image_path)`
* `prepare_image_payload(image_path)`
* `save_llm_response(response, path)`

### 2. Utilitarios

Funciones que combinan primitivas y representan operaciones completas del pipeline.

* `process_prompt(template, variables, schema=None)`

  * carga template;
  * inyecta variables;
  * sanitiza contenido;
  * agrega schema;
  * genera prompt final.

* `process_template(template_path, context)`

  * resuelve `<doc>`, `<extra>`, `<schema>` y otras variables.

* `process_schema(schema_path, response)`

  * carga el schema;
  * parsea respuesta;
  * valida tipos y campos;
  * devuelve errores si corresponde.

* `process_image_input(image_path, model)`

  * valida imagen;
  * adapta formato;
  * prepara payload multimodal.

* `process_text_input(text, model)`

  * normaliza contenido;
  * controla tamaño/tokens;
  * prepara payload textual.

* `process_llm_request(request)`

  * arma prompt;
  * prepara texto/imágenes;
  * selecciona modelo;
  * ejecuta llamada;
  * valida salida;
  * registra metadata.

* `process_llm_node(node_config, state)`

  * obtiene inputs desde el estado;
  * procesa template;
  * ejecuta modelo;
  * valida schema;
  * persiste resultado.

* `process_page(page_dir, workflow)`

  * lee `metadata.json`;
  * selecciona `text.txt`, `page.png` o ambos;
  * ejecuta los nodos correspondientes;
  * almacena resultados.

* `classify_document(page_data)`

  * ejecuta nodo clasificador.

* `extract_document_data(page_data, schema)`

  * ejecuta nodo extractor.

* `validate_extraction(extraction, rules)`

  * valida salida con schema y reglas de negocio.

* `compare_outputs(outputs)`

  * compara resultados de múltiples modelos/prompts.

* `calculate_consensus(outputs)`

  * determina coincidencias y discrepancias.

* `retry_llm_request(request, errors)`

  * crea nuevo intento utilizando errores/contexto anterior.

* `select_next_node(node_result, routing_rules)`

  * implementa el routing condicional.

* `execute_workflow(workflow, initial_state)`

  * ejecuta el grafo completo.

### 3. Helpers

Funciones pequeñas y reutilizables.

* `build_messages(system, user, images=None)`
* `build_llm_request(model, messages, schema=None)`
* `build_node_context(state, required_fields)`
* `merge_contexts(*contexts)`
* `sanitize_prompt_input(text)`
* `escape_xml_content(text)`
* `inject_doc(template, document)`
* `inject_extra(template, extra)`
* `inject_schema(template, schema)`
* `truncate_to_token_limit(content, max_tokens)`
* `calculate_available_tokens(model, prompt_tokens)`
* `normalize_llm_response(response)`
* `extract_json_from_response(response)`
* `is_valid_json(value)`
* `compare_field_values(value_a, value_b)`
* `calculate_output_similarity(output_a, output_b)`
* `detect_field_conflicts(outputs)`
* `calculate_confidence(outputs)`
* `should_retry(validation_result)`
* `build_retry_context(errors, previous_output)`
* `build_run_id()`
* `build_node_id()`
* `write_json(path, data)`
* `read_json(path)`
* `append_trace(trace_path, event)`

Conceptualmente:

```text
process_page()
      ↓
select input
(text / image / both)
      ↓
process_llm_node()
      ↓
process_prompt()
      ↓
template + doc + extra + schema
      ↓
LLM primitive
(Ollama / API / VLM)
      ↓
process_schema()
      ↓
validate_extraction()
      ↓
compare_outputs()
      ↓
consensus / retry / route
      ↓
next node
```

La regla de separación sería la misma que venís usando: **las primitivas conocen Ollama y los SDKs; los utilitarios conocen el flujo LLM y documental; los helpers resuelven transformación, validación, contexto y trazabilidad.**
