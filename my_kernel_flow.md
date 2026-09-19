# Kernels: primitivas reutilizables

**Concepto base:** primitivas usables por componentes/pipelines, cada una ejecutable también por línea de comandos para poder probarlas de forma aislada antes de integrarlas.

## 1. `pdf`
- Cortar el PDF en páginas.
- Determinar si la página es predominantemente texto o imagen.
- Si es texto → extraer con `pdftotext --layout` y guardar en archivo.
- Si es imagen → exportar la página como imagen para su posterior OCR.

## 2. `imagenes`
- Redimensionar (por DPI y tamaño).
- Recortar.
- Validar legibilidad.

## 3. `ocr`
- Tomar una imagen y extraer el texto a un archivo, preservando el layout lo más posible.

## 4. `llm.local`
- Modelos sin visión: enviar el texto extraído por OCR + prompt para extraer campos.
- Modelos con visión: enviar la imagen correspondiente + prompt para extraer campos directamente.

## 5. `llm.frontier`
- Enviar la imagen + prompts de mayor nivel para extraer campos.
- Opcionalmente, enviar también el resultado de `llm.local` junto con la imagen original, para que evalúe la eficacia de esa extracción.

## 6. `orquestado`
- Toma una carpeta como entrada.
- Por cada archivo, determina el tipo: imagen / PDF / no válido.
  - Si es no válido → **TODO:** convertirlo a PDF.
- Valida el archivo según su tipo:
  - Si es imagen → determinar legibilidad.
  - Si es PDF → determinar si está protegido por password (y si es legible).
- Procesa según tipo:
  - Si es PDF → extrae texto a `.txt` o exporta a imagen (según corresponda).
  - Si es imagen → aplica `ocr` y guarda la extracción en `.txt`.
- Realiza una validación de contenido (texto/imagen) para determinar si el documento es procesable — por ejemplo, si el texto extraído no corresponde al tipo de documento esperado, se salta el proceso.
- Con el resultado, llama a `llm.local` para extraer los campos.
- **Replica la estructura de carpetas de entrada en la salida**, generando los `.txt`/`.json` resultantes en la ruta espejo correspondiente, para permitir comparación directa (input vs. output, y output entre distintas corridas).

## 7. `hitl`
- Usa `llm.frontier` para tomar la salida de `llm.local` y evaluar la calidad de la extracción.
- Al apoyarse en la misma estructura espejo, puede comparar fácilmente el `.json`/`.txt` de `llm.local` contra el de `llm.frontier` para el mismo archivo.