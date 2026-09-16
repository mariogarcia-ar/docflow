# Extracción de documentos

Versión resumida. El detalle está en `README.md`.

Los **flujos** se nombran por qué recibe el extractor. Los **componentes**, por qué producen.

| Flujo | Recibe |
|---|---|
| **Reglas** | Nada |
| **Interpretación** | Texto |
| **Visión** | Píxeles |

| Componente | Produce |
|---|---|
| **Segmentador** | Documentos lógicos + confianza de corte |
| **Identificador** | Tipo de documento + evidencia |
| **Diagnóstico** | Ruta y advertencias de entrada |
| **Lector** | Tokens posicionados + confianza |
| **Reconstructor** | Documento estructurado |
| **Validador** | Veredicto por campo |
| **Consistencia** | Veredicto entre campos y entre flujos |
| **Catálogo** | Veredicto contra fuente externa |
| **Contrato** | Forma de la salida |
| **Revisor** | Correcciones + casos nuevos |
## Niveles

Un archivo no es un documento. Un PDF de 20 páginas puede contener una factura, o tres.

| Nivel | Qué es |
|---|---|
| **Archivo** | Lo que entra al sistema |
| **Documento** | Una unidad con sentido propio dentro del archivo |
| **Página** | La unidad física de procesamiento |

## Componentes

Corren dentro de un flujo, entre flujos, o después de todos. La columna **Nivel** dice qué recibe cada uno y **Cuándo** dice dónde se ubica.

| Componente | Nivel | Cuándo | Qué hace | Reglas | Interp. | Visión |
|---|---|---|---|:---:|:---:|:---:|
| **Segmentador** | Archivo | Dentro | Agrupa páginas en documentos lógicos | ✓ | ✓ | ✓ |
| **Identificador** | Documento | Dentro | Determina el tipo y el ruteo | ✓ | ✓ | ✓ |
| **Diagnóstico** | Página | Dentro | Detecta contenido, mide calidad, adecúa | ✓ | ✓ | — |
| **Lector** | Página | Dentro | Extrae tokens por conversión u OCR | ✓ | ✓ | — |
| **Reconstructor** | Páginas | Dentro | Layout, tablas, orden de lectura | ✓ | ✓ | ◐ |
| **Validador** | Campo | Dentro | Forma, tipo, contenido, dígito verificador | ✓ | ✓ | ✓ |
| **Catálogo** | Documento | Dentro | Valida contra fuentes externas | ✓ | ✓ | ✓ |
| **Consistencia** | Documento | **Entre** | Cruza campos y compara flujos | ✓ | ✓ | ✓ |
| **Contrato** | Documento | **Después** | Forma canónica de la salida | ✓ | ✓ | ✓ |
| **Revisor** | Todos | **Después** | Cierra el bucle con correcciones humanas | ✓ | ✓ | ✓ |

Visión no usa Diagnóstico ni Lector: le pasa píxeles al modelo, que lee y extrae en un paso. El ◐ del Reconstructor en Visión es por lo mismo: el VLM absorbe el layout de una página, pero la continuidad entre páginas sigue haciendo falta.

**Barreras.** Tres componentes no pueden emitir hasta que otro terminó:

| Barrera | Espera a |
|---|---|
| **Segmentador** | Todas las páginas leídas |
| **Consistencia entre flujos** | Los dos flujos sobre el mismo campo |
| **Contrato** | Todas las páginas resueltas |

Los de nivel página son **paralelizables**. Consistencia entre campos no es barrera: opera dentro de un flujo, sobre campos ya extraídos.

### Segmentador

```mermaid
graph LR
    A["Archivo<br/>20 páginas"] --> B["Detectar cortes<br/>continuidad · numeración"]
    B --> C["Confianza<br/>por corte"]
    C -->|"alta"| D["Doc 1<br/>págs 1-7"]
    C -->|"alta"| E["Doc 2<br/>págs 8-12"]
    C -->|"dudosa"| F["Sobre-segmentar<br/>págs 13-14 · 15-20"]
```

Agrupa las páginas en documentos lógicos antes del Identificador. Sin él, un PDF con tres facturas se procesa como una sola y los campos se mezclan entre comprobantes.

Las señales de corte son la numeración de página reiniciada, un encabezado de documento nuevo, o la ausencia de continuidad en tablas abiertas.

**Es el único componente sin escape.** Todos los demás tienen salida ante la duda: el Identificador deriva, el Diagnóstico deriva con motivo, el Contrato emite parcial. El Segmentador decide primero y su error es **irrecuperable aguas abajo**: si une dos documentos, los campos del segundo pisan los del primero y no hay chequeo posterior que lo note.

De ahí la asimetría que gobierna su política:

| Error | Consecuencia | Se detecta después |
|---|---|---|
| **Partir de más** | Dos documentos donde había uno | Sí: el Identificador da el mismo tipo dos veces y el Contrato ve campos faltantes en ambos |
| **Unir de más** | Un documento donde había dos | **No**: los campos se mezclan en silencio |

Ante corte dudoso, **sobre-segmentar**. Un documento de más es ruido recuperable; un documento de menos es corrupción silenciosa.

### Identificador

```mermaid
graph LR
    A["Documento<br/>lógico"] --> B{"¿Qué evidencia<br/>hay?"}
    B -->|"texto"| C["Por campos<br/>y palabras clave"]
    B -->|"imagen"| D["Por formas<br/>y marcas"]
    B -->|"ambos"| E["Mixto<br/>estructura + contenido"]
    C --> F["Tipo + confianza<br/>+ evidencia"]
    D --> F
    E --> F
    F --> G{"¿Confianza<br/>suficiente?"}
    G -->|"sí"| H["Ruteo:<br/>plantilla · extractor"]
    G -->|"baja"| I["Revisión"]
    G -->|"dos tipos"| J["Re-segmentar<br/>una sola vez"]
    J --> K["Páginas ya<br/>leídas: reusar"]
    K --> A
```

Tres variantes según qué evidencia esté disponible: solo texto, solo imagen, o ambos. La diferencia no es de precisión sino de qué se puede observar.

Devuelve la **evidencia** junto al tipo: qué palabras o formas dispararon la decisión. Sin eso, un documento mal clasificado es invisible y el error aparece recién al final, como un campo mal extraído.

Confianza baja deriva a revisión en vez de elegir el tipo más probable. Y hace falta una categoría "otro" con ruta propia: de ahí salen los tipos nuevos.

**Tiene una arista de vuelta al Segmentador, con tres límites.** Segmentar bien a veces requiere saber el tipo, e identificar requiere el segmento: es circular, y el sistema era estrictamente hacia adelante. Cuando la evidencia muestra **dos tipos distintos** en el mismo segmento, el Identificador no elige uno: devuelve el corte y fuerza re-segmentación. Pero un bucle sin condición de corte es un riesgo, así que:

| Límite | Por qué |
|---|---|
| **Una sola re-segmentación** | Si la segunda pasada vuelve a dar dos tipos, va a revisión. No hay tercera |
| **Reusar lo ya leído** | Diagnóstico y Lector son de nivel página y no dependen del corte: se conservan. Re-segmentar no implica releer |
| **Alimentar la confianza de corte** | El caso se registra, y si se repite el mismo patrón, el Segmentador ajusta su umbral |

Ese último punto cierra el solapamiento entre los dos mecanismos: **la duda parte, el error vuelve**. Si el Segmentador dudó, ya sobre-segmentó — el caso "dos tipos" no debería aparecer. Si aparece, es porque la confianza de corte dio alta y se equivocó, y esa señal es exactamente lo que el umbral necesita para corregirse. Los dos mecanismos no compiten: uno actúa antes y el otro alimenta al primero.

### Diagnóstico

```mermaid
graph LR
    A["Página"] --> B{"¿Qué<br/>contiene?"}
    B -->|"capa de texto"| C["Medir<br/>proporción · alfabéticos"]
    B -->|"imagen"| D["Medir<br/>DPI · peso · legibilidad"]
    C --> E{"¿Usable?"}
    D --> E
    E -->|"sí"| F["Ruta:<br/>conversión"]
    E -->|"no"| G["Adecuar<br/>reescalar · comprimir"]
    G --> H["Ruta:<br/>OCR"]
    E -->|"ilegible"| I["Derivar<br/>con motivo"]
```

Corre antes de leer y hace tres cosas: **detecta** qué hay, **mide** si es procesable, y **adecúa** la entrada.

No alcanza con preguntar si hay texto: hay que ver si es usable. Un PDF puede traer una capa de OCR vieja y mala; el ruteo por presencia lo manda a conversión y arrastra esos errores sin que nadie los revise. El chequeo es de proporción y calidad — una capa con 40 caracteres en una A4 es basura.

Legibilidad es distinto de resolución: una imagen puede tener DPI suficiente y estar desenfocada. Si no pasa, hay dos salidas válidas (preprocesar o derivar) y una inválida: pasarla al OCR igual y dejar que devuelva texto inventado indistinguible de una lectura real.

### Lector

```mermaid
graph LR
    A["Página"] --> B["Diagnóstico"] --> C{"¿Texto<br/>usable?"}
    C -->|"sí"| D["Conversión"]
    C -->|"no"| E["OCR"] --> F["Corrección"]
    D --> G["Tokens<br/>posicionados"]
    F --> G
```

| Camino | Entrada | Corrección | Confianza |
|---|---|:---:|---|
| Conversión | Capa de texto existente | No | 1.0 |
| OCR | Imagen | Sí | Estimada |

La corrección existe solo en OCR: un conversor no lee mal, transcribe lo que hay. Aplicarle un modelo de lenguaje "por las dudas" solo puede introducir daño.

El ruteo es **por página**: un PDF mixto combina ambos caminos y los une al final.

**Devuelve tokens, no texto.** La distinción importa y resuelve un problema del diseño anterior: si el Lector entregara texto ya ordenado, absorbería parte del Reconstructor y no haría falta ese componente. Entrega **tokens con coordenadas**, sin orden de lectura resuelto — así el Reconstructor tiene razón de existir y los dos flujos de texto lo necesitan por igual.

### Reconstructor

```mermaid
graph LR
    A["Páginas<br/>1-7"] --> B["Layout<br/>por página"]
    B --> C["Continuidad<br/>cruzar páginas"]
    C --> D["Tablas<br/>encabezado + filas"]
    C --> E["Encabezados<br/>colapsar repetidos"]
    C --> F["Orden<br/>de lectura"]
    D --> G["Documento<br/>estructurado"]
    E --> G
    F --> G
```

Recibe **varias páginas**, no una: el layout es local, pero la continuidad lo cruza.

- Una tabla con encabezado en una página y filas que siguen en la siguiente pierde la asociación si cada página se procesa aislada.
- Un encabezado repetido en las 5 páginas se captura 5 veces sin control de continuidad.

**Corre en Reglas e Interpretación; en Visión solo la continuidad.** El diseño anterior lo dejaba únicamente en Reglas, lo cual era inconsistente: un documento multipágina aplanado a texto pierde orden de lectura y continuidad igual, y el LLM **rellena esa estructura inventándola**, que es su peor modo de falla. En Visión el ◐ se explica porque el VLM absorbe el layout de cada página, pero la continuidad entre páginas sigue haciendo falta.

### Validador

```mermaid
graph LR
    A["Campo<br/>extraído"] --> B["Forma"]
    A --> C["Tipo"]
    A --> D["Contenido"]
    A --> E["Dígito<br/>verificador"]
    B --> F["Veredicto<br/>por chequeo"]
    C --> F
    D --> F
    E --> F
    F --> G["Decidir<br/>según las fallas"]
```

Cuatro chequeos **independientes**: cada uno mira el mismo campo y emite su propio veredicto. No están encadenados — que la forma sea correcta no habilita al de tipo, ni al revés.

| Chequeo | Pregunta | Qué ve que los otros no | Falla → |
|---|---|---|---|
| **Forma** | ¿Tiene la forma esperada? | Que *algo* con la apariencia correcta está ahí | Reintentar con otra ancla |
| **Tipo** | ¿Es del tipo que dice ser? | Que el valor es usable | Reintentar, si no revisión |
| **Contenido** | ¿Es admisible en el dominio? | Que corresponde al negocio: único que conoce las reglas | Revisión |
| **Dígito verificador** | ¿Es válido en sí mismo? | Garantía matemática: único sin falsos positivos | Rechazar |

El orden de la tabla va de más débil a más fuerte, y **ese orden no describe ejecución**: los cuatro corren sobre el mismo campo y ninguno necesita el resultado de otro.

Lo que sí cambia entre ellos es la fuerza de la evidencia:

- **Forma** no dice si el valor es cierto. Un importe que matchea el patrón puede ser cualquier número.
- **Tipo** confirma que es usable, no que sea correcto.
- **Contenido** es el único que conoce el negocio: un IVA de 17% pasa forma y tipo, y sigue siendo error.
- **Dígito verificador** es el único con garantía: un número inventado no pasa salvo azar de 1 en 10.

La decisión final combina los veredictos, y la **falla más grave manda**: un campo puede pasar forma y tipo, fallar contenido, y derivar a revisión; o fallar dígito verificador y rechazarse aunque los otros tres pasen.

**También es el que gobierna el escalamiento.** "No pudo" se define acá y en ningún otro lado. La política vivía dispersa en tres componentes —Identificador, Diagnóstico y Validador— sin que ninguno supiera de los otros; centralizarla acá es lo que la vuelve aplicable.

Y "no pudo" son **dos casos distintos**, que no pueden escalar igual:

| Caso | Qué hay | Cómo escala |
|---|---|---|
| **Campo inválido** | Valor, página y offset | **Targeted**: se renderiza esa región y se pregunta por ese campo |
| **Campo ausente** | Nada: no encontró el ancla | **Documento entero**: no hay región que apuntar |

La diferencia decide el costo. Un campo inválido tiene ubicación, así que Visión mira un recorte: barato y preciso. Un campo ausente no tiene dónde mirar, así que Visión tiene que releer el documento completo igual que si fuera el único flujo.

Por eso **"reprocesa esos 2, no los 20" aplica solo al primer caso**. Si el escalamiento es mayoritariamente por campos ausentes, el ahorro no es de un orden de magnitud sino de ninguno. La cifra hay que medirla sobre la mezcla real de ambos casos, no suponerla.

### Consistencia

```mermaid
graph LR
    A["Campos<br/>validados"] --> N["Normalizar<br/>formato común"]
    N --> B{"¿Cierran<br/>entre sí?"}
    N --> C{"¿Coinciden<br/>entre flujos?"}
    B -->|"no"| D["Marcar<br/>campos implicados"]
    C -->|"no"| G{"¿Aritmética<br/>desempata?"}
    G -->|"sí"| H["Resolver<br/>sin humano"]
    G -->|"no"| E["Desacuerdo<br/>→ revisión"]
    B -->|"sí"| F["Refuerzo<br/>de confianza"]
    C -->|"sí"| F
```

Compara valores entre sí. Opera en dos niveles con el mismo mecanismo:

| Nivel | Qué compara | Ejemplo |
|---|---|---|
| **Entre campos** | Aritmética y orden dentro del documento | subtotal + impuestos = total; emisión ≤ vencimiento |
| **Entre flujos** | El mismo campo extraído por dos caminos | total según Reglas vs. total según Visión |

**El segundo nivel es la respuesta al hueco de plausible-pero-falso.** Un total de 15400 que era 1540 pasa forma, tipo, contenido y no tiene dígito verificador: ningún chequeo interno lo ve. Pero si Reglas lee 1540 y Visión lee 15400 sobre el mismo documento, el desacuerdo aparece — y es la señal más fuerte disponible en todo el sistema.

Sin esto, el híbrido es solo fallback: cada flujo hace su parte y la arquitectura descarta la capacidad de contraste, que es justamente lo que la validación interna no puede dar.

#### Lo que hace falta para que el contraste sea usable

Emitir `Difieren → revisión` a secas convierte cada diferencia de formato en un ítem de cola. A volumen alto, el contraste deja de costar cómputo y pasa a costar **tiempo de persona**, que es el recurso que limita el throughput. Tres decisiones, todas antes de comparar:

**Normalizar primero.** Si no, se compara formato en vez de valor: `1.540,00` contra `1540.00`, un CUIT con espacios contra uno sin, una fecha `16/09/2026` contra `2026-09-16`. Hay que llevar ambos valores a forma canónica y **comparar los normalizados**, no los crudos.

**Tolerancia por tipo de campo.**

| Tipo | Tolerancia | Por qué |
|---|---|---|
| Importes | Centavos | El redondeo entre caminos es legítimo |
| Identificadores | **Exacta** | Un CUIT no tiene redondeo: un dígito distinto es un error |
| Fechas | Exacta | No hay equivalente aproximado |

**Que la aritmética arbitre.** Los dos niveles no son independientes y hoy no se hablan. Si los flujos difieren en el total pero solo uno de los dos valores cierra con `subtotal + impuestos` del propio documento, **Consistencia ya tiene la respuesta** y no hace falta un humano. El nivel aritmético desempata el nivel entre-flujos: es la única señal interna capaz de decidir cuál de los dos tiene razón, y es gratis.

Solo cuando ninguno de los dos cierra, o el campo es un identificador sin relación aritmética, el desacuerdo va a revisión.

**Costo.** Correr dos flujos sobre todo es caro, así que el contraste se reserva: por campo crítico (importes, identificadores) y no por documento entero. La política de cuándo contrastar es una decisión explícita, no un efecto lateral.

El de consistencia aritmética también es el único chequeo que **agarra errores de dígito del OCR**: si dos cifras leídas mal no suman, el error se detecta sin comparar contra nada externo.

### Catálogo

```mermaid
graph LR
    A["Campo de<br/>identidad"] --> B["Consultar<br/>fuente externa"]
    B --> C{"¿Existe y<br/>coincide?"}
    C -->|"sí"| D["Verificado"]
    C -->|"no"| E["Revisión"]
    C -->|"sin respuesta"| F["Sin verificar"]
    F --> G["Cola de<br/>reintento"]
    G --> B
```

Valida contra algo que existe fuera del documento: un padrón de proveedores, el servicio del ente emisor, el registro de un identificador.

**Es el único que cierra el hueco para campos de identidad.** Un CUIT puede tener dígito verificador correcto y pertenecer a una empresa que no emitió el documento. Ningún chequeo interno lo distingue; consultarlo contra la fuente, sí.

Distinto de Consistencia: aquel compara el documento contra sí mismo, este contra la realidad externa. Y distinto del Validador en que **no es determinista** — depende de disponibilidad y latencia de un tercero.

Por eso la falla por indisponibilidad no es un rechazo: si la fuente externa no responde, el campo queda **sin verificar**, no inválido. Confundir las dos cosas convierte una caída del servicio en una cola de rechazos.

**`Sin verificar` tiene dueño: el propio Catálogo.** No basta con marcarlo, porque un campo sin verificar es deuda invisible — el documento se emite y nadie vuelve a mirarlo. Por eso mantiene su **cola de reintento** con backoff, y el estado es visible en la salida como campo pendiente, no como campo ausente. Sin reintento propio, el estado es un agujero por donde se van los documentos con identidad nunca confirmada.

### Contrato

```mermaid
graph LR
    A["Documentos<br/>validados"] --> B["Unir<br/>campos por documento"]
    B --> C["Adjuntar<br/>procedencia por campo"]
    C --> D["Adjuntar<br/>vector de veredictos"]
    D --> E["JSON<br/>+ trazabilidad"]
    F["Página<br/>ilegible"] -.-> E
```

Emitir es una **barrera**: espera a que todas las páginas estén resueltas antes de producir la salida del documento.

Une los campos que vinieron de páginas distintas, adjunta la traza `(página, traza)` por campo, y con ella la procedencia.

**Maneja procedencia heterogénea.** Como el escalamiento es por campo, en un mismo documento conviven campos resueltos por Reglas con `offset exacto` y campos resueltos por Visión con `bbox aproximado`. El Contrato no puede asumir un origen único: cada campo declara su flujo y su tipo de traza, y eso es información de salida, no un detalle interno.

**Emite el vector de veredictos, no un score.** Hoy un campo acumula señales de cinco fuentes: confianza de corte, confianza del Lector, los cuatro veredictos del Validador, refuerzo o desacuerdo de Consistencia, y verificado/sin-verificar del Catálogo. Colapsarlas en un número repite el error que el Catálogo prohíbe: mezclar `sin verificar por caída del servicio` con `verificado y coincidente`.

Entonces cada campo se emite con sus veredictos separados:

```
{
  "total": {
    "valor": "15400.00",
    "flujo": "reglas",
    "traza": { "pagina": 3, "offset": [412, 424] },
    "veredictos": {
      "forma": "ok",
      "tipo": "ok",
      "contenido": "ok",
      "digito": null,
      "consistencia": "ok",
      "catalogo": "sin_verificar"
    }
  }
}
```

**El umbral lo pone el consumidor.** No hay un número mágico único: para un caso de uso, `sin_verificar` en identidad es bloqueante; para otro, un importe con `contenido: dudoso` es aceptable. Un escalar obliga a elegir un umbral en el lugar equivocado — el productor, que no conoce el caso de uso.

El fallo es **parcial**: una página ilegible se marca como tal y el resto del documento se emite igual, con esa ausencia declarada.

### Revisor

```mermaid
graph LR
    A["Casos<br/>derivados"] --> B["Corrección<br/>humana"]
    B --> C["Registrar<br/>par original → corregido"]
    C --> D["Agrupar<br/>casuística"]
    D --> E["¿Se repite?<br/>sí → regla"]
    E --> F["Nueva regla<br/>o plantilla"]
    E --> G["Nuevo tipo<br/>en Identificador"]
    F --> H["Volver<br/>al flujo"]
    G --> H
```

Cierra el bucle. Sin él, la arquitectura termina en "revisión" y todo lo que la revisión produce se pierde.

Recibe lo que derivaron los demás: confianza baja del Identificador, ilegibles del Diagnóstico, fallas de contenido del Validador, desacuerdos de Consistencia, y la categoría "otro".

Y tiene tres salidas, no una:

| Salida | Cuándo |
|---|---|
| **Dato corregido** | El caso era puntual: se arregla y sigue |
| **Regla nueva** | El caso se repite: pasa a Reglas y deja de llegar a revisión |
| **Tipo nuevo** | La categoría "otro" acumula casos: se define un tipo y su ruta |

Es también el que cierra el bucle del Segmentador: cuando el Identificador devuelve dos tipos en un segmento, el caso vuelve acá y la re-segmentación se vuelve una regla si se repite.

**Sin el Revisor, el sistema no mejora.** Las correcciones humanas se acumulan en logs que nadie lee y los mismos errores vuelven en cada lote: el mismo modo de falla que la revisión existía para resolver.

## Los tres flujos

Cada uno resuelve lo que puede y pasa al siguiente lo que no. El escalamiento lo gobierna el Validador.

### Reglas

```mermaid
graph LR
    A["Archivo"] --> B["Segmentador"] --> C["Identificador"] --> D["Lector"]
    D --> E["Reconstructor"] --> F["Extraer<br/>anclas + regex"] --> G["Validador"]
    G --> H["Consistencia"] --> I["Catálogo"] --> J["Contrato"]
    C -.->|"dos tipos"| B
    G -.->|"no pudo"| K["Escalar<br/>por campo"]
```

### Interpretación

```mermaid
graph LR
    A["Archivo"] --> B["Segmentador"] --> C["Identificador"] --> D["Lector"]
    D --> E["Reconstructor"] --> F["LLM<br/>interpreta"] --> G["Verificar<br/>cita = valor"]
    G --> H["Validador"] --> I["Consistencia"] --> J["Catálogo"] --> K["Contrato"]
    H -.->|"no pudo"| L["Escalar<br/>por campo"]
```

### Visión

```mermaid
graph LR
    A["Archivo"] --> B["Segmentador"] --> C["Identificador"] --> D["Renderizar"]
    D --> E["VLM<br/>lee y extrae"] --> F["Continuidad<br/>entre páginas"]
    F --> G["Validador"] --> H["Consistencia"] --> I["Catálogo"] --> J["Contrato"]
```

Los tres terminan en **Revisor**: lo que se deriva por cualquier motivo vuelve, se corrige, y se convierte en regla o en tipo nuevo.

## Diferencias

| | Reglas | Interpretación | Visión |
|---|---|---|---|
| Recibe | Nada | Texto | Píxeles |
| Ve firmas, sellos | Si se modeló | No | Sí |
| Costo | Bajo | Medio | Alto |
| **Inventa valores** | No | Sí | Sí |
| **Ancla mal** | Sí: proximidad textual | Sí: confusión semántica | Sí: fila o región equivocada |
| Cómo se equivoca | Toma un valor real del bloque vecino | Atribuye un valor real al campo equivocado | Lee la fila que no era |
| Determinista | Sí | No | No |
| Trazabilidad | Offset exacto | Cita + offset | bbox aproximado |

**Los tres anclan mal.** Lo que cambia es el mecanismo y la frecuencia, no la existencia del problema: un regex se equivoca por cercanía, un LLM sobre tokens aplanados atribuye el total del bloque resumen al comprobante igual que el regex —cambia la causa, no el resultado—, y un VLM lee la fila equivocada de una tabla con frecuencia conocida. Poner "No" en dos de las tres columnas sería la misma sobreventa que corregimos al eliminar "No alucina".

La diferencia útil no es *si* anclan mal, sino **cómo se detecta cada error**:

| Error | Se detecta con |
|---|---|
| Valor inventado | Aritmética, dígito verificador |
| Ancla mal en Reglas | **Solo contraste entre flujos**: el valor existe, tiene forma y tipo correctos |
| Ancla mal en Interpretación | Contraste, o cita que no sostiene el valor |
| Ancla mal en Visión | Contraste, o bbox fuera de la región esperada |

Esto refuerza lo mismo que el resto del documento: **el contraste no es una optimización, es el único mecanismo que ve la clase de error más silenciosa** — la que produce un valor válido en el lugar equivocado.

## Orden de ejecución

El híbrido resuelve dos cosas distintas, y conviene no confundirlas.

**Cascada** — cada etapa hace lo más barato y pasa al siguiente lo que no pudo. Define el costo.

```mermaid
graph LR
    A["Conversión"] --> B["Reglas"] --> C["Interpretación"] --> D["Visión"]
```

**Contraste** — dos flujos sobre el mismo campo, comparados. Define la confianza, y es lo único que agarra el error plausible-pero-falso.

```mermaid
graph LR
    A["Campos<br/>críticos"] --> B["Reglas"]
    A --> C["Visión"]
    B --> D["Consistencia<br/>compara"]
    C --> D
    D --> E["Coinciden →<br/>confianza alta"]
    D --> F["Difieren →<br/>revisión"]
```

Sin contraste, el híbrido es solo fallback y la arquitectura descarta la única señal que la validación interna no puede dar. El costo se acota contrastando **por campo crítico** —importes, identificadores— y no el documento entero.

## Invariantes

Aplican a los tres flujos:

- **Ante duda en el Segmentador, sobre-segmentar.** Partir de más se detecta después; unir de más es silencioso y contamina campos de documentos ajenos.
- **El bucle de re-segmentación corre una sola vez.** Un bucle sin tope es un riesgo; la segunda pasada es final.
- **El modelo nunca reemplaza al Validador.** La aritmética atrapa la alucinación en importes.
- **La cita prueba procedencia, no acierto.** Verificar el literal y el valor por separado.
- **La estructura se valida aparte.** Una columna desplazada tiene importes reales y pasa cualquier chequeo de valores.
- **Normalizar antes de comparar.** Sin eso se mide formato en vez de valor, y la cola de revisión se llena de diferencias de escritura.
- **La emisión es un vector de veredictos, no un score.** El umbral lo pone el consumidor, que conoce su caso de uso.
- **La traza declara página y flujo.** Con escalamiento por campo, la procedencia deja de ser única.
- **El fallo es parcial.** Una página ilegible marca esa página; no descarta el documento entero.
- **`Sin verificar` no es un estado final.** Necesita dueño y cola de reintento, o es deuda invisible.
- **Sin bucle de retorno, el sistema no mejora.** Las correcciones que no vuelven al flujo son las que hacen que el mismo error se repita.
- **Auditar no es normalizar.** Ver `d.md`.

## Limitaciones conocidas

Se declaran en lugar de suponerlas cubiertas:

| Limitación | Por qué no se resuelve adentro |
|---|---|
| Valor plausible pero falso | Necesita contraste entre flujos o fuente externa; ningún chequeo interno lo ve |
| Ancla mal en cualquiera de los tres flujos | El valor es real y del tipo correcto; solo el contraste lo detecta |
| Corte de segmentación dudoso | La sobre-segmentación mitiga, no elimina |
| Fuente externa caída | Se reintenta, pero mientras tanto el campo queda sin verificar |
| Campo ausente escalado | Sin ubicación previa, Visión relee el documento entero: no hay ahorro |

## Documentos

| Archivo | Contenido |
|---|---|
| `README.md` | Versión extendida |
| `d.md` | Nota técnica: validación con Pydantic |
| `a.md` | Flujo de texto |
| `b.md` | Flujo visual |
| `c.md` | Flujo multimodal |
