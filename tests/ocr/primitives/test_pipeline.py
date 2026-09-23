"""Tests for the pipeline and configuration primitives (``OCR-03``).

Two halves, tested separately on purpose. The **predicates** decide and the **enablers** apply,
so the decisions are checked without an engine and the mechanism is checked without a request —
which is the whole reason the module splits them. A single function doing both would need Docling
installed to test a boolean.

The acceptance criteria are both here: normalization is order-stable and identical across runs for
equal input, and a disabled capability is *really* disabled. That second one carries the weight.
Docling defaults ``do_ocr`` and ``do_table_structure`` to ``True``, so a processor that only ever
switched capabilities on would pass a naive test and silently ignore ``tables=False``.
"""

from __future__ import annotations

import json

import pytest

from docflow.ocr.contracts import NormalizedOCROptions, OCROptions
from docflow.ocr.primitives import pipeline
from docflow.ocr.primitives.engine import DOCLING_MODULE_NAME
from tests.ocr.primitives import probes


def raw_options(
    *,
    ocr: bool = True,
    layout: bool = True,
    tables: bool = True,
    reading_order: bool = True,
) -> OCROptions:
    """Return a raw request's options.

    Args:
        ocr: Whether OCR is requested.
        layout: Whether layout is requested.
        tables: Whether tables are requested.
        reading_order: Whether reading order is requested.

    Returns:
        The options.
    """
    return OCROptions(
        ocr=ocr,
        layout=layout,
        tables=tables,
        reading_order=reading_order,
        language="EN",
        engine_options={"beta": 2, "alpha": 1},
    )


def normalized(**overrides: bool) -> NormalizedOCROptions:
    """Return the normalized form of a default request's options.

    Args:
        **overrides: Flags to replace.

    Returns:
        The normalized options.
    """
    return pipeline.normalize_docling_options(raw_options(**overrides))


# ======================================================================================
# The seam stays lazy
# ======================================================================================


def test_importing_the_pipeline_module_loads_no_engine() -> None:
    """``GEN-01``: a clean interpreter imports every sub-package without pulling an engine in.

    The engine is imported inside the functions that build an options object, so the module's own
    import stays free of Docling — which matters because this module is imported by the
    processor's package initialiser.
    """
    assert probes.module_absent_from_a_clean_import(
        "docflow.ocr.primitives.pipeline", DOCLING_MODULE_NAME
    )


# ======================================================================================
# Acceptance criterion 1 — normalization is stable
# ======================================================================================


def test_normalization_is_identical_across_runs_for_equal_input() -> None:
    """The acceptance criterion, stated directly: equal input, equal output, twice."""
    first = pipeline.normalize_docling_options(raw_options())
    second = pipeline.normalize_docling_options(raw_options())

    assert first == second
    assert first.engine_options == second.engine_options


def test_normalization_sorts_the_engine_option_keys() -> None:
    """A dict compares equal regardless of order, but its *serialization* does not.

    The serialization is what reaches the processing key, so two requests that mean the same thing
    would hash differently and the reuse rule would fail to trigger.

    **Both inputs are written out of order**, and that is the correction of a defective first
    draft. The earlier version gave the "forward" case an already-alphabetical mapping, so removing
    the sort changed nothing it could observe — the assertion held for the wrong reason and a
    mutation that deleted the sort survived it. A test whose input is already in the expected order
    cannot test the ordering.
    """
    forward = pipeline.normalize_docling_options(
        OCROptions(
            ocr=True,
            layout=True,
            tables=True,
            reading_order=True,
            language=None,
            engine_options={"zeta": 3, "alpha": 1, "mu": 2},
        )
    )
    backward = pipeline.normalize_docling_options(
        OCROptions(
            ocr=True,
            layout=True,
            tables=True,
            reading_order=True,
            language=None,
            engine_options={"mu": 2, "zeta": 3, "alpha": 1},
        )
    )

    assert list(forward.engine_options) == ["alpha", "mu", "zeta"]
    assert json.dumps(forward.engine_options) == json.dumps(backward.engine_options)


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("EN", "en"),
        ("  en  ", "en"),
        ("En", "en"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalization_canonicalizes_the_language(
    language: str | None, expected: str | None
) -> None:
    """Three spellings of one language are one request, and blank means "not specified".

    An empty string becoming ``None`` is the part worth pinning: ``""`` is not "the empty
    language", it is a caller who did not fill the field in, and the two must not produce different
    processing keys.
    """
    options = OCROptions(
        ocr=True,
        layout=True,
        tables=True,
        reading_order=True,
        language=language,
        engine_options={},
    )

    assert pipeline.normalize_docling_options(options).language == expected


@pytest.mark.parametrize("name", ["ocr", "layout", "tables", "reading_order"])
def test_normalization_refuses_a_non_boolean_flag(name: str) -> None:
    """Refused, not coerced. ``bool("false")`` is ``True``.

    A request that arrives as JSON with a string where a flag belongs would turn a capability *on*
    while the caller asked for it off, and nothing downstream could tell — the same failure class
    as the silent stand-in, arriving through the type system instead of through a default.
    """
    options = OCROptions(
        ocr=True,
        layout=True,
        tables=True,
        reading_order=True,
        language=None,
        engine_options={},
    )
    object.__setattr__(options, name, "false")

    with pytest.raises(ValueError, match=name):
        pipeline.normalize_docling_options(options)


def test_normalization_does_not_mutate_its_input() -> None:
    """The engine-options copy must not alias the original, and the original keeps its order."""
    options = raw_options()

    normalized_options = pipeline.normalize_docling_options(options)

    assert list(options.engine_options) == ["beta", "alpha"], "the input was reordered"
    assert normalized_options.engine_options is not options.engine_options


# ======================================================================================
# The predicates — the decision half
# ======================================================================================


def test_every_predicate_is_true_only_when_its_capability_was_requested() -> None:
    """All four, over a request with every capability on."""
    options = normalized()

    assert pipeline.should_enable_ocr(options) is True
    assert pipeline.should_enable_layout(options) is True
    assert pipeline.should_enable_tables(options) is True
    assert pipeline.should_enable_reading_order(options) is True


def test_every_predicate_is_false_when_its_capability_was_not_requested() -> None:
    """Over a request with every capability off — the direction a naive implementation misses."""
    options = normalized(ocr=False, layout=False, tables=False, reading_order=False)

    assert pipeline.should_enable_ocr(options) is False
    assert pipeline.should_enable_layout(options) is False
    assert pipeline.should_enable_tables(options) is False
    assert pipeline.should_enable_reading_order(options) is False


def test_the_predicates_do_not_leak_into_each_other() -> None:
    """Each one reads its own field.

    A mutation that made every predicate return the first field's value would pass the two tests
    above, because those set all four flags together. This one turns exactly one on at a time.
    """
    for enabled in ("ocr", "layout", "tables", "reading_order"):
        flags = dict.fromkeys(("ocr", "layout", "tables", "reading_order"), False)
        flags[enabled] = True
        options = normalized(**flags)

        answers = {
            "ocr": pipeline.should_enable_ocr(options),
            "layout": pipeline.should_enable_layout(options),
            "tables": pipeline.should_enable_tables(options),
            "reading_order": pipeline.should_enable_reading_order(options),
        }
        assert answers[enabled] is True, enabled
        assert sum(answers.values()) == 1, f"{enabled} leaked: {answers}"


@pytest.mark.parametrize("truthy", [1, "yes", [0], object()])
def test_a_predicate_treats_a_non_boolean_as_disabled(truthy: object) -> None:
    """The safe direction: a value that is not ``True`` disables the capability.

    ``is True`` rather than truthiness, because the subplan forbids a *missing* option silently
    enabling a capability — and a truthiness test would enable OCR for any non-empty value that
    reached it. Normalization refuses such a value outright, so this is defence in depth for a
    record assembled without it.
    """
    options = NormalizedOCROptions(
        ocr=truthy,  # type: ignore[arg-type]
        layout=False,
        tables=False,
        reading_order=False,
        language=None,
        engine_options={},
    )

    assert pipeline.should_enable_ocr(options) is False


# ======================================================================================
# The enablers — the mechanism half
# ======================================================================================


def test_enable_ocr_sets_the_engine_flag_in_both_directions() -> None:
    """On and off, on a real Docling options object."""
    docling_options = pipeline.load_docling_pipeline()

    pipeline.enable_ocr(docling_options, False)
    assert docling_options.do_ocr is False

    pipeline.enable_ocr(docling_options, True)
    assert docling_options.do_ocr is True


def test_docling_defaults_the_flags_this_module_has_to_override() -> None:
    """The measurement that makes "set it in both directions" a requirement rather than a style.

    Docling ships ``do_ocr`` and ``do_table_structure`` as ``True``. If that ever changed, the
    both-directions tests above would still pass, but this one would fail and say why they matter.
    """
    defaults = pipeline.load_docling_pipeline()

    assert defaults.do_ocr is True
    assert defaults.do_table_structure is True


def test_enable_table_detection_sets_the_flag_in_both_directions() -> None:
    """Off is the case that matters: Docling defaults this flag to ``True``."""
    docling_options = pipeline.load_docling_pipeline()

    pipeline.enable_table_detection(docling_options, False)
    assert docling_options.do_table_structure is False

    pipeline.enable_table_detection(docling_options, True)
    assert docling_options.do_table_structure is True


def test_layout_is_not_a_boolean_flag_in_this_engine() -> None:
    """There is no ``do_layout``, and the primitive does not pretend otherwise.

    Measured rather than assumed. A primitive that looked for a boolean would have found nothing,
    set a stray attribute, and changed no behaviour while appearing to work — so the absence is
    pinned here and the field name is asserted instead.
    """
    docling_options = pipeline.load_docling_pipeline()

    assert not hasattr(docling_options, "do_layout")
    assert pipeline.DOCLING_LAYOUT_FIELD in type(docling_options).model_fields


def test_enable_layout_analysis_turns_layout_off_and_on() -> None:
    """Off is ``None``; on gives the field a value again."""
    docling_options = pipeline.load_docling_pipeline()

    pipeline.enable_layout_analysis(docling_options, False)
    assert docling_options.layout_options is None

    pipeline.enable_layout_analysis(docling_options, True)
    assert docling_options.layout_options is not None


def test_enable_layout_analysis_leaves_existing_settings_alone() -> None:
    """Turning layout *on* when it is already configured must not replace the configuration.

    Those options may carry settings a caller placed there deliberately, and rebuilding them would
    discard a decision this module was not asked to revisit.
    """
    docling_options = pipeline.load_docling_pipeline()
    pipeline.enable_layout_analysis(docling_options, True)
    existing = docling_options.layout_options
    existing.create_orphan_clusters = False

    pipeline.enable_layout_analysis(docling_options, True)

    assert docling_options.layout_options is existing
    assert docling_options.layout_options.create_orphan_clusters is False


def test_the_enablers_return_the_object_they_modified() -> None:
    """So a caller can chain them, which is what :func:`configure_image_pipeline` does."""
    docling_options = pipeline.load_docling_pipeline()

    assert pipeline.enable_ocr(docling_options, True) is docling_options
    assert pipeline.enable_table_detection(docling_options, True) is docling_options
    assert pipeline.enable_layout_analysis(docling_options, True) is docling_options


# ======================================================================================
# Acceptance criterion 2 — a disabled capability is really disabled
# ======================================================================================


def test_a_configured_pipeline_matches_the_request_for_every_combination() -> None:
    """The acceptance criterion, swept over all eight combinations of the three flags.

    Swept rather than sampled because the interesting failure is asymmetric: Docling defaults two
    of the three flags to ``True``, so a processor that only ever enabled capabilities would look
    correct on every request that asks for them and be silently wrong on every one that does not.
    """
    checked = 0
    for ocr in (True, False):
        for layout in (True, False):
            for tables in (True, False):
                configured = pipeline.configure_image_pipeline(
                    normalized(ocr=ocr, layout=layout, tables=tables)
                )
                assert configured.do_ocr is ocr, (ocr, layout, tables)
                assert configured.do_table_structure is tables, (ocr, layout, tables)
                assert (configured.layout_options is not None) is layout, (
                    ocr,
                    layout,
                    tables,
                )
                checked += 1

    assert checked == 8


def test_tables_disabled_is_really_disabled_despite_the_engine_default() -> None:
    """The acceptance criterion's own example, stated on its own.

    ``tables=False`` against an engine that defaults table structure to ``True``: the only way this
    passes is if the flag is set explicitly, which is what the criterion is checking.
    """
    configured = pipeline.configure_image_pipeline(normalized(tables=False))

    assert configured.do_table_structure is False


def test_reading_order_is_not_a_docling_flag_and_configuring_does_not_invent_one() -> (
    None
):
    """``reading_order`` is a processor decision, not an engine setting.

    It is honoured in ``OCR-05``, where the blocks are ordered. Setting a Docling attribute for it
    here would look like configuration while doing nothing, and would put a processor concept into
    the engine's namespace.
    """
    configured = pipeline.configure_image_pipeline(normalized(reading_order=True))

    assert not hasattr(configured, "do_reading_order")
    assert not hasattr(configured, "reading_order")


def test_configuring_twice_from_the_same_options_gives_equal_pipelines() -> None:
    """Determinism at the configuration step, not only at the normalization step."""
    options = normalized(tables=False)

    first = pipeline.configure_image_pipeline(options)
    second = pipeline.configure_image_pipeline(options)

    assert first.do_ocr == second.do_ocr
    assert first.do_table_structure == second.do_table_structure
    assert (first.layout_options is None) == (second.layout_options is None)
