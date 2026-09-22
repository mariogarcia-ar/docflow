# idea
Tu idea ordenada cronológicamente quedaría así: 

* **1. Entrada del documento**

  * Recibir PDF o imagen.
  * Identificar el tipo de archivo y derivarlo al pipeline correspondiente.

* **2. Procesamiento PDF**

  * Usar Poppler / `python-poppler`.
  * Dividir el PDF en páginas.
  * Por cada página:

    * generar PDF individual;
    * convertir a imagen;
    * extraer texto preservando layout;
    * extraer imágenes embebidas;
    * determinar si predomina texto o imagen.
  * Permitir volver a unir páginas/PDFs. 

* **3. Procesamiento de imagen**

  * Evaluar nitidez y legibilidad.
  * Detectar si contiene texto.
  * Detectar y corregir rotación.
  * Adecuar resolución.
  * Optimizar formato y peso para procesamiento posterior. 

* **4. OCR**

  * Si la página es imagen o requiere extracción textual, ejecutar OCR con Docling.
  * Obtener el texto/estructura resultante para usarlo como nueva fuente de entrada. 

* **5. Decisor de fuente**

  * Seleccionar qué representación usar:

    * texto nativo del PDF;
    * imagen;
    * texto proveniente del OCR;
    * eventualmente combinación de fuentes.

* **6. Preparación de llamada al LLM**

  * Construir prompt.
  * Adjuntar schema.
  * Adjuntar imagen si corresponde.
  * Inyectar texto/documento y contexto adicional. 

* **7. Ejecución del flujo LLM**

  * Encadenar llamadas, por ejemplo:

    * clasificar documento;
    * extraer campos;
    * validar campos.
  * Representar estas operaciones como un **grafo dirigido**. 

* **8. Validación y comparación**

  * Capturar cada salida.
  * Reutilizarla como entrada de nodos posteriores.
  * Comparar múltiples salidas.
  * Resolver discrepancias, validar y consolidar el resultado final. 

En una línea, el flujo sería:

**Entrada → PDF/Image Processing → OCR → Decisor de fuente → Prompt/Schema → LLM Graph → Comparación/Validación → Resultado final.**

--- 
# refactorizacion 

El problema principal es que hoy los cuatro módulos mezclan responsabilidades: PDF extrae texto e imágenes, Image decide OCR/VLM, OCR decide cómo alimentar al LLM y LLM vuelve a decidir qué fuente usar. Eso genera superposición y riesgo de que cada módulo “orqueste” al siguiente por su cuenta.    

### Recomendación de separación

* **`procesador-pdf`**

  * Foco exclusivo: **estructura física del PDF**.
  * Divide páginas.
  * Renderiza cada página.
  * Extrae texto nativo e imágenes embebidas.
  * Calcula métricas básicas.
  * No debe ejecutar OCR.
  * No debe llamar LLM.
  * No debe decidir workflows posteriores.
  * Su salida debe ser una carpeta de página autocontenida. Actualmente ya está muy cerca de este modelo. 

* **`procesador-image`**

  * Foco exclusivo: **preparación y análisis visual**.
  * Recibe cualquier imagen:

    * imagen nativa;
    * `page.png` proveniente de PDF.
  * Evalúa blur, resolución, orientación, skew, etc.
  * Genera `normalized.png`.
  * Detecta presencia de texto/visual.
  * No ejecuta Docling.
  * No ejecuta LLM.
  * No debería decidir directamente `OCR / VLM / BOTH`; solamente producir metadata que permita a otro componente tomar esa decisión. Hoy `select_image_pipeline()` invade esa responsabilidad. 

* **`procesador-ocr`**

  * Foco exclusivo: **extracción de contenido desde imagen**.
  * Recibe preferentemente `normalized.png`.
  * Ejecuta Docling.
  * Produce:

    * texto;
    * Markdown;
    * tablas;
    * bloques/layout;
    * metadata OCR.
  * No debe decidir si ese contenido va en `<doc>` o `<extra>`.
  * No debe comparar directamente con VLM.
  * Funciones como `compare_ocr_with_vlm()` y `build_llm_context_from_ocr()` deberían salir de este módulo. 

* **`procesador-llm-call`**

  * Foco exclusivo: **ejecutar llamadas LLM**.
  * Recibe inputs ya preparados.
  * Procesa:

    * template;
    * prompt;
    * schema;
    * texto;
    * imágenes;
    * contexto.
  * Ejecuta Ollama/API/VLM.
  * Valida salida estructurada.
  * Compara múltiples respuestas cuando corresponda.
  * No debe abrir una carpeta de página y decidir qué archivo utilizar.
  * `process_page()` debería eliminarse de este módulo. 

### Agregar una quinta capa: `workflow` / `orchestrator`

Esta debería ser la única capa que conozca a todos los módulos.

```text
                 ORCHESTRATOR
                      │
                      ▼
                  input file
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
         PDF                    IMAGE
          │                       │
          ▼                       │
   procesador-pdf                 │
          │                       │
          └───────────┬───────────┘
                      ▼
              procesador-image
                      │
             metadata visual
                      │
                      ▼
                   DECISOR
             ┌────────┼────────┐
             ▼        ▼        ▼
         native      OCR      image
          text        │        │
             │   procesador-ocr│
             │        │        │
             └────────┼────────┘
                      ▼
              prepared input
                      │
                      ▼
             procesador-llm-call
                      │
                      ▼
                   output
```

### Regla fundamental

Cada módulo debería responder solamente:

> **“Recibo X y produzco Y.”**

No:

> **“Recibo X, produzco Y y decido qué otro módulo ejecutar.”**

La orquestación queda afuera.

### Contratos entre módulos

Usaría una estructura común mínima:

```text
PageContext
├── page_id
├── source
│   ├── page.pdf
│   ├── page.png
│   └── embedded_images/
│
├── native_text
│   └── text.txt
│
├── image
│   ├── normalized.png
│   └── metadata.json
│
├── ocr
│   ├── text.txt
│   ├── document.md
│   └── metadata.json
│
└── llm/
```

Así **ningún módulo pisa archivos de otro módulo**.

### Cambios concretos que haría

* `procesador-pdf`

  * Mantener `process_pdf()` y `process_page()`.
  * `process_page()` significa únicamente **procesamiento PDF**.
  * Eliminar cualquier futura dependencia OCR/LLM.

* `procesador-image`

  * Mantener `process_image()`.
  * Renombrar `process_page_image()` → `process_image_from_page()` si necesitás distinguir origen.
  * Eliminar `select_image_pipeline()`.
  * Reemplazarlo por algo como:

    * `analyze_image()`
    * `classify_image()`
  * Solo devuelve metadata. 

* `procesador-ocr`

  * Mantener `process_ocr_image()`.
  * `process_ocr_page()` puede ser simplemente un wrapper que recibe el path de la imagen.
  * Eliminar:

    * `process_ocr_pdf()`;
    * `compare_ocr_with_native_text()`;
    * `compare_ocr_with_vlm()`;
    * `build_llm_context_from_ocr()`.
  * Esas son tareas de orquestación/comparación, no OCR.  

* `procesador-llm-call`

  * Eliminar `process_page()`.
  * Mantener:

    * `process_prompt()`;
    * `process_template()`;
    * `process_schema()`;
    * `process_llm_request()`;
    * `process_llm_node()`;
    * comparación/retry.
  * `execute_workflow()` podría quedar acá solo si se refiere exclusivamente al **grafo LLM**; no al workflow documental completo. 

### Estructura final recomendada

```text
processors/
├── pdf/
│   ├── primitives
│   ├── utils
│   └── helpers
│
├── image/
│   ├── primitives
│   ├── utils
│   └── helpers
│
├── ocr/
│   ├── primitives
│   ├── utils
│   └── helpers
│
├── llm/
│   ├── primitives
│   ├── utils
│   └── helpers
│
└── workflow/
    ├── process_document()
    ├── process_page()
    ├── select_source()
    ├── select_extraction_strategy()
    ├── build_llm_input()
    └── execute_document_workflow()
```

La clave sería que **solo `workflow/process_page()` tenga el nombre y la responsabilidad global de procesar una página**. Los demás deberían usar nombres explícitos como `process_pdf_page`, `process_image`, `process_ocr_image` y `process_llm_node`.

Eso mantiene independencia de cada librería, pero les da un **contrato común y una única capa de coordinación**, evitando tanto archivos pisados como dependencias circulares.
