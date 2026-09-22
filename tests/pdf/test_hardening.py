"""Hardening tests: the invariants and the failure paths (``PDF-12``, ``PDF-13``).

Three tasks meet in this module, and each contributes something the others cannot:

* **``PDF-12``** — atomic publication. The guarantee is not "the happy path leaves no
  ``.tmp``"; it is that an *interrupted* or *failed* run leaves neither a final-named
  artifact nor a staged one. That is only observable from a failure path, so the failure
  paths are what is tested.
* **``PDF-13``** — the fixtures and the three invariants of ``subplan-procesador-pdf.md`` §6.
  Each invariant test carries the mutation that must break it, and each mutation is recorded
  with its observed result. An invariant test that stays green under its mutation is a defect
  of the test, not a guarantee that holds.
* **``PDF-11``** — the typed error model at document scope: a document that cannot be read
  fails fast with a named cause rather than a guess.

The invariants are all about *absence* — no dropped page, no modified input, no fourth
classification. Absence is what a passing test cannot show on its own, which is why the
mutation record matters more here than anywhere else in the suite.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from docflow.pdf import PDFContext, PDFRequest
from docflow.pdf.contracts import PDFPageMetrics
from docflow.pdf.entrypoints import EMPTY_METRICS, process_pdf, process_pdf_page
from docflow.pdf.primitives import failures as failures_module
from docflow.pdf.primitives import images as images_module
from docflow.pdf.primitives.composition import (
    IMAGE_COVERAGE_MIN,
    TEXT_CHAR_MIN,
    WORD_MIN,
    classify_pdf_page,
)
from docflow.pdf.primitives.document import get_page_count
from docflow.pdf.primitives.failures import PDFPrimitiveError
from docflow.pdf.primitives.images import extract_images_from_page
from docflow.pdf.primitives.publishing import TEMP_SUFFIX
from docflow.pdf.primitives.render import render_page_to_image
from tests.factories import PAGE_ARTIFACT_TREE, build_pdf_request_for

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MATRIX = FIXTURES / "matrix"

TEXT_PDF = MATRIX / "three-invoices.pdf"
SCAN_PDF = MATRIX / "scan150.pdf"
MASKED_PDF = FIXTURES / "pdf_aptos_layout" / "36744cc6-2ed9-47e5-b4b8-66c31768164b.pdf"
CORRUPT_PDF = MATRIX / "pdf_corrupt.pdf"
ENCRYPTED_PDF = MATRIX / "pdf_encrypted.pdf"

TEXT_PAGES = 3


def sha256(path: Path) -> str:
    """Return a file's hex digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def staged_files(root: Path) -> list[Path]:
    """Return every staged file under a tree.

    The staging marker is not always the ``.tmp`` suffix: the primitives that drive
    ``pdftoppm`` and ``pdfimages`` hand the engine their own prefix, so a residue there is
    named ``_staged-000.png``. Both shapes are residues, so both are found.
    """
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and (path.name.endswith(TEMP_SUFFIX) or "_staged" in path.name)
    ]


# ======================================================================================
# Invariant 1 — page completeness
# ======================================================================================
# Mutation: in `process_pdf`, iterate `iter_page_indexes(page_count - 1)` so the last page is
# dropped. Observed: 6 tests fail — this one, the page-order test, the per-page-directory
# test, the single-page test, the success-status test and the metadata page-count test.
# Restored: green.
#
# The invariant is stated at document scope because no page-level test can see it. A loop
# that drops its last page produces page results that are each independently valid; only the
# count against the engine's own figure reveals the gap.


def test_invariant_1_every_page_yields_exactly_one_result_and_directory(
    tmp_path: Path,
) -> None:
    """``metadata.page_count == len(pages) == get_page_count(pdf)``, and one directory each."""
    root = tmp_path / "document"
    result = process_pdf(build_pdf_request_for(TEXT_PDF, root))

    engine_count = get_page_count(TEXT_PDF)
    directories = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("page_")
    )

    assert result.metadata.page_count == engine_count
    assert len(result.pages) == engine_count
    assert directories == [f"page_{index:03d}" for index in range(1, engine_count + 1)]
    assert [page.page_number for page in result.pages] == list(
        range(1, engine_count + 1)
    )


# ======================================================================================
# Invariant 2 — immutable input
# ======================================================================================
# Mutation: make `extract_page` write its output to `request.pdf_path` instead of the
# caller's `output_path`. Observed: both tests below fail — the digest changes and the
# directory gains a file. Restored: green.


@pytest.mark.parametrize("source", [TEXT_PDF, SCAN_PDF, MASKED_PDF])
def test_invariant_2_the_input_is_byte_identical_after_a_run(
    tmp_path: Path, source: Path
) -> None:
    """The source document is unchanged, and nothing is written beside it.

    Parametrised across three fixtures because the three primitives reach the engine
    differently — ``pdfseparate``, ``pdftoppm`` and ``pdfimages`` — and a primitive that
    wrote beside its input would only be caught on the fixture that exercises that engine
    call.

    The directory listing is compared before and after as well as the digest, because a
    stray file beside the input is the failure mode ``pdftohtml`` was rejected for, and a
    digest cannot see it.
    """
    before_digest = sha256(source)
    before_tree = sorted(path.name for path in source.parent.iterdir())

    process_pdf(build_pdf_request_for(source, tmp_path / "document"))

    assert sha256(source) == before_digest
    assert sorted(path.name for path in source.parent.iterdir()) == before_tree


# ======================================================================================
# Invariant 3 — classification vocabulary and purity
# ======================================================================================
# Mutation: return `"OCR"` from a branch of `classify_pdf_page`. Observed: 3 tests fail.
# A second mutation, importing `docflow.workflow` in the composition module, fails the purity
# check. Restored: green.
#
# The vocabulary is closed because a fourth value is the visible symptom of this processor
# taking a routing decision, which `subplan-procesador-pdf.md` §2 puts out of bounds.


def test_invariant_3_every_real_page_carries_a_classification_from_the_closed_set(
    tmp_path: Path,
) -> None:
    """No page of any fixture carries a classification outside the closed set.

    Swept across three fixtures that produce two different answers, so the check is not
    green merely because one classification happens to dominate.

    Note what this test does **not** cover, because it took a surviving mutation to find
    out: iterating real pages can only reach the branches those pages exercise. A mutation
    that returns a fourth value from a branch no fixture reaches survives this test
    untouched — which happened, and is why the vector sweep below exists. Both are needed:
    this one grounds the invariant in real bytes, that one covers the classifier's domain.
    """
    seen: set[str] = set()

    for index, source in enumerate((TEXT_PDF, SCAN_PDF, MASKED_PDF)):
        result = process_pdf(build_pdf_request_for(source, tmp_path / f"doc{index}"))
        for page in result.pages:
            assert page.classification in ("TEXT", "IMAGE", "MIXED")
            seen.add(page.classification)

    assert seen, "no page was classified at all, so the assertion above proved nothing"


def test_invariant_3_holds_over_the_classifiers_whole_domain() -> None:
    """No metric vector produces a value outside the closed set.

    The domain is swept rather than sampled, because the branches of ``classify_pdf_page``
    are chosen by thresholds and a fixture set can only ever exercise the corners its
    documents happen to sit in. The specific gap this closes: a vector with no text *and* no
    images is reachable for a blank or failed page, no committed fixture produces it, and a
    mutation returning a fourth value from that branch was invisible to every real-bytes test
    in this module.

    Mutation that breaks it: change any branch's return to ``"OCR"``. The sweep reaches that
    branch and the assertion fails. Verified — before this test existed, that mutation passed
    the entire hardening module.
    """
    character_counts = (0, 1, TEXT_CHAR_MIN, TEXT_CHAR_MIN * 10)
    word_counts = (0, 1, WORD_MIN, WORD_MIN * 10)
    coverages = (0.0, IMAGE_COVERAGE_MIN, 1.0)

    checked = 0
    for characters in character_counts:
        for words in word_counts:
            for image_coverage in coverages:
                for largest in coverages:
                    metrics = PDFPageMetrics(
                        characters=characters,
                        words=words,
                        text_blocks=1 if characters else 0,
                        images=1 if image_coverage else 0,
                        text_coverage=min(1.0, characters / 1000),
                        image_coverage=image_coverage,
                        largest_image_coverage=largest,
                    )
                    assert classify_pdf_page(metrics) in ("TEXT", "IMAGE", "MIXED"), (
                        metrics
                    )
                    checked += 1

    # The empty vector is named explicitly: it is the one that was uncovered, and a sweep
    # that silently stopped including it would look identical to one that never did.
    assert checked >= 100
    # `EMPTY_METRICS` is the library's own definition of "a page that produced no
    # measurement", so the uncovered vector is named by reusing it rather than by spelling
    # the same zeroes out again.
    assert classify_pdf_page(EMPTY_METRICS) in ("TEXT", "IMAGE", "MIXED")


# ======================================================================================
# The happy path across the fixture set
# ======================================================================================


@pytest.mark.parametrize(
    ("source", "expected_pages"),
    [(TEXT_PDF, TEXT_PAGES), (SCAN_PDF, 1), (MASKED_PDF, 1)],
)
def test_the_happy_path_over_every_fixture(
    tmp_path: Path, source: Path, expected_pages: int
) -> None:
    """Each fixture runs to ``success`` with one page directory per page.

    The artifact tree is asserted as the complete top-level set, because an extra entry is a
    namespace this processor has no business publishing into.
    """
    root = tmp_path / "document"

    result = process_pdf(build_pdf_request_for(source, root))

    assert result.status == "success"
    assert result.validation.status == "VALID"
    assert len(result.pages) == expected_pages
    assert {path.name for path in root.iterdir()} == {
        "source",
        "metadata.json",
        *(f"page_{index:03d}" for index in range(1, expected_pages + 1)),
    }


def test_the_document_namespace_stays_inside_this_processor(tmp_path: Path) -> None:
    """No ``image/``, ``ocr/`` or ``llm/`` directory appears anywhere.

    Those belong to other processors. Writing into them would have this processor claim work
    it does not do, and ``subplan-procesador-pdf.md`` §2 puts them out of bounds.
    """
    root = tmp_path / "document"

    process_pdf(build_pdf_request_for(MASKED_PDF, root))

    for namespace in ("image", "ocr", "llm"):
        assert not (root / namespace).exists()


# ======================================================================================
# PDF-11 — the typed error model at document scope
# ======================================================================================


@pytest.mark.parametrize(
    ("source", "expected_type"),
    [
        (CORRUPT_PDF, "CORRUPTED_PDF"),
        (ENCRYPTED_PDF, "ENCRYPTED_PDF"),
        (MATRIX / "definitely-absent.pdf", "MISSING_FILE"),
    ],
)
def test_an_unreadable_document_fails_fast_with_a_named_cause(
    tmp_path: Path, source: Path, expected_type: str
) -> None:
    """Each way of being unreadable produces its own classification, not a generic failure.

    Mutation that breaks it: drop the encryption check from ``check_pdf_is_readable``. The
    encrypted fixture then degrades to ``CORRUPTED_PDF``, which is a worse answer — it tells
    an operator to replace a file that is merely password-protected.

    A document with no readable pages has no partial result worth returning, so this is the
    failure the plan allows to be raised rather than recorded.
    """
    with pytest.raises(PDFPrimitiveError) as failure:
        process_pdf(build_pdf_request_for(source, tmp_path / "document"))

    assert failure.value.error_type == expected_type
    assert failure.value.recoverable is False


def test_an_unreadable_document_publishes_nothing(tmp_path: Path) -> None:
    """A failed document run leaves no artifact behind.

    The output root may exist — creating it happens before the failure — but it must contain
    no page directory and no metadata, because a reader that found one would treat an
    unreadable document as a processed one.
    """
    root = tmp_path / "document"

    with pytest.raises(PDFPrimitiveError):
        process_pdf(build_pdf_request_for(ENCRYPTED_PDF, root))

    assert not (root / "metadata.json").exists()
    assert not list(root.glob("page_*"))


def test_the_unsupported_classification_is_not_invented() -> None:
    """``UNSUPPORTED_PDF`` is a contract literal this implementation never produces.

    Pinned deliberately. Poppler has no version gate to fail — a document whose header was
    rewritten to ``%PDF-9.9`` is read exactly like ``%PDF-1.7`` — and a file that does not
    parse is corruption, not "unsupported". Producing the literal would mean inventing a
    distinction the engine does not make, which is the plausible-but-wrong classification the
    plan forbids.

    If a future engine gains a real version gate, this test fails and the reasoning recorded
    in ``check_pdf_is_readable`` becomes stale — which is the point of asserting it.
    """
    source = Path(failures_module.__file__).read_text(encoding="utf-8")

    assert "UNSUPPORTED_PDF" in source
    assert 'PDFPrimitiveError(\n            "UNSUPPORTED_PDF"' not in source


# ======================================================================================
# PDF-12 — atomic publication on the failure paths
# ======================================================================================


def test_an_interrupted_image_publish_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The acceptance criterion: an interruption leaves no artifact and no staged file.

    The interruption is injected between the engine's extraction and the rename step, which
    is the window where the engine's own output exists under a staging name. Before this was
    handled, five ``_staged-*`` files survived — verified by observation, not assumed.

    They mattered because ``PDF-09`` treats every file under ``embedded_images/`` as an
    artifact of the page, so a residue would be read as an image no record describes.

    Mutation that breaks it: remove the ``_discard_staged`` call from the except branch. The
    staged files survive and the assertion fails.
    """
    published = tmp_path / "embedded_images"

    def interrupt(*_args: object, **_kwargs: object) -> None:
        raise OSError("interrupted before the rename step")

    monkeypatch.setattr(images_module, "_publish_images", interrupt)

    with pytest.raises(PDFPrimitiveError):
        extract_images_from_page(MASKED_PDF, 1, published)

    assert not staged_files(published)
    assert not published.exists() or not list(published.iterdir())


def test_an_interrupted_render_publishes_no_artifact(tmp_path: Path) -> None:
    """A render that produced nothing is reported, and nothing keeps its name.

    The engine's staged file is removed before the failure is raised, so the published name
    is not occupied by an empty file.
    """
    target = tmp_path / "render" / "page.png"

    with pytest.raises(PDFPrimitiveError):
        render_page_to_image(ENCRYPTED_PDF, 1, target)

    assert not target.exists()
    assert not staged_files(tmp_path)


def test_a_successful_document_run_leaves_no_staged_file(tmp_path: Path) -> None:
    """The happy path is clean too, over a fixture with images and masks.

    A run that cleans up only on failure would still be leaving the engine's intermediate
    files behind on the path that runs most often.
    """
    root = tmp_path / "document"

    process_pdf(build_pdf_request_for(MASKED_PDF, root))

    assert not staged_files(root)


def test_a_partial_page_keeps_only_its_valid_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page whose images failed retains its render, its text and its metadata — and no more.

    The directory listing is the assertion: a partial page that kept a fragment of the failed
    capability would be publishing an artifact its result does not describe.
    """

    def fail_images(*_args: object, **_kwargs: object) -> None:
        raise PDFPrimitiveError(
            "IMAGE_EXTRACTION_ERROR", "simulated", page_number=1, recoverable=True
        )

    monkeypatch.setattr("docflow.pdf.entrypoints.extract_images_from_page", fail_images)

    root = tmp_path / "document"
    request = build_pdf_request_for(MASKED_PDF, root)
    page_dir = root / "page_001"

    result = process_pdf_page(request, 1, page_dir)

    assert result.status == "partial"
    present = sorted(
        str(path.relative_to(page_dir))
        for path in page_dir.rglob("*")
        if path.is_file()
    )
    assert present == list(PAGE_ARTIFACT_TREE)
    assert not (page_dir / "embedded_images").exists()
    assert not staged_files(page_dir)


def test_the_partial_status_reaches_the_document_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file a consumer reads says ``partial``, not the provisional ``success``.

    The metadata is published after the verdict is settled for exactly this reason; an
    earlier version wrote it with the provisional status and the file disagreed with the
    result it described.
    """

    def fail_images(*_args: object, **_kwargs: object) -> None:
        raise PDFPrimitiveError(
            "IMAGE_EXTRACTION_ERROR", "simulated", page_number=1, recoverable=True
        )

    monkeypatch.setattr("docflow.pdf.entrypoints.extract_images_from_page", fail_images)

    root = tmp_path / "document"
    result = process_pdf(build_pdf_request_for(MASKED_PDF, root))

    payload = json.loads((root / "metadata.json").read_text())

    assert result.status == "partial"
    assert payload["status"] == "partial"
    assert any(error["type"] == "IMAGE_EXTRACTION_ERROR" for error in payload["errors"])


def test_the_validation_state_is_never_a_workflow_action(tmp_path: Path) -> None:
    """States are the contract's own vocabulary, never ``REUSE`` / ``SKIP`` / ``FORCE``.

    ``docs/plan/README.md`` §7 forbids converting a validation state into a workflow action;
    this processor has no business naming one. Checked on the written metadata, which is what
    a consumer actually reads.
    """
    root = tmp_path / "document"

    process_pdf(build_pdf_request_for(TEXT_PDF, root))

    payload = json.loads((root / "metadata.json").read_text())

    assert payload["validation"] in ("VALID", "PARTIAL", "INVALID", "ERROR")
    for forbidden in ("REUSE", "SKIP", "FORCE", "RESUME", "EXECUTE", "BLOCKED"):
        assert forbidden not in json.dumps(payload)


def test_no_contract_field_is_filled_with_a_silent_stand_in(tmp_path: Path) -> None:
    """The written metadata carries no empty string, no zeroed default, no fake engine.

    ``docs/plan/README.md`` §7's rule, checked on the artifact rather than in the code: the
    engine and its version are real, the identities are the requested ones, and
    ``processing_key`` is explicitly ``None`` rather than an invented hash.
    """
    root = tmp_path / "document"

    process_pdf(build_pdf_request_for(TEXT_PDF, root))

    payload = json.loads((root / "metadata.json").read_text())

    assert payload["engine"] == "poppler"
    assert payload["engine_version"]
    assert payload["processor_version"]
    assert payload["document_id"] == "doc-1"
    assert payload["workflow_run_id"] == "run-1"
    assert payload["processing_key"] is None


def test_the_request_identity_is_preserved_end_to_end(tmp_path: Path) -> None:
    """The correlation context echoes unchanged, at document and at page scope."""
    root = tmp_path / "document"
    request = PDFRequest(
        pdf_path=TEXT_PDF,
        output_dir=root,
        options=build_pdf_request_for(TEXT_PDF, root).options,
        context=PDFContext(document_id="doc-42", workflow_run_id="run-7"),
    )

    result = process_pdf(request)

    assert result.metadata.context == request.context
    assert all(page.metadata.context == request.context for page in result.pages)
    payload = json.loads((root / "metadata.json").read_text())
    assert payload["document_id"] == "doc-42"
    assert payload["workflow_run_id"] == "run-7"
