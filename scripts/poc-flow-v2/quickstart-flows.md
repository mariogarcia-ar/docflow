# Quickstart — los circuitos de `my_flow.md`, uno por uno

Esta página muestra **cómo ver cada circuito** de `my_flow.md` corriendo el flujo
real, con la salida citada de invocaciones hechas en este workspace.

La contracara del Anexo B: una lección que no se puede **observar** sigue siendo una
opinión (B.17). Acá cada circuito tiene un comando y una salida que lo delata.

> **Los números que se citan abajo salen de una corrida real y varían entre corridas.**
> El modelo local `deepseek-r1:1.5b` no es determinístico; dos corridas devuelven
> valores distintos (`my_flow.md` B.7). Lo que es estable es la **forma** del reporte,
> los **códigos de razón** y los **artefactos** — no los valores extraídos.

---

## Estado — qué se puede ver hoy, y qué no

Tres estados, y la diferencia importa: un circuito **cableado** se ve desde el CLI;
uno que vive **solo en el módulo** tiene código y test pero el `run` no lo llama; uno
**diferido** está declarado como `# TODO: [MVP]`.

| Circuito | § | Estado | Cómo se ve |
|---|---|---|---|
| Los 4 stages (`read`→`extract`→`decide`→`hitl`) | §1 | **cableado** | `path` en el reporte |
| C1 clasificar (fast-fail) | §3 | **cableado** | nota `classified out:` |
| C2 lanes (texto/vision, A/B) | §4.1 | **cableado** | `producers` y `CROSS_MODAL` en `decision.json` |
| C3 QR | §4.2 | **solo módulo** | `flow/qr.py` + `test_c3_*`; el `run` no lo llama |
| C4 `verified` real | §4.2 | **cableado** | `DOCUMENT_CONTENT` en las señales |
| C5 grupos de consistencia | §6.4 | **cableado** | `ESC_NO_UNIQUE_ARITHMETIC_COMBINATION` |
| C6 lane-on-demand | §6.5 | **parcial** | nota `lane-on-demand deferred:` |
| C7 resolver (loop → motor) | §7 | **cableado** | `ESC_NO_NEW_EVIDENCE` en notas |
| C8 frontier + HITL | §8 | **cableado** | `--resolve`, `--confirm` |
| C9 aprender | §9 | **solo módulo** | `flow/learn.py` + `test_c9_*`; el `run` no lo llama |

El detalle de cada brecha está en [`plan/cierre-circuitos.md`](plan/cierre-circuitos.md),
que es donde vive el inventario completo.

---

## Antes de empezar — los modelos

El flujo corre contra **Ollama local** (§4.1) y contra el **frontier** (§8). Sin
modelos, los stages corren igual pero las lanes se niegan con una nota — que es lo
correcto: una negativa es una nota, nunca un valor por defecto (`my_flow.md` §4.1).

```bash
ollama list
```

Los diales están en `flow/config.py`. **Los tags del config y los que hay pulled no
siempre coinciden**, y el desajuste es silencioso en el reporte (una nota, no un
error):

| Dial | `config.py` pide | En este workspace | Efecto |
|---|---|---|---|
| `TEXT_MODEL_A` | `deepseek-r1:1.5b` | pulled | lane A texto corre |
| `TEXT_MODEL_B` | `gemma3` | pulled como `gemma3:1b` | **lane B texto se calla** |
| `VISION_MODEL_A` | `qwen2.5vl:3b` | pulled | lane A vision corre |
| `VISION_MODEL_B` | `granite-vision:2b` | **no pulled** | lane B vision se niega |
| `FRONTIER_MODEL` | `deepseek:deepseek-v4-pro` | sin credencial | `--resolve` se niega |

El desajuste de lane B se ve en el reporte como
`- text lane B produced no review verdicts`, y se confirma con:

```bash
curl -s http://localhost:11434/api/generate -d '{"model":"gemma3","prompt":"hi","stream":false}'
# {"error":"model 'gemma3' not found"}
```

---

## El reporte — dónde se ve todo

Toda la página es una variación de este comando:

```bash
python scripts/poc-flow-v2/myflow.py tests/fixtures/casos/66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf \
    --work-root var/work/caso
```

```
document: 66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf
work root: var/work/caso

path
  1. read      ran     read ran
  2. extract   ran     17 field(s) with candidates
  3. decide    ran     17 field(s) decided, 2 confirmed
  4. hitl      ran     15 field(s) pending

confirmed (2)
  alta    cuit_emisor                    20-22087601-3  CONF_SCORE_MARGIN_GATE
  alta    fecha_emision                  2026-08-07     CONF_SCORE_MARGIN_GATE

review (6)
  critica importe_total_facturado        $17.898,30     REV_GATE_UNMET
      why: score 2 meets the floor but strong evidence is missing
  baja    tipo_comprobante               C              REV_SCORE_MID
      why: score 2 below the threshold 3
  ...

escalate (11)
  critica iva                            21.00%         ESC_LOW_SCORE
      why: score 0 below the escalate floor 2
      signals: UNKNOWN=DOCUMENT_CONTENT
  ...

read next
  var/work/caso/pending.json  (17 field(s)) — the fields a human must settle
  var/work/caso/decision.json — every decision, with the signals behind it

notes
  - text lane B produced no review verdicts
  - lane-on-demand deferred: importe_total_facturado still lack strong evidence
  - ESC_NO_NEW_EVIDENCE
```

El reporte responde las tres preguntas de la cabecera de [`README.md`](README.md):

- **`path`** — ¿por dónde pasó el documento? Cada stage con `ran` o `reused`.
- **`confirmed` / `review` / `escalate`** — ¿qué se decidió? Agrupado por veredicto,
  con el **código de razón** y las señales que no llegaron (`FAIL=` / `UNKNOWN=`).
- **`read next`** — ¿qué abrir? Sólo nombra los archivos **que se escribieron**.

### Los dos diales de salida

```bash
--json      # el resultado del motor, para un programa
--pretty    # el mismo resultado, indentado
```

```bash
python scripts/poc-flow-v2/myflow.py <doc> --work-root var/work/caso --pretty
```

```json
{
  "decisions": {
    "cuit_emisor": {
      "field": "cuit_emisor",
      "severity": "alta",
      "decision": "CONFIRMED",
      "reason_codes": ["CONF_SCORE_MARGIN_GATE"],
      "winner": {
        "normalized_value": "20-22087601-3",
        "producers": ["regexp", "extractor_llm_texto"],
        "signals": [
          {"family": "DOCUMENT_CONTENT", "result": "PASS", "points": 2,
           "detail": "value present in the text", "verified": true},
          ...
        ]
      },
      "score": 4, "margin": 4, "threshold": 5, "gate_satisfied": true
    },
    ...
  }
}
```

`--json` y `--pretty` son **vistas del mismo registro** que el reporte: ninguno
inventa datos.

### El progreso va a stderr

`--verbose` escribe el avance a **stderr**, así que stdout sigue siendo el reporte
y un pipe no se contamina (B.4):

```bash
python scripts/poc-flow-v2/myflow.py <doc> --work-root var/work/caso --verbose > report.txt 2> progress.txt
```

```
== read: 66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf
   read ran
== extract: 66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf
   17 field(s) with candidates
== decide: 66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf
   17 field(s) decided, 2 confirmed
== hitl: 66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.pdf
   15 field(s) pending
run: 4 step(s) recorded
```

---

## Reanudar — el circuito que más se paga

Los cuatro stages corren una vez y escriben su artefacto. Una segunda invocación
**reusa** lo hecho; el journal dice dónde retomar (B.5, B.14).

```bash
# 1) frena tras el stage en curso, dejando el journal consistente
python scripts/poc-flow-v2/myflow.py <doc> --work-root var/work/caso --pause
```

```
path
  1. read      ran     read ran
```

`read` quedó `done`, los otros tres no:

```
read    -> {'done': True}
extract -> {'done': False}
decide  -> {'done': False}
hitl    -> {'done': False}
```

```bash
# 2) la siguiente invocación retoma exactamente en `extract`
python scripts/poc-flow-v2/myflow.py <doc> --work-root var/work/caso
```

```
path
  1. read      reused  reused from material.json
  2. extract   ran     15 field(s) with candidates
  3. decide    ran     15 field(s) decided, 3 confirmed
  4. hitl      ran     12 field(s) pending
```

Ese es el circuito entero: **`reused` no es `ran`** (B.3), y la diferencia está en el
reporte, no en un log.

Los otros dos comandos de control:

```bash
--stop      # frena tras el stage en curso y marca el run como detenido
--redo      # ignora el journal y re-ejecuta todo
```

---

## C1 — Clasificar: un no-comprobante se descarta antes de pagar el modelo

`§3`. El gate corre **antes** de `extract`, así que un no-comprobante no cuesta una
llamada al modelo.

```bash
python scripts/poc-flow-v2/myflow.py tests/fixtures/negativos/neg_2026-11_foto_pizarra.jpg \
    --work-root var/work/neg
```

```
path
  1. read      ran     read ran
  2. extract   ran     0 field(s) with candidates
  3. decide    ran     0 field(s) decided, 0 confirmed
  4. hitl      ran     0 field(s) pending

notes
  - classified out: not a receipt (fiscal_word)
  - ESC_NO_NEW_EVIDENCE
```

El veredicto es **débil a propósito, no astuto**: un falso negativo paga el modelo de
más, un falso positivo paga un modelo que no va a extraer nada. Se exigen **dos**
señales fiscales independientes (CUIT, monto, fecha, palabra fiscal) porque una
palabra suelta en prosa no es un comprobante.

Probá el mismo comando con `tests/fixtures/negativos/neg_2026-07_resumen_tarjeta.pdf`:
también se descarta, y la razón nombra qué señales faltaron.

---

## C2 — Las lanes: dos lecturas de material distinto

`§4.1`. La lane A extrae, la lane B revisa. El invariante **I1** dice que A y B del
mismo lane **nunca** cuentan como fuentes independientes: el `+2` de independencia es
sólo para el cruce texto↔vision.

En un **escaneado** corren las dos lanes (texto y vision), así que el cruce se ve:

```bash
python scripts/poc-flow-v2/myflow.py tests/fixtures/pdf_escaneados/9b7a423c-189c-4b9b-8ab1-23b38d4518b4.pdf \
    --work-root var/work/scan
```

En `decision.json`, el campo que ganó por cruce:

```
=== nro_comprobante | CONFIRMED | score 4 | gate_satisfied True
  winner: 04928-00054475 producers ['extractor_llm_texto', 'vision']
      DOCUMENT_CONTENT PASS +2 | value present in the text
      CROSS_MODAL      PASS +2 | text and vision lanes agree
      CROSS_MODAL      PASS +2 | text and vision lanes agree
```

Dos cosas que leer ahí:

- **`producers` nombra ambos lanes** — el valor lo propusieron el extractor de texto
  *y* la vision lane. Esa es la prueba independiente.
- **`CROSS_MODAL` aparece dos veces y suma dos veces.** El tope por familia es **por
  candidato**, no por campo (I4): el `+2` se cobra una vez por cada valor distinto que
  ambas lanes corroboran. Para ver el tope actuando, mirá un campo con un solo valor
  cruzado — cobra un `+2`, no cuatro.

En un **texto nativo** la vision lane no corre (no hay páginas renderizadas), así que
el cruce no aparece. Es el caso del `66cd35e9-…pdf` de más arriba: su `cuit_emisor` se
confirma con `regexp` + `extractor_llm_texto` y **no** lleva `CROSS_MODAL` — dos
lecturas del mismo material no son dos pruebas.

---

## C4 — `verified`: un valor anclado o `UNKNOWN`, nunca `PASS` por subcadena

`§4.2`. El modo de fallo peligroso es el que devuelve un valor plausible (B.10), así
que un valor numérico sólo se da por presente si es un número **completo**, no la cola
de uno más largo.

Se ve en las señales, campo por campo:

```
signals: UNKNOWN=DOCUMENT_CONTENT
```

Ese `UNKNOWN` es la lección: **no puntúa y no veta** (I10). Un ancla que no se pudo
verificar no se convierte en un `PASS` optimista ni en un `FAIL` que descarte el
valor — se declara desconocida. En el reporte se distingue `FAIL=` de `UNKNOWN=`
(B.9), porque un cero que no dice por qué es cero convierte un defecto en un dato.

**Confirmá la frontera vos mismo** — es el test que guarda el invariante:

```bash
pytest tests/poc_flow_v2/test_circuitos.py -k c4 -q     # 5 passed
```

Y probá que **falla** al romperlo (B.16). Reemplazá el cuerpo de
`_present_at_location` en `flow/extract.py` por un substring plano
(`return value in haystack`) y corré otra vez:

```
FAILED tests/poc_flow_v2/test_circuitos.py::test_c4_a_value_inside_a_longer_number_is_not_verified
1 failed, 4 passed, 25 deselected
```

Restaurá el archivo y volvé a verde. **Esa observación es el punto** — un test que
sólo pasa cuando el código está bien no prueba nada.

> El arnés `mutation_invariants.py` cubre I2/I3/I4/I10, no C4: esa mutación la hacés
> a mano. Cerrar esa brecha es trabajo pendiente, no una omisión de esta página.

---

## C5 — Consistencia aritmética: el validador no veta lo que no puede evaluar

`§6.4`. Un veto aritmético exige que la regla declare tener **todos** sus
componentes; si no, es `UNKNOWN`. Y las combinaciones se evalúan de una: exactamente
una consistente suma; cero o más de una escalan.

Sobre el escaneado, el escalamiento se ve con su propio código:

```
escalate (12)
  critica importe_total_facturado        $75306.21      ESC_NO_UNIQUE_ARITHMETIC_COMBINATION
      why: zero or more than one arithmetic combination is consistent
  critica iva                            $21.00%        ESC_NO_UNIQUE_ARITHMETIC_COMBINATION
      why: zero or more than one arithmetic combination is consistent
      signals: UNKNOWN=DOCUMENT_CONTENT
```

**Cero o más de una** combinación es el mismo veredicto: cuando hay más de una
aritmética consistente, el documento no dirime — y el motor se niega a elegir.

El otro lado del circuito: una **Factura C** no discrimina IVA, así que no tiene
componentes requeridos y no se la veta por un IVA que nunca iba a estar
(`required_components_for`). Se prueba con:

```bash
pytest tests/poc_flow_v2/test_circuitos.py -k c5 -q
```

---

## C6 — Lane-on-demand: la escalera reporta lo que le falta

`§6.5`. Cuando un campo **crítico** queda en `REVIEW` con el gate sin cerrar, la
escalera decide que hace falta la vision lane. Hoy **detecta y reporta**; el render a
demanda queda diferido, y no en silencio:

```
notes
  - lane-on-demand deferred: importe_total_facturado still lack strong evidence
```

Esa nota es el circuito funcionando de verdad: la detección es pura
(`flow/lane.py::needs_vision_lane`) y nombra **qué campo** y **qué familia fuerte**
falta. Lo que no está es el adapter que renderiza una página de un texto nativo
(`# TODO: [MVP]`). La negativa se declara en vez de fingir una lane que no corrió.

```bash
pytest tests/poc_flow_v2/test_circuitos.py -k c6 -q    # gate no satisfecho necesita lane
```

---

## C7 — El resolver: re-entra sólo con evidencia nueva

`§7`. Un loop que vuelve a correr el motor sobre la **misma** evidencia no puede dar
otra respuesta. Dos invariantes lo acotan: re-entra **sólo** si cambió el conjunto de
candidatos o de señales, y el loop está **capado** en `max_loops=2`.

Se ve en las notas del reporte:

```
notes
  - ESC_NO_NEW_EVIDENCE
```

`ESC_NO_NEW_EVIDENCE` es el loop negándose a repetirse: no había nada nuevo, así que
no hay motivo para volver al motor. Con evidencia nueva el código sería otro (o
ninguno, si el campo cierra). El otro código del loop, `ESC_LOOP_LIMIT`, aparece al
agotar las dos vueltas.

```bash
pytest tests/poc_flow_v2/test_circuitos.py -k c7 -q
```

---

## C8 — Frontier y confirmación humana

`§8`. Lo que el motor no cerró va a una cola; un humano lo settlea. El invariante
**I6** es el que manda acá: **la sugerencia es evidencia, nunca veredicto.**

### La cola

El `hitl` escribe `pending.json` con lo que un humano debe resolver, y el reporte lo
nombra en `read next`:

```
read next
  var/work/caso/pending.json  (17 field(s)) — the fields a human must settle
```

### Pedirle una sugerencia al frontier

```bash
python scripts/poc-flow-v2/myflow.py <doc> --work-root var/work/caso --resolve
```

Sin credencial, la negativa es una **nota**, no un fake:

```
notes
  - frontier: frontier refused: provider_unavailable
```

Esa es la aceptación del circuito: *un escalamiento llega al frontier **o se reporta
su negativa***. Lo que nunca hace es inventar un valor.

Con credencial disponible, en cambio, escribe `resolution.json` **al lado** de la cola
— jamás en lugar de ella:

```json
{"suggestions": [{"field": "...", "suggested_value": "...", "reason": "..."}]}
```

#### El frontier es DeepSeek, y DeepSeek no lee pixeles

El dial es `FRONTIER_MODEL = "deepseek:deepseek-v4-pro"`, y el proveedor declara
`supports_vision = False` — **medido, no supuesto**: si se le manda una imagen, acepta
el request, ignora los pixeles y contesta como si el documento estuviera en blanco.
K6 lo rechaza con `unsupported_format` **antes** de la red, así que mandarle páginas
no es una opción.

La consecuencia se ve en un **escaneado**, que tiene las dos cosas — OCR y páginas
renderizadas:

```bash
python scripts/poc-flow-v2/myflow.py tests/fixtures/pdf_escaneados/9b7a423c-189c-4b9b-8ab1-23b38d4518b4.pdf \
    --work-root var/work/scan --resolve
```

El paso no manda la imagen (sería un rechazo) ni se queda sin material (tiraría el
OCR que el run ya pagó): manda **el texto**, y **anuncia la degradación** (B.12):

```
notes
  - frontier: read the OCR text, not the pages: this provider declares no vision, so the image is refused before the call rather than sent and ignored
```

Esa nota es la diferencia entre un recorte anunciado y uno silencioso. Las tres ramas
están cubiertas por tests que fallan al romperse (`test_c8_a_provider_without_vision_*`,
`test_c8_a_provider_with_vision_*`, `test_c8_a_scan_without_text_*`).

Un documento **sin capa de texto y sin vision** no tiene nada honesto que mandar: no
hay llamada, y la nota dice por qué (`nothing to send: …`).

```bash
pytest tests/poc_flow_v2/test_circuitos.py -k c8 -q     # 6 passed
```

### Confirmar como humano

```bash
python scripts/poc-flow-v2/myflow.py <doc> --work-root var/work/caso \
    --confirm 'iva=21.00%' --confirm 'moneda=ARS'
```

Escribe `confirmed.json`:

```json
{
  "human_confirmed": {
    "iva": "21.00%",
    "moneda": "ARS"
  }
}
```

Sólo un campo **pendiente** se puede confirmar: confirmar uno que el motor ya
confirmó es una edición fuera de banda, y se **rechaza** con una nota
(`confirmation refused: …`) en vez de pisar la decisión en silencio.

---

## Lo que todavía no se ve desde el CLI

Dos circuitos tienen módulo, test y código puro — pero **el `run` no los llama**. Vale
la pena saberlo antes de buscarlos en un reporte:

### C3 — QR

`flow/qr.py` decodifica el payload de ARCA (fecha, CUIT emisor, punto de venta,
tipo/nro, importe, moneda, receptor, CAE) y sabe distinguir acuerdo de conflicto:

- acuerdo QR ↔ impreso → señal `DETERMINISTIC`
- desacuerdo → flag `conflicto_qr`, que **nunca se resuelve por puntaje** (`§4.2`)

El circuito está probado (`test_c3_*`), pero `extract_stage` no lo invoca: no hay
candidatos `qr_*` en ningún `extraction.json` de una corrida real. Es un módulo
cerrado esperando su cableado.

```bash
pytest tests/poc_flow_v2/test_circuitos.py -k c3 -q
```

### C9 — Aprender

`flow/learn.py` implementa los dos canales de **I7**: `SYSTEM_CONFIRMED` alimenta
estadísticas en sombra **sin efecto**, y sólo `HUMAN_CONFIRMED` activa templates. El
ciclo de vida es `shadow → active → stale → retired`.

La prueba que importa es negativa, y es la lección entera: **`SYSTEM_CONFIRMED` no
activa un template** — un error sistemático no puede enseñarse a sí mismo.

```bash
pytest tests/poc_flow_v2/test_circuitos.py -k c9 -q
```

Nota honesta del plan: `activate_template` persiste la regla, pero la clave
`(emisor, tipo, layout_fingerprint)` y el contador `LAYOUT_HISTORY` son del store, no
de este módulo puro — quedan `# TODO: [MVP]` en el caller.

---

## El work root — donde el registro queda en disco

Un `--work-root` guarda el run entero. Es lo que hace reanudable la corrida y auditable
la decisión:

```
material.json    lo que produjo `read`              (stage: read)
extraction.json  candidatos + señales + notas       (stage: extract)
decision.json    veredicto, score, margen, gate     (stage: decide)
pending.json     la cola de lo no confirmado        (stage: hitl)
journal.json     qué stages están `done`            (fuente del resume)
control.json     running / paused / stopped         (fuente del pause/stop)
run.json         el trace derivado del journal      (vista, nunca fuente)
```

Más lo que escribe la escalera cuando se la invoca:

```
resolution.json  la sugerencia del frontier         (con --resolve)
confirmed.json   las confirmaciones humanas         (con --confirm)
```

Tres reglas del registro, todas del Anexo B:

- **`run.json` se deriva** del journal y los artefactos; nunca es la fuente (B.15).
  Borralo y se reconstruye.
- **Un stage se marca `done` sólo después** de escribir su artefacto, y la escritura
  es atómica (temp + rename) para que un kill no trunque el archivo (B.5).
- **Invalidar no es borrar**: re-correr un stage marca ése y los posteriores como
  no-hechos, pero **deja los archivos**; el journal simplemente deja de confiar en
  ellos (B.5).

`control.json` es el que gobierna `pause` / `stop`:

```json
{
  "state": "paused"
}
```

---

## La puerta de calidad

Todo lo de arriba cierra con los cuatro gates sobre este árbol:

```bash
pytest tests/poc_flow_v2
ruff check scripts/poc-flow-v2 tests/poc_flow_v2
ruff format --check scripts/poc-flow-v2 tests/poc_flow_v2
pylint scripts/poc-flow-v2/flow scripts/poc-flow-v2/myflow.py tests/poc_flow_v2
```

Más el arnés que prueba que un invariante **falla** cuando se lo rompe (B.16):

```bash
python -B tests/poc_flow_v2/mutation_invariants.py
```

Un test que sólo pasa cuando el código está bien no prueba nada. El arnés muta la
fuente de I2/I3/I4/I10 y comprueba que el test que guarda cada invariante se pone
rojo.

---

## Ver también

| Documento | Qué tiene |
|---|---|
| [`README.md`](README.md) | la arquitectura del proceso `run` y el contrato de stages |
| [`plan/README.md`](plan/README.md) | el plan de migración, cerrado: las tres fases y su aceptación |
| [`plan/cierre-circuitos.md`](plan/cierre-circuitos.md) | el inventario C1–C9 con lo diferido declarado |
| [`../../my_flow.md`](../../my_flow.md) | la especificación: §1–§9, invariantes I1–I10, Anexo A y B |
