creo que en v3 vamos a tener que ajustar los pasos porque ahora se especializaron los prompts (extraction/review) y los schemas

en v1 usamos bien las primitivas
en v2 mejoramos todo framework de recupero
vn v3 vamos a mejorar el uso de los prompts 

se aplico para 
registry/prompts/extraction/invoice.txt
pero falto 
registry/prompts/extraction/vision.txt

revisar si cambio el objetivo ... creeria que no oprque el run es agnostico a los prompts 

necesito un
scripts/poc-flow-v2/myllmlocal.py 
que me permita pasar un archivo , prompt y que me de el resultado
si el archivo es usar los metodos existente en scripts/poc-flow-v2/flow
- texto, directo 
- pdf texto: usar pdftotext y enviar texto 
- pdf imagen: exportar imagen y continuar con ocr
- imagen: usar ocr (doclint) y enviar texto 


ollama ls
NAME                 ID              SIZE      MODIFIED     
gemma3:1b            8648f39daa8f    815 MB    23 hours ago    
granite3.1-moe:1b    3269ce3e31ea    1.4 GB    23 hours ago    
deepseek-r1:1.5b     e0979632db5a    1.1 GB    2 weeks ago     
qwen2.5vl:3b         fb90415cde1e    3.2 GB    2 months ago  

```bash
# es factura
python scripts/poc-flow-v2/myllmlocal.py \
  'tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt' \
  --prompt 'registry/prompts/extraction/invoice_deteccion.txt' \
  --model 'deepseek-r1:1.5b'

# no es factura
python scripts/poc-flow-v2/myllmlocal.py \
  'tests/fixtures-txt/negativos/neg_2026-06_correo_liquidacion.txt' \
  --prompt 'registry/prompts/extraction/invoice_deteccion.txt' \
  --model 'deepseek-r1:1.5b'


# extraer los campos de una factura
python scripts/poc-flow-v2/myllmlocal.py \
  'tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt' \
  --prompt 'registry/prompts/extraction/invoice.txt' \
  --model 'deepseek-r1:1.5b'





python scripts/poc-flow-v2/myllmlocal.py \
  'tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt' \
  --prompt 'registry/prompts/extraction/invoice.txt' \
  --model 'deepseek-r1:1.5b'

python scripts/poc-flow-v2/myllmlocal.py \
  'tests/fixtures-txt/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.txt' \
  --prompt 'registry/prompts/extraction/invoice.txt' \
  --model 'deepseek-r1:1.5b'



```



revisar que introducimos y rompimos ocn el modelo 

script.sh > cli > kernel > port > adapter 

revisar sobreingenieria, usar tavily para identificar si una funcionalidad ya existe: 
hay muchas cosas que lo resuelven utilitarios de linux , python, u otras librerias


un cliente echo con python o similar 
un cli deberia tener 
entrada > proceso > salida 

---
usar estos ejemplos 
pdf texto : sin comprobante 
tests/fixtures/negativos/neg_2026-06_correo_liquidacion.pdf

pdf texto : con comprobante
tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf

pdf imagen : sin comprobante 
tests/fixtures/negativos/neg_2026-10_pantalla_aprobacion.pdf

pdf imagen : con comprobante
tests/fixtures/pdf_aptos_layout/36744cc6-2ed9-47e5-b4b8-66c31768164b.pdf


imagen : sin comprobante 
tests/fixtures/negativos/neg_2026-06_correo_liquidacion.pdf

imagen : con comprobante
tests/fixtures/casos/66e6e0ea-e910-41f4-9037-13f0309812c1.jpg


analizar si esta funcionando segun la especificacion de my_flow.md.



```bash
#!/bin/bash

# Limpiar ejecuciones anteriores
rm -rf var 

# ==============================================================================
# 1. PDF TEXTO
# ==============================================================================

# pdf texto : sin comprobante 
python scripts/poc-flow-v2/myflow.py \
  'tests/fixtures/negativos/neg_2026-06_correo_liquidacion.pdf' \
  --work-root var/work/pdf_text_sin_comprobante \
  --verbose

# pdf texto : con comprobante
python scripts/poc-flow-v2/myflow.py \
  'tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf' \
  --work-root var/work/pdf_text_con_comprobante \
  --verbose

# ==============================================================================
# 2. PDF IMAGEN
# ==============================================================================

# pdf imagen : sin comprobante 
python scripts/poc-flow-v2/myflow.py \
  'tests/fixtures/negativos/neg_2026-10_pantalla_aprobacion.pdf' \
  --work-root var/work/pdf_imagen_sin_comprobante \
  --verbose

# pdf imagen : con comprobante
python scripts/poc-flow-v2/myflow.py \
  'tests/fixtures/pdf_aptos_layout/36744cc6-2ed9-47e5-b4b8-66c31768164b.pdf' \
  --work-root var/work/pdf_imagen_con_comprobante \
  --verbose

# ==============================================================================
# 3. IMAGENES NATIVAS
# ==============================================================================

# imagen : sin comprobante 
python scripts/poc-flow-v2/myflow.py \
  'tests/fixtures/negativos/neg_2026-06_correo_liquidacion.pdf' \
  --work-root var/work/imagen_sin_comprobante \
  --verbose

# imagen : con comprobante
python scripts/poc-flow-v2/myflow.py \
  'tests/fixtures/casos/66e6e0ea-e910-41f4-9037-13f0309812c1.jpg' \
  --work-root var/work/imagen_con_comprobante \
  --verbose


```

---
cat var/work/run.json| jq 
jq -r '.text' var/work/material.json


rm -rf var
python scripts/poc/batch_pdf.py  tests/fixtures/ --out var/run
python scripts/poc/batch_ocr.py  tests/fixtures/ --out var/run
python scripts/poc/batch_ocr.py  var/run --out var/run2



 python scripts/poc/batch_llm_local.py 'var/poc/batch_pdf/' --schema scripts/poc/FIELDS.json


 python scripts/poc/batch_llm_local.py 'var/poc/batch_pdf/casos' --schema scripts/poc/FIELDS.json
 python scripts/poc/batch_llm_local.py 'var/poc/batch_pdf/pdf_escaneados' --schema scripts/poc/FIELDS.json


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

