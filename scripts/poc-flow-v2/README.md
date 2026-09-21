# `scripts/poc-flow-v2/` — el proceso de ejecución, reconstruido

v2 es la implementación **única y vigente** del flujo de `my_flow.md`. Nació como segunda
versión construida sobre las lecciones del Anexo B, y su diferencia con el predecesor era de
método: **primero el proceso `run`** (trazabilidad, journal, pause/resume/stop, reporte),
probado sobre fakes, y **después** la migración de las librerías. El plan está en
[`plan/README.md`](plan/README.md).

Esto **no** es `scripts/poc/` (el banco de kernels). Es la capa que responde *por dónde pasó
el documento, qué se decidió y cómo se reanuda*. El predecesor —`scripts/poc-flow/`— se
retiró al cerrar la migración: v2 es su reemplazo, y lo que quedaba vivo de v1 (los
artefactos de prompt y schema) vive en `registry/` y se lee por K8.

```bash
python scripts/poc-flow-v2/myflow.py <document>            # el reporte
python scripts/poc-flow-v2/myflow.py <document> --json     # el resultado, máquina
python scripts/poc-flow-v2/myflow.py <document> --pretty   # el resultado, indentado
```

**Una sola pregunta, sin correr todo el pipeline** — *dado este documento y este
prompt, qué dice el modelo local*. `--prompt` es obligatorio; el schema es
opcional y sin él la respuesta sólo tiene que ser un objeto, porque es el prompt
el que pide la forma:

```bash
# el documento y un prompt, que es toda la interfaz
python scripts/poc-flow-v2/myllmlocal.py tests/fixtures-txt/casos/<doc>.txt \
  --prompt registry/prompts/extraction/invoice_deteccion.txt

# otro modelo, tal como lo nombra el runtime
python scripts/poc-flow-v2/myllmlocal.py <document> --prompt <file> \
  --model gemma3:1b

# un schema propio, cuando querés restringir la generación
python scripts/poc-flow-v2/myllmlocal.py <document> --prompt <file> \
  --schema registry/schemas/extraction/invoice_detection.json

# la ruta la elige el tipo de documento, así que no lleva flag
python scripts/poc-flow-v2/myllmlocal.py tests/fixtures-txt/casos/<doc>.txt \
  --prompt <file>
python scripts/poc-flow-v2/myllmlocal.py tests/fixtures/casos/<doc>.pdf \
  --prompt <file>
python scripts/poc-flow-v2/myllmlocal.py tests/fixtures/casos/<doc>.jpg \
  --prompt <file>

# leer la respuesta con jq, porque stdout es un solo objeto JSON
python scripts/poc-flow-v2/myllmlocal.py <document> --prompt <file> --pretty \
  | jq .answer
python scripts/poc-flow-v2/myllmlocal.py <document> --prompt <file> \
  | jq -r .refusal

# una ventana más grande: el flujo declara 8192 y un valor exportado gana
DOCFLOW_OLLAMA_NUM_CTX=16384 python scripts/poc-flow-v2/myllmlocal.py <document> \
  --prompt <file>
```

`--model` es el único *dial*; `--prompt` y `--schema` son *entradas*, y por eso
ninguno se deriva del otro: emparejarlos acá sería este cliente decidiendo qué
pregunta hizo el llamador. Sin `--prompt`/`--schema` **no** se lee el registry.

La ruta del documento a texto es la del flujo, nunca un segundo lector: un `.txt`
se lee tal cual, un PDF con capa de texto pasa por `pdftotext -layout`, una página
sin capa se renderiza y va a OCR, y una imagen pasa por el filtro de legibilidad y
OCR. Sólo se envía **texto** — la lane de visión es la de `myflow.py`. `stdout` es
**un** objeto JSON; la ruta, el modelo y la ventana van a `stderr`.
Códigos de salida: `0` valor, `2` rechazo tipado, `4` invocación mal formada.

**Qué NO hace**: no clasifica el documento (`flow.classify` decide si la *corrida*
procede, y eso es una decisión del pipeline, no de una llamada al modelo) y no
corre las lanes, el engine de decisión ni el resolver. Es un probe.

**Ver cada circuito de `my_flow.md` en acción** — clasificar, las lanes, `verified`,
la aritmética, lane-on-demand, el resolver, el frontier y el HITL, uno por uno con su
comando y su salida: [`quickstart-flows.md`](quickstart-flows.md). Incluye qué
circuitos todavía **no** se ven desde el CLI (C3 QR y C9 aprender) y por qué.

## Estado — migración cerrada

Las tres fases del plan están ejecutadas:

- **Fase A** — el proceso `run`: stages, journal, pause/resume/stop, trace, reporte.
- **Fase B** — el motor de decisión portado y la plomería real: `read` y `extract`
  llaman a los adapters, el prompt y el schema se leen del registry (K8), y `decide`
  corre el motor.
- **Fase C** — gates como tests de build (alcanzabilidad I8, deriva prompt↔schema,
  journal) con prueba de mutación, y paridad del **motor** verificada contra el predecesor.

Queda diferido, declarado y no silencioso (`# TODO: [MVP]`): el split por rol/lane
en el registry (review y vision lane) y `required_components` por `tipo_comprobante`.
El detalle está en [`plan/README.md`](plan/README.md).

## Las tres preguntas que el run responde

1. **¿Por dónde pasó el documento?** — cada stage con `ran` o `reused`, su
   resultado y los artefactos que escribió.
2. **¿Qué decisiones se tomaron?** — cada campo con veredicto, código de razón y
   señales; los vetados y los `UNKNOWN` se conservan como evidencia.
3. **¿Cómo se reanuda?** — el journal dice qué stage está `done` y cuál quedó a
   medio hacer; la próxima corrida retoma en el primero no terminado.

El reporte y `--json` son **vistas** de ese registro; pause/resume/stop son
**operaciones** sobre él. Ninguno inventa datos.

## Uso

```bash
# run completo, persistiendo el registro en un work root:
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<doc>

# segunda corrida: reusa los stages terminados, retoma en el primero pendiente:
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<doc>

# pausar tras el stage en curso (journal consistente):
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<doc> --pause

# detener tras el stage en curso, marcando el run como detenido:
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<doc> --stop

# re-ejecutar todo, ignorando el journal:
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<doc> --redo

# progreso en vivo (stderr; stdout sigue siendo el reporte):
python scripts/poc-flow-v2/myflow.py <document> --work-root var/work/<doc> --verbose
```

### El reporte

```
document: 66cd35e9-…pdf
work root: /tmp/v2-work

path
  1. read      ran     read ran
  2. extract   ran     extract ran
  3. decide    ran     decide ran
  4. hitl      ran     hitl ran

confirmed (1)
  alta    cuit_emisor                    20-12345678-3  CONF_SCORE_MARGIN_GATE

review (1)
  critica importe_total_facturado        17.898,30      REV_GATE_UNMET
      why: score 2 meets the floor but strong evidence is missing

read next
  /tmp/v2-work/pending.json  (1 field(s)) — the fields a human must settle
  /tmp/v2-work/decision.json — every decision, with the signals behind it

notes
  - stub: no model ran
```

En una corrida reanudada, `path` cambia a `reused`:

```
  1. read      reused  reused from material.json
  2. extract   reused  reused from extraction.json
  3. decide    reused  reused from decision.json
  4. hitl      reused  reused from pending.json
```

`read next` nombra **sólo los archivos que se escribieron**; una ruta que no
existe no es una instrucción, es una adivinanza.

## El work root

Un work root contiene:

```
material.json    lo que produjo `read`            (stage: read)
extraction.json  lo que produjo `extract`         (stage: extract)
decision.json    las decisiones de `decide`       (stage: decide)
pending.json     la cola de `hitl`                (stage: hitl)
journal.json     qué stages están `done`          (fuente del resume)
control.json     el estado: running/paused/stopped (fuente del pause/stop)
run.json         el trace derivado del journal     (vista, nunca fuente)
```

Tres reglas del registro, heredadas del Anexo B:

- **`run.json` se deriva** del journal y los artefactos; nunca es la fuente
  (B.15). Si se borra, se reconstruye.
- **Un stage se marca `done` sólo después** de escribir su artefacto; una
  escritura atómica (temp + rename) evita que un kill trunque el archivo (B.5).
- **Invalidar no es borrar**: re-correr un stage marca ese y los posteriores como
  no-hechos, pero deja los archivos — el journal deja de confiar en ellos (B.5).

## La biblioteca

La librería es el entregable; `myflow.py` y `myllmlocal.py` son clientes. El punto
de entrada:

```python
from flow import render_report, run, trace

outcome = run(path, {}, work_root=pathlib.Path("var/work/doc"))
print(render_report(path, outcome.result, outcome.steps))
```

| Módulo | Qué posee | Lección |
|---|---|---|
| `stages.py` | nombres, dependencias y artefactos de los cuatro stages, en **una** tabla | B.2, B.15 |
| `journal.py` | journal de stages: firma canónica, digest, invalidar ≠ borrar | B.5, B.14 |
| `control.py` | `control.json`: `running` / `paused` / `stopped` | pause/stop |
| `record.py` | `run.json` derivado: el trace como dato | B.15 |
| `work.py` | el work tree: único dueño de los nombres de archivo | B.2, B.15 |
| `serial.py` | única serialización del contrato de datos | B.6, B.15 |
| `run.py` | el proceso: corre/reusa, marca el journal, escribe el record | B.3, B.4 |
| `progress.py` | trace en vivo a stderr, switch único | B.4 |
| `report.py` | el reporte del operador, con columna `FAIL`/`UNKNOWN` | B.1, B.9 |
| `fields.py` | el contrato de datos (`FieldResult`, `Extraction`, …) | — |
| `config.py` | los diales: umbrales, severidades, puntos por familia | — |
| `route.py` | la decisión de ruta, pura | B.13 |
| `validators.py` | CUIT, fecha, aritmética — PASS / FAIL / UNKNOWN | I10 |
| `engine.py` | el consenso MoE: merge, veto, score, gate | I2/I3/I4/I10 |
| `material.py` | lee el documento a través de los adapters, por página | B.13 |
| `extract.py` | candidatos: regexp + lane A (modelo local + registry) | B.10 |
| `artifacts.py` | prompt y schema desde el registry (K8) | B.11, B.15 |
| `hitl.py` | la cola de lo no confirmado, y las confirmaciones | I6 |

## Por qué el journal no reusa `_mirror`

`scripts/poc/_mirror.py::Resume` es un journal de **walk de archivos** — una
entrada por input, con tres disparadores de flush (conteo, tiempo, `atexit`).
El proceso `run` necesita uno de **run de stages** — una entrada por stage — y
en un run de cuatro stages no hay un walk que acotar. Se reimplementó `Journal`
con las reglas idénticas de B.5 y unidad distinta. Si un tercer consumidor
pidiera lo común, habría que extraerlo (`# TODO: [MVP]`).

## Quality gates

```bash
pytest tests/poc_flow_v2                      # proceso, invariantes y gates
python -B tests/poc_flow_v2/mutation_invariants.py  # los invariantes fallan al mutar
ruff check scripts/poc-flow-v2 tests/poc_flow_v2
ruff format --check scripts/poc-flow-v2 tests/poc_flow_v2
pylint scripts/poc-flow-v2/flow scripts/poc-flow-v2/myflow.py tests/poc_flow_v2
```

Tres suites cubren las tres capas:

- `test_process.py` — el proceso: artefactos por stage, reuso, `redo`, `pause`,
  `resume`, `stop`, el record derivado, el artifact faltante que derrota al
  journal, y el input cambiado que descarta el journal.
- `test_invariants.py` — I2 (merge por valor), I3 (veto), I4 (tope por familia),
  I10 (`UNKNOWN` no puntúa ni veta).
- `test_gates.py` — alcanzabilidad del Anexo A (I8), deriva prompt↔schema (B.11)
  y journal (B.5); cada una demostrada roja al romper su fuente (B.16).

Los tests de proceso corren sobre entradas ilegibles (bytes que ningún adapter
lee), así que degradan rápido y no pagan modelos: un test de proceso que
necesitara un modelo probaría el modelo, no el proceso.

## Paridad con el predecesor

Dado el mismo set de candidatos, el motor de v2 produjo **las mismas decisiones,
scores y códigos de razón** que `scripts/poc-flow/` (verificado por subproceso
mientras ambos coexistían). La paridad de salidas no se persigue: el modelo local
`deepseek-r1:1.5b` no es determinístico, y dos corridas devuelven valores distintos
(`my_flow.md` B.7). La paridad que se garantiza es la del motor, que es lo que la
migración portó.

Esa comparación por subproceso fue una verificación de una sola vez, no un test
del repo: con el predecesor retirado ya no es re-ejecutable. La paridad que hoy
queda **vigilada** es la de los invariantes (I2, I3, I4, I10), que
`test_invariants.py` guarda con valores construidos y
`mutation_invariants.py` demuestra roja al mutar la fuente.
