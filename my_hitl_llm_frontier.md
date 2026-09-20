# Flujos

## principal
documento
  → rutear (tipo de material + legibilidad)
  → extraer campos
  → validar campos
       ├─ ok → confirmar → aprender
       ├─ corregible con evidencia → corregir → validar (loop) → confirmar → aprender
       └─ no corregible / material degradado → escalar (cola) → [no aprende de esto todavía]


## rutear

documento
  → ¿tiene capa de texto? 
       ├─ sí  → texto_nativo   (confianza alta, sin OCR de por medio)
       └─ no  → ¿es imagen o PDF sin texto?
                 → rasterizar si hace falta
                 → chequear legibilidad (sharpness)
                      ├─ legible     → escaneado_ocr   (confianza media, depende de OCR)
                      └─ no legible  → degradado        → escalar directo

## extraer campos
documento (con tier ya definido por el ruteo)

tier == texto_nativo
  → extraer texto de la capa del PDF (sin modelo, es el string real)
  → correr LLM local sobre ese texto → campos_A
  → correr LLM local otra vez, mismo texto → campos_B
       ├─ campos_A == campos_B → campos_texto  (listo para validar)
       └─ difieren               → inestable → escalar
 no hay lectura de vision acá: no hay frontera OCR que aislar

tier == escaneado_ocr
  → OCR sobre el render → texto_ocr
  → correr LLM local sobre texto_ocr → campos_A
  → correr LLM local otra vez, mismo texto_ocr → campos_B
       ├─ campos_A == campos_B → campos_texto
       └─ difieren               → inestable → escalar
  → (en paralelo, no depende del resultado anterior)
    correr LLM local vision sobre el render → campos_vision

  salida: campos_texto + campos_vision   (los dos, sin fusionar todavía —
          eso lo decide "validar", no "extraer")

## validar campos 
tier == texto_nativo
  campos_texto (ya estable, viene de "extraer")
  → refutadores mecánicos sobre campos_texto vs. documento
       (etiqueta↔evidencia, trazabilidad al prompt, aritmética, ventana de contexto)
       ├─ sin violaciones → confirmado
       └─ con violaciones → ¿la violación señala un valor correcto?
              ├─ sí (ej: aritmética indica cuál de dos lecturas cierra)
              │      → corregible → corregir
              └─ no (ej: fabricación sin evidencia de reemplazo)
                     → escalar

tier == escaneado_ocr
  campos_texto + campos_vision (dos lecturas separadas, de "extraer")
  → refutadores mecánicos sobre cada lectura por separado
       ├─ ambas limpias → comparar campo a campo
       │      ├─ coinciden → confirmado
       │      └─ difieren  → ¿aritmética u otro refutador dirime cuál vale?
       │             ├─ sí → corregible → corregir
       │             └─ no → escalar
       └─ una o ambas con violaciones → escalar
              (una lectura sucia no vota; no promedies con la limpia)

--- 
# notas

campos:
- nombre
- tipo y formato
- reglas de validacion


Fuente:
- texto: confianza alta 
- pdf_texto / pdf_imagen: confianza alta, confianza media
- imagen: confianza media


convertir:
- pdf_imagen: exportar a imagen

preprocesamiento de imagenes:
- imagen: es legible? > rechazar imagen
- imagen: es pesada o pesada dpi? > redimensionar imagen

extraccion texto:
- texto: no realizar operacion
- pdf_texto: usar pdftotext layout o similar 
- imagen: usar ocr (docling o similar)

clasificar, es comprobante:
- texto: en base a la extraccion de texto (pdftotext, ocr) aplicar reglas para determinar si es un comprobante
- imagen: en base a reglas de elementos (visual) determinar si es comprobante


confianza texto
- alta: regexp, llm_local
- media: llm_local 


extraccion campso?
- texto usando regexp
- texto usando llm_local modelo razonamiento
- imagen usando llm_local modelo visual
- imagen usando llm_frontier modelo multimodal 




