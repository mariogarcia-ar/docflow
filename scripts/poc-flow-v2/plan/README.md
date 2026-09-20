# Plan — `scripts/poc-flow-v2`

| Campo | Valor |
|---|---|
| Alcance | Migrar `scripts/poc-flow/` a `scripts/poc-flow-v2/`, incorporando las lecciones del Anexo B **como diseño**, no como anexo |
| Fuente | `my_flow.md` (flujo + Anexo A/B) · `scripts/poc-flow/` (implementación actual) · `scripts/poc/` (librerías robustas) |
| Estado | **Plan** — esperando aprobación antes de ejecutar |
| Esfuerzo | `S` / `M` / `L` por ola; sin fechas |

---

## Visión

El mismo flujo (leer → extraer → decidir → revisar) reconstruido para que cada lección
del Anexo B sea un **componente del código** —un test, un campo del reporte, un
invariante— y no una nota al pie. Las piezas que ya demostraron ser robustas
(`_mirror.py`, routing-as-value, política leída del registry) se **reusan**; la lógica de
decisión se **porta**; la plomería que quedó forzada se **reescribe**.

## Principio rector

> Una lección que no se convierte en código sigue siendo una opinión (B.17).

Cada fila del mapa de abajo es una obligación de diseño, no un recordatorio.

## Mapa lección → artefacto v2

| Lección | Qué es en v2 (obligatorio) |
|---|---|
| B.1 trazabilidad, dos salidas | `report.py` + `trace` son parte de la librería; `--json` es la salida máquina |
| B.2 stages como unidad | tabla única `STAGE_DEPENDENCIES` / `STAGE_ARTIFACTS` |
| B.3 `ran` ≠ `reused` | el trace registra `ran\|reused` como dato, siempre |
| B.4 progreso a stderr | `progress.py`, dueño único del switch; stdout sólo reporte o JSON |
| B.5 / B.14 resume | `persist.py` delega en `_mirror.py` (3 disparadores de flush); invalidar ≠ borrar; conjuntos ordenados en la firma |
| B.6 formateo | un `_encode` (`indent=2`); firma canónica sin indentar |
| B.7 corrida real | lane-on-demand (§6.5) cableada; `required_components` por tipo; `enum` real en el schema |
| B.8 convenciones | la librería es el entregable; un dueño por nombre de campo |
| B.9 cero no dice por qué | validadores tri-estado (I10); el reporte distingue `UNKNOWN` de `FAIL` |
| B.10 valor plausible | `verified` lo calcula el sistema, nunca el modelo |
| B.11 dos artefactos | prompt y schema viven en `registry/` (K8); test de deriva como gate |
| B.12 recorte anunciado | códigos de razón como dato; lane-on-demand dice qué falta |
| B.13 ruta por página | `material.py` decide por página, con caps anunciados |
| B.15 un dueño por forma | tipos de frontera portados sin duplicar; sin encoder propio |
| B.16 mutante | harness de mutaciones sobre I2 / I3 / I4 / I10 |
| Anexo A (I8) | test de alcanzabilidad que **falla el build** si un (campo, tier) pierde su camino |

## Mapa de puertos

| Pieza | Destino en v2 | Acción |
|---|---|---|
| `scripts/poc/_mirror.py` | `flow/persist.py` | **reusar por import** (journal con 3 disparadores) |
| `scripts/poc/decide.py` (routing-as-value) | `flow/route.py` | **portar** (v1 ya lo es) |
| `flow/fields.py`, `validators.py`, `engine.py`, `config.py`, `hitl.py` | igual ruta | **portar** (contrato de decisión) |
| `flow/artifacts.py` | `flow/artifacts.py` | **reescribir**: leer de `registry/` vía K8, no de `artifacts/` local |
| `flow/material.py` | `flow/material.py` | **reescribir**: por página + caps anunciados |
| `flow/extract.py` | `flow/extract.py` | **reescribir**: lane-on-demand, `enum`, `verified` por sistema |
| `flow/persist.py` | `flow/persist.py` | **reescribir**: delegar en `_mirror` |
| `flow/progress.py`, `flow/report.py`, `myflow.py` | igual ruta | **portar** + columna `UNKNOWN`/`FAIL` |
| `flow/run.py` | `flow/run.py` | **reescribir**: lane-on-demand + resolver loop (§7) |

Los artefactos de cada stage quedan congelados desde la Ola 0:

| Stage | Artefacto |
|---|---|
| `read` | `material.json`, `images/` |
| `extract` | `extraction.json` |
| `decide` | `decision.json` |
| `hitl` | `pending.json` (+ `resolution.json`, `confirmed.json`) |

## Olas

### Ola 0 — Esqueleto y decisiones

- [ ] Crear `scripts/poc-flow-v2/flow/`, `myflow.py` y este `plan/`
- [ ] Decidir cómo se importa `_mirror`: por path desde `scripts/poc/` (PoC) o extraído a
      módulo compartido — marcado `# TODO: [MVP]` si es por path
- [ ] Decidir el split por rol/lane (texto/vision × extract/review) del prompt dentro del
      registry, sin copia local
- [ ] Anotar en este plan el contrato de artefactos por stage (tabla de arriba)

**Aceptación**: el árbol existe, las decisiones están anotadas, y `ruff check`,
`ruff format --check`, `pylint` pasan sobre el esqueleto.

### Ola 1 — El motor de decisión (portar, no tocar)

- [ ] Portar `fields.py`, `validators.py`, `engine.py`, `config.py`, `route.py`
- [ ] Portar `hitl.py`
- [ ] Probar cada invariante con valores construidos (I2, I3, I4, I10)

**Aceptación**: los módulos puros pasan `pytest` sin adapters, y cada test de invariante
**falla al mutar** la fuente (B.16).

### Ola 2 — La plomería reescrita

- [ ] `artifacts.py`: leer prompt/schema de `registry/` (K8), nunca de copia local (B.15)
- [ ] `material.py`: ruta por página, cap anunciado (B.12 / B.13)
- [ ] `extract.py`: lane-on-demand, `enum` real, `verified` por el sistema (B.7 / B.10 / B.11)
- [ ] `validators.py`: `required_components` por `tipo_comprobante`; un componente no-importe
      responde `UNKNOWN`, nunca `FAIL` (B.7)
- [ ] `persist.py`: journal delegado en `_mirror` (B.5 / B.14)

**Aceptación**: el flujo corre `read → extract → decide → hitl` sobre el fixture con
`--work-root`, y una corrida interrumpida retoma en el stage exacto.

### Ola 3 — Las gates como tests de build

- [ ] Test de alcanzabilidad del Anexo A (I8): falla el build si un (campo, tier) pierde su camino
- [ ] Test de deriva prompt↔schema sobre el registry (B.11)
- [ ] Harness de mutaciones para I2 / I3 / I4 / I10 (B.16)
- [ ] Test de journal: 3 disparadores de flush, invalidación ≠ borrado, firma canónica

**Aceptación**: `pytest` incluye las cuatro gates, y cada una se demuestra **roja** al
romper su invariante.

### Ola 4 — Reporte y cierre

- [ ] `report.py`: columna que distingue `UNKNOWN` de `FAIL` (B.9); `read next` nombra sólo lo escrito (B.1)
- [ ] `progress.py`: trace como dato (B.3 / B.4)
- [ ] `myflow.py`: reporte por defecto, `--json` / `--pretty` (B.1)
- [ ] Smoke run sobre `66cd35e9-…pdf` con **paridad** de decisiones contra v1

**Aceptación**: el smoke run reproduce las decisiones de v1 (mismos `CONFIRMED` / `REVIEW` /
`ESCALATE` con los mismos códigos de razón), el reporte cabe en 80 columnas, y los cuatro
QA gates pasan.

## Criterio de cierre

1. **Paridad** — v2 reproduce las decisiones de v1 sobre el fixture.
2. **Gates nuevas en verde** — alcanzabilidad (Anexo A), deriva prompt↔schema, mutaciones, journal.
3. **Ninguna lección sin artefacto** — toda fila del mapa lección → artefacto tiene código que la respalda.

## Fuera de alcance

- Aprendizaje (§9: templates, calibración, auditoría) → `# TODO: [MVP]`
- QR (§4.2) → `# TODO: [MVP]`
- Golden set → `# TODO: [MVP]` (circular si lo gradúa el mismo modelo)
- `scripts/poc-flow/` no se modifica: v2 se construye al lado y v1 queda como referencia hasta el cierre

## Cómo ejecutar

En orden de olas. Cada ola cierra con sus cuatro QA gates (`pytest`, `ruff check`,
`ruff format --check`, `pylint`) y con la prueba de mutación de su invariante. No se avanza
de ola sin la aceptación de la anterior.
