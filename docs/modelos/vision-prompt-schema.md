Sí, existen los dos tipos, aunque en visión los instruct son mayoría y los reasoning son más nuevos y menos comunes.

## Instruct (la mayoría)

De tu lista, `qwen2.5vl:7b` y `3b`, `gemma3:12b` y `4b`, y `granite3.2-vision:2b` son instruct. Responden directo, sin bloque de razonamiento. `deepseek-ocr:3b` es un caso aparte: es OCR puro.

Fuera de tu lista están `llama3.2-vision`, `minicpm-v` y `mistral-small3.x`.

## Reasoning / thinking

- **`qwen3-vl`** tiene variantes instruct y thinking, y es la más relevante para tu stack.
- **`qwq`/`QVQ`** son versiones de razonamiento visual de Qwen, pero más experimentales y pesadas.
- **Híbridos:** algunas familias nuevas traen visión y modo thinking en el mismo modelo, con un switch. No estoy seguro de que `qwen3.5:9b` sea así, y lo más rápido es mirarlo localmente:

```bash
ollama show qwen3.5:9b
```

En la sección **Capabilities** aparece `vision` y/o `thinking` si el modelo las soporta. Es la forma más confiable de saberlo para cada modelo que tenés.

## Cómo se controla en Ollama

En los modelos con `thinking` hay un parámetro para activarlo o apagarlo:

```python
resp = ollama.chat(
    model="qwen3.5:9b",
    messages=[...],
    format=SCHEMA,
    think=False,   # True para razonar; el razonamiento llega en message.thinking
)
```

En CLI: `ollama run <modelo> --think=false`, o `/set nothink` en modo interactivo.

## Cuál conviene para extracción

Para **extraer** (transcribir lo que se ve), instruct. El razonamiento no mejora la lectura de un CUIT o un total, agrega latencia y aumenta el riesgo de bucles o de que ignore el schema. Es el mismo problema que viste con `deepseek-r1:8b` en la etapa de review.

Un modelo thinking o un híbrido con `think=True` tiene más sentido en la **etapa de revisión**: cruzar campos, verificar `subtotal + iva == total`, decidir entre dos lecturas contradictorias. Eso encaja con tu separación de extracción y revisión con modelos y prompts distintos.

Como ya tenés dos prompts según instruct o reason, si usás un híbrido con thinking apagado se comporta como instruct y le sirve el prompt de instruct.