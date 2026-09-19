revisar que introducimos y rompimos ocn el modelo 

cli > kernel > port > adapter 

revisar sobreingenieria, usar tavily para identificar si una funcionalidad ya existe: 
hay muchas cosas que lo resuelven utilitarios de linux , python, u otras librerias


un cliente echo con python o similar 
un cli deberia tener 
entrada > proceso > salida 

---


**Kernels and methods (from `quickstart`)**

- **K1 `orchestrator`** — `plan`, `run`, `status`, `jobs`, `pause`, `resume`, `stop`, `ledger-read`, `manifest-rebuild`
- **K2 `pdf`** — `probe`, `classify`, `tokens`, `render`, `split` · adapter-only: `effective_dpi`, `layout_text`
- **K3 `image`** — `info`, `load`, `legibility`, `rescale`, `crop`
- **K4 `ocr`** — `capabilities`, `engine_info`, `read` · adapter-only: `layout`
- **K5 `llm.local`** — `capabilities`, `warm`, `structured`, `vision`, `judge`
- **K6 `llm.frontier`** — `capabilities`, `warm`, `structured`, `vision`, `judge`
- **K7 `store`** — `put`, `get`, `verify`, `ls`, `ledger-read`, `manifest-rebuild`
- **K8 `registry`** — `validate`, `hash`, `show`, `ls`
- **Bench (`docflow-kernel`)** — `--list`, `<kernel> <operation> [flags]`, `--repeat N`
- **Declared but not implemented (exit `4`)** — `pdf facts`, `pdf images`, `image deskew`, `image phash`, `image tile`, `llm.local ps`, `llm.local pull`, `llm.local generate`, `llm.frontier judge`, `llm.frontier count-tokens`



La idea de los kernels es tener una primitivas que luego seran usadas por componentes y pipelines.
Los mismos deben de ser usable desde linea de comandos para realizar pruebas antes de avanzar.
Los kernels son necesario:
- pdf: cortar en paginas los pdf, determinar si son mas texto que imagenes, si son mas textos que imagenes usar pdftotext --layout para obtener el texto y guardarlo en un archivo, si es una imagen poder exportarla a imagen para su posterior tratamiento con ocr de imagenes

- imagenes: redimensionarlas por dpi y size, recortarlas, validar su legibilidad

- ocr: tomar una imagen y extraer su texto en un archivo respetando lo mas posible el layout del mismo

- llm.local: modelos no de vison le envio un prompt con el texto extraido del ocr para extraer campos , para modelos de vision le envio la imagen adecuada con prompts para que extraingan los valores de los campos 

- llm.frontier: envio la imagen adecuada con prompts de mas alto nivel para extrear los campos, puedo tambien enviarle el resultado del llm.local en conjunto a la imagen original para que analizce la eficacia 



---

add cli examples to 
docs/quickstart/kernel-image.md
docs/quickstart/kernel-pdf.md

docs/quickstart/kernel-ocr.md
docs/quickstart/kernel-llm-local.md
docs/quickstart/kernel-llm-frontier.md



hay que revisar que se cumpla 

kernel, port, adapter 
para desacoplar esto esta en epic04 con los ports y adpaters


un punto importante por cada capa 

- completar flujo rapido
- goldenn set / test 
- code (para reutilizar)
- cli (para probar)



tengo 11k archivos en la carpeta documentos documentos
necesito extraer informacion de los mismos y dejarlos disponibles para ser consumidos por otro sistema

nombre de la solucion 
 - docflow 

la solucion es una libreria que va a tener diferentes formas de ser consumida:
 - como includes en otros programas
 - como un cli 

La idea es que podamos invocar a cada componente como parte del cli 
docflow segmetntador 
docflow identificador 


un punto critico es que tengamos un modo batch que pueda tomar 1 archivo, varios o una carpeta. Si es una carpeta, tiene que respetar la estructura de salida de la mismas. debe de exisitr un mecanismo de stop con force . se debe poder pausar y reanudar los procesamientoes, 




las extracciones las vamos a realizar con modelos locales corriendo por ej en ollama, los cuales necesitan un ajuste 

vamos a usar un validador que sera el guia de la solucion, el mismos es un llm frontier que puede ser deepseek o claude o openai u otro. la idea es que el golden para usarlos tanto como


usar docling para el OCR (por debajo usa easy ocr para diferentes formatos de documentos)
el circuito 
imagen > aplicar ocr 
se puede hacer con docling 


pdf texto > extraer texto > usar reglas / prompts > validar > reportar
pdf texto > extraer texto > usar reglas  > reportar
pdf texto > extraer texto > usar  prompts > validar > reportar

pdf imagen > convertir img > aplicar ocr >  usar reglas / prompts > validar > reportar
pdf imagen > convertir img > aplicar ocr >  usar reglas  > validar > reportar
pdf imagen > convertir img > aplicar ocr >  usar prompts > validar > reportar

imagen > aplicar ocr >  usar reglas / prompts > validar > reportar
imagen > aplicar ocr >  usar reglas > validar > reportar
imagen > aplicar ocr >  usar  prompts > validar > reportar

imagen > usar  prompts > validar > reportar

