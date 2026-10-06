# Decision — trim the plan to the PoC it claims to be

> Status: **applied**. Supersedes no earlier note; it records a scope revision applied to
> `docs/plan/` (6 subplan/WBS pairs plus `README.md` and `wbs-general.md`).
>
> **Documents only.** No code, no test and no `src/` file was changed by this revision. What
> it changes is how much the plan *promises*: the rows keep their IDs and are re-scoped, and
> the deferred items carry `# TODO: [MVP]` exactly where the plan requires them.

## 1. The problem

`.github/copilot-instructions.md` fixes the PoC posture: happy path only, no abstractions, no
generic wrappers, low McCabe, and `# TODO` tags as *the* way to defer. A review of the five
subplans found the plan largely disciplined but accumulating two concentrations of machinery
the happy path never reaches, plus a vocabulary wider than anything that produces it:

| Finding | Where | Symptom |
|---|---|---|
| A second workflow engine inside a processor | `LLM-10`…`LLM-14` | node claims, parallel branches, per-node `SKIP`/`FORCE`/`INVALIDATE`, graph stop/resume, per-node artifact tree, consensus scoring — 3 of the subplan's 4 `L` tasks, and the programme's "highest-risk item" |
| 53 primitives for one conversion | `procesador-ocr` | 8 functions mapping 6 option flags, 4 `export_docling_*` beside the 4 `extract_docling_*`, 4 `count_*` helpers recomputing `OCRMetrics` |
| Vocabulary with no producer | `procesador-orquestador` | `CANCELLED` (no cancel in the PoC), `stop_requested` (its only writer deferred), 6 error outcomes while `§9.4` keeps 2 |
| Generics with no caller | `procesador-image`, `procesador-pdf` | `crop_region` / `image/regions/` in no task; `get_pdf_metadata` / `get_page_count` / `get_page_dimensions` / `get_text_blocks` / `get_image_blocks` overlapping the readers that already exist |
| Structure with no owner | all four processors | `utils/` and `helpers/` created by `GEN-01`, assigned no symbol by any subplan |

## 2. What was trimmed

| # | Trim | Files touched | Deferred, tagged |
|---|---|---|---|
| OE-1 | The inference subgraph becomes a **fixed linear chain** with node reuse and per-field comparison | `subplan-procesador-llm-call.md`, `issues/wbs-procesador-llm-call.md` | `claim_node`, parallel branches, node `SKIP`/`FORCE`/`INVALIDATE`, `request_graph_stop`, `resume_llm_graph`, `invalidate_downstream_nodes`, the per-node artifact tree, `calculate_consensus` |
| OE-2 | OCR's surface closes at 25 names: one engine call, one measurement, one producer per artifact | `subplan-procesador-ocr.md`, `issues/wbs-procesador-ocr.md` | `enable_*` / `should_enable_*`, `export_docling_*`, `count_*`, `clean_ocr_text`, `is_ocr_empty`, `table_to_json`, `read_json`, `merge_ocr_metadata`, `get_processor_version`, `create_ocr_directory`, `build_ocr_output_paths`, `validate_ocr_request`, `extract_docling_metadata` |
| OE-3 | The PoC vocabulary is the one the PoC produces | `subplan-orquestador.md`, `issues/wbs-orquestador.md` | `CANCELLED`, `stop_requested`, `request_stop`; four of six `handle_processor_error` outcomes |
| OE-4 | One reader per concern; no crop surface; `utils/` + `helpers/` reserved and empty | `subplan-procesador-{image,pdf}.md`, `issues/wbs-procesador-{image,pdf}.md`, `README.md` | `crop_region`, `image/regions/`, `get_pdf_metadata`, `get_page_count`, `get_page_dimensions`, `get_text_blocks`, `get_image_blocks` |
| OE-5 | The source matrix stays a literal table with no default; only reached cells assert a reason | `subplan-orquestador.md`, `issues/wbs-orquestador.md` | reason strings for the cells Phase 3 does not walk |
| OE-6 | The reuse rule is stated once and deliberately repeated in three lines at node level | `subplan-orquestador.md`, `subplan-procesador-llm-call.md` | nothing — a shared helper was **rejected** on purpose: it would couple the documental and inference levels for a three-line comparison |

Every deferred item is named in the task that used to carry it and tagged there, so the debt
stays visible instead of disappearing into an unmentioned gap.

## 3. How IDs, ranges and counts were handled

- **No ID was renumbered.** `LLM-10`…`LLM-14`, `OCR-02`…`OCR-10`, `PDF-03`/`PDF-06`/`PDF-07`,
  `ORC-01`/`ORC-12`/`ORC-15`/`ORC-16` keep their numbers; the rows are re-scoped, which is what
  the ID-stability rule is for. Every range citation (`wbs-general.md` §1, §4, §5 and the five
  WBS headers) still resolves.
- **Effort was left as estimated.** The subplan table and the WBS summary still agree
  (`Phase 1 = 22 / 32 / 4`), so the counts in `wbs-general.md` §1 stay true; re-estimating a
  re-scoped row is a separate pass and is recorded as such in `subplan-procesador-llm-call.md`
  §9.6.
- **Subplan and WBS were edited in the same pass**, as the plan convention requires: every
  trimmed name is gone from both files or present in both.

## 4. Divergences from the idea, deliberately created

The `docs/idea/procesador-*.md` documents list more primitives and more states than the plan
now builds. The artifact wins (`README.md` §1), and each divergence is recorded as an item in
the corresponding subplan's §9 and named for `GEN-17`'s reconciliation list, so the trim is a
decision with a citation rather than an omission.

## 5. Verification

```bash
pytest            # 62 passed
ruff check .
ruff format --check .
pylint src tests  # 10.00/10
```

Plus the sweeps the plan already prescribes — a trimmed name must not survive anywhere:

```bash
grep -rn 'crop_region\|regions/\|should_enable_\|export_docling\|count_ocr_\|count_tables\|count_blocks' docs/plan/src src tests
grep -rn 'calculate_consensus\|request_graph_stop\|resume_llm_graph\|invalidate_downstream_nodes\|claim_node' docs/plan/
grep -rn 'CANCELLED\|stop_requested\|request_stop' docs/plan/
grep -rn 'get_text_blocks\|get_image_blocks\|get_pdf_metadata\|get_page_count\|get_page_dimensions' docs/plan/
```

A hit is expected only where a passage **states the deferral** ("not built", "deferred",
`# TODO: [MVP]`); a hit that still reads as a deliverable is a defect of this revision.
