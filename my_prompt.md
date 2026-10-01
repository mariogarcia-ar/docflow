# ollama ls
NAME                   ID              SIZE      MODIFIED     

razonamiento
deepseek-r1:8b         6995872bfe4c    5.2 GB    8 days ago     

vision
qwen2.5vl:3b           fb90415cde1e    3.2 GB    2 months ago    
deepseek-ocr:3b
qwen2.5vl:7b 
qwen3.5:9b 
qwen3-vl:8b 

llama3.2-vision:11b

general
qwen2.5:7b-instruct    845dbda0ea48    4.7 GB    8 days ago      
gemma3:4b              a2af6cc3eb7f    3.3 GB    9 days ago      

moe
granite4.2:8b
granite3.1-moe:1b      3269ce3e31ea    1.4 GB    10 days ago     
granite3.2-vision:2b 




ollama pull deepseek-ocr:3b

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