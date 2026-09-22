Necesito unas librerias minimalistas para procesar
- pdf
- imagen
- llm call 
- flujo de trabajo

---

necesito para pdf:
- usar poppler como base , y https://github.com/cbrunet/python-poppler para la implementacion

- dividir en pdfs, ejemplos pdf con 10 paginas , genera 10 pdf 
- unir pdfs en uno

- extraer el texto preservando el layout (pdftotext --layout)
- extraer las imagenes del pdf 
- convertir pdf a imagen 

- por pagina
    - convertir a imagen 
    - extraer texto conservando el layout
    - extraer imagenes del pdf 
    - determinar si es una pagina basada en texto o en imagenes 

- decisor:
    - si la pagina/pdf es imagen exportarla a imagen, sino exportarla a texto 


---
necesito para imagen:
- nitidez, determinar si es legible o no (tal vez un laplacian variance)
- si hay texto para extraer
- revisar rotaciones
- adecuar la resolucion (para llm)
- adecuar formato para que sean livianos 


---

necesito para llm call:
- enviar el prompt
- enviar el schema
- enviar imagenes
- capturar la salida para poder reenivarla
- una cadena de llm call ej (determinar si es factura, extraer campos, validar campos), creando una estrcutura como un grafo dirigido de como se llamaran
- poder comparar salidas 
