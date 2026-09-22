"""Structural validation — the result is checked against what it claims to be.

Owned by ``PDF-09`` for the page-level verdict; ``PDF-11`` owns the document-level
``validate_pdf_result``, ``validate_pdf`` and the ``ENCRYPTED_PDF`` / ``CORRUPTED_PDF`` /
``UNSUPPORTED_PDF`` fail-fast paths.

"Structural" is the whole point, and ``docs/plan/README.md`` §7 says why: silent failures —
a truncated prompt, a plausible wrong value — are reported as correct unless something
checks. So the check here is not "did the run finish" but "does every path this result
claims to have published actually exist, and is every field it promises populated".

The vocabulary is the contract's own: ``VALID``, ``PARTIAL``, ``INVALID``, ``ERROR``, plus
the per-page ``RENDER_ERROR`` / ``TEXT_EXTRACTION_ERROR`` / ``IMAGE_EXTRACTION_ERROR``. Each
named state has a builder below, so a caller cannot invent one and cannot forget the errors
that justify it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from docflow.pdf.contracts import (
    PDFContext,
    PDFError,
    PDFOptions,
    PDFPageMetadata,
    PDFPageResult,
    PDFPageValidation,
)

VALID = "VALID"
PARTIAL = "PARTIAL"
INVALID = "INVALID"
ERROR = "ERROR"


def _missing(paths: list[Path | None]) -> list[Path]:
    """Return the paths that are ``None`` or absent from disk.

    Args:
        paths: The artifact paths the result claims.

    Returns:
        The paths that cannot be found, in the order given. A ``None`` entry is reported as a
        bare name rather than skipped: a result that promises an artifact and has none is
        exactly the case this function exists for.
    """
    absent: list[Path] = []
    for path in paths:
        if path is None:
            absent.append(Path("<not published>"))
        elif not path.exists():
            absent.append(path)
    return absent


ARTIFACT_CAPABILITIES: Final[tuple[tuple[str, str, str], ...]] = (
    ("extract_pages", "page_pdf", "IO_ERROR"),
    ("render", "page_image", "RENDER_ERROR"),
    ("extract_text", "native_text", "TEXT_EXTRACTION_ERROR"),
)
"""Each capability with the result field its artifact lands in and the failure it raises.

One table rather than two parallel lists. An earlier version derived the missing paths and
the unsatisfied capabilities separately and zipped them together, which silently mispaired
them as soon as the lists had different lengths: a capability that was not requested appears
in one and not the other, so every error after it named the wrong capability. The table makes
the pairing explicit and impossible to get wrong.
"""

_OPTION_FIELD: Final[dict[str, str]] = {
    "page_pdf": "extract_pages",
    "page_image": "render",
    "native_text": "extract_text",
}
"""The request option that asks for each artifact field."""


def _capability_gap(
    result: PDFPageResult, field: str, options: PDFOptions | None
) -> bool:
    """Report whether a capability was requested and published nothing.

    A capability that was **not requested** is not a gap: ``render: false`` means there is no
    render and no failure, and reading the absent artifact as a gap would report a page as
    ``PARTIAL`` for doing exactly what it was asked to do.

    Args:
        result: The page result to check.
        field: The result attribute holding the capability's artifact.
        options: The options the page was processed under, or ``None`` when unknown. Without
            them every absent artifact counts, because the validator cannot tell a deliberate
            omission from a failure and the stricter answer is the safe one.

    Returns:
        ``True`` when the artifact is absent and its capability was requested.
    """
    if getattr(result, field) is not None:
        return False
    return options is None or bool(getattr(options, _OPTION_FIELD[field]))


def validate_pdf_page_result(
    result: PDFPageResult,
    recorded_errors: list[PDFError] | None = None,
    options: PDFOptions | None = None,
) -> PDFPageValidation:
    """Validate one page result structurally.

    Three independent signals are combined, and all three are needed:

    * **A capability that was requested and published nothing** — the page promised an
      artifact and did not deliver it.
    * **Recorded failures** — a capability that raised and was caught. This is the signal an
      earlier version missed: the page's three core artifacts were all present, so the
      verdict came back ``VALID`` even though image extraction had failed and the failure sat
      in the error list. A page that reports a failure is not a valid page, whatever else it
      managed to publish.
    * **The options** — a capability that was never asked for is not a gap. Treating it as
      one made ``render: false`` report ``PARTIAL`` for a page that did exactly as it was
      told.

    Args:
        result: The page result to validate.
        recorded_errors: Failures the caller caught while processing the page.
        options: The options the page was processed under.

    Returns:
        The verdict. ``VALID`` when every requested artifact is present and nothing failed,
        ``PARTIAL`` when something survived a failure, ``INVALID`` when nothing did, and
        ``ERROR`` when no verdict could be reached at all.

    Note:
        The function never returns a workflow action. A validation state is data; turning it
        into ``REUSE`` / ``RETRY`` belongs to the orchestrator, and ``docs/plan/README.md``
        §7 forbids the conversion here.
    """
    recorded = list(recorded_errors) if recorded_errors is not None else []

    gaps = [
        (capability, field, error_type)
        for capability, field, error_type in ARTIFACT_CAPABILITIES
        if _capability_gap(result, field, options)
    ]

    if not gaps and not recorded:
        return PDFPageValidation(status=VALID, errors=[], missing_artifacts=[])

    missing = _missing([result.page_pdf, result.page_image, result.native_text])
    errors = [
        PDFError(
            type=error_type,  # type: ignore[arg-type]
            page_number=result.page_number,
            message=f"the {capability} artifact was not published",
            recoverable=True,
            metadata={"capability": capability, "field": field},
        )
        for capability, field, error_type in gaps
    ]
    errors.extend(recorded)

    # "Nothing survived" is measured against what was **requested**, not against the full
    # table: a run that asked for two capabilities and lost both of them has nothing left,
    # and comparing against all three would call it partial forever.
    requested = [
        capability
        for capability, field, _ in ARTIFACT_CAPABILITIES
        if options is None or bool(getattr(options, _OPTION_FIELD[field]))
    ]
    if gaps and len(gaps) == len(requested) and not result.embedded_images:
        return PDFPageValidation(
            status=INVALID, errors=errors, missing_artifacts=missing
        )

    return PDFPageValidation(status=PARTIAL, errors=errors, missing_artifacts=missing)


def page_validation_with(
    status: str,
    errors: list[PDFError],
    missing_artifacts: list[Path] | None = None,
) -> PDFPageValidation:
    """Assemble a page validation verdict.

    Args:
        status: One of the per-page validation states.
        errors: The failures that justify the state.
        missing_artifacts: Paths the validation expected and did not find.

    Returns:
        The verdict. Errors are required rather than defaulted: a state that is not ``VALID``
        and carries no reason is a state nobody can act on.

    Raises:
        ValueError: ``status`` is not one of the per-page validation states, or a non-``VALID``
            state carries no error. Both are reported rather than accepted, because the
            alternative is a result that says something went wrong without saying what.
    """
    if status not in (VALID, PARTIAL, INVALID, ERROR):
        raise ValueError(f"unknown page validation state: {status!r}")
    if status != VALID and not errors:
        raise ValueError(f"validation state {status!r} requires at least one error")
    return PDFPageValidation(
        status=status,  # type: ignore[arg-type]
        errors=errors,
        missing_artifacts=missing_artifacts if missing_artifacts is not None else [],
    )


def page_metadata(
    engine_name: str,
    engine_version: str,
    processor: str,
    processor_version: str,
    context: PDFContext,
    timing: dict[str, float],
) -> PDFPageMetadata:
    """Assemble the provenance record for a page.

    Args:
        engine_name: The engine's name.
        engine_version: The engine's version.
        processor: The processor's name.
        processor_version: The processor's version.
        context: The request's correlation context, echoed unchanged.
        timing: Wall-clock seconds by stage.

    Returns:
        The provenance record. No field has a fallback: a blank engine or version would be
        the silent stand-in the plan forbids, and a caller that cannot supply one has a
        failure to report instead.
    """
    return PDFPageMetadata(
        processor=processor,
        processor_version=processor_version,
        engine=engine_name,
        engine_version=engine_version,
        context=context,
        timing=timing,
    )


__all__ = [
    "ERROR",
    "INVALID",
    "PARTIAL",
    "VALID",
    "page_metadata",
    "page_validation_with",
    "validate_pdf_page_result",
]
