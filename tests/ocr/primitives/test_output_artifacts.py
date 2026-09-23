"""Acceptance tests for the three output builders (``OCR-06``).

The two criteria are the spine of this module:

* ``text.txt`` is non-empty, ``document.md`` is valid Markdown and ``document.json`` deserializes
  to the documented schema;
* **none of the three contains a run-time timestamp.**

The second is the one that needs care. The fixture is a real invoice, and a real invoice carries
dates: ``01/11/2016``, ``27/02/26`` and a ``13:09`` are all in the extracted text. So a test that
searched these artifacts for date-*shaped* strings would fail on correct output, and — worse — a
test that searched for the *current* date would pass on a file that had frozen one into it. The
invariant is about run-time data entering a builder, so the test pins the clock to a value that
appears nowhere in the page and asserts the artifacts do not move when it does. That is the only
formulation that can fail for the right reason.

The builders return *values*. Writing them is ``OCR-10``'s atomic publication and is deliberately
absent here, so these tests never touch a filesystem.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import re
import time
from typing import Any

import pytest

from docflow.ocr.contracts import BlockResult, TableResult
from docflow.ocr.primitives import export
from tests.ocr.primitives.engine_corpus import (
    DOCUMENT_JSON_SECTIONS,
    extracted_document,
)

#: A date far from anything the fixture's page can contain, used to detect run-time data by
#: pinning the clock rather than by looking for a shape.
PINNED_NOW = datetime.datetime(2099, 12, 31, 23, 59, 58, tzinfo=datetime.UTC)


class _FrozenDateTime(datetime.datetime):
    """A ``datetime`` whose ``now``/``utcnow``/``today`` are pinned.

    Subclassed rather than patched attribute by attribute so the production code is free to reach
    for any of the three names: a builder that stamped a time would call one of them, and all three
    answer with the same value here.
    """

    @classmethod
    def now(cls, tz: datetime.tzinfo | None = None) -> datetime.datetime:
        """Return the pinned instant."""
        return PINNED_NOW if tz is not None else PINNED_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls) -> datetime.datetime:
        """Return the pinned instant, naive."""
        return PINNED_NOW.replace(tzinfo=None)

    @classmethod
    def today(cls) -> datetime.datetime:
        """Return the pinned instant."""
        return PINNED_NOW.replace(tzinfo=None)


def _pinned_epoch() -> float:
    """Return the pinned instant as a Unix timestamp.

    A named function rather than a lambda so the pinned ``time.time`` is inspectable and so pylint
    does not flag an unnecessary lambda.
    """
    return PINNED_NOW.timestamp()


def _pinned_monotonic() -> float:
    """Return a fixed monotonic reading.

    Monotonic time is meaningless across processes, but a builder that stamped a *duration* would
    read it, and a fixed value is what makes that observable.
    """
    return 0.0


@pytest.fixture(name="frozen_clock")
def frozen_clock_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin every clock a builder could reach for.

    ``time.time`` and ``time.monotonic`` are pinned too: a builder that wanted a timestamp without
    importing ``datetime`` would reach for one of them, and a test that only patched ``datetime``
    would miss it.
    """
    monkeypatch.setattr(datetime, "datetime", _FrozenDateTime)
    monkeypatch.setattr(time, "time", _pinned_epoch)
    monkeypatch.setattr(time, "monotonic", _pinned_monotonic)


def builders() -> dict[str, str]:
    """Return the three artifacts as text, keyed by the file name each one becomes.

    Returns:
        The rendered artifacts.
    """
    document = extracted_document()
    return {
        "text.txt": export.export_docling_text(document),
        "document.md": export.export_docling_markdown(document),
        "document.json": export.serialize_document_json(
            export.export_docling_json(document)
        ),
    }


# ======================================================================================
# Criterion 1 - the three artifacts hold the documented content
# ======================================================================================


def test_text_is_non_empty_and_newline_terminated() -> None:
    """The criterion says non-empty; the newline is what makes it a well-formed text file."""
    rendered = builders()["text.txt"]

    assert rendered.strip(), "text.txt is empty"
    assert rendered.endswith("\n")
    assert not rendered.endswith("\n\n"), (
        "the terminator was added to text that had one"
    )


def test_text_holds_the_content_the_extraction_found() -> None:
    """Non-empty is not enough: the file has to hold the page's text.

    A builder that wrote a placeholder would satisfy the shape criterion and be useless, so the
    heading the fixture is known to carry must appear.
    """
    document = extracted_document()
    rendered = builders()["text.txt"]

    assert document.text.strip(), "the fixture produced no text at all"
    first_line = document.text.strip().splitlines()[0].strip()
    assert first_line in rendered


def test_markdown_is_a_heading_followed_by_content() -> None:
    """The fixture's own title is topmost, so the file opens with a heading.

    A sanity check with teeth: an artifact whose heading was rendered as plain text would still be
    "valid Markdown" and would have lost the document's structure.
    """
    rendered = builders()["document.md"]

    assert rendered.lstrip().startswith("#"), rendered[:80]
    assert rendered.endswith("\n")


def test_markdown_carries_the_tables_cells_as_a_pipe_table() -> None:
    """Valid Markdown includes the table the page has, with its divider row."""
    rendered = builders()["document.md"]
    lines = [line for line in rendered.splitlines() if line.startswith("|")]

    assert len(lines) >= 3, f"not a table: {lines}"
    assert lines[1].replace("|", "").replace(" ", "") == "---" * (
        lines[1].count("|") - 1
    ) or set(lines[1].replace("|", "").replace(" ", "")) == {"-"}
    assert all(line.count("|") == lines[0].count("|") for line in lines), (
        "the table's rows are ragged, so a renderer cannot agree on its column count"
    )


def test_markdown_is_already_canonical() -> None:
    """The artifact is what the canonicalizer produces, so a reader needs no second pass."""
    rendered = builders()["document.md"]

    assert export.normalize_markdown(rendered) == rendered.rstrip("\n")


def test_json_deserializes_to_the_documented_schema() -> None:
    """The criterion, stated directly: a consumer can read the file back."""
    payload = json.loads(builders()["document.json"])

    assert payload["schema_version"] == export.DOCUMENT_SCHEMA_VERSION
    for key in DOCUMENT_JSON_SECTIONS:
        assert key in payload, f"the schema lost {key}"


def test_json_blocks_carry_the_fields_a_reader_needs() -> None:
    """A block's shape is the schema's contract with a consumer, field by field."""
    payload = json.loads(builders()["document.json"])

    assert payload["blocks"], "no blocks were serialized"
    for block in payload["blocks"]:
        assert set(block) == {"block_id", "type", "text", "bbox", "level"}
        assert block["bbox"] is None or len(block["bbox"]) == 4


def test_json_layout_is_serialized_faithfully_in_the_frame_it_arrived_in() -> None:
    """The exporter reports the layout it was handed; it does not reinterpret coordinates.

    ``build_ocr_document`` (``OCR-04``) currently returns the engine's **pixel** frame, and this
    asserts the exporter neither normalizes it nor pretends it did — a second module that knew how
    to map coordinates would be the second definition of the frame, which is what ``OCR-05`` exists
    to prevent. The frame recorded here is a fact about the pipeline's current composition, not a
    claim about the artifact's final form; see the test below.
    """
    document = extracted_document()
    payload = json.loads(builders()["document.json"])

    assert payload["layout"]["page_width"] == document.layout.page_width
    assert payload["layout"]["page_height"] == document.layout.page_height
    for box, source in zip(
        payload["layout"]["region_bboxes"], document.layout.region_bboxes, strict=True
    ):
        assert box == list(source)


def test_the_artifacts_do_not_yet_apply_ocr05_normalization_and_ocr11_must_wire_it() -> (
    None
):
    """A gap recorded rather than hidden, because nothing else in the suite can see it.

    ``subplan-procesador-ocr.md`` §9 decision 4 is **frozen**: the ``bbox`` normalization reference
    is "normalized 0-1 coordinates". ``OCR-05`` built ``normalize_layout`` and
    ``preserve_reading_order`` to deliver exactly that, and ``OCR-04``'s docstring says in as many
    words that it does not attempt the sort because that is ``OCR-05``'s work.

    But **no production module calls either primitive.** They appear only in docstrings. So today
    ``document.json`` carries pixel coordinates and the engine's iteration order, and §9's frozen
    decision is unmet — not because the primitive is wrong (its own suite pins it against a real
    conversion) but because nothing composes it.

    This is the expected shape of a task-by-task build: ``OCR-05`` landed primitives, and ``OCR-11``
    ("``process_ocr_image`` orchestration") is the task that runs the stages in order. The point of
    asserting it *now* is that this is the only place the omission is observable — every other test
    passes either way, and the failure mode is a plausible-looking artifact with coordinates no
    consumer can interpret. When ``OCR-11`` wires it, this test must be inverted along with the one
    above, and the contract's ``layout: Normalized layout`` docstring becomes true.
    """
    document = extracted_document()
    payload = json.loads(builders()["document.json"])

    assert document.layout.page_width > 1.0, (
        "the layout is already normalized, so OCR-11 has wired OCR-05: invert this test and "
        "test_json_layout_is_serialized_faithfully_in_the_frame_it_arrived_in"
    )
    assert payload["layout"]["page_width"] > 1.0

    ordered = [block["block_id"] for block in payload["blocks"]]
    assert ordered == [block.block_id for block in document.blocks], (
        "the blocks are no longer in extraction order"
    )
    assert payload["reading_order"] == document.reading_order


def test_the_three_artifacts_agree_about_the_text() -> None:
    """One extraction, three renderings, and they must not disagree about its content.

    The heading is the cheapest content they all carry, so a discrepancy between the plain text and
    the structured one shows up here.
    """
    document = extracted_document()
    artifacts = builders()

    for title in document.titles:
        assert title.strip() in artifacts["text.txt"]
        assert title.strip().lstrip("# ").strip() in artifacts["document.md"]
        assert title.strip() in json.loads(artifacts["document.json"])["text"]


# ======================================================================================
# Criterion 2 - no run-time data in functional content
# ======================================================================================


def test_the_artifacts_do_not_move_when_the_clock_does(frozen_clock: None) -> None:
    """Invariant 2, in the only form that can fail for the right reason.

    The builders run twice with the clock pinned to a value no page can contain. If any of them
    stamped a time, the pinned instant would appear in an artifact and the search below would find
    it. The two runs are compared as well, so a builder that read the clock into something
    *derived* — a hash, a duration, an id — is caught even when the raw value is not recognizable.

    Note the fixture is a real invoice that genuinely contains ``01/11/2016``, ``27/02/26`` and a
    ``13:09``. Asserting "no date-shaped string" would therefore fail on correct output, which is
    why the clock is pinned instead.
    """
    assert frozen_clock is None

    artifacts = builders()

    for name, rendered in artifacts.items():
        assert "2099" not in rendered, f"{name} carries the run-time clock"
        assert PINNED_NOW.isoformat() not in rendered
        assert f"{PINNED_NOW.timestamp():.0f}" not in rendered, (
            f"{name} carries a run-time epoch"
        )


def test_the_artifacts_are_byte_identical_across_two_builds() -> None:
    """The determinism posture's claim, on the artifacts themselves.

    Two builds of one document produce the same bytes, so a diff between two artifacts from the
    same page shows a real difference or nothing at all.
    """
    first = builders()
    second = builders()

    assert first == second
    for name, rendered in first.items():
        assert rendered == second[name], f"{name} is not reproducible"


def test_no_artifact_holds_a_documented_timestamp_field() -> None:
    """The structural half: the schema has no place for a time, so none can be added silently.

    Field *names* are what a consumer reads, so a schema that gained ``generated_at`` would be a
    visible change. This pins the absence rather than trusting it.
    """
    payload = json.loads(builders()["document.json"])
    forbidden = {
        "generated_at",
        "created_at",
        "timestamp",
        "processed_at",
        "run_at",
        "date",
    }

    assert not forbidden & set(payload), "the schema grew a timestamp field"
    for block in payload["blocks"]:
        assert not forbidden & set(block)


def test_the_rule_matches_what_the_page_really_contains() -> None:
    """The finding that shaped the test above, pinned so it cannot be forgotten.

    The fixture's own content carries dates and a time. Anyone tempted to write the
    no-timestamps test as a date-shaped search needs to see this first.
    """
    rendered = builders()["text.txt"]

    assert re.search(r"\d{2}/\d{2}/\d{2,4}", rendered), (
        "the fixture no longer carries a date, so the reason for pinning the clock instead of "
        "searching for a shape needs rechecking"
    )


def test_blank_input_yields_empty_artifacts_rather_than_placeholders() -> None:
    """``is_ocr_empty``'s consumer path, and the no-silent-stand-in rule.

    A blank page must produce an empty ``text.txt`` and an empty ``document.md`` — not a file
    holding a bare newline, which would read as content and make ``OCR-09``'s ``EMPTY`` status
    unreachable.
    """
    document = extracted_document()
    blanks = {
        "text": export.export_docling_text(_emptied(document)),
        "markdown": export.export_docling_markdown(_emptied(document)),
    }

    assert blanks["text"] == ""
    assert blanks["markdown"] == ""


# ======================================================================================
# Canonicalization - the builders own it, so these tests drive it through them
# ======================================================================================


def _with_raw_content(
    document: Any,
    text: str,
    blocks: list[Any],
    tables: list[Any] | None = None,
) -> Any:
    """Return the document with its text, blocks and tables replaced by deliberately raw content.

    The engine's own output is already well formed, so a test that fed it to a builder and asserted
    canonical output would pass whether or not the builder canonicalized anything. Replacing the
    content is what makes the builder's own step observable.

    ``reading_order`` is rebuilt from what was passed, because the Markdown exporter walks it: a
    stand-in table that never appears in the order is never rendered, and a test asserting the
    absence of a character in an *empty* rendering passes without testing anything.

    Args:
        document: The document to re-content.
        text: The raw text to install.
        blocks: The raw blocks to install.
        tables: The raw tables to install.

    Returns:
        The document, with the raw content in place.
    """
    installed_tables = tables if tables is not None else []
    return dataclasses.replace(
        document,
        text=text,
        paragraphs=[],
        titles=[],
        blocks=blocks,
        tables=installed_tables,
        reading_order=[block.block_id for block in blocks]
        + [table.table_id for table in installed_tables],
    )


def test_text_txt_is_canonicalized_by_the_builder_not_by_the_engine() -> None:
    """A builder that passed the text through would put the engine's padding in the artifact.

    The engine's output happens to be clean, which is exactly why this drives the builder with
    deliberately *unclean* content: the margin of this test is the difference between ``"a\nb\n"``
    and ``"a  \r\n\r\n\r\n\r\nb"``, and only a builder that canonicalizes can close it.
    """
    document = extracted_document()
    raw = "  heading  \r\n\r\n\r\n\r\n  body  "

    rendered = export.export_docling_text(_with_raw_content(document, raw, []))

    assert rendered == "  heading\n\n  body\n"


def test_document_md_is_canonicalized_by_the_builder_not_by_the_engine() -> None:
    """The same claim for the Markdown artifact, through ``merge_ocr_blocks``."""
    document = extracted_document()
    raw_blocks = [
        BlockResult(
            block_id="block_001",
            type="title",
            text="Heading",
            bbox=None,
            level=1,
        ),
        BlockResult(
            block_id="block_002",
            type="text",
            text="body with padding   \r\n\r\n\r\n\r\nand more",
            bbox=None,
            level=None,
        ),
    ]

    rendered = export.export_docling_markdown(
        _with_raw_content(document, "", raw_blocks)
    )

    assert rendered == "# Heading\n\nbody with padding\n\nand more\n"


def test_json_text_field_is_canonicalized_the_same_way_as_the_artifact() -> None:
    """One extraction, and the structured artifact must not disagree with the plain one.

    ``document.json`` carries the document's ``text``; if only ``text.txt`` were canonicalized, a
    consumer comparing the two would see a difference the page does not have.
    """
    document = extracted_document()
    raw = "a  \r\n\r\n\r\n\r\nb"
    payload = export.export_docling_json(_with_raw_content(document, raw, []))

    assert payload["text"] == export.export_docling_text(
        _with_raw_content(document, raw, [])
    ).rstrip("\n")


def test_a_table_cell_cannot_smuggle_a_control_character_into_the_markdown() -> None:
    """The reason the exporter canonicalizes the *whole* document, not just each block run.

    ``_render_table`` joins cell values straight into a pipe row, so a character the engine left in
    a cell reaches the artifact unless something canonicalizes what the table rendered. A first
    draft canonicalized only the block runs, which is why this test exists: it is the one case where
    the document-wide pass does work no other call does.
    """

    document = extracted_document()
    hostile = TableResult(
        table_id="table_001",
        index=1,
        markdown="",
        bbox=None,
        cells=[["a\x00b", "c"], ["1\r\n2", "3"]],
    )
    hostile_document = _with_raw_content(document, "", [], [hostile])

    rendered = export.export_docling_markdown(hostile_document)

    assert rendered, "the table was not rendered at all, so this test proves nothing"
    assert "\x00" not in rendered, "a control character reached document.md"
    assert "\r" not in rendered, "a raw carriage return reached document.md"
    assert "| ab | c |" in rendered


def test_every_text_field_in_the_payload_is_canonicalized_including_a_blocks() -> None:
    """One raw value, and every place it appears in the schema must agree about it.

    A block's ``text`` is the field a consumer reads to reconstruct the document, and it is *not*
    the same string as the payload's top-level ``text``. A first version of the test above read only
    the top-level field, so a mutation that stopped canonicalizing the block field survived.
    """
    document = extracted_document()
    raw = "a  \r\n\r\n\r\n\r\nb"
    canonical = "a\n\nb"
    raw_block = BlockResult(
        block_id="block_001", type="text", text=raw, bbox=None, level=None
    )

    payload = export.export_docling_json(_with_raw_content(document, raw, [raw_block]))

    assert payload["text"] == canonical
    assert payload["blocks"][0]["text"] == canonical, (
        "a block's text field was left as the engine wrote it"
    )


def test_the_json_serialization_is_key_sorted_so_two_payloads_of_one_shape_match() -> (
    None
):
    """Key order is not content, so it must not appear in a diff between two runs.

    Driving it with two payloads that hold the **same keys in different insertion order** is what
    makes the sort observable: comparing a payload against itself would pass without it.
    """
    ascending = {"a": 1, "b": 2, "c": 3}
    descending = {"c": 3, "b": 2, "a": 1}

    assert export.serialize_document_json(ascending) == export.serialize_document_json(
        descending
    )
    assert export.serialize_document_json(ascending).index('"a"') < (
        export.serialize_document_json(ascending).index('"c"')
    )


def _emptied(document: Any) -> Any:
    """Return the document with every content field emptied.

    A stand-in built from the real record rather than a fixture file, because the assertion is
    about the *builder's* reaction to empty content and not about whether Docling can be made to
    produce it. The blank input itself belongs to ``OCR-08``'s and ``OCR-12``'s fixture set.

    ``dataclasses.replace`` rather than a hand-rolled look-alike: a class with the same attribute
    names would drift from ``OCRDocument`` the moment the contract gained a field, and the test
    would then be asserting about a document the builders never see.

    Args:
        document: The document to empty.

    Returns:
        The document, with no content and the same layout and metadata.
    """
    return dataclasses.replace(
        document,
        text="",
        paragraphs=[],
        titles=[],
        blocks=[],
        tables=[],
        reading_order=[],
    )
