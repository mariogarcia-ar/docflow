# Estrategia de Procesamiento Inteligente de Documentos (IDP) sobre Ollama

**Versión 2:** cada vía (texto y visión) tiene una etapa de **extracción** y una de **revisión**, con **modelos, prompts y schemas distintos** en cada etapa. **Alcance:** facturas y tickets (PDF o imagen) procesados con modelos 100 % locales. **Runtime:** Ollama.

---

## 1. Resumen ejecutivo

Cada documento recorre dos vías independientes. En cada una, un modelo **extrae** y otro **revisa** el resultado con un prompt y un schema propios. Un **árbitro determinista en Python** valida las revisiones, cruza las dos vías y emite el JSON final con **confianza** y **procedencia** por campo. Lo que no se puede validar se deriva a revisión humana (`needs_review`).

Ningún dato llega al resultado porque "un modelo lo dijo": tiene que superar reglas de negocio (aritmética, formato, anclaje al texto) y, además, ser confirmado por un segundo modelo que no es el que lo extrajo.

## 2. Arquitectura

```
                  ┌─ VÍA TEXTO ──────────────────────────────────────────────────────────┐
                  │ Docling (MD) ─> [T1 Extracción] ─> JSON A ─> [T2 Revisión] ─> A'     │
[PDF / Imagen] ───┤                                                                      ├─> [Árbitro] ─> JSON FINAL
                  │ VÍA VISIÓN ──────────────────────────────────────────────────────────┤
                  │ Render 200 dpi ─> [V1 Extracción] ─> JSON B ─> [V2 Revisión] ─> B'   │
                  └──────────────────────────────────────────────────────────────────────┘
```

| Etapa | Rol | Entrada | Salida |
| --- | --- | --- | --- |
| **T1** | Extrae datos del texto | Markdown de Docling | JSON A (`ExtraccionTexto`) |
| **T2** | Verifica A contra el texto | Markdown + JSON A | `RevisionTexto` |
| **V1** | Extrae datos de la imagen | Imagen de la página | JSON B (`ExtraccionVision`) |
| **V2** | Verifica B contra la imagen | Imagen + JSON B | `RevisionVision` |

## 3. Principios de diseño

1. **Un modelo distinto por etapa.** Cuatro modelos, de al menos tres familias. El revisor nunca es el mismo modelo que extrajo, así no comparte sus sesgos.
2. **Un prompt distinto por etapa.** El extractor transcribe; el revisor audita. Mezclar ambos roles en un mismo prompt hace que el modelo confirme lo que ya escribió.
3. **Un schema distinto por etapa.** La extracción devuelve datos; la revisión devuelve veredictos con evidencia.
4. **El revisor no reescribe.** Solo emite veredictos. Quien aplica correcciones es el árbitro, y solo si superan las validaciones deterministas.
5. **Lectura independiente primero.** En el schema de revisión, `valor_observado` va antes que `veredicto`: con salida estructurada los campos se generan en orden, así el revisor lee el dato por su cuenta antes de compararlo con la extracción.
6. **Evidencia obligatoria.** Todo veredicto cita su evidencia (cita literal en texto; zona y valor leído en visión).

## 4. Modelos por etapa

| Etapa | Modelo recomendado | Tag Ollama | Tamaño Q4 | Familia | Licencia |
| --- | --- | --- | --- | --- | --- |
| **T1** Extracción texto | Gemma 3 12B | `gemma3:12b` | 8,1 GB | Google | Gemma Terms |
| **T2** Revisión texto | Qwen3.5 9B | `qwen3.5:9b` | 6,6 GB | Alibaba | Apache 2.0 |
| **V1** Extracción visión | Qwen3-VL 8B | `qwen3-vl:8b` | 6,1 GB | Alibaba | Apache 2.0 |
| **V2** Revisión visión | Ministral 3 8B | `ministral-3:8b` | 6,0 GB | Mistral | Apache 2.0 |

**Por qué estos:**

- **T1 Gemma 3 12B:** muy sólido en español y buen seguimiento de schema.
- **T2 Qwen3.5 9B:** el mejor equilibrio calidad/tamaño del catálogo y de otra familia que T1.
- **V1 Qwen3-VL 8B:** OCR de primer nivel (32 idiomas), sucesor de Qwen2.5-VL.
- **V2 Ministral 3 8B:** multimodal, de una familia distinta a V1. **Es la elección menos probada para OCR de facturas en español**: validarla en el set dorado (§10) antes de fijarla.

### 4.1 Alternativas

| Etapa | Alternativa | Cuándo |
| --- | --- | --- |
| T1 | `granite4.1:8b` (5,3 GB, Apache 2.0) | Si el cliente exige licencia permisiva o hay 8 GB |
| T2 | `ministral-3:8b` o `granite4.1:8b` | Si se prefiere otra familia que T1 |
| V2 | `qwen2.5vl:7b` (6,0 GB) | Ya probado en facturas, pero misma familia que V1 |
| V2 | `gemma3:12b` (multimodal, 8,1 GB) | Otra familia, pero repite el modelo de T1 |

> Confirmar los tags exactos con `ollama list` o en la Ollama Library antes de fijarlos.

### 4.2 Descartados

Phi-4 (16K de contexto), Llama 3.2 Vision (imagen+texto solo en inglés), modelos de razonamiento tipo DeepSeek R1 (lentos y no mejoran la transcripción), Aya Expanse (no comercial) y cuantizaciones Q3 (degradan la extracción estructurada).

### 4.3 VRAM y orden de carga

Cada modelo pesa entre 6 y 8 GB, así que **con 12 GB corre uno a la vez** y con 16 GB o más pueden convivir dos. Para no recargar modelos en cada documento, **procesar por lotes por etapa**: pasar todos los documentos por T1, luego todos por T2, y así sucesivamente.

## 5. Schemas (Pydantic)

Las dos extracciones comparten un **núcleo común** (`DatosComprobante`) para que el árbitro pueda cruzarlas campo a campo. Cada vía agrega solo sus campos propios. Los schemas de revisión son distintos de los de extracción y distintos entre sí.

```python
from enum import Enum
from typing import Literal
from pydantic import BaseModel

class Item(BaseModel):
    descripcion: str
    cantidad: float | None
    precio_unitario: float | None
    alicuota_iva: float | None
    importe: float

class IvaLinea(BaseModel):
    alicuota: float
    importe: float

class DatosComprobante(BaseModel):          # núcleo común de T1 y V1
    tipo_comprobante: str                   # A, B, C, M, ticket
    cuit_emisor: str
    razon_social_emisor: str
    punto_venta: str
    numero: str
    fecha: str                              # YYYY-MM-DD
    cae: str | None
    vencimiento_cae: str | None
    neto_gravado: float | None
    no_gravado: float | None
    exento: float | None
    iva: list[IvaLinea]
    otros_tributos: float | None
    descuentos: float | None
    total: float
    items: list[Item]

# --- Extracción: datos + extras propios de cada vía ---
class ExtraccionTexto(DatosComprobante):    # T1
    campos_no_encontrados: list[str]

class ExtraccionVision(DatosComprobante):   # V1
    campos_ilegibles: list[str]
    observaciones_visuales: str | None      # borroso, sello, tachadura, torcido

# --- Revisión: veredictos con evidencia ---
class Veredicto(str, Enum):
    confirmado = "confirmado"
    discrepa = "discrepa"
    no_verificable = "no_verificable"

class RevisionCampoTexto(BaseModel):        # T2
    campo: str
    valor_observado: str | None             # primero: lectura independiente
    cita_literal: str | None                # fragmento exacto del Markdown
    veredicto: Veredicto                    # último: la comparación

class RevisionTexto(BaseModel):
    campos: list[RevisionCampoTexto]
    items_omitidos: list[str]               # líneas del texto ausentes en el JSON
    items_sobrantes: list[str]              # ítems del JSON que no están en el texto
    hallazgos: list[str]

class RevisionCampoVision(BaseModel):       # V2
    campo: str
    valor_observado: str | None
    zona: str | None                        # p. ej. "pie, esquina inferior derecha"
    legible: bool
    veredicto: Veredicto

class RevisionVision(BaseModel):
    campos: list[RevisionCampoVision]
    legibilidad_global: Literal["buena", "regular", "mala"]
    items_omitidos: list[str]
    items_sobrantes: list[str]
    hallazgos: list[str]
```

## 6. Prompts por etapa

| Etapa | Rol del prompt | Instrucciones clave | Restricciones |
| --- | --- | --- | --- |
| **T1** | Extractor de comprobantes fiscales argentinos | Copiar valores tal como figuran; fechas ISO; importes con punto decimal y sin separador de miles; si falta un dato, `null` y registrarlo en `campos_no_encontrados` | No calcular, no inferir, no completar |
| **T2** | Auditor del texto | Para cada campo: 1) leer el valor en el Markdown por cuenta propia, 2) citar el fragmento literal, 3) recién entonces comparar con la extracción; además listar líneas de ítems omitidas o sobrantes | No reescribir el JSON, no recalcular totales, no asumir que la extracción es correcta |
| **V1** | Lector de imágenes de comprobantes | Igual que T1, más `campos_ilegibles` y `observaciones_visuales`; usar jerarquía y posición de los bloques para ubicar totales | No adivinar lo ilegible: `null` y registrarlo |
| **V2** | Auditor visual | Para cada campo: localizar la zona, leer el valor, indicar si es legible, luego comparar; revisar ítems omitidos o sobrantes | Mismas que T2; ante duda, `no_verificable` |

Esqueleto de los dos roles (adaptar a cada etapa):

```text
# Extractor (T1 / V1)
Sos un extractor de comprobantes fiscales argentinos. Devolvé únicamente el JSON
del schema. Copiá cada valor tal como figura en el documento. No calcules ni
infieras. Si un dato no está o no se lee, usá null y registralo en la lista
correspondiente. Fechas en YYYY-MM-DD; importes con punto decimal, sin miles.

# Revisor (T2 / V2)
Sos un auditor. Recibís el documento y una extracción candidata. Para cada campo:
primero leé el valor en el documento por tu cuenta (valor_observado) y citá la
evidencia; recién después decidí el veredicto (confirmado / discrepa /
no_verificable). No reescribas el JSON, no recalcules totales y no asumas que la
extracción es correcta. Si no podés verificarlo, no_verificable.
```

## 7. Flujo de ejecución

| Modo | Secuencia | Llamadas por documento |
| --- | --- | --- |
| **Cascada (recomendado)** | T1 → T2 → validación determinista. Si pasa, se emite el resultado. Si falla (ecuación, CUIT, anclaje o disputa), se ejecutan V1 → V2 y el árbitro cruza ambas vías. | 2 (típico), 4 (si se activa visión) |
| **Paralelo** | T1 → T2 y V1 → V2 siempre; el árbitro cruza. | 4 |

Medir qué porcentaje de documentos activa la vía visión antes de decidir si el modo paralelo vale su costo.

## 8. El árbitro (módulo Python)

### 8.1 Aplicación de las revisiones (dentro de cada vía)

| Veredicto del revisor | Acción del árbitro | Procedencia |
| --- | --- | --- |
| `confirmado` | Se conserva el valor | `extraido_y_confirmado` |
| `discrepa` y solo el `valor_observado` pasa las validaciones | Se corrige | `corregido_por_revision` |
| `discrepa` y ambos valores pasan las validaciones | No se decide | `en_disputa` |
| `discrepa` y ninguno pasa | Se deriva | `needs_review` |
| `no_verificable` | Se conserva sin aumentar confianza | `sin_verificar` |

El revisor **nunca modifica un campo por sí solo**: toda corrección pasa antes por las validaciones de §8.2.

### 8.2 Validaciones deterministas (Argentina)

| Campo | Regla |
| --- | --- |
| CUIT | 11 dígitos con dígito verificador (módulo 11) |
| Punto de venta / Nº comprobante | 4–5 y 8 dígitos |
| CAE | 14 dígitos; vencimiento no anterior a la fecha del comprobante |
| Tipo de comprobante | A/B/C/M coherente con el IVA discriminado (en B y C no se discrimina) |
| Alícuotas | 0 %, 2,5 %, 5 %, 10,5 %, 21 %, 27 % |
| Ecuación | `Neto gravado + No gravado + Exento + IVA (por alícuota) + Otros tributos − Descuentos = Total`, tolerancia ±0,01 por línea |
| Ítems | `Σ ítems == subtotal` |
| Anclaje | Cada número del resultado debe aparecer literalmente en el texto de Docling |

### 8.3 Cruce entre vías

Con los resultados ya revisados de cada vía (A′ y B′):

- **Texto / IDs:** prioridad a la vía texto, siempre sujeta a validación.
- **Numéricos:** si divergen, gana la vía que cumpla la ecuación. Si ambas la cumplen con valores distintos, o ninguna, `needs_review`.
- **Tablas:** alinear ítems por similitud de texto y usar `items_omitidos` de ambos revisores como pista.

### 8.4 Salida

Cada campo del JSON final incluye `valor`, `confianza` (0–1) y `procedencia`. La confianza es máxima cuando ambas vías coinciden y ambos revisores confirman, y cae cuando el valor depende de un solo modelo o de una corrección. Los umbrales de `needs_review` se calibran con el set dorado.

## 9. Configuración de Ollama

| Etapa | `format` | `temperature` | `think` | `num_ctx` |
| --- | --- | --- | --- | --- |
| T1 | `ExtraccionTexto` | 0 | `false` | Documento + schema (8192–16384) |
| T2 | `RevisionTexto` | 0 | Opcional: probar con y sin | Documento + JSON A + schema (más alto que T1) |
| V1 | `ExtraccionVision` | 0 | `false` | Tokens de imagen + schema (≥ 8192) |
| V2 | `RevisionVision` | 0 | `false` | Tokens de imagen + JSON B + schema |

- Una A4 a 200 dpi son \~3.800 tokens visuales en Qwen3-VL (usa 32×32 px por token; Qwen2.5-VL usa 28×28). En Ministral 3 medir el consumo real.
- Procesar página por página; para tickets muy largos, por franjas.
- Variables de entorno: `OLLAMA_MAX_LOADED_MODELS` (1 en 12 GB, 2 con 16 GB o más) y `OLLAMA_NUM_PARALLEL` según la VRAM libre.

```python
import ollama

def correr(modelo, schema, prompt, imagen=None, num_ctx=8192, think=False):
    msg = {"role": "user", "content": prompt}
    if imagen:
        msg["images"] = [imagen]
    r = ollama.chat(
        model=modelo,
        messages=[msg],
        format=schema.model_json_schema(),
        think=think,
        options={"temperature": 0, "num_ctx": num_ctx},
    )
    return schema.model_validate_json(r.message.content)

a  = correr("gemma3:12b",     ExtraccionTexto, prompt_t1(markdown))
ra = correr("qwen3.5:9b",     RevisionTexto,   prompt_t2(markdown, a))
b  = correr("qwen3-vl:8b",    ExtraccionVision, prompt_v1(), imagen=img)
rb = correr("ministral-3:8b", RevisionVision,  prompt_v2(b), imagen=img)
```

## 10. Evaluación

- **Set dorado de 50 a 100 documentos** con casos difíciles: tickets térmicos, fotos torcidas, multipágina.
- Medir **precisión por campo**, no solo por documento.
- **Errores inyectados:** incluir documentos con valores deliberadamente erróneos en el JSON candidato para medir cuántos detecta cada revisor (recall) y cuántas falsas alarmas genera. Un revisor que confirma todo no aporta nada.
- Métricas clave: % de documentos que activan la vía visión, % en `needs_review`, aporte de cada revisor (correcciones válidas) y errores que pasan el árbitro sin ser detectados.
- Validar V2 (Ministral 3) frente a `qwen2.5vl:7b` y `gemma3:12b` como revisor visual.

## 11. Licencias

| Modelo | Licencia | Nota |
| --- | --- | --- |
| Qwen3.5, Qwen3-VL, Ministral 3, Granite 4.1 | Apache 2.0 | Sin restricciones relevantes |
| Gemma 3 | Gemma Terms | Tiene condiciones de uso: revisar antes de proyectos con clientes; alternativa `granite4.1:8b` |

## 12. Próximos pasos

1. Confirmar GPU/VRAM y fijar los tags de los cuatro modelos.
2. Implementar el árbitro (validadores de CUIT/CAE, aplicación de revisiones, cruce, `needs_review`).
3. Redactar y afinar los cuatro prompts con documentos reales.
4. Armar el set dorado con errores inyectados y medir la línea base (cascada vs. paralelo).
5. Calibrar umbrales de confianza, `num_ctx` y dpi con los resultados.