"""Choosing the documentary source and the extraction strategy (``ORC-12``).

Two decisions, and both belong to the orchestrator: *what does this page offer?* and *in
what form should it be read?* The processors never see the question — they receive an
:class:`~docflow.llm.contracts.LLMInput` that already reflects the answer, which is what
keeps the routing out of every processor.

The rules are a **literal table with no fallback**: each reachable combination names its
reason, and a combination the PoC never reaches carries a ``# TODO: [MVP]`` for the reason
it should eventually report rather than a claim nobody tests. Where a page offers nothing
readable, the selection is *no source* — stated as such, never defaulted to the image.

The source is read from what the page's stages actually produced: a live result when the
stage ran in this process, and the published artifact when the stage was reused from a
previous run. Both are facts about the page, not content the orchestrator interprets.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from docflow.workflow.configuration import policy_flag
from docflow.workflow.contracts import (
    ExtractionStrategy,
    PageContext,
    SourceKind,
)

#: Result keys the orchestrator stores processor results under, per page.
RESULT_PDF = "pdf_result"
RESULT_IMAGE = "image_result"
RESULT_OCR = "ocr_result"
RESULT_LLM = "llm_result"

#: Artifact keys the routing reads. ``vlm_ready_image`` and ``ocr_ready_image`` are the two
#: purpose-specific variants; ``normalized_image`` is the general one.
ARTIFACT_NATIVE_TEXT = "native_text"
ARTIFACT_PAGE_IMAGE = "page_image"
ARTIFACT_NORMALIZED_IMAGE = "normalized_image"
ARTIFACT_OCR_READY = "ocr_ready_image"
ARTIFACT_VLM_READY = "vlm_ready_image"
ARTIFACT_OCR_TEXT = "ocr_text"


@dataclass(frozen=True)
class SourceSelection:
    """The source chosen for a page, and why.

    Attributes:
        source: The source, or ``None`` when the page offers nothing readable.
        reason: Why this source was chosen.
    """

    source: SourceKind | None
    reason: str


@dataclass(frozen=True)
class StrategySelection:
    """The extraction strategy chosen for a page, and why.

    Attributes:
        strategy: The strategy, or ``None`` when no source was selected.
        reason: Why this strategy was chosen.
    """

    strategy: ExtractionStrategy | None
    reason: str


def readable(path: Path | None) -> bool:
    """Return whether a path holds a non-empty artifact.

    A path recorded in the durable context is a statement about where an artifact
    belongs, not a promise that it is still there: the file is what is checked.

    Args:
        path: The artifact path, or ``None`` when the page never recorded one.

    Returns:
        ``True`` when the artifact exists and is non-empty.
    """
    return path is not None and path.is_file() and path.stat().st_size > 0


def native_text_present(page: PageContext) -> bool:
    """Return whether the page has native text.

    Args:
        page: The page to inspect.

    Returns:
        ``True`` when the PDF stage reported characters for this page, or when the native
        text artifact it published is non-empty.
    """
    result = page.results.get(RESULT_PDF)
    if result is not None:
        metrics = getattr(result, "metrics", None)
        return bool(metrics is not None and metrics.characters > 0)
    return readable(page.artifacts.get(ARTIFACT_NATIVE_TEXT))


def ocr_text_present(page: PageContext) -> bool:
    """Return whether the page has extracted text from OCR.

    Args:
        page: The page to inspect.

    Returns:
        ``True`` when the OCR stage produced text, or when the published text artifact
        holds some.
    """
    result = page.results.get(RESULT_OCR)
    if result is not None:
        return bool(result.text)
    return readable(page.artifacts.get(ARTIFACT_OCR_TEXT))


def ocr_skip_reason(page: PageContext, policies: Mapping[str, object]) -> str | None:
    """Return why the OCR stage is not needed for this page, or ``None`` when it is.

    Args:
        page: The page being routed.
        policies: Document policies in force.

    Returns:
        ``skipped_by_policy`` when the document forbids OCR, ``native_text_present`` when
        the native text is already there, and ``None`` otherwise.
    """
    if not policy_flag(policies, "allow_ocr"):
        return "skipped_by_policy"
    if native_text_present(page):
        return "native_text_present"
    return None


def select_source(page: PageContext, policies: Mapping[str, object]) -> SourceSelection:
    """Choose which source the LLM stage should read for this page.

    Args:
        page: The page being routed.
        policies: Document policies in force.

    Returns:
        The source and its reason. When the page offers neither text nor an image, the
        source is ``None`` with the reason that says so — a default source would be a claim
        about content nobody read.
    """
    allow_vlm = policy_flag(policies, "allow_vlm")
    with_image = allow_vlm and readable(page.artifacts.get(ARTIFACT_VLM_READY))

    if native_text_present(page):
        if with_image:
            return SourceSelection("NATIVE_TEXT + IMAGE", "native_text_present")
        return SourceSelection("NATIVE_TEXT", "native_text_present")
    if ocr_text_present(page):
        if with_image:
            return SourceSelection("OCR_TEXT + IMAGE", "native_text_empty")
        return SourceSelection("OCR_TEXT", "native_text_empty")
    if readable(page.artifacts.get(ARTIFACT_PAGE_IMAGE)):
        # TODO: [MVP] the reason names the path that reached here rather than a refined
        # description of the page; the corpus is what will distinguish the sub-cases.
        return SourceSelection("IMAGE", "no_text_source_available")
    return SourceSelection(None, "no_source_available")


def select_extraction_strategy(
    selection: SourceSelection,
) -> StrategySelection:
    """Map the chosen source to the extraction strategy.

    The mapping is literal: every source has exactly one strategy, and there is no default,
    so an unmodelled source is a defect rather than a silently chosen strategy.

    Args:
        selection: The source chosen for the page.

    Returns:
        The strategy and the reason it follows from.
    """
    table: dict[SourceKind, ExtractionStrategy] = {
        "NATIVE_TEXT": "TEXT_ONLY",
        "OCR_TEXT": "OCR_ONLY",
        "IMAGE": "VLM_ONLY",
        "NATIVE_TEXT + IMAGE": "TEXT_PLUS_VLM",
        "OCR_TEXT + IMAGE": "OCR_PLUS_VLM",
    }
    if selection.source is None:
        return StrategySelection(None, selection.reason)
    return StrategySelection(table[selection.source], selection.reason)
