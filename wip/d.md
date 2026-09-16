# Nota técnica: validación con Pydantic

Pendiente para cuando encaremos la implementación.

## La regla

Auditar no es normalizar. Son dos pasos separados y no deben compartir modelo.

| Paso | Qué hace | Con qué |
|------|----------|---------|
| **Auditar** | Registra qué devolvió el modelo, sin convertir ni completar | Modelo sin tipos de negocio, sin defaults |
| **Normalizar** | Convierte a `Decimal`, `date`, etc. | Código aparte, solo sobre lo auditable |

Mezclarlos hace que la coerción ocurra antes de poder ver qué salió del modelo. El dato crudo se pierde y solo queda el resultado convertido.

## Qué se rompe si no se respeta

**Los defaults fabrican datos.** Un campo `total: Decimal = 0` convierte "el modelo no lo devolvió" en `0`. Sin error, sin aviso.

**La coerción oculta el error.** `"15.400,00"` o `"N/A"` en un campo numérico se convierten o fallan, pero en ningún caso ves el valor original.

**Tres casos distintos se confunden en uno.** Son cosas diferentes y Pydantic las distingue:

- campo ausente → no está en `model_fields_set`
- `null` explícito → está en el set, valor `None`
- valor presente → está en el set, valor real

Con defaults, el primero se vuelve indistinguible del tercero.

## Modelo de observación

Campos `str | None`, `extra="forbid"`, **ninguno con default**.

```python
class Observacion(BaseModel):
    """Lo que el documento dice, sin interpretar."""
    model_config = ConfigDict(extra="forbid")

    total: str | None
    fecha: str | None
    moneda: str | None
```

El diagnóstico sale de `model_fields_set` y de `errors()`, no del objeto convertido.

## El valor crudo

`errors()` devuelve por cada falla:

| Campo | Qué trae |
|-------|----------|
| `loc` | Qué campo falló |
| `type` | Identificador del tipo de error |
| `input` | **El valor crudo que devolvió el modelo** |
| `ctx` | Contexto para renderizar el mensaje |

`input` es el dato que interesa para diagnóstico: el valor tal como salió del modelo, antes de cualquier conversión. Alimenta directo la métrica de F1 por tipo de error.

## Strict: campo por campo

Nunca `strict=True` en el modelo completo contra un LLM. Los modelos devuelven números como string con frecuencia, así que en strict esos casos se vuelven errores, los reintentos se disparan, y el costo y la latencia se inflan.

Laxo en el borde, `Field(strict=True)` solo donde la coerción ocultaría un error real.

## Restricciones a tener presentes

- `experimental_allow_partial` (validar solo lo presente sin fallar por lo ausente) **solo funciona con `TypeAdapter`, no con `BaseModel`**. Definir antes de elegir.
- OpenAI Structured Outputs soporta un subconjunto de JSON Schema: `minimum`, `maximum`, `minLength`, `maxLength` se eliminan antes de enviarse y pasan a las descripciones de campo. El modelo las ve como instrucciones; Pydantic las valida en la respuesta.
- Sin tipos recursivos. Mantener los modelos planos.
- La primera llamada con un esquema nuevo compila una gramática en el proveedor (~10 s). Las siguientes son rápidas.
- Nunca `model_construct()` con datos externos: saltea la validación entera.

## Lo que sí conviene usar

**El esquema como contrato.** `model_json_schema()` genera el JSON Schema que se pasa al proveedor. `ConfigDict(extra="forbid")` es obligatorio para que el JSON Schema lleve `additionalProperties: false`.

**`Literal[...]` para enumeraciones.** Evita que el modelo devuelva `"visa"` cuando definiste `cash | credit | debit`.

**`Field(description=...)` como prompt.** Las descripciones viajan al modelo dentro del esquema. Las reglas dejan de ser prosa suelta.

**Aritmética entre campos.** `model_validator(mode='after')` para verificar subtotal + impuestos = total, con tolerancia de redondeo y mensaje que incluya los valores reales.

Dos usos que valen la pena: validar los tres flujos contra el mismo esquema (hace comparables las arquitecturas sobre el mismo set dorado), y trazas con Logfire (responde por qué un documento se extrajo mal y por qué subió el costo).

## Archivos relacionados

`a.md`, `b.md`, `c.md` — los tres flujos. `README.md` — flujos primarios y comparación.
