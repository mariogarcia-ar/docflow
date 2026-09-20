# Plan — `scripts/poc-flow-v2`

| Campo | Valor |
|---|---|
| Alcance | Migrar `scripts/poc-flow/` a `scripts/poc-flow-v2/`, incorporando las lecciones del Anexo B **como diseño**, no como anexo |
| Fuente | `my_flow.md` (flujo + Anexo A/B) · `scripts/poc-flow/` (implementación actual) · `scripts/poc/` (librerías robustas) |
| Estado | **Plan** — esperando aprobación antes de ejecutar |
| Esfuerzo | `S` / `M` / `L` por ola; sin fechas |

---

## Visión

Dos mitades, en este orden:

1. **Primero el proceso `run`** — el registro del run (trazabilidad + decisiones + resume),
   pause/resume/stop, reporte. Es plomería pura: se construye y se prueba **sobre fakes**,
   sin tocar el motor de decisión ni las validaciones. Corrige *cómo se ejecuta y se
   observa* el flujo antes de corregir *qué decide*.
2. **Después la migración de las librerías** — el motor de decisión y los adapters se
   portan y reescriben **sobre ese esqueleto ya probado**, reemplazando los fakes uno a
   uno.

La apuesta: si el proceso `run` (stages, journal, pause/resume/stop, trace, reporte) es
correcto desde el día uno, todo lo que venga después se enchufa sin volver a pensar la
plomería.

**Lo más importante es una sola cosa: saber por dónde pasó el documento, qué decisiones se
tomaron y cómo se reanuda.** Todo lo demás —el reporte, `--json`, pause/resume/stop— es una
vista o una operación sobre ese registro. Con eso, los ajustes (umbrales, reglas, prompts)
se hacen **mirando el registro**, no adivinando.

## Principio rector

> Una lección que no se convierte en código sigue siendo una opinión (B.17).

Cada fila del mapa de abajo es una obligación de diseño, no un recordatorio.

## Estrategia: proceso primero, librerías después

| Fase | Qué cierra | Lecciones que vuelve código | Requiere el motor |
|---|---|---|---|
| **A — El proceso `run`** | stages, journal, pause/resume/stop, trace, reporte, `--json` | B.1, B.2, B.3, B.4, B.5, B.6, B.14 | **No** — corre sobre fakes |
| **B — Migración de librerías** | motor de decisión portado + plomería de adapters reescrita | B.7, B.8, B.9, B.10, B.11, B.12, B.13, B.15 | Sí — reemplaza los fakes |
| **C — Gates y paridad** | alcanzabilidad (I8), deriva, mutaciones, smoke run | Anexo A, B.16 | Sí |

## Lo más importante: el registro del run

Un run deja **un registro legible y reconstruible** que responde tres preguntas, siempre:

1. **¿Por dónde pasó el documento?** — cada stage con su resultado, `ran` o `reused`, y los
   artefactos que escribió (B.2, B.3).
2. **¿Qué decisiones se tomaron?** — cada campo con su veredicto, su código de razón y las
   señales que lo sostuvieron (B.1, B.9). El registro conserva los candidatos vetados y las
   señales `UNKNOWN`: es evidencia, no un resumen.
3. **¿Cómo se reanuda?** — el journal dice qué stage está `done` y cuál quedó a medio hacer;
   la próxima corrida retoma en el primer no terminado (B.5, B.14).

El reporte y `--json` son **vistas** de ese registro; pause/resume/stop son **operaciones**
sobre él. Ninguno inventa datos: todos leen lo que el run registró.

### Forma del registro (congelada en la Ola A0)

| Stage | Registra (el artefacto del stage) | Responde |
|---|---|---|
| `read` | `material.json` — tier, route, páginas | ¿qué se leyó y por qué ruta? |
| `extract` | `extraction.json` — candidatos + señales + notas | ¿qué se extrajo, de qué fuente, qué falló? |
| `decide` | `decision.json` — veredicto, score, margen, gate, código de razón, traza | ¿por qué se tomó cada decisión? |
| `hitl` | `pending.json` — la cola de lo no confirmado | ¿qué necesita un humano? |

| Archivo | Rol | Vista/operación que lo consume |
|---|---|---|
| `journal.json` | qué stage está `done`; firma y digest | resume, pause, stop |
| `control.json` | estado del run: `running` / `paused` / `stopped` | pause, resume, stop |
| `run.json` | el trace del run: steps (`ran`/`reused`), artefactos, notas | reporte y `--json` |

`run.json` se **deriva del journal y de los artefactos**, nunca es la fuente (B.15): la
fuente es lo que cada stage registró al terminarlo. Un `run.json` autoritativo se desincroniza.

### Aceptación de la Fase A (lo que define "proceso correcto")

Un operador, ante cualquier run, puede responder las tres preguntas **sin mirar el código**:

- lee `report.py` y ve el `path` completo (`ran`/`reused`), las decisiones y qué abrir;
- mata la corrida en cualquier stage, relanza, y el documento retoma **en ese stage**;
- un ajuste (umbral, regla, prompt) se decide leyendo el registro, no reproduciendo la corrida.

### El fake y su reemplazo

La Fase A ejecuta los cuatro stages con **stubs** que devuelven valores construidos:
`read` un `Material` fijo, `extract` un `Extraction` fijo, `decide` un conjunto de
`FieldDecision` fijo, `hitl` una cola fija. Nada llama a un adapter. Lo que es real desde
el primer día es todo lo que rodea a los stages: el journal, el trace, el reporte, la
separación stdout/stderr y los comandos de control.

La Fase B reemplaza cada stub por la librería real — y los tests de la Fase A siguen
pasando sin cambios, porque el contrato de cada stage no cambió.

## Mapa lección → artefacto (por fase)

### Fase A — proceso `run`

| Lección | Qué es en v2 (obligatorio) |
|---|---|
| B.1 trazabilidad, dos salidas | `report.py` + `trace` son parte de la librería; `--json` es la salida máquina |
| B.2 stages como unidad | tabla única `STAGE_DEPENDENCIES` / `STAGE_ARTIFACTS` |
| B.3 `ran` ≠ `reused` | el trace registra `ran\|reused` como dato, siempre |
| B.4 progreso a stderr | `progress.py`, dueño único del switch; stdout sólo reporte o JSON |
| B.5 / B.14 resume | journal con 3 disparadores de flush; invalidar ≠ borrar; conjuntos ordenados en la firma |
| B.6 formateo | un `_encode` (`indent=2`); firma canónica sin indentar |
| — pause / resume / stop | estado del run como dato; `stop --force` deja el journal consistente |

### Fase B — migración de librerías

| Lección | Qué es en v2 (obligatorio) |
|---|---|
| B.7 corrida real | lane-on-demand (§6.5) cableada; `required_components` por tipo; `enum` real en el schema |
| B.8 convenciones | la librería es el entregable; un dueño por nombre de campo |
| B.9 cero no dice por qué | validadores tri-estado (I10); el reporte distingue `UNKNOWN` de `FAIL` |
| B.10 valor plausible | `verified` lo calcula el sistema, nunca el modelo |
| B.11 dos artefactos | prompt y schema viven en `registry/` (K8); test de deriva como gate |
| B.12 recorte anunciado | códigos de razón como dato; lane-on-demand dice qué falta |
| B.13 ruta por página | `material.py` decide por página, con caps anunciados |
| B.15 un dueño por forma | tipos de frontera portados sin duplicar; sin encoder propio |

### Fase C — gates

| Lección | Qué es en v2 (obligatorio) |
|---|---|
| Anexo A (I8) | test de alcanzabilidad que **falla el build** si un (campo, tier) pierde su camino |
| B.16 mutante | harness de mutaciones sobre I2 / I3 / I4 / I10 |

## Mapa de puertos

| Pieza | Destino en v2 | Acción | Fase |
|---|---|---|---|
| `scripts/poc/_mirror.py` | `flow/persist.py` | **reusar por import** (journal con 3 disparadores) | A |
| `flow/progress.py`, `flow/report.py`, `myflow.py` | igual ruta | **portar** + columna `UNKNOWN`/`FAIL` | A |
| `flow/run.py` | `flow/run.py` | **reescribir**: pause/resume/stop + lane-on-demand (§7) | A → B |
| `scripts/poc/decide.py` (routing-as-value) | `flow/route.py` | **portar** (v1 ya lo es) | B |
| `flow/fields.py`, `validators.py`, `engine.py`, `config.py`, `hitl.py` | igual ruta | **portar** (contrato de decisión) | B |
| `flow/artifacts.py` | `flow/artifacts.py` | **reescribir**: leer de `registry/` vía K8, no de `artifacts/` local | B |
| `flow/material.py` | `flow/material.py` | **reescribir**: por página + caps anunciados | B |
| `flow/extract.py` | `flow/extract.py` | **reescribir**: lane-on-demand, `enum`, `verified` por sistema | B |
| `flow/persist.py` | `flow/persist.py` | **reescribir**: delegar en `_mirror` | A |

Los artefactos de cada stage quedan congelados desde la Ola A0:

| Stage | Artefacto |
|---|---|
| `read` | `material.json`, `images/` |
| `extract` | `extraction.json` |
| `decide` | `decision.json` |
| `hitl` | `pending.json` (+ `resolution.json`, `confirmed.json`) |

## Fase A — El proceso `run` (fakes, sin motor)

### Ola A0 — Esqueleto y decisiones

- [x] Crear `scripts/poc-flow-v2/flow/`, `myflow.py` y este `plan/`
- [x] Congelar el contrato de stages (tabla de arriba) y los **stubs** de los cuatro
- [x] Definir la forma del registro: `journal.json`, `control.json`, `run.json` (tabla de arriba)
- [x] Decidir cómo se importa `_mirror`: **se reimplementó `Journal`** en `flow/journal.py`
      — `_mirror.Resume` es un journal de *walk de archivos* (una entrada por input), y el
      proceso necesita uno de *run de stages* (una entrada por stage). Reglas idénticas
      (B.5), unidad distinta. Queda como `# TODO: [MVP]` extraer lo común si un tercer
      consumidor lo pide
- [x] Definir la semántica de **pause / resume / stop**: `control.json` con estados
      `running` / `paused` / `stopped`, escrito **entre stages** — `pause`/`stop` terminan
      el stage en curso, lo marcan, escriben el estado y frenan

**Aceptación**: el árbol existe, `run` sobre fakes completa `read → extract → decide → hitl`
con `--work-root`, y `ruff check` / `ruff format --check` / `pylint` pasan sobre el esqueleto.

### Ola A1 — Journal y resume

- [x] `persist.py`: journal con invalidar ≠ borrar; firma canónica con conjuntos ordenados
      (B.5). Los 3 disparadores de flush de `_mirror` no aplican a un run de 4 stages — no hay
      walk que acotar — así que el journal se escribe atómicamente al marcar cada stage
- [x] `ran` / `reused` como dato del trace, registrado siempre (B.3)
- [x] `run.json` derivado: se reconstruye desde el journal + artefactos, nunca es la fuente

**Aceptación**: matar la corrida a mitad de un stage, relanzar, y retoma **en ese stage**
sin re-ejecutar los completados; `run.json` reconstruido es idéntico al del run completo.

### Ola A2 — Pause / resume / stop

- [x] `pause`: el run se detiene al terminar el stage en curso, dejando el journal consistente
- [x] `resume`: la siguiente invocación retoma en el primer stage no terminado
- [x] `stop --force`: deja el journal consistente (nada a medio escribir), sin pretender éxito

**Aceptación**: `pause` deja el stage en curso no-marcado, `resume` retoma exactamente ahí,
`stop --force` deja un journal que la próxima corrida lee sin rehacer lo ya hecho.

### Ola A3 — Reporte y salida

- [x] `report.py`: `path` (ran/reused), decisiones agrupadas, `read next` nombra **sólo lo escrito** (B.1)
- [x] `progress.py`: trace como dato, switch único, stderr (B.4)
- [x] `myflow.py`: reporte por defecto, `--json` / `--pretty` (B.1)
- [x] Formateo: `_encode` indentado; firma canónica sin indentar (B.6)

**Aceptación**: el reporte sobre fakes cabe en 80 columnas, `read next` lista exactamente
los artefactos escritos, y `--json` emite el `FieldResult` fijo. Un operador responde las
tres preguntas de §Lo más importante sin mirar el código.

## Fase B — Migración de librerías (reemplazar los fakes)

### Ola B1 — Motor de decisión (portar, no tocar)

- [ ] Portar `fields.py`, `validators.py`, `engine.py`, `config.py`, `route.py`
- [ ] Portar `hitl.py`
- [ ] Reemplazar los stubs de `decide` / `hitl` por los módulos portados
- [ ] Probar cada invariante con valores construidos (I2, I3, I4, I10)

**Aceptación**: los módulos puros pasan `pytest` sin adapters, y cada test de invariante
**falla al mutar** la fuente (B.16).

### Ola B2 — Plomería de adapters (reescribir)

- [ ] `artifacts.py`: leer prompt/schema de `registry/` (K8), nunca de copia local (B.15)
- [ ] `material.py`: ruta por página, cap anunciado (B.12 / B.13)
- [ ] `extract.py`: lane-on-demand, `enum` real, `verified` por el sistema (B.7 / B.10 / B.11)
- [ ] `validators.py`: `required_components` por `tipo_comprobante`; un componente no-importe
      responde `UNKNOWN`, nunca `FAIL` (B.7)
- [ ] Reemplazar los stubs de `read` / `extract`

**Aceptación**: el flujo corre sobre el fixture real con `--work-root`, y una corrida
interrumpida retoma en el stage exacto (los tests de la Fase A siguen en verde sin cambios).

## Fase C — Gates y paridad

### Ola C1 — Gates como tests de build

- [ ] Test de alcanzabilidad del Anexo A (I8): falla el build si un (campo, tier) pierde su camino
- [ ] Test de deriva prompt↔schema sobre el registry (B.11)
- [ ] Harness de mutaciones para I2 / I3 / I4 / I10 (B.16)
- [ ] Test de journal: 3 disparadores de flush, invalidación ≠ borrado, firma canónica

**Aceptación**: `pytest` incluye las cuatro gates, y cada una se demuestra **roja** al
romper su invariante.

### Ola C2 — Smoke run y paridad

- [ ] Smoke run sobre `66cd35e9-…pdf` con **paridad** de decisiones contra v1
- [ ] Reporte con columna `UNKNOWN` / `FAIL` (B.9)

**Aceptación**: el smoke run reproduce las decisiones de v1 (mismos `CONFIRMED` / `REVIEW` /
`ESCALATE` con los mismos códigos de razón), el reporte cabe en 80 columnas, y los cuatro
QA gates pasan.

## Criterio de cierre

1. **Proceso `run` probado sobre fakes** — journal, pause/resume/stop, trace `ran|reused`,
   reporte y `--json` funcionan **antes** de conectar el motor (gate de la Fase A).
2. **Registro legible** — un operador responde las tres preguntas (¿por dónde pasó?, ¿qué se
   decidió?, ¿cómo se reanuda?) sin mirar el código ni reproducir la corrida.
3. **Paridad** — v2 reproduce las decisiones de v1 sobre el fixture.
4. **Gates nuevas en verde** — alcanzabilidad (Anexo A), deriva prompt↔schema, mutaciones, journal.
5. **Ninguna lección sin artefacto** — toda fila del mapa lección → artefacto tiene código que la respalda.

## Fuera de alcance

- Aprendizaje (§9: templates, calibración, auditoría) → `# TODO: [MVP]`
- QR (§4.2) → `# TODO: [MVP]`
- Golden set → `# TODO: [MVP]` (circular si lo gradúa el mismo modelo)
- `scripts/poc-flow/` no se modifica: v2 se construye al lado y v1 queda como referencia hasta el cierre

## Cómo ejecutar

En orden de fases y olas. La Fase A no necesita modelos: cierra con los cuatro QA gates
(`pytest`, `ruff check`, `ruff format --check`, `pylint`) sobre fakes. La Fase B reemplaza
los fakes sin cambiar su contrato. No se avanza de ola sin la aceptación de la anterior.
