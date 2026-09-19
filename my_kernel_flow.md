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

