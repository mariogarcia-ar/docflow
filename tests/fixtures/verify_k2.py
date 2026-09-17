"""Verify K2 (``kernel.pdf``) against the committed golden set.

A tool, not a test: it reports, it does not assert. The suite's assertions live in
``tests/kernels/test_pdf.py`` and run against fixtures generated on the spot; this
script runs the same kernel over documents **nobody chose to make it pass**, which
is a different kind of evidence and cannot be replaced by a test.

Three passes, each answering a question the generated fixtures cannot:

**Pass 1 — does ``classify`` agree with the manifest?** The manifest's ``pdf_type``
comes from the legacy detector, which counts pages whose text extraction yields
non-whitespace. That is an *independent* measurement, so agreement means something.
It is also a limited one: the detector's own docstring records that it cannot see a
stale invisible text layer, so a disagreement is not automatically a defect on
either side.

**Pass 2 — does ``render`` refuse resolutions the source cannot supply?** The
invariant is that a request above the embedded pixels is refused and produces no
larger file. The golden set's scans are real documents, so this measures the corpus
rather than a fixture built to provoke the failure.

**Pass 3 — does any real page carry an invisible text layer?** The detector for
that failure is proven against a fixture this project generates. A real document
would be stronger evidence, and this pass is how the question gets asked rather
than assumed.

Usage:
    python tests/fixtures/verify_k2.py [--json]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter
from typing import Any

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

# pylint: disable=wrong-import-position
# The import genuinely follows the `sys.path` insertion on the line above: the
# script must resolve `docflow` from the checkout it lives in rather than from an
# installed copy, and a fresh clone has no install.
import pymupdf  # noqa: E402

from docflow.kernels import pdf  # noqa: E402

MANIFEST: pathlib.Path = REPO / "tests" / "fixtures" / "manifest.json"
ROOT: pathlib.Path = REPO / "tests" / "fixtures"

#: The character threshold a caller would plausibly use. It is passed in because
#: the kernel owns no threshold of its own.
MIN_CHARS: int = 40

#: The resolution the scans are asked to honour. Above what this corpus's scans
#: hold, so the pass exercises the refusal rather than the happy path.
HIGH_DPI: int = 600


def entries() -> list[dict[str, Any]]:
    """Read the manifest's PDF entries.

    Returns:
        Each PDF entry as recorded.

    """
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return [entry for entry in manifest["entries"] if entry.get("extension") == "pdf"]


def page_count(path: pathlib.Path) -> int:
    """Count a document's pages.

    Args:
        path: The PDF to open.

    Returns:
        Its page count, or ``0`` when it cannot be opened. Zero is a measurement —
        the document is unreadable — and never a stand-in for one.

    """
    try:
        document = pymupdf.open(path)
    except Exception:  # pylint: disable=broad-exception-caught
        # PyMuPDF raises several unrelated types for a damaged file, and the only
        # decision here is "count it or not". Enumerating the types would let an
        # unexpected one escape as a crash on a document that is merely odd.
        return 0

    try:
        return int(document.page_count)
    finally:
        document.close()


def classify_document(path: pathlib.Path, pages: int) -> tuple[Counter[str], list[int]]:
    """Measure every page of one document.

    Args:
        path: The PDF to measure.
        pages: How many pages it has.

    Returns:
        The shape tally, and the one-based numbers of the pages reported blank.

    """
    shapes: Counter[str] = Counter()
    blanks: list[int] = []

    for number in range(1, pages + 1):
        result = pdf.classify(path, number, min_chars=MIN_CHARS)
        if result.value is None:
            code = result.reason.code if result.reason else "unknown"
            shapes[f"<{code}>"] += 1
            if code == "blank_page":
                blanks.append(number)
        else:
            shapes[str(result.value.observed["shape"])] += 1

    return shapes, blanks


def document_label(shapes: Counter[str]) -> str:
    """Derive the label the manifest would use, from the shapes measured.

    The manifest's question is binary — does the document carry a text layer? — so
    a page holding text *and* an image is a text document that embeds a picture,
    not a third category. Mirroring that question is what makes the comparison
    meaningful; inventing a ``mixto`` label here would manufacture disagreements
    that say nothing about either measurement.

    Args:
        shapes: The shape tally for the document.

    Returns:
        ``pdf_texto``, ``pdf_escaneado`` or ``sin_contenido``.

    """
    if shapes["text"] + shapes["mixed"] > 0:
        return "pdf_texto"
    if shapes["image"]:
        return "pdf_escaneado"
    return "sin_contenido"


def pass_one(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare ``classify`` against the manifest's label for every document.

    Args:
        records: The manifest's PDF entries.

    Returns:
        The pass's results.

    """
    agreements: list[str] = []
    disagreements: list[dict[str, Any]] = []
    unreadable: list[dict[str, str]] = []

    for record in records:
        relative = str(record["path"])
        expected = str(record["pdf_type"])
        path = ROOT / relative

        pages = page_count(path)
        if pages == 0:
            unreadable.append({"path": relative, "why": "could not be opened"})
            continue

        shapes, blanks = classify_document(path, pages)
        measured = document_label(shapes)

        if measured == expected:
            agreements.append(relative)
        else:
            disagreements.append(
                {
                    "path": relative,
                    "manifest": expected,
                    "measured": measured,
                    "pages": pages,
                    "shapes": dict(shapes),
                    "blank_pages": blanks,
                }
            )

    return {
        "agreements": len(agreements),
        "total": len(records),
        "disagreements": disagreements,
        "unreadable": unreadable,
    }


def rendered_page(path: pathlib.Path, number: int) -> dict[str, Any]:
    """Measure one page's resolution and ask for a render above it.

    Args:
        path: The PDF holding the page.
        number: The one-based page number.

    Returns:
        The page's measured resolution and what the render did.

    """
    dpi_result = pdf.effective_dpi(path, number)
    measured = (
        float(dpi_result.value.measurements["effective_dpi"])
        if dpi_result.value is not None
        else None
    )

    result = pdf.render(path, [number], dpi=HIGH_DPI)

    return {
        "effective_dpi": measured,
        "refused": result.value is None,
        "code": result.reason.code if result.reason else None,
        "files_written": result.evidence.observed.get("files_written"),
    }


def pass_two(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Ask every page of every scan to render above its own resolution.

    Args:
        records: The manifest's PDF entries.

    Returns:
        The pass's results.

    """
    scans = [r for r in records if r.get("pdf_type") == "pdf_escaneado"]
    measured_pages: list[dict[str, Any]] = []
    wrote_while_refusing: list[str] = []
    wrong_code: list[dict[str, Any]] = []

    for record in scans:
        relative = str(record["path"])
        path = ROOT / relative

        for number in range(1, page_count(path) + 1):
            outcome = rendered_page(path, number)
            location = f"{relative} p{number}"

            if outcome["refused"] and outcome["code"] != (
                "insufficient_effective_resolution"
            ):
                wrong_code.append(
                    {"path": relative, "page": number, "code": outcome["code"]}
                )
            if outcome["refused"] and outcome["files_written"] != 0:
                wrote_while_refusing.append(location)

            measured_pages.append(
                {
                    "path": relative,
                    "page": number,
                    "effective_dpi": outcome["effective_dpi"],
                    "verdict": "refused" if outcome["refused"] else "honoured",
                }
            )

    return {
        "scans": len(scans),
        "pages_refused": sum(1 for p in measured_pages if p["verdict"] == "refused"),
        "pages_honoured": sum(1 for p in measured_pages if p["verdict"] == "honoured"),
        "wrote_while_refusing": wrote_while_refusing,
        "wrong_code": wrong_code,
        "measured_pages": measured_pages,
    }


def pass_three(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Look for a page whose text layer draws nothing.

    Args:
        records: The manifest's PDF entries.

    Returns:
        The pass's results.

    """
    found: list[dict[str, Any]] = []
    inspected = 0
    carrying_text = 0

    for record in records:
        relative = str(record["path"])
        path = ROOT / relative

        for number in range(1, page_count(path) + 1):
            inspected += 1
            result = pdf.classify(path, number, min_chars=MIN_CHARS)
            observed = (
                result.value.observed
                if result.value is not None
                else result.evidence.observed
            )
            characters = int(result.evidence.measurements.get("char_count", 0))
            if characters > 0:
                carrying_text += 1

            if observed.get("invisible_text"):
                found.append(
                    {"path": relative, "page": number, "characters": characters}
                )

    return {
        "pages_inspected": inspected,
        "pages_carrying_text": carrying_text,
        "pages_with_invisible_layer": found,
    }


def report(results: dict[str, Any]) -> None:
    """Print the three passes for a person to read.

    Args:
        results: The collected results.

    """
    one = results["pass_one"]
    print("=" * 78)
    print("PASS 1 - classify versus the manifest label")
    print("=" * 78)
    print(f"\nagreements:    {one['agreements']}/{one['total']}")
    print(f"disagreements: {len(one['disagreements'])}")
    print(f"unreadable:    {len(one['unreadable'])}")

    for entry in one["unreadable"]:
        print(f"  ! {entry['path']}: {entry['why']}")

    for entry in one["disagreements"]:
        print(f"\n  {entry['path']}")
        print(
            f"      manifest says {entry['manifest']!r}, "
            f"kernel measures {entry['measured']!r}"
        )
        print(f"      pages={entry['pages']} shapes={entry['shapes']}")
        if entry["blank_pages"]:
            print(f"      blank pages: {entry['blank_pages']}")

    two = results["pass_two"]
    print()
    print("=" * 78)
    print(f"PASS 2 - render at {HIGH_DPI} DPI: refuse, and produce nothing")
    print("=" * 78)
    print(f"\nscans:          {two['scans']}")
    print(f"pages refused:  {two['pages_refused']}")
    print(f"pages honoured: {two['pages_honoured']}")
    print(f"files written while refusing: {len(two['wrote_while_refusing'])}")

    for entry in two["wrong_code"]:
        print(f"  ? {entry['path']} p{entry['page']}: refused with {entry['code']!r}")

    print("\n-- measured resolution of every scanned page --")
    for entry in two["measured_pages"]:
        dpi = entry["effective_dpi"]
        shown = "unmeasurable" if dpi is None else f"{dpi} DPI"
        print(f"  {entry['path']} p{entry['page']}: {shown} -> {entry['verdict']}")

    three = results["pass_three"]
    print()
    print("=" * 78)
    print("PASS 3 - invisible text layers in real documents")
    print("=" * 78)
    print(f"\npages inspected:      {three['pages_inspected']}")
    print(f"pages carrying text:  {three['pages_carrying_text']}")
    print(f"pages with an invisible layer: {len(three['pages_with_invisible_layer'])}")

    for entry in three["pages_with_invisible_layer"]:
        print(f"  {entry['path']} p{entry['page']}: {entry['characters']} characters")

    if not three["pages_with_invisible_layer"]:
        print(
            "\n  None. The detector's only real evidence remains the fixture this\n"
            "  project generates; no document in the golden set exercises it."
        )

    print()


def defects(results: dict[str, Any]) -> int:
    """Count the findings that make this a failing run.

    Args:
        results: The collected results.

    Returns:
        The number of defects. A disagreement is counted because it is a
        discrepancy worth a human's attention, not because the kernel is assumed
        wrong: the two measurements answer different questions.

    """
    one = results["pass_one"]
    two = results["pass_two"]

    return (
        len(one["disagreements"])
        + len(one["unreadable"])
        + len(two["wrote_while_refusing"])
        + len(two["wrong_code"])
    )


def main() -> int:
    """Run the three passes.

    Returns:
        A process exit code: non-zero when a pass found a defect.

    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json", action="store_true", help="emit the results as JSON instead"
    )
    args = parser.parse_args()

    records = entries()
    results: dict[str, Any] = {
        "golden_set_pdfs": len(records),
        "min_chars": MIN_CHARS,
        "high_dpi": HIGH_DPI,
        "pass_one": pass_one(records),
        "pass_two": pass_two(records),
        "pass_three": pass_three(records),
    }

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print(f"golden set: {len(records)} PDFs, min_chars={MIN_CHARS}\n")
        report(results)

    return 1 if defects(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
