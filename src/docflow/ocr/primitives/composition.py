# pylint: disable=duplicate-code
"""The internal flow of the OCR processor (``OCR-11``) — the stages, in one place.

One run of :func:`process_ocr_result`, expressed as the twelve stages §3.3's flow diagram fixes:

    validate request → validate input → normalize options → configure → convert → extract
    → normalize layout and order → build the three representations → metrics
    → persist → validate → publish metadata

That is one more stage than the diagram draws, and :data:`RUN_STAGES` records why: ``persist`` and
``validate`` are split around a verdict that cannot be computed until the artifacts it inspects are
on disk, and ``publish metadata`` is then a second write of the one file the verdict lives in.

Two decisions shape this module, and both come from measurements taken before it was written.

**Every stage runs through one `attempt` call, because eight of the ten can fail.** The image
processor records what happens otherwise: its first draft put the cleanup on two of eight failure
paths, and a corrupt input left the *previous* run's `normalized.png` looking like this run's
output. Here the failure is recorded, the flow stops, and :meth:`_Run.finish` is the single place
that abandons the namespace — so a failed run cannot leave a partially published artifact under a
final name.

**The reading order is applied here, and it is observable rather than cosmetic.** ``OCR-04``
extracted the document in the *engine's* order and said in as many words that the sort is not its
job. On the committed fixture the two differ: the engine lists the table last (position 19) while
``preserve_reading_order`` puts it at position 11, between the line items and the totals - which is
where it is on the page. So this module is what makes ``reading_order`` in the artifact mean
something, and what makes ``document.json``'s layout a *unit* page instead of the engine's pixels.
Until it runs, §9's resolved decision 4 ("normalized 0-1 coordinates") is unmet.

The text is **the engine's own**, and that is a measured decision rather than a passthrough by
default. An earlier draft rebuilt it from the ordered items on the theory that the engine emitted
it out of order; the measurement that suggested so was wrong. It compared the table's *line index*
in each rendering (18 against 9), and line indices are skewed by the engine's blank-line spacing —
the figure that decides the question is how many items *precede* the table, and there are nine in
both. Walked against the computed order, every item's offset in the engine's text increases. So the
engine's text is already in reading order, and re-deriving it would buy nothing while discarding
the engine's paragraph spacing. :func:`docflow.ocr.primitives.export.export_docling_text` is the
declared producer of ``text.txt`` and it reads ``document.text``; this module leaves that field
alone.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Final

from docflow.ocr.contracts import (
    ArtifactPaths,
    BlockResult,
    LayoutResult,
    OCRDocument,
    OCRError,
    OCRErrorType,
    OCRMetadata,
    OCRMetrics,
    OCRRequest,
    OCRResult,
    OCRStatus,
    OCRValidation,
    TableResult,
)
from docflow.ocr.primitives import (
    analyze,
    execution,
    export,
    extraction,
    files,
    layout,
    pipeline,
    validation,
)
from docflow.ocr.primitives import (
    metadata as metadata_primitive,
)
from docflow.ocr.primitives.engine import (
    DOCLING_VERSION_UNKNOWN,
    OCREngineError,
    engine_provenance,
)

RUN_STAGES: Final[tuple[str, ...]] = (
    "validate_request",
    "validate_input",
    "normalize_options",
    "configure_pipeline",
    "convert",
    "extract",
    "order",
    "build_outputs",
    "metrics",
    "persist",
    "validate_result",
    "publish_metadata",
)
"""Every stage's name, in the order the flow runs them.

Stated as data so the sequence reads as one list rather than as a sequence of early returns, and so
:attr:`_Run.timing` has a fixed key set that a reader can compare between two runs. ``total`` is
added by :meth:`_Run.finish` and is deliberately not here: it is not a stage.

**``validate_result`` sits after ``persist``, which is not how §3.3's diagram draws it, and the
diagram cannot be followed.** ``validate_ocr_result`` asks ``validate_output_artifacts`` whether
each promised path ``is_file()`` — and that check names all four artifacts, ``metadata.json``
included, because ``OCR-09`` wrote it to report *any* promised file that is absent. A verdict taken
before the write therefore reports ``INCOMPLETE`` for a run that is about to publish every
one of its artifacts: measured on the first draft of this module, where every happy-path run came
back ``INCOMPLETE`` with all four files sitting on disk. The acceptance criterion fixes which of
the two gives — ``status == "success"``, ``validation.status == "VALID"`` and the four files
present cannot all hold under the diagram's order.

So ``persist`` writes all four, with ``metadata.json`` carrying the provisional verdict, and
``publish_metadata`` rewrites that one file once the real verdict is readable from disk. The rewrite
is unconditional rather than "only when the verdict changed": one code path that always leaves the
file agreeing with the returned object beats two where the rarer one is the one nobody exercises.
"""

RECORDED_STAGES: Final[tuple[str, ...]] = ("total", *RUN_STAGES[:-1])
"""The stages whose duration appears in ``metadata.json``, and the run's total.

``publish_metadata`` is absent, and the reason is not an oversight: that stage *writes the file that
holds this record*, so its own duration is unknowable at the moment the record is built. The run's
total is therefore sealed just before the payload is assembled, which is why ``total`` is here and
the last stage is not. A test asserts the artifact's ``timing`` names exactly these keys, so a stage
that stopped being recorded — or a new one added without being sealed — shows up as a failure rather
than as a quietly partial account.
"""


@dataclass
# pylint: disable=too-many-instance-attributes
# The record is the run's state, and it holds one attribute per stage's output because the
# alternative is threading a dozen values through eleven method signatures — which is what the
# single-function version did. The attribute count tracks the pipeline's length, so a cheaper
# linter number would come from hiding the state rather than from simplifying it. The image
# processor's ``_Run`` records the same reasoning and carries the same disable.
class _Run:
    """What one attempt accumulates, and the steps it performs.

    A record rather than a dozen locals, and the steps as methods rather than one long function, for
    the reason the image processor's ``_Run`` records: the bookkeeping for ten stages pushed the
    single-function version past pylint's statement and branch limits, and the point of holding the
    state here is that the teardown then exists in exactly one place.

    Attributes:
        request: The request being served.
        processing_key: The reuse key, when the orchestrator supplied one.
        started: When the run began, for the ``total`` timing.
        timing: Wall-clock seconds by stage.
        engine: The engine's name, from the seam.
        engine_version: The engine's version, from the seam.
        options: The normalized options, once computed.
        configured: The configured engine pipeline.
        converted: The engine's own conversion result.
        document: The engine-independent document, once extracted.
        block_list: The blocks, in reading order.
        table_list: The tables, in reading order.
        failures: The typed failures that ended the run, if any.
        output_text: ``text.txt``'s content.
        output_markdown: ``document.md``'s content.
        output_payload: ``document.json``'s payload.
        table_files: The per-table ``(name, content)`` pairs.
        metrics: The content metrics.
        verdict: The structural verdict.
        artifacts: The published paths.
        provenance: The provenance record.
        failure: The failure that ended the run, or ``None`` while it is still going.
    """

    request: OCRRequest
    processing_key: str | None
    started: float
    timing: dict[str, float] = field(default_factory=dict)
    engine: str = ""
    engine_version: str = ""
    options: Any = None
    configured: Any = None
    converted: Any = None
    document: OCRDocument | None = None
    block_list: list[BlockResult] = field(default_factory=list)
    table_list: list[TableResult] = field(default_factory=list)
    failures: list[OCRError] = field(default_factory=list)
    output_text: str = ""
    output_markdown: str = ""
    output_payload: dict[str, Any] = field(default_factory=dict)
    table_files: list[tuple[str, str]] = field(default_factory=list)
    metrics: OCRMetrics | None = None
    verdict: OCRValidation | None = None
    artifacts: ArtifactPaths | None = None
    provenance: OCRMetadata | None = None
    failure: Exception | None = None

    def attempt(self, stage: str, call: Any) -> Any:
        """Run one stage, recording its duration and containing its failure.

        The seam's errors are caught beside the filesystem's and the primitives' own.
        ``OCREngineError`` and its subclasses are raised from deep inside a primitive — a missing
        Docling install raises ``OCREngineNotAvailableError`` from the seam, and a malformed grid
        raises ``OCREngineExecutionError`` from the extractor. Letting one escape would put an
        engine error across the contract, which §3.5 forbids: the caller asked for an ``OCRResult``
        and would get an exception it has no vocabulary for.

        ``OCRError`` is **not** in this tuple and cannot be: it is the record the contract carries,
        a plain dataclass with no ``Exception`` in its MRO, so a stage reports a contract failure by
        *returning* one rather than by raising. An earlier draft caught it here, which would have
        been dead code dressed as error handling. ``OSError`` covers the publication and input
        stages, and ``ValueError`` the primitives' own refusals — an unknown option, a non-positive
        page size.

        Args:
            stage: The stage's name, used as its key in ``timing``.
            call: The stage's work.

        Returns:
            Whatever the stage returned. The caller checks :attr:`failure` rather than this value,
            because several stages legitimately return ``None``.
        """
        self.failure = None
        started = time.perf_counter()
        try:
            value = call()
        except (OCREngineError, OSError, ValueError) as failure:
            self.timing[stage] = time.perf_counter() - started
            self.failure = failure
            return None
        self.timing[stage] = time.perf_counter() - started
        return value

    def validate_request(self) -> bool:
        """Check the request before any work starts.

        Returns:
            Whether the request is usable.
        """
        errors = self.attempt(
            "validate_request", lambda: validation.validate_ocr_request(self.request)
        )
        if self.failure is not None:
            return False
        self.failures = list(errors or [])
        return not self.failures

    def validate_input(self) -> bool:
        """Check that the image can be read.

        Separate from the request check because the two answer different questions: the request may
        name an image that no longer exists, and this is the stage that reads the filesystem.

        Returns:
            Whether the image is readable.
        """
        errors = self.attempt(
            "validate_input",
            lambda: validation.validate_ocr_input(self.request.image_path),
        )
        if self.failure is not None:
            return False
        self.failures = list(errors or [])
        return not self.failures

    def normalize_options(self) -> bool:
        """Canonicalize the raw options into the form the pipeline and the key use.

        Returns:
            Whether the options were normalized.
        """
        self.options = self.attempt(
            "normalize_options",
            lambda: pipeline.normalize_docling_options(self.request.options),
        )
        return self.failure is None

    def configure_pipeline(self) -> bool:
        """Build the configured converter, resolving the engine's version on the way.

        The version is read here rather than at publish time so that a missing engine fails the
        run
        *before* a conversion is attempted, which is the only ordering that gives the caller a
        usable error instead of a stack trace from inside Docling.

        Returns:
            Whether the pipeline was built.
        """
        configured = self.attempt(
            "configure_pipeline",
            lambda: pipeline.configure_image_pipeline(self.options),
        )
        if self.failure is not None:
            return False
        self.configured = configured
        return True

    def convert(self) -> bool:
        """Run the engine over the prepared image.

        Returns:
            Whether the conversion succeeded.
        """
        converted = self.attempt("convert", self._convert)
        return self.failure is None and converted is not None

    def _convert(self) -> Any:
        """Read the engine's provenance, then run the engine over the prepared image.

        The provenance is read here rather than at publish time so a deployment without the engine
        fails *before* a conversion is attempted: the seam raises ``OCREngineNotAvailableError``
        from a missing import, and a caller is better served by that than by the engine's own stack
        trace from thirty frames down.

        Returns:
            The engine's conversion result.
        """
        provenance = engine_provenance()
        self.engine = provenance["engine"]
        self.engine_version = provenance["engine_version"]
        self.converted = execution.convert_image_with_docling(
            self.request.image_path, self.configured
        )
        return self.converted

    def extract(self) -> bool:
        """Turn the engine's result into the engine-independent document.

        Returns:
            Whether the document was assembled.
        """
        self.document = self.attempt(
            "extract", lambda: extraction.build_ocr_document(self.converted)
        )
        return self.failure is None and self.document is not None

    def order(self) -> bool:
        """Normalize the geometry and put the blocks and tables into reading order.

        The one step in the flow that has no engine involvement at all, and the one that makes
        ``reading_order`` mean something: measured on the committed fixture, the engine lists the
        table last while this puts it at position 11 — where it is on the page. The layout is
        normalized in the same step because the order is *defined* on normalized geometry.

        Returns:
            Whether the document was reordered.
        """
        ordered = self.attempt("order", self._order_and_normalize)
        return self.failure is None and ordered is not None

    def _order_and_normalize(self) -> bool:
        """Apply the reading order and the unit-page layout to the document.

        Returns:
            ``True`` once the document has been replaced by its ordered form.
        """
        document = self.document
        assert document is not None, "order() ran before extract() succeeded"
        blocks, tables, reading_order = layout.preserve_reading_order(
            document.blocks,
            document.tables,
            document.layout.page_width,
            document.layout.page_height,
        )
        self.block_list = blocks
        self.table_list = tables
        self.document = OCRDocument(
            text=document.text,
            paragraphs=[
                block.text for block in blocks if block.type in ("text", "paragraph")
            ],
            titles=[block.text for block in blocks if block.type == "title"],
            blocks=blocks,
            tables=tables,
            layout=layout.normalize_layout(document.layout),
            reading_order=reading_order,
            metadata=document.metadata,
        )
        return True

    def build_outputs(self) -> bool:
        """Build the three canonical representations.

        Args:
            None.

        Returns:
            Whether every representation was built.
        """
        built = self.attempt("build_outputs", self._build_outputs)
        return self.failure is None and built is not None

    def _build_outputs(self) -> bool:
        """Render the text, the Markdown, the JSON payload and the per-table files.

        Returns:
            ``True`` once all four are in hand.
        """
        document = self.document
        assert document is not None, "build_outputs() ran before order() succeeded"
        self.output_text = export.export_docling_text(document)
        self.output_markdown = export.export_docling_markdown(document)
        self.output_payload = export.export_docling_json(document)
        self.table_files = export.export_docling_tables(document)
        return True

    def measure(self) -> bool:
        """Measure the extraction.

        Named ``measure`` rather than ``metrics`` because :attr:`metrics` is a field of this record:
        a method of the same name would be shadowed by the field the moment the dataclass was
        constructed, and the stage tuple would then hold an ``OCRMetrics`` where it expects a
        callable. The first draft did exactly that, and the run failed at the ninth stage with
        ``TypeError: _Run.metrics() missing 1 required positional argument: 'self'``.

        Returns:
            Whether the metrics were computed. They are descriptive evidence, so nothing here can
            fail for a content reason — only for a defect in the analyzer.
        """
        self.metrics = self.attempt(
            "metrics", lambda: analyze.analyze_ocr_result(self.document)
        )
        return self.failure is None and self.metrics is not None

    def persist(self) -> bool:
        """Write every artifact atomically, the provenance record included.

        ``metadata.json`` is written here with the provisional verdict for the reason ``RUN_STAGES``
        records: the verdict cannot be computed until every promised file is readable, and the
        record that carries it is one of the files it promises. :meth:`publish_metadata` rewrites it
        once the verdict is real.

        Returns:
            Whether every artifact was written.
        """
        written = self.attempt("persist", self._persist)
        return self.failure is None and written is not None

    def _persist(self) -> bool:
        """Write the five artifacts, then the per-table files.

        Returns:
            ``True`` once everything is on disk.
        """
        artifacts = self.artifacts_paths()
        files.create_ocr_directory(self.request.output_dir)
        files.write_text_atomic(artifacts.text, self.output_text)
        files.write_text_atomic(artifacts.markdown, self.output_markdown)
        files.write_text_atomic(
            artifacts.structured_document,
            export.serialize_document_json(self.output_payload),
        )
        files.write_json_atomic(
            artifacts.metadata,
            metadata_primitive.build_metadata_payload(
                self._provenance(self._pending_verdict()),
                processing_key=self.processing_key,
                tables_published=len(self.table_files),
            ),
        )
        if self.table_files:
            files.ensure_directory(artifacts.tables_dir)
            for name, content in self.table_files:
                files.write_text_atomic(artifacts.tables_dir / name, content)
        self.artifacts = artifacts
        return True

    def validate_result(self) -> bool:
        """Decide the structural verdict, now that every artifact it inspects is on disk.

        A verdict that is not ``VALID`` is **not** a run failure: ``EMPTY`` and ``LOW_CONTENT``
        are
        descriptions of what the page yielded, and the plan is explicit that the processor reports
        them rather than acting on them — ``LOW_CONTENT -> use the VLM`` belongs to the
        orchestrator. The one verdict that does end the run is ``INCOMPLETE``, because an artifact
        the result
        promises and cannot deliver is a fact about *this run*, not a description of the page.

        Returns:
            Whether the run may settle its provenance record.
        """
        self.verdict = self.attempt("validate_result", self._validate_result)
        if self.failure is not None or self.verdict is None:
            return False
        return self.verdict.status != "INCOMPLETE"

    def _validate_result(self) -> OCRValidation:
        """Assemble the result as it stands and validate it against what it claims.

        The ``metadata.json`` on disk still holds the provisional verdict at this moment, and the
        verdict this returns is what :meth:`publish_metadata` writes over it. The result handed to
        the validator carries a *failed* status only when the run is in fact the failed path, which
        ``validate_ocr_result`` reads first — the happy path never reaches this method with one.

        Returns:
            The verdict.
        """
        return validation.validate_ocr_result(self.result(self._pending_verdict()))

    def _pending_verdict(self) -> OCRValidation:
        """Return a placeholder verdict for the moment before the real one is computed.

        ``OCRResult.validation`` has no optional form, so the record handed to
        :func:`docflow.ocr.primitives.validation.validate_ocr_result` must carry *something* — but
        that function reads ``result.status`` and the published paths, never this field, so the
        value cannot influence the verdict. ``ERROR`` rather than ``VALID``: a placeholder that
        claimed validity would be the silent stand-in the plan forbids if a future edit ever did
        read it.

        Returns:
            An ``ERROR``-typed empty verdict.
        """
        return OCRValidation(status="ERROR", errors=[], missing_artifacts=[])

    def publish_metadata(self) -> bool:
        """Rewrite ``metadata.json`` with the settled verdict.

        :meth:`persist` already wrote the file, so this stage is a deliberate second write rather
        than the only one. It exists because the verdict cannot be known before the file does: the
        check reads the disk, and the record that carries the outcome is on the disk it reads. Two
        writes of one small file is the price, and the alternative — a verdict taken from paths that
        are not yet written — reports ``INCOMPLETE`` for a run that published everything.

        Returns:
            Whether the file was rewritten.
        """
        published = self.attempt("publish_metadata", self._publish_metadata)
        return self.failure is None and published is not None

    def _publish_metadata(self) -> bool:
        """Build the provenance record from the settled verdict and write it.

        The total is sealed here, immediately before the payload is assembled, because this is the
        last moment at which the record can include one: the write that follows is this stage's own
        duration, and it cannot appear in the file it produces.

        Returns:
            ``True`` once the file is on disk.
        """
        assert self.verdict is not None, (
            "metadata published before the verdict was taken"
        )
        self.seal_timing()
        self.provenance = self._provenance(self.verdict)
        files.write_json_atomic(
            self.artifacts_paths().metadata,
            metadata_primitive.build_metadata_payload(
                self.provenance,
                processing_key=self.processing_key,
                tables_published=len(self.table_files),
            ),
        )
        return True

    def artifacts_paths(self) -> ArtifactPaths:
        """Return the canonical paths for this request's namespace.

        Returns:
            Every path this run publishes, whether or not it has reached them.
        """
        return files.build_ocr_output_paths(self.request.output_dir)

    def result(
        self,
        verdict: OCRValidation,
        *,
        status: OCRStatus = "success",
        error: OCRError | None = None,
    ) -> OCRResult:
        """Build the contract's result from whatever the run has reached.

        One builder for both outcomes. A second one for the failed case would be a near-copy whose
        divergence would show up as a *missing* field rather than as a wrong one, and the failed
        result is read precisely when a caller has least to go on.

        Args:
            verdict: The verdict to carry.
            status: ``"success"`` or ``"failed"``.
            error: The typed failure, on a failed run.

        Returns:
            The result. Fields the run never reached are filled with values that say so rather than
            with plausible-looking defaults: an absent document contributes an empty layout at the
            origin, and an absent measurement contributes zeroes with ``empty`` set.
        """
        document = self.document
        return OCRResult(
            text=self.output_text,
            markdown=self.output_markdown,
            structured_document=self.output_payload,
            tables=list(self.table_list),
            blocks=list(self.block_list),
            layout=(
                document.layout
                if document is not None
                else LayoutResult(page_width=0.0, page_height=0.0, region_bboxes=[])
            ),
            reading_order=list(document.reading_order) if document is not None else [],
            metrics=self.metrics or _unmeasured(),
            artifacts=self.artifacts or self.artifacts_paths(),
            validation=verdict,
            metadata=self._provenance(verdict),
            status=status,
            error=error,
        )

    def _provenance(self, verdict: OCRValidation) -> OCRMetadata:
        """Assemble the provenance record.

        Args:
            verdict: The verdict as it stands.

        Returns:
            The record.
        """
        return metadata_primitive.build_ocr_metadata(
            engine=self.engine or metadata_primitive.PROCESSOR_NAME,
            engine_version=self.engine_version or DOCLING_VERSION_UNKNOWN,
            processor_version=metadata_primitive.get_processor_version(),
            options=self.options,
            image_path=self.request.image_path,
            metrics=self.metrics or _unmeasured(),
            validation=verdict,
            timing=dict(self.timing),
            transformations=[],
            context=self.request.context,
        )

    def settle(self) -> OCRResult:
        """Return the result of a run that published.

        Returns:
            The result, whose ``artifacts`` name files that exist.

        Raises:
            AssertionError: Called on a run that did not publish. The flow never does; the assertion
                exists so a future edit cannot silently return a result pointing at nothing.
        """
        assert self.verdict is not None, (
            "settle() ran before validate_result() succeeded"
        )
        assert self.provenance is not None, (
            "settle() ran before publish_metadata() succeeded"
        )
        return self.result(self.verdict)

    def seal_timing(self) -> None:
        """Record the run's total duration.

        Called from both outcomes, so a failed run reports a total for the same reason a
        successful
        one does: the figure is the only measure of how long the attempt took, and it is exactly
        what a caller deciding whether to retry needs.
        """
        self.timing["total"] = time.perf_counter() - self.started

    def finish(self) -> OCRResult:
        """Abandon the namespace and return the failed result.

        The namespace is abandoned *here* rather than in a ``finally``, because the decision to
        clean
        up belongs to the code that knows the run failed — this module cannot tell a half-written
        artifact from one that is simply the only one requested. ``abandon`` removes the staged
        files
        and the final-named ones together, which is what makes "a failed run leaves nothing a
        reader
        could mistake for a result" true rather than aspirational.

        Returns:
            The failed result, with ``status == "failed"`` and ``error`` populated.
        """
        self.seal_timing()
        files.abandon(self.request.output_dir)
        return _failed(self)


def process_ocr_result(
    request: OCRRequest,
    *,
    processing_key: str | None,
) -> OCRResult:
    """Run the flow over one request and return the contract's result, whatever happened.

    Args:
        request: The prepared image to read, its options and its correlation context.
        processing_key: The reuse key, when the orchestrator has computed one. Required, not
            defaulted: the signature suite refuses a defaulted argument, and ``None`` here means
            "the orchestrator has not computed one", which a caller must say deliberately.

    Returns:
        The result. On the happy path ``status`` is ``"success"``; otherwise it is ``"failed"`` and
        ``error`` carries the typed failure. A run that failed published nothing.

    Note:
        The stages are a tuple of bound methods so the order is stated once, as data, rather than
        as
        a sequence of early returns. Each stage reports whether it succeeded; the first that does
        not ends the run, and :meth:`_Run.finish` is the one place the teardown happens.
    """
    run = _Run(
        request=request,
        processing_key=processing_key,
        started=time.perf_counter(),
    )
    stages = (
        run.validate_request,
        run.validate_input,
        run.normalize_options,
        run.configure_pipeline,
        run.convert,
        run.extract,
        run.order,
        run.build_outputs,
        run.measure,
        run.persist,
        run.validate_result,
        run.publish_metadata,
    )
    for stage in stages:
        if not stage():
            return run.finish()
    return run.settle()


def _failed(run: _Run) -> OCRResult:
    """Build the failed result for whatever ended a run.

    Args:
        run: The run that failed.

    Returns:
        The failed result. Every field the contract requires is present, filled with what the run
        had reached: the validation record carries the failures it collected, and the paths are the
        ones the run *would* have published so a caller can see where nothing was written.
    """
    failures = list(run.failures)
    if not failures:
        failures = [_as_error(run.failure)]
    verdict = OCRValidation(status="ERROR", errors=failures, missing_artifacts=[])
    return run.result(verdict, status="failed", error=failures[0])


def _unmeasured() -> OCRMetrics:
    """Describe a measurement that was never taken.

    Zeroes *and* ``empty``, together, because either alone would mislead: the counts say nothing was
    measured, and the flag says the same thing in the field a consumer reads first. A failed run's
    result needs this because ``OCRResult.metrics`` has no optional form.

    Returns:
        The zero measurement.
    """
    return OCRMetrics(
        characters=0,
        words=0,
        blocks=0,
        tables=0,
        paragraphs=0,
        text_density=0.0,
        empty=True,
        structure_detected=False,
    )


def _as_error(failure: Exception | None) -> OCRError:
    """Translate whatever ended a run into the contract's error record.

    Args:
        failure: The failure, or ``None`` when a stage reported a failure without raising.

    Returns:
        The typed error. Every failure reaching here is one :meth:`_Run.attempt` caught, so the
        engine's vocabulary maps to ``ENGINE_ERROR`` and everything else to ``INTERNAL_ERROR`` —
        a filesystem failure is the run's own problem, not the page's, and §3.5's set has no better
        name for it. ``recoverable`` is ``False`` throughout: this processor cannot promise that a
        retry of the same page behaves differently.
    """
    if failure is None:
        return OCRError(
            type="INTERNAL_ERROR",
            message="the run failed without a recorded cause",
            recoverable=False,
            metadata={"cause": "unknown"},
        )
    error_type: OCRErrorType = (
        "ENGINE_ERROR" if isinstance(failure, OCREngineError) else "INTERNAL_ERROR"
    )
    return OCRError(
        type=error_type,
        message=str(failure) or type(failure).__name__,
        recoverable=False,
        metadata={"cause": type(failure).__name__},
    )


__all__ = [
    "RECORDED_STAGES",
    "RUN_STAGES",
    "process_ocr_result",
]
