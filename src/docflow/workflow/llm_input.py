"""Composing the LLM input from the selected source and strategy (``ORC-13``).

The last routing step: what the inference is asked to do, what it is given, and what its
answer will be validated against. The composition is mechanical on purpose — every value
comes from the configuration or from the chosen source, so there is nowhere for a model, a
task or a schema to be invented when the configuration did not state one.

Two groups of strategies exist and the difference is exactly the payload:

* strategies that include text send the document — the native text or the OCR text;
* strategies that include vision send the ``vlm_ready`` image, and only then.

A strategy of ``None`` (the page offered nothing readable) is refused here rather than
mapped onto a default, because the caller is supposed to have resolved that earlier: a
``VLM_ONLY`` inference over a page with no image would be an inference over nothing.
"""

from __future__ import annotations

from docflow.llm import LLMInput
from docflow.workflow import configuration, keys
from docflow.workflow.contracts import (
    DocumentContext,
    DocumentRequest,
    ExtractionStrategy,
    PageContext,
)

#: Strategies whose payload includes the document text.
TEXT_STRATEGIES: frozenset[ExtractionStrategy] = frozenset(
    {"TEXT_ONLY", "OCR_ONLY", "TEXT_PLUS_VLM", "OCR_PLUS_VLM"}
)

#: Strategies whose payload includes an image.
VISION_STRATEGIES: frozenset[ExtractionStrategy] = frozenset(
    {"VLM_ONLY", "TEXT_PLUS_VLM", "OCR_PLUS_VLM"}
)


def build_llm_input(
    context: DocumentContext,
    page: PageContext,
    request: DocumentRequest,
) -> LLMInput:
    """Compose the inference request for one page.

    Args:
        context: The document context, for identity and the working root.
        page: The page whose source and strategy were selected.
        request: The request being served.

    Returns:
        The inference input, carrying the document text and/or the image the strategy asks
        for, the configured task, template and schema, and no default anywhere.

    Raises:
        ValueError: When no strategy was selected for the page. A default here would run an
            inference the routing never asked for.
    """
    strategy = page.extraction_strategy
    if strategy is None:
        raise ValueError(
            f"page {page.page_number} has no extraction strategy; "
            "the routing must select a source before an LLM input is composed"
        )
    settings = configuration.llm_settings(request)
    document = keys.document_text(page) if strategy in TEXT_STRATEGIES else None
    images: list[str] = []
    if strategy in VISION_STRATEGIES:
        source = keys.vlm_source(page)
        if source is not None:
            images.append(str(source))

    output_dir = (
        configuration.work_root(request) / "llm" / f"page_{page.page_number:03d}"
    )
    return LLMInput(
        task=settings.task,
        provider=settings.provider,
        model=settings.model,
        template=settings.template,
        document=document,
        images=images,
        extra_context={},
        schema=settings.schema,
        options=dict(settings.options),
        graph=None,
        metadata={
            "document_id": context.document_id,
            "workflow_run_id": context.workflow_run_id,
            "page_number": page.page_number,
            "output_dir": str(output_dir),
        },
    )
