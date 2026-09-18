revisar que introducimos y rompimos ocn el modelo 

cli > kernel > port > adapter 

revisar sobreingenieria, usar tavily para identificar si una funcionalidad ya existe: 
hay muchas cosas que lo resuelven utilitarios de linux , python, u otras librerias



---

imagen
arreglar 
- docflow-kernel image rescale tests/fixtures/otros/4c261bc8-3b30-4493-b5d4-6f499cde014e.jpeg --target-dpi 72
- y el save 


en pdf 
- probe 
- clasiffy : ver el tema de mixed
- tokens : tenemos que tener uno que sea el texto como pdftotext --layout 

```bash
docflow-kernel pdf probe tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf

docflow-kernel pdf classify tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf --page 1

docflow-kernel pdf tokens tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf


docflow-kernel pdf render tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf --page 1 --dpi 72 --save /tmp/out

docflow-kernel pdf layout tests/fixtures/pdf_aptos_layout/242823d2-afd3-4107-a49c-ce382592c6a5.pdf --pages 1


docflow-kernel pdf split tests/fixtures/pdf_aptos_layout/9073693b-f8bf-4f9b-88e0-1008de266c0e.pdf --pages 1,2
docflow-kernel pdf split tests/fixtures/pdf_aptos_layout/9073693b-f8bf-4f9b-88e0-1008de266c0e.pdf --pages 11-22

s
```
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

