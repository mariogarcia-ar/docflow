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