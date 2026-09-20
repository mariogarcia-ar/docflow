# `scripts/poc-flow-v2/` — el proceso de ejecución, reconstruido

v2 es la **segunda versión** del flujo de `my_flow.md`, construida sobre las
lecciones del Anexo B. La diferencia con v1 es de método: **primero el proceso
`run`** (trazabilidad, journal, pause/resume/stop, reporte), probado sobre fakes,
y **después** la migración de las librerías. El plan está en
[`plan/README.md`](plan/README.md).

Esto **no** es `scripts/poc-flow/` (que se mantiene como referencia) ni
`scripts/poc/` (el banco de kernels). Es la capa que responde *por dónde pasó el
documento, qué se decidió y cómo se reanuda*.

```bash
python scripts/poc-flow-v2/myflow.py <document>            # el reporte
python scripts/poc-flow-v2/myflow.py <document> --json     # el resultado, máquina
python scripts/poc-flow-v2/myflow.py <document> --pretty   # el resultado, indentado
```

## Estado actual — Fase A completa

La **Fase A** (el proceso `run`) está implementada y cerrada. Las fases **B**
(migración del motor de decisión y adapters) y **C** (gates y paridad) están
planificadas, no ejecutadas. Mientras tanto, los cuatro stages corren sobre
**stubs** (`flow/stubs.py`) que devuelven valores fijos: el proceso es real, el
motor es falso.

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

La librería es el entregable; `myflow.py` es un cliente. El punto de entrada:

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
| `report.py` | el reporte del operador | B.1 |
| `stubs.py` | los cuatro stages falsos de la Fase A | — |
| `fields.py` | el contrato de datos (`FieldResult`, …), portado de v1 | — |

## Por qué el journal no reusa `_mirror`

`scripts/poc/_mirror.py::Resume` es un journal de **walk de archivos** — una
entrada por input, con tres disparadores de flush (conteo, tiempo, `atexit`).
El proceso `run` necesita uno de **run de stages** — una entrada por stage — y
en un run de cuatro stages no hay un walk que acotar. Se reimplementó `Journal`
con las reglas idénticas de B.5 y unidad distinta. Si un tercer consumidor
pidiera lo común, habría que extraerlo (`# TODO: [MVP]`).

## Quality gates

```bash
pytest tests/poc_flow_v2                      # los tests de la Fase A
ruff check scripts/poc-flow-v2 tests/poc_flow_v2
ruff format --check scripts/poc-flow-v2 tests/poc_flow_v2
pylint scripts/poc-flow-v2/flow scripts/poc-flow-v2/myflow.py tests/poc_flow_v2
```

Los tests de la Fase A (`tests/poc_flow_v2/test_process.py`) ejercitan el proceso
sobre stubs, nunca sobre un adapter: un test de proceso que necesitara un modelo
probaría el modelo, no el proceso. Cubren artefactos por stage, reuso, `redo`,
`pause`, `resume`, `stop`, el record derivado, el artifact faltante que derrota al
journal, y el input cambiado que descarta el journal.

## Qué falta (Fase B y C)

- **Fase B** — portar el motor de decisión (`fields`, `validators`, `engine`,
  `config`, `route`) y reescribir la plomería (`artifacts` desde el registry,
  `material` por página, `extract` con lane-on-demand, `validators` con
  `required_components`), reemplazando los stubs uno a uno.
- **Fase C** — gates como tests de build (alcanzabilidad del Anexo A, deriva
  prompt↔schema, mutaciones de invariantes) y el smoke run con **paridad** contra
  v1.

El detalle está en [`plan/README.md`](plan/README.md).
