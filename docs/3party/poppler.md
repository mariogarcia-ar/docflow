# Poppler — dossier

> Kind: CLI binaries (`poppler-utils`)
> Processor / seam: `docflow.pdf.primitives`
> Status: collecting (2026-09-24)

## A. Identity and provenance

| Field | Value |
|---|---|
| `engine` value in metadata | `poppler` (already asserted in `tests/pdf/test_contracts.py`) |
| Kind | **CLI binaries**, one process per call — no library, no return value |
| Upstream | <https://poppler.freedesktop.org> (fork of Xpdf); man pages via `manpages.debian.org/testing/poppler-utils/` |
| Context7 IDs | `/websites/pdf2image_readthedocs_io_en` — the reference for the **CLI** contract (a subprocess driver); `/fdawgs/node-poppler` — the binary inventory; `/cbrunet/python-poppler` — bindings we do **not** use |
| Maintainer / cadence | The Poppler Developers; monthly-ish point releases (see `poppler.freedesktop.org/releases.html`) |
| Version this page was read against | man pages of `poppler-utils 26.01.0-5` (Debian testing) + local binaries **25.02.0** — the two disagree where noted |

## B. Install, pin and version discovery

- **Install shape:** a system package (`poppler-utils` via `apt`/`dnf`/`brew`/`nix`), never a Python wheel. `pyproject.toml` `dependencies = []` today, so the pin is a **documented version requirement**, not a pip pin (`GEN-05` has no wheel to pin here).
- **Local environment (2026-09-24):** `pdftotext`, `pdftoppm`, `pdftocairo`, `pdfimages`, `pdfseparate`, `pdfinfo` all present at **25.02.0** (macOS/Homebrew path).
- **Version command:** `<binary> -v`. It prints **two lines**:

  ```
  pdftotext version 25.02.0
  Copyright 2005-2025 The Poppler Developers - http://poppler.freedesktop.org
  ```

  Normalization for `engine_version`: first line, token after `version`. Every binary we call supports `-v` and `-h`.
- **Probe safety:** Poppler ≤ 0.24.2 returned `99`/`1` for `-h`, `-v` and `-printenc`; fixed in 0.24.3 ("Do not return 99 (or 1) with -h, -v and -printenc"). A version probe must still run with `check=False`.
- **Absent / present check at the right stage:** `import docflow.pdf.primitives` must succeed with Poppler absent (`tests/test_skeleton.py`); the engine is resolved **at call time**, so absence surfaces as `FileNotFoundError` from `subprocess.run`, not as an import error.
- **Suite without it:** the whole suite runs on the in-memory double; nothing here is ever installed by CI (`GEN-21`).

## C. Licence and distribution posture

- Poppler is **GPL** (the plan's risk table already names "Engine licensing (Poppler GPL) → distribution/legal constraint, decide license posture before Release"). Exact variant (GPL-2.0-only vs `-or-later`) — `TBD`.
- We **call** the binary rather than link it; whether the PoC redistributes a binary at all is an open question (K).
- Attribution/notice obligations: `TBD` — read the upstream `COPYING` before Release.

## D. Interface contract — what the seam actually calls

Argv shapes read from the Debian man pages (`26.01.0-5`).

| Binary | Synopsis | Options we need |
|---|---|---|
| `pdftotext` | `pdftotext [options] PDF-file [text-file]` | `-f <n>` first page, `-l <n>` last page, `-r <n>` DPI (default **72**), `-layout` (keep physical layout; default undoes it into reading order), `-bbox-layout` (XHTML with block/line/word bboxes), `-tsv`, `-enc <name>` (default `UTF-8`), `-eol unix\|dos\|mac`, `-nopgbrk`, `-nodiag` (≥ 0.80), `-colspacing <n>` (default 0.7), `-opw`/`-upw`, `-q`, `-v`, `-h`; `-` as text-file writes to stdout |
| `pdfimages` | `pdfimages [options] PDF-file image-root` | `-f`, `-l`, `-png`, `-j` (native JPEG), `-tiff`, `-all` (= `-png -tiff -j -jp2 -jbig2 -ccitt`), `-list` (list, **must not** be given an image-root), `-p` (page number in the file name), `-min-width`/`-min-height`, `-q`, `-opw`/`-upw` |
| `pdfseparate` | `pdfseparate [-f first] [-l last] [options] input.pdf output-pattern` | pattern **must** contain `%d` (`%03d` accepted → `page-001.pdf`); `-v`, `-h` |
| `pdfinfo` | `pdfinfo [options] [PDF-file]` | `-f`/`-l` (with multiple pages: per-page size, and with `-box` per-page boxes), `-box`, `-meta`, `-custom`, `-js`, `-struct`, `-enc` (default `UTF-8`), `-opw`/`-upw`, `-v`, `-h` |
| `pdftoppm` | `pdftoppm [options] PDF-file PPM-root` | `-f`, `-l`, `-o`/`-e` (odd/even), `-r <n>` DPI (default **150**), `-rx`/`-ry`, `-scale-to`/`-scale-to-x`/`-scale-to-y`, `-png`, `-jpeg`, `-jpegopt <opts>`, `-tiff`, `-gray`, `-singlefile` |
| `pdftocairo` | `pdftocairo [options] PDF-file [output-file]` | exactly **one** format flag required (`-png`, `-jpeg`, `-tiff`, `-pdf`, `-ps`, `-eps`, `-svg`); `-r` (default **150 PPI**), `-rx`/`-ry`, `-scale-to`, `-singlefile`, `-f`/`-l`, `-o`/`-e`, `-transp`, `-gray` |

**Output naming (the engine's, before our rename):** `pdftotext` → `file.txt`; `pdfimages` → `image-root-nnn.xxx` (sequential number, extension by format); `pdfseparate` → the caller's `%d` pattern; `pdftoppm`/`pdftocairo` → `root-number.ext`, digits suppressed by `-singlefile`.

**Must be explicit, never inherited:** `dpi` (`-r 200`, because the engine default is 150 while `subplan-procesador-pdf.md` fixes `dpi=200`), the page range, the output format, and the passwords. A missed flag is a silent artifact, not an error.

**Resolution:** the seam resolves `subprocess` at **call time** so the fake can patch `docflow.pdf.primitives.subprocess.run`.

## E. Inputs, outputs and artifact naming

| Field | Value |
|---|---|
| Inputs | a PDF path (and `-` for stdin on most binaries) |
| Outputs | **files** (text, images, per-page PDFs), not return values; `pdfinfo` is the only one whose useful payload is **stdout** |
| Our naming | `page_001/…`, `image_001.png`, `native_text/text.txt` — the engine writes into a temporary root and we rename. The engine's numbering is **not** our contract |
| Ordering | `pdfimages` numbering follows the page scan order with `-f`/`-l`; our artifact order is ours to preserve |
| Encoding | `pdftotext -enc` defaults to UTF-8; fix it explicitly rather than relying on the default |

## F. Determinism levers

| Lever | Enters `processing_key`? |
|---|---|
| `dpi` (`-r`) | yes |
| Page range (`-f`/`-l`) | yes |
| Text layout mode (`-layout` vs reading order), `-colspacing`, `-raw`, `-nodiag` | yes |
| Output format flags (`-png`/`-jpeg`/`-all`), `-jpegopt` | yes |
| `-enc`, `-eol`, `-nopgbrk` | yes (bytes change) |
| Poppler version | **yes** — recorded as `engine_version`, and the plan's drift risk is caught on the version bump, not by a test |

## G. Failure modes and our error mapping

**Exit codes** (Xpdf heritage, identical across these man pages):

| Code | Meaning |
|---|---|
| 0 | No error |
| 1 | Error opening a PDF file |
| 2 | Error opening an output file |
| 3 | Error related to PDF permissions |
| 99 | Other error |

**Signals we translate.** `pdf2image` (the CLI-driver reference) treats a *successful* exit with `b"Syntax Error"` in stderr as a hard failure and raises `PDFSyntaxError` — that is the pattern to copy: exit code **and** stderr, never one alone.

| Engine signal | Our `PDFErrorType` | `recoverable` |
|---|---|---|
| exit 1, file absent/unreadable | `MISSING_FILE` | no |
| exit 3 (or stderr about permission/password) | `ENCRYPTED_PDF` | no (a password could make it recoverable — `TBD`) |
| exit 99 + `Syntax Error` in stderr | `CORRUPTED_PDF` | no |
| exit 99 during a render call | `RENDER_ERROR` | yes |
| exit 99 during `pdftotext` | `TEXT_EXTRACTION_ERROR` | yes |
| exit 99 during `pdfimages` | `IMAGE_EXTRACTION_ERROR` | yes |
| exit 2 | `WRITE_ERROR` | yes |
| `FileNotFoundError` (binary absent) | `IO_ERROR` (no `DEPENDENCY_ERROR` exists) | no |
| page outside `-f`/`-l` range | `PAGE_OUT_OF_RANGE` | no |

**Pre-engine vs injected:** a file that is missing, out of range or unreadable is decided by `validate_pdf`'s fail-fast **before** any Poppler call; everything else in the table is an injected failure the double must be able to produce.

> **Divergence to report (not fixed here).** `src/docflow/pdf/contracts.py` today declares
> `MISSING_FILE, ENCRYPTED_PDF, CORRUPTED_PDF, UNSUPPORTED_PDF, PAGE_OUT_OF_RANGE,
> RENDER_ERROR, TEXT_EXTRACTION_ERROR, IMAGE_EXTRACTION_ERROR, WRITE_ERROR, IO_ERROR,
> INTERNAL_ERROR`, while `subplan-procesador-pdf.md` §3.7 lists `INVALID_INPUT`,
> `PAGE_EXTRACTION_ERROR` and no `WRITE_ERROR`. The plan wins; the drift is recorded here so
> the mapping above is read against the right names.

## H. Seam ownership and the double

| Field | Value |
|---|---|
| Owning module | `docflow.pdf.primitives` — the only place that knows Poppler |
| Symbols needed here | `inspect_pdf`, `extract_page`, `split_pdf`, `merge_pdfs`, `render_page_to_image`, `extract_text_from_page`, `extract_images_from_page` (plus `analyze_pdf_page`, `classify_pdf_page`, which are ours) |
| Injection point | the **`subprocess.run` call** inside `pdf/primitives/` — `monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", fake_poppler)` |
| What "native-shaped" means | the artifacts the CLI would have written **plus an exit code and stderr** — never our `PDFPageResult`, never the output of `extract_text_from_page` |
| Shared helper | `missing_from_double(seam, "subprocess", fake)` **applies** (the seam reaches an engine namespace) |
| Other processors | none may reach Poppler (`README.md` §7) |

## I. Cost, latency and limits

- Rendering dominates and is ~quadratic in `dpi` (200 DPI ≈ 4× the pixels of 100 DPI); `pdfimages` is cheap but yields nothing on a text-only PDF; `pdftotext` is fast and layout mode costs more than reading order.
- No hard limits are documented in the man pages read; a page count is available from `pdfinfo` before work starts.
- Timeout lives in the primitive (the thing that owns the call); Poppler itself has no timeout flag.

## J. Alternatives and swap story

| Alternative | Note |
|---|---|
| `pypdfium2` (5.12.1 installed) | in-process, no subprocess → the double's shape changes |
| `PyMuPDF` (1.28.2 installed) | in-process; AGPL licence posture |
| `pdf2image` (1.17.0 installed) | a **subprocess wrapper**, not an engine; reference only, must never be imported from `primitives/` |
| `python-poppler` (Context7) | in-process bindings; would delete the exit-code/stderr half of the contract |

A swap touches `pdf/primitives/` only — never the contract or the workflow — and **does** break the double (a subprocess fake becomes a return-value fake).

## K. Open questions and drift log

- [ ] Which binary renders a page — `pdftoppm` or `pdftocairo`? `PDF-05` names neither, and `pdftocairo` requires exactly one format flag while `pdftoppm` defaults to PPM/PGM/PBM.
- [ ] Does `pdfinfo` support a JSON output (`-json`)? **Not** in the man page read (`26.01.0-5`) — confirm against `pdfinfo -h` on **25.02.0** before relying on it.
- [ ] Ordered text blocks come from `-bbox-layout` (XHTML) or `-tsv` — which one feeds `extract_text_from_page(layout=True)`'s `blocks.json`?
- [ ] Exit code for "PDF is fine but has no text layer" is **0** with an empty file — an empty `text.txt` must be a reported `TEXT_EXTRACTION_ERROR`, never a silent empty artifact.
- [ ] Exact GPL variant, and whether the PoC distributes a Poppler binary at all.
- [ ] `-nodiag` needs Poppler ≥ 0.80 — satisfied by 25.02.0; record the floor if the pin is ever stated as a range.
- [ ] Drift log: (2026-09-24) local binaries 25.02.0; man pages read at 26.01.0-5. No seam change observed.
