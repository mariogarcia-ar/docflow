# Poppler — dossier

> Kind: CLI binaries (`poppler-utils`)
> Processor / seam: `docflow.pdf.primitives`
> Status: collecting (2026-09-24; pendings resolved against the installed 25.02.0, 2026-09-25)

## A. Identity and provenance

| Field | Value |
|---|---|
| `engine` value in metadata | `poppler` (already asserted in `tests/pdf/test_contracts.py`) |
| Kind | **CLI binaries**, one process per call — no library, no return value |
| Upstream | <https://poppler.freedesktop.org> (fork of Xpdf); man pages via `manpages.debian.org/testing/poppler-utils/` |
| Context7 IDs | `/websites/pdf2image_readthedocs_io_en` — the reference for the **CLI** contract (a subprocess driver; re-queried 2026-09-24 for the `pdfinfo` and render contract); `/fdawgs/node-poppler` — the binary inventory; `/cbrunet/python-poppler` — bindings we do **not** use |
| Maintainer / cadence | The Poppler Developers; monthly-ish point releases (see `poppler.freedesktop.org/releases.html`) |
| Version this page was read against | man pages of `poppler-utils 26.01.0-5` (Debian testing) + local binaries **25.02.0** — the two disagree where noted |

## B. Install, pin and version discovery

- **Install shape:** a system package (`poppler-utils` via `apt`/`dnf`/`brew`/`nix`), never a Python wheel. `pyproject.toml` `dependencies = []` today, so the pin is a **documented version requirement**, not a pip pin (`GEN-05` has no wheel to pin here).
- **Local environment (2026-09-24, re-probed 2026-09-25):** `pdftotext`, `pdftoppm`, `pdftocairo`, `pdfimages`, `pdfseparate`, `pdfinfo` and `pdfunite` all present at **25.02.0** (macOS/Homebrew path) — `pdfunite` matters because `merge_pdfs` is a primitive of the seam.
- **Version command:** `<binary> -v`. It prints **two lines**:

  ```
  pdftotext version 25.02.0
  Copyright 2005-2025 The Poppler Developers - http://poppler.freedesktop.org
  ```

  Normalization for `engine_version`: first line, token after `version`. Every binary we call supports `-v` and `-h`.
- **Probe safety:** Poppler ≤ 0.24.2 returned `99`/`1` for `-h`, `-v` and `-printenc`; fixed in 0.24.3 ("Do not return 99 (or 1) with -h, -v and -printenc"). A version probe must still run with `check=False`.
- **Feature gates by version** (read from the `pdf2image` source, Context7): a feature is not available on every Poppler. `-jpegopt` is dropped for ≤ 0.57 and `-hide-annotations` for ≤ 0.83. A primitive that passes an option without a version guard fails on an older engine; our recorded floor must therefore be a **version check**, not a hope. 25.02.0 clears both.
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
| `pdfinfo` | `pdfinfo [options] [PDF-file]` | `-f`/`-l` (with multiple pages: per-page size, and with `-box` per-page boxes), `-box`, `-meta`, `-custom`, `-js`, `-struct`, `-isodates`, `-rawdates`, `-enc` (default `UTF-8`), `-opw`/`-upw`, `-v`, `-h`. **No `-json`** (re-probed 2026-09-25). One call with `-box -f 1 -l <n>` yields the page count *and* the per-page geometry — the shape `inspect_pdf` needs |
| `pdftoppm` | `pdftoppm [options] PDF-file PPM-root` | `-f`, `-l`, `-o`/`-e` (odd/even), `-r <n>` DPI (default **150**), `-rx`/`-ry`, `-scale-to`/`-scale-to-x`/`-scale-to-y`, `-png`, `-jpeg`, `-jpegopt <opts>`, `-tiff`, `-gray`, `-singlefile`. **The render binary of `PDF-05`**; frozen argv `-png -r <dpi> -f <n> -l <n> -singlefile` |
| `pdftocairo` | `pdftocairo [options] PDF-file [output-file]` | exactly **one** format flag required (`-png`, `-jpeg`, `-tiff`, `-pdf`, `-ps`, `-eps`, `-svg`); `-r` (default **150 PPI**), `-rx`/`-ry`, `-scale-to`, `-singlefile`, `-f`/`-l`, `-o`/`-e`, `-transp`, `-gray` |

**Verified from the `pdf2image` source** (Context7, `/websites/pdf2image_readthedocs_io_en`) — the parts of the CLI contract a caller must not guess:

- **`pdfinfo` is parsed from stdout, `key: value` per line** — no `-json` needed (and none exists in the man page read). `pdf2image` splits each line on `:`, strips it, casts the numeric keys, and **fails when `Pages` is missing** (`if "Pages" not in d:` → raise). That is the shape `inspect_pdf` consumes.
- **Passwords go to `pdfinfo` too**: `pdfinfo -upw <pw> -opw <pw>`, and `-rawdates` when undated metadata must be preserved.
- **Page count is obtained first**, then `first_page`/`last_page` are **clamped** to it (`last_page > page_count` → `page_count`; `first_page < 1` → `1`), and `first_page > last_page` returns an **empty list** rather than failing. Our `PAGE_OUT_OF_RANGE` decision has to be taken deliberately, not inherited from that silent behaviour.
- **The render binary is chosen by output need, not by preference**: `pdftocairo` is used when the format requires it or a transparent background is requested; otherwise `pdftoppm`. That is the decision rule for §K's open question.
- **Failure detection is `Popen` + `communicate`**: `TimeoutExpired` → kill and raise a timeout error; `OSError` → "is poppler installed and in PATH?"; a `Syntax Error` in stderr is fatal when strict. Nothing inspects a return value, because there is none.

**Verified against the installed binaries (25.02.0, probed 2026-09-25)** — the behaviours the wrapper hides:

- **The page range is not handled uniformly.** `pdfinfo -f 3 -l 99` on a 3-page PDF exits **0** and silently clamps `-l` to the real count. `pdftoppm -f 0 -l 1` exits **0** and renders page 1 — below-range is accepted silently too. But `pdftoppm -f 99 -l 99` exits **99** with stderr `Wrong page range given: the first page (99) can not be after the last page (3).` and writes **no** file. So a range fault arrives under exit 99 — the same code as a render failure — and only the stderr text separates them, while a `-f` below 1 never errors at all. The range decision is ours to take before the call; if one slips through, the seam must discriminate on stderr instead of reporting `RENDER_ERROR`.
- **`-singlefile` retires the naming ambiguity at the source.** `pdftoppm -png -r 20 -f 1 -l 1 -singlefile <pdf> <root>` writes exactly `<root>.png` — no page digits. A per-page render therefore never enumerates a directory, so the lexicographic-sort trap (`page-10` before `page-2`) cannot arise on the render path.
- **`pdfinfo -box -f 1 -l <n>` returns the page count and the per-page geometry in one call** — `Pages:` plus, per page, `Page N size:` / `Page N rot:` and the five boxes (`MediaBox`, `CropBox`, `BleedBox`, `TrimBox`, `ArtBox`), with `-l` clamped as above. Two parser notes: the per-page lines arrive in **two grouped blocks** (sizes and rotation first, then every page's boxes — not interleaved), and the values are PDF points, not pixels.
- **A page with no text layer is not a zero-byte file.** `pdftotext` on a scanned, text-free fixture exits **0** and writes **one byte — a lone form feed (`\f`)**. A blankness test written as `size == 0` would therefore pass a `\f` off as extracted text.

**Output naming (the engine's, before our rename):** `pdftotext` → `file.txt`; `pdfimages` → `image-root-nnn.xxx` (sequential number, extension by format); `pdfseparate` → the caller's `%d` pattern; `pdftoppm`/`pdftocairo` → `root-number.ext`, digits suppressed by `-singlefile`.

**Must be explicit, never inherited:** `dpi` (`-r 200`, because the engine default is 150 while `subplan-procesador-pdf.md` fixes `dpi=200`), the page range, the output format, and the passwords. A missed flag is a silent artifact, not an error.

**Resolution:** the seam resolves `subprocess` at **call time** so the fake can patch `docflow.pdf.primitives.subprocess.run`.

## E. Inputs, outputs and artifact naming

| Field | Value |
|---|---|
| Inputs | a PDF path (and `-` for stdin on most binaries) |
| Outputs | **files** (text, images, per-page PDFs), not return values; `pdfinfo` is the only one whose useful payload is **stdout** |
| Our naming | `page_001/…`, `image_001.png`, `native_text/text.txt` — the engine writes into a temporary root and we rename. The engine's numbering is **not** our contract |
| Ordering | `pdfimages` numbering follows the page scan order with `-f`/`-l`; our artifact order is ours to preserve. **Beware the sort:** `pdf2image` recovers page order by sorting the directory listing lexicographically — which is only correct if the numbers are zero-padded (`page-10` sorts before `page-2`). Our `page_001` naming is padded for exactly this reason; keep it. The render path does not enumerate at all (`-singlefile`, §D), so the padding matters for `pdfimages` output and for our own names |
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
| exit 99 + `Wrong page range given` in stderr | `PAGE_OUT_OF_RANGE` — **not** `RENDER_ERROR`, although the exit code is identical | no |
| page outside `-f`/`-l` range, decided before the call | `PAGE_OUT_OF_RANGE` | no |

**Pre-engine vs injected:** a file that is missing, out of range or unreadable is decided by `validate_pdf`'s fail-fast **before** any Poppler call; everything else in the table is an injected failure the double must be able to produce. The range case must be pre-engine rather than inherited: the CLI clamps a low `-f` silently and rejects an impossible range with a generic exit 99, so delegating it to the engine can silently render the wrong page (`-f 0` → page 1).

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

Resolved against the installed **25.02.0** on 2026-09-25 by local probe (evidence gathering, not a
test — the engine is never invoked by the suite). Each answer is a fact plus the choice it implies;
the choice itself lands in `docs/plan/` (`PDF-03`, `PDF-05`, `PDF-06`), never here.

- [x] Which binary renders a page — **`pdftoppm`**, with `-png -r <dpi> -f <n> -l <n> -singlefile`.
      `pdftocairo` stays documented and is reached only for a format that needs it (`-svg` / `-ps` /
      `-eps`) or a transparent background (`-transp`), per the decision rule in §D. The tie-breaker is
      `-singlefile`: one call, one known output name, no directory to sort.
- [x] `inspect_pdf` and clamping — **the closure is ours, and it is not a clamp.** `pdfinfo` clamps a
      high `-l` silently, `pdftoppm` accepts `-f 0` silently, and an impossible range exits 99; so the
      page range is validated **before** the call and an out-of-range page is reported
      `PAGE_OUT_OF_RANGE`, never rendered as a neighbouring page. The one-call read of §D supplies the
      page count and the per-page geometry together.
- [x] `pdfinfo -json` — **does not exist** on 25.02.0 (`-isodates` / `-rawdates` are the date
      options). The `key: value` stdout parser is the only path, as §D already assumes.
- [x] Ordered blocks — **`-tsv`** feeds `blocks.json`: tab-separated, with an explicit `level` column
      (`1 = ###PAGE###`, `3 = ###FLOW###`, `4 = ###LINE###`, `5 = word`), parseable with `str.split`
      and no XML parser — where `-bbox-layout` emits an XHTML document that would want one. Both
      shapes are recorded in §D.
      *Left to `PDF-06`:* whether `text.txt` is joined from the same `-tsv` word rows (one read, and
      then `text.txt` and `blocks.json` provably cannot describe two different reads) or comes from a
      separate `-layout` call (the engine's own spacing, at the cost of a second read).
- [x] A page with no text layer — **not an error by itself.** The engine exits 0 and writes a single
      form feed, so blankness is tested after stripping page separators, never as `size == 0`. A
      legitimately image-only page is *data* (no `native_text`, classification `IMAGE`); the failure is
      an empty artifact published as a successful text extraction.
- [ ] Exact GPL variant, and whether the PoC distributes a Poppler binary at all. **Release gate** —
      the PoC calls the binary and redistributes nothing, so the constraint lands only if that
      changes; read the upstream `COPYING` and record the variant then.
- [x] `-nodiag` floor — **moot**: Phase 1 passes none of `-nodiag`, `-jpegopt` or `-hide-annotations`,
      so no version floor is asserted. The floor question is re-opened if one of them is added.
- [x] Drift log: (2026-09-24) local binaries 25.02.0; man pages read at 26.01.0-5; the CLI contract
      re-verified against the `pdf2image` source (`pdfinfo` parsing, render-binary rule, clamping,
      error detection). (2026-09-25) re-probed against the installed 25.02.0: `pdfinfo -box` one-call
      geometry, the split range behaviour (silent clamp below and above, exit 99 for an impossible
      range), `-singlefile` naming, the one-byte `\f` from a text-free page, and the absence of
      `-json`. **One mapping refinement** (§G): exit 99 with `Wrong page range given` in stderr is
      `PAGE_OUT_OF_RANGE`, not `RENDER_ERROR` — the exit code alone cannot decide the type.
