"""Structural validation (``OCR-09``) - §3.4's *Validation* group.

Validation says whether what the processor is about to hand back is complete. States are
**descriptive**: ``VALID``, ``EMPTY``, ``LOW_CONTENT``, ``INCOMPLETE``, ``PARSE_ERROR``, ``ERROR``.
Nothing here retries, nothing here throws, and nothing here decides what to do next — a failure is
classified and returned, because the orchestrator owns the decision. ``LOW_CONTENT -> use the VLM``
is the orchestrator's call and this module does not know the VLM exists.

Four functions, answering four different questions, and the split is what keeps the vocabulary
honest:

* :func:`validate_ocr_request` — is the request usable *before* any work starts?
* :func:`validate_ocr_input` — can the image be read at all?
* :func:`validate_output_artifacts` — is every promised artifact on disk?
* :func:`validate_ocr_result` — given all of that, what is the verdict?

**The error vocabulary is §3.1's, not this task's.** ``OCR-09``'s scope names the eight values from
``subplan-procesador-ocr.md`` §3.7 (``INVALID_INPUT``, ``UNSUPPORTED_IMAGE``, ``OCR_ERROR``,
``LAYOUT_ERROR``, …) while the contract declares §3.1's set (``MISSING_FILE``,
``UNSUPPORTED_FORMAT``, ``DECODE_ERROR``, …). The two share only ``IO_ERROR`` and
``INTERNAL_ERROR``. The contract wins, for the reason recorded beside the literal in
:mod:`docflow.ocr.contracts`: §3.1 is the section titled *Contract types*, §3.7 is a posture
statement that does not present its list as a contract, and ``OCRError.type`` is annotated with the
contract's literal — so a §3.7 value would raise at construction rather than classify anything.
The reconciliation belongs to ``GEN-17``.

Writes are :mod:`docflow.ocr.primitives.files`, which is §3.4's *Files* group. The ``OCR-02``
skeleton declared both groups in one ``persistence.py``; ``OCR-09`` split them so each module is one
of the plan's groups, and a reader looking up a name finds it where the plan files it.
"""

from __future__ import annotations

import typing
from pathlib import Path

from docflow.ocr.contracts import (
    ArtifactPaths,
    OCRError,
    OCRErrorType,
    OCRRequest,
    OCRResult,
    OCRValidation,
    OCRValidationState,
)

CONTRACT_ERROR_TYPES: tuple[str, ...] = typing.get_args(OCRErrorType)
"""The failure vocabulary, derived from the contract rather than restated.

``typing.get_args`` on the literal means adding a value to the contract cannot leave this module
behind, and a test asserts the two agree. A second hand-written copy is the defect the image
processor records: two lists that drift, where the one nobody edits keeps passing.
"""

CONTRACT_VALIDATION_STATES: tuple[str, ...] = typing.get_args(OCRValidationState)
"""The verdict vocabulary, derived the same way and for the same reason."""

UNREADABLE_INPUT_ERROR_TYPES: frozenset[str] = frozenset(
    {"MISSING_FILE", "UNSUPPORTED_FORMAT", "DECODE_ERROR"}
)
"""The failures that mean "this image cannot be read", as opposed to "the processor broke".

Nothing about the processor failed when the file is absent or is not an image, and reporting that as
an internal error would send a reader looking for a bug that does not exist.
"""

LOW_CONTENT_CHARACTER_FLOOR: int = 32
"""Characters below which a *non-empty* extraction is reported as ``LOW_CONTENT``.

Deliberately small and deliberately not zero. ``EMPTY`` already covers "nothing at all", so this
threshold exists for the page that yielded a word or two — a stamp, a page number, a form label —
where the extraction succeeded and the *result* is thin. Zero would make the state unreachable,
which is the defect the image processor's classification records.

The value is a PoC judgement rather than a measured one, and it says so: no committed fixture sits
near it on both sides. ``# TODO: [MVP]`` calibrate it against the corpus once ``OCR-12`` commits a
fixture set that includes a genuinely sparse page.
"""


def validate_ocr_request(request: OCRRequest) -> list[OCRError]:
    """Check the request before any work starts.

    Four questions, each a failure the processor would otherwise discover later, after paying for a
    conversion:

    * is the image path present and a file?
    * is the output path usable — absent, or a directory?
    * is ``context.document_id`` set, since every artifact records it?
    * is ``context.page_number`` at least 1, since it is documented as 1-based?

    ``MISSING_FILE`` for the image and ``IO_ERROR`` for the output path, because the two are
    different problems with different remedies: one is a caller pointing at bytes that are not
    there, the other at a place the processor may not write.

    Args:
        request: The request to check.

    Returns:
        The failures found; empty when the request is usable. Never raises: a caller forced to catch
        an exception to learn that a path was absent is being told twice.
    """
    errors: list[OCRError] = []

    if not request.image_path.is_file():
        errors.append(
            OCRError(
                type="MISSING_FILE",
                message=f"input image is not a readable file: {request.image_path}",
                recoverable=False,
                metadata={"image_path": str(request.image_path)},
            )
        )

    output_dir = request.output_dir
    if output_dir.exists() and not output_dir.is_dir():
        errors.append(
            OCRError(
                type="IO_ERROR",
                message=f"output path exists and is not a directory: {output_dir}",
                recoverable=False,
                metadata={"output_dir": str(output_dir)},
            )
        )

    if not request.context.document_id.strip():
        errors.append(
            OCRError(
                type="INTERNAL_ERROR",
                message="the request carries no document_id, so its artifacts cannot be identified",
                recoverable=False,
                metadata={"field": "context.document_id"},
            )
        )

    if request.context.page_number < 1:
        errors.append(
            OCRError(
                type="INTERNAL_ERROR",
                message=(
                    f"page_number is {request.context.page_number}; pages are numbered from 1"
                ),
                recoverable=False,
                metadata={"field": "context.page_number"},
            )
        )

    return errors


def validate_ocr_input(image_path: Path) -> list[OCRError]:
    """Check that the input image can be read.

    Structural only, and that is the boundary: this asks whether there are bytes, not whether the
    image is *good*. Sharpness, contrast and skew belong to the image processor's own analysis, and
    whether the bytes decode in the format claimed is the engine's answer at conversion time —
    guessing it here would be a second opinion free to disagree with the one that matters.

    A zero-byte file is ``DECODE_ERROR`` rather than ``MISSING_FILE``: the caller was right that a
    file is there, and the failure is that nothing can be decoded from it.

    Args:
        image_path: The image to check.

    Returns:
        The failures found; empty when the image is readable.
    """
    if not image_path.is_file():
        return [
            OCRError(
                type="MISSING_FILE",
                message=f"input image is not a readable file: {image_path}",
                recoverable=False,
                metadata={"image_path": str(image_path)},
            )
        ]

    try:
        size = image_path.stat().st_size
    except OSError as error:
        return [
            OCRError(
                type="IO_ERROR",
                message=f"input image cannot be inspected: {error}",
                recoverable=False,
                metadata={"image_path": str(image_path)},
            )
        ]

    if size == 0:
        return [
            OCRError(
                type="DECODE_ERROR",
                message=f"input image is empty: {image_path}",
                recoverable=False,
                metadata={"image_path": str(image_path), "size": 0},
            )
        ]

    return []


def validate_output_artifacts(paths: ArtifactPaths) -> list[Path]:
    """Report which promised artifacts are absent.

    ``tables_dir`` is **not** required, and the distinction is the plan's own: an image with no
    table
    needs no ``tables/`` artifact, and that is data rather than a failure. Requiring the directory
    would make every tableless page ``INCOMPLETE``.

    Args:
        paths: The paths the result claims to have published.

    Returns:
        The artifacts that were expected and not found, in a fixed order so two runs over one
        namespace report them identically.
    """
    required = (
        ("metadata", paths.metadata),
        ("markdown", paths.markdown),
        ("structured_document", paths.structured_document),
        ("text", paths.text),
    )
    return [path for _, path in required if not path.is_file()]


def validate_ocr_result(result: OCRResult) -> OCRValidation:
    """Check a result against what it claims.

    Five verdicts, and the order they are decided in is the point — each is only reachable when the
    ones before it do not apply, so a page cannot be reported ``VALID`` while an artifact is
    missing:

    1. **``ERROR``** — the run recorded a failure. Its own errors are carried through rather than
       re-derived, because the stage that failed knows more than a reader of the result does.
    2. **``INCOMPLETE``** — an artifact the result promises is absent. The missing paths are
    reported
       in the verdict's own field, so a caller never has to re-derive which one.
    3. **``PARSE_ERROR``** — there is no structured document to validate. The engine returned
       something this processor could not turn into a document, which is a different fact from a
       blank page: ``EMPTY``.
    4. **``EMPTY``** — the extraction produced no content and everything it promised is on disk.
       Reachable and not an error: ``OCR-12``'s blank fixture exists to exercise exactly this.
    5. **``LOW_CONTENT``** — content, but less than :data:`LOW_CONTENT_CHARACTER_FLOOR`.
    6. **``VALID``** — none of the above.

    ``LOW_CONTENT`` and ``VALID`` are the only verdicts that read the *content* rather than the
    structure, and they come last because a thin result with a missing artifact is ``INCOMPLETE``
    first. ``INCOMPLETE`` before ``PARSE_ERROR`` for the mirror-image reason: an artifact that was
    promised and is not there is a fact about *this run*, whereas an unparseable document is a fact
    about the engine, and the run's own failure is the more actionable of the two.

    The content verdicts read ``result.structured_document`` — the payload ``document.json`` will
    hold — rather than the typed fields beside it, because the artifact is what a consumer reads and
    validating anything else would let a complete result with an empty payload pass as ``VALID``.
    ``blocks`` and ``tables`` come from the typed fields, which is where the extraction puts them.

    Args:
        result: The result to validate.

    Returns:
        The verdict: a state, the typed errors behind it, and any missing artifacts. Never raises,
        and never reports a silent empty result as valid.
    """
    if result.status == "failed":
        return _validation("ERROR", _recorded_errors(result), [])

    missing = validate_output_artifacts(result.artifacts)
    if missing:
        return _validation(
            "INCOMPLETE", [_missing_artifact_error(path) for path in missing], missing
        )

    payload = result.structured_document
    if not payload or "schema_version" not in payload:
        return _validation("PARSE_ERROR", [_unparseable_document_error(result)], [])

    text = str(payload.get("text", ""))

    if not text.strip() and not result.blocks and not result.tables:
        return _validation("EMPTY", [], [])

    if len(text.strip()) < LOW_CONTENT_CHARACTER_FLOOR:
        return _validation("LOW_CONTENT", [], [])

    return _validation("VALID", [], [])


def _validation(
    state: str, errors: list[OCRError], missing: list[Path]
) -> OCRValidation:
    """Assemble a verdict, refusing a state the contract does not declare.

    Args:
        state: The validation state.
        errors: The failures behind it.
        missing: The artifacts that were expected and absent.

    Returns:
        The verdict.

    Raises:
        ValueError: The state is not a contract value. Raised rather than returned because it is a
            defect in *this* module, not a fact about the extraction, and a caller cannot act on a
            verdict it does not recognise.
    """
    if state not in CONTRACT_VALIDATION_STATES:
        raise ValueError(
            f"unknown validation state {state!r}; the contract declares "
            f"{CONTRACT_VALIDATION_STATES}"
        )
    return OCRValidation(
        status=typing.cast("OCRValidationState", state),
        errors=errors,
        missing_artifacts=missing,
    )


def _recorded_errors(result: OCRResult) -> list[OCRError]:
    """Return the failures a failed run already classified.

    The typed failure lives in ``OCRResult.error`` — the contract's own field for it — and the
    validation record may *also* carry failures collected while validating. Both are reported, with
    ``error`` first, and neither is re-derived: the stage that failed knows more than a reader of
    the result does, and a validator that reclassified the failure would be a second opinion about
    a cause it did not witness.

    An earlier version read only ``result.validation.errors``, and a test with a failed run and a
    populated ``error`` returned an empty list — the failure disappeared exactly when it mattered.

    Args:
        result: The failed result.

    Returns:
        The failures, without duplicates.
    """
    errors = [result.error] if result.error is not None else []
    for recorded in result.validation.errors:
        if recorded not in errors:
            errors.append(recorded)
    return errors


def _missing_artifact_error(path: Path) -> OCRError:
    """Return the typed failure for an artifact that was promised and absent.

    Args:
        path: The artifact that is missing.

    Returns:
        The failure. ``IO_ERROR`` rather than a new vocabulary: the contract has no "missing
        artifact" type, and inventing a ninth value nothing declares is the divergence this module
        already refuses to repeat.
    """
    return OCRError(
        type="IO_ERROR",
        message=f"a promised artifact is missing: {path}",
        recoverable=False,
        metadata={"artifact": str(path)},
    )


def _unparseable_document_error(result: OCRResult) -> OCRError:
    """Return the typed failure for a result that carries no structured document.

    Args:
        result: The result under validation.

    Returns:
        The failure. ``ENGINE_ERROR`` because the engine returned nothing this processor could turn
        into a document, and the counts are recorded so a reader can tell that from a blank page
        without re-running the conversion.
    """
    return OCRError(
        type="ENGINE_ERROR",
        message="the result carries no structured document to validate",
        recoverable=False,
        metadata={
            "blocks": len(result.blocks),
            "tables": len(result.tables),
            "status": result.status,
        },
    )


__all__ = [
    "CONTRACT_ERROR_TYPES",
    "CONTRACT_VALIDATION_STATES",
    "LOW_CONTENT_CHARACTER_FLOOR",
    "UNREADABLE_INPUT_ERROR_TYPES",
    "validate_ocr_input",
    "validate_ocr_request",
    "validate_ocr_result",
    "validate_output_artifacts",
]
