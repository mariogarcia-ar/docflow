# Decision — the OCR bench's `text` publishes the text it reports

> Status: **applied**. Supersedes no earlier note. It revises the wording of decision 15 in
> `docs/plan/subplan-scripts.md` §9 and is applied to that subplan and to
> `docs/plan/issues/wbs-scripts.md` in the same pass, as the plan convention requires — together
> with `scripts/tools/_ocr.py`, `scripts/tools/ocr.py`, `scripts/tools/batch_ocr.py` and
> `tests/test_lab_tools.py`.

## 1. What the bench showed

`batch_pdf.py <folder> text` publishes `page_NNN.txt` per page; its OCR twin reported the same kind
of reading and left nothing on disk but its record:

```bash
python scripts/tools/batch_pdf.py tests/fixtures/pdf text
  → var/batch_pdf/pdf/pdf_sample_text/{text.json, page_001.txt, page_002.txt, page_003.txt}

python scripts/tools/batch_ocr.py tests/fixtures/ocr          # the default command is `text`
  → var/batch_ocr/ocr/ocr_prepared_text_and_table/text.json   # and nothing else
```

A corpus run therefore produced a tree of JSON payloads, and the one thing an operator actually
reads back — the extracted text — could only be reached by parsing a record. `run` does publish
`text.txt`, but it also publishes the whole document, which is not what someone checking an
extraction asked for.

## 2. What was decided

| # | Decision | Where it lands |
|---|---|---|
| D-1 | `ocr.py text` and `batch_ocr.py … text` publish the text they report as `text.txt`, in that input's run root, and the payload gains one key, `output`, carrying the path | `scripts/tools/_ocr.py` (`_text`, `TEXT_NAME`) |
| D-2 | The published bytes are the **normalized** text (`normalize_ocr_text`), which is the form `ocr/entrypoints.py` gives `text.txt` — so the file a `text` run writes and the file a `run` of the same image writes are byte-identical. One name, one reading | `_ocr._text` |
| D-3 | `ocr.py`'s `REPORT_ONLY` loses `text`: six subcommands write, five report | `scripts/tools/ocr.py` |
| D-4 | The batch default **stays** `text`, and decision 15's rule is reworded: a bare run publishes *at most the reading it reports* — never a render, a split, an extracted image or a contract's document | `subplan-scripts.md` §3.4, `wbs-scripts.md` §SCR-14 |

**Why the name is the processor's, and restated rather than imported.** `TEXT_NAME` is stated in the
layer the way `SUFFIXES` is: which inputs a processor takes, and what it calls what it publishes,
are that processor's own facts. The bench reaches a processor's public contract and its own
`primitives/` (the §3.2 exception) — not a private name of its `entrypoints` module.

**Why the default could stay.** Decision 15 exists so that a bare run cannot fill a tree nobody
asked to fill. `text` now writes exactly one small file per input, and it is the *same* text the
run's own record states, so the rule still holds in the form that matters: the default derives
nothing and publishes nothing the caller did not ask to read. The alternative — moving the default
to `metrics` — was rejected because it would answer a bare corpus run with metrics where the
operator's first question is "what does this page say?".

## 3. What did not change

- **The six other methods.** `md`, `json`, `tables`, `blocks` and `metrics` still publish nothing,
  and `run` is still the only method that publishes the contract's document.
- **`_batch.py` and `_cli.py`.** No line was needed: the frame files `<command>.json` and the method
  publishes beside it, which is exactly the shape `page_NNN.txt` already used for `pdf` — and the
  two file names cannot collide (`text.txt` beside `text.json`).
- **The atomic publication rule.** The write goes through the processor's own
  `write_text_atomic` (`.tmp` → rename), and an empty text is still a legitimate artifact: a blank
  page publishes a zero-byte `text.txt` and is reported `EMPTY`.
- **`md`.** Publishing `document.md` from `md` is the same question and was deliberately **not**
  taken: this note answers the `txt` reading the bench asked for, and a second published
  representation is its own decision.
