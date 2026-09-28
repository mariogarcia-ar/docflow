```bash
# info
python scripts/tools/batch_pdf.py tests/fixtures/pdf

# classify
python scripts/tools/pdf.py classify documento.pdf --page 1 --json
python scripts/tools/batch_pdf.py tests/fixtures/pdf classify --page 1

```