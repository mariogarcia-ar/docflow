# ollama ls

NAME                    ID              SIZE      MODIFIED           
gemma3:12b              f4031aab637d    8.1 GB    About a minute ago    
gemma3:4b               a2af6cc3eb7f    3.3 GB    9 days ago            
qwen3.5:9b              6488c96fa5fa    6.6 GB    8 minutes ago         
granite4.2:8b           f586c02fdecd    5.3 GB    11 minutes ago        
qwen2.5:7b-instruct     845dbda0ea48    4.7 GB    8 days ago            

granite3.2-vision:2b    3be41a661804    2.4 GB    4 minutes ago         
qwen2.5vl:7b            5ced39dfa4ba    6.0 GB    26 minutes ago        
qwen2.5vl:3b            fb90415cde1e    3.2 GB    2 months ago  
deepseek-ocr:3b         0e7b018b8a22    6.7 GB    About an hour ago     

deepseek-r1:8b          6995872bfe4c    5.2 GB    8 days ago            

granite3.1-moe:1b       3269ce3e31ea    1.4 GB    10 days ago           



T1 E gemma3
T2 R qwen3.5 
V1 E qwen3-vl 
V2 R mistral3

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