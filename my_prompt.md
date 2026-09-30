# notas
al extraer la imagen de un pdf que solo tiene una imagen, extrajo el original .... esto es genial 



pdf > texto o render
imagen > ocr-ready 
ocr > extrae texto y tabla 

# comandos
```bash
# info
python scripts/tools/batch_pdf.py tests/fixtures/pdf

# classify
python scripts/tools/pdf.py classify documento.pdf --page 1 --json
python scripts/tools/batch_pdf.py tests/fixtures/pdf classify --page 1

```