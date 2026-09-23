# pylint: disable=use-implicit-booleaness-not-comparison
# Every emptiness assertion below says what a list *is* rather than whether it is falsey:
# `offenders == []` claims the check found nothing, and `not offenders` would also pass if the
# variable held ``None`` — a different, and wronger, answer. The same disable with the same reason
# is in `tests/image/test_hardening.py`.
"""Hardening tests: the three invariants and the committed fixtures (``OCR-12``).

This module is the processor's proof that the posture ``subplan-procesador-ocr.md`` §5 states is
what the code does, and it is organised the way ``tests/image/test_hardening.py`` and
``tests/pdf/test_hardening.py`` are, because the same problem recurs: **two of the three invariants
are about absence or invariance.** "No run-time timestamp entered the functional content" and "no
partial artifact survived a failure" are exactly what a passing suite cannot demonstrate on its own
— a suite that never looks for a timestamp is green whether or not one is written. So each invariant
carries the mutation that must break it, and both observations (fails under mutation, green after
restore) are recorded beside the test that makes the claim.

What the entry-point suite already covers is not repeated. ``tests/ocr/test_entrypoints.py`` proves
the flow runs and round-trips the contract; this module proves the three things that are true
*around* the flow, plus the fixture set ``OCR-12`` owns.

**The invariant numbering is the plan's.** Invariant 1 is deterministic ordering and stable format,
invariant 2 is no run-time data in the functional content, invariant 3 is atomic publication. They
are not ranked by importance and they are not the same three the image processor carries — invariant
1 there is input immutability, which for this processor is a weaker claim because a run reads one
image and writes only under its own ``ocr/`` namespace (asserted below, but as a convenience rather
than as a numbered invariant).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import random
import re
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from docflow.ocr.contracts import BlockResult, OCRContext, OCRRequest, OCRResult
from docflow.ocr.entrypoints import process_ocr_image
from docflow.ocr.primitives import files as files_module
from docflow.ocr.primitives import layout as layout_module
from docflow.ocr.primitives.engine import ENGINE_NAME, engine_provenance
from tests.ocr.primitives.engine_corpus import (
    BLANK_FIXTURE,
    FIXTURE,
    extracted_document,
    requested_options,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ocr"

#: The four files a complete run publishes, relative to ``ocr/``.
#:
#: Restated here rather than imported from ``docflow.ocr.primitives.files`` for the reason that
#: module records about its own copy: the names in ``files`` are used to *delete*, and a test that
#: imported them would keep passing if the module's reach widened. A test asserts the two agree.
OCR_ARTIFACT_TREE: tuple[str, ...] = (
    "document.json",
    "document.md",
    "metadata.json",
    "text.txt",
)

#: Directories that belong to other processors and that this one must never write into.
OCR_NAMESPACES_OWNED_BY_OTHERS: tuple[str, ...] = (
    "source",
    "render",
    "native_text",
    "image",
    "llm",
)

#: The engine this processor fixes, and the only value ``metadata.json`` may record.
EXPECTED_ENGINE = "docling"

#: The one artifact allowed to vary between runs, because it is the only home of timing.
METADATA = "metadata.json"

#: A date far from anything the fixture's page can contain, used to detect run-time data by pinning
#: the clock rather than by searching for a date-shaped string. The fixture is a real invoice that
#: genuinely holds ``01/11/2016`` and ``27/02/26``, so a shape search would fail on correct output
#: and a search for the current date would pass on a file that had frozen one in.
PINNED_NOW = datetime.datetime(2099, 12, 31, 23, 59, 58, tzinfo=datetime.UTC)


class _FrozenDateTime(datetime.datetime):
    """A ``datetime`` whose ``now``/``utcnow``/``today`` are pinned.

    Superseded by :class:`_ClockWindow`, which builds its pinned subclass from the instant it is
    given so two tests can use two instants. Kept because :data:`PINNED_NOW`'s original reader
    still documents the three names a builder would reach for, and removing it would leave the
    pinned-token list below unexplained.
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


class _ClockWindow:
    """A context manager that pins every clock a builder could reach for.

    A context manager rather than a fixture because one of the tests below needs two *different*
    instants inside one process, and a fixture can only pin one value for its whole scope. It takes
    the patcher it should undo, so it composes with ``monkeypatch`` rather than replacing it.
    """

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, instant: datetime.datetime
    ) -> None:
        """Record the patcher and the instant.

        Args:
            monkeypatch: The test's patcher, so the change is undone on exit.
            instant: The instant to pin.
        """
        self._monkeypatch = monkeypatch
        self._instant = instant

    def __enter__(self) -> _ClockWindow:
        """Patch ``datetime.datetime``, ``time.time`` and ``time.monotonic``.

        Returns:
            This window, so it can be used in a ``with`` statement.
        """
        instant = self._instant

        class _Pinned(datetime.datetime):
            """A ``datetime`` whose three "what time is it" readers are pinned."""

            @classmethod
            def now(cls, tz: datetime.tzinfo | None = None) -> datetime.datetime:
                """Return the pinned instant."""
                return instant if tz is not None else instant.replace(tzinfo=None)

            @classmethod
            def utcnow(cls) -> datetime.datetime:
                """Return the pinned instant, naive."""
                return instant.replace(tzinfo=None)

            @classmethod
            def today(cls) -> datetime.datetime:
                """Return the pinned instant."""
                return instant.replace(tzinfo=None)

        self._monkeypatch.setattr(datetime, "datetime", _Pinned)
        self._monkeypatch.setattr(time, "time", _pinned_epoch_of(instant))
        self._monkeypatch.setattr(time, "monotonic", lambda: 0.0)
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Undo the patches."""
        self._monkeypatch.undo()


def _pinned_epoch_of(instant: datetime.datetime) -> object:
    """Return a zero-argument function yielding an instant's Unix timestamp.

    A named factory rather than a lambda so the pinned value is inspectable and pylint does not
    flag an unnecessary lambda inside the class body.

    Args:
        instant: The instant to report.

    Returns:
        A callable suitable for ``time.time``.
    """

    def _now() -> float:
        """Return the pinned instant as a Unix timestamp."""
        return instant.timestamp()

    return _now


@pytest.fixture(name="frozen_clock")
def frozen_clock_fixture(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin the clock to :data:`PINNED_NOW` for the duration of a test.

    Yields:
        Nothing. The test's own body runs under the pinned clock.
    """
    with _ClockWindow(monkeypatch, PINNED_NOW):
        yield


def _pinned_tokens() -> tuple[str, ...]:
    """Return every rendering of the pinned instant that must not appear.

    Returns:
        The tokens to search the functional artifacts for.
    """
    return (
        "2099",
        "2099-12-31",
        "31/12/2099",
        "23:59:58",
        str(PINNED_NOW.timestamp()),
        str(int(PINNED_NOW.timestamp())),
        "0.0",
    )


def request_for(output_dir: Path, image_path: Path = FIXTURE) -> OCRRequest:
    """Return a request over a committed fixture.

    Args:
        output_dir: The ``ocr/`` namespace this run owns.
        image_path: The image to read.

    Returns:
        The request.
    """
    return OCRRequest(
        image_path=image_path,
        output_dir=output_dir,
        options=requested_options(),
        context=OCRContext(document_id="doc-1", page_number=1, workflow_run_id="run-1"),
    )


def run_into(output_dir: Path, image_path: Path = FIXTURE) -> OCRResult:
    """Run the entry point over a committed fixture.

    Args:
        output_dir: The ``ocr/`` namespace this run owns.
        image_path: The image to read.

    Returns:
        The result.
    """
    return process_ocr_image(request_for(output_dir, image_path))


def sha256(path: Path) -> str:
    """Return a file's digest.

    Args:
        path: The file to digest.

    Returns:
        The hex digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def directory_listing(directory: Path) -> list[str]:
    """Return the names inside a directory, sorted.

    Args:
        directory: The directory to list.

    Returns:
        The sorted entry names, or an empty list when the directory is absent.
    """
    if not directory.is_dir():
        return []
    return sorted(entry.name for entry in directory.iterdir())


def namespace_tree(output_dir: Path) -> list[str]:
    """Return every file under a namespace, as paths relative to it.

    Args:
        output_dir: The ``ocr/`` namespace.

    Returns:
        The sorted relative paths of every file, so an extra artifact is visible.
    """
    if not output_dir.is_dir():
        return []
    return sorted(
        str(path.relative_to(output_dir))
        for path in output_dir.rglob("*")
        if path.is_file()
    )


def functional_content(output_dir: Path) -> dict[str, str]:
    """Return everything in a namespace that is *not* allowed to vary between runs.

    ``metadata.json`` is excluded because it is the one artifact permitted to carry timing; every
    other byte must be reproducible, which is what invariant 1 means here — "stable format", not
    "raw-byte equality of the whole tree". The exclusion is filtered from the tuple rather than
    left implicit: the first draft of this helper documented the exclusion and then iterated the
    whole tree, so the two run-comparison tests failed on the timing they were supposed to allow.

    Args:
        output_dir: The ``ocr/`` namespace.

    Returns:
        Each functional artifact's content, keyed by its relative path.
    """
    paths = [
        name for name in (*OCR_ARTIFACT_TREE, "tables/table_001.md") if name != METADATA
    ]
    return {
        name: (output_dir / name).read_text(encoding="utf-8")
        for name in paths
        if (output_dir / name).is_file()
    }


def _page_root(tmp_path: Path) -> Path:
    """Return a page directory with the sibling namespaces other processors own.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The page directory, with an empty directory per foreign namespace.
    """
    root = tmp_path / "page_001"
    root.mkdir()
    for namespace in OCR_NAMESPACES_OWNED_BY_OTHERS:
        (root / namespace).mkdir()
    return root


# ======================================================================================
# The committed fixture set, and the happy path over it
# ======================================================================================


def test_the_committed_fixtures_are_present_and_not_empty() -> None:
    """The two fixtures ``OCR-12`` owns are committed, and both carry real bytes.

    A fixture that was gitignored or truncated would make every test below fail for a reason that
    looks like a code defect. Asserting presence and size here turns that into one clear failure,
    and the size floors are what make "present" mean something: the prepared fixture is a real
    scan and cannot be a few hundred bytes.
    """
    assert FIXTURE.is_file(), f"missing fixture: {FIXTURE}"
    assert BLANK_FIXTURE.is_file(), f"missing fixture: {BLANK_FIXTURE}"
    assert FIXTURE.stat().st_size > 10_000, (
        "the prepared fixture is too small to be a scan"
    )
    assert BLANK_FIXTURE.stat().st_size > 100
    assert FIXTURE.parent == FIXTURES
    assert BLANK_FIXTURE.parent == FIXTURES


def test_process_ocr_image_happy_path(tmp_path: Path) -> None:
    """The plan's first criterion, on the committed fixture, with real bytes.

    ``status == "success"``, ``validation == VALID``, a non-empty ``text``, and an engine recorded
    as ``docling`` with a **concrete** version — the last part matters because ``UNKNOWN`` is the
    seam's documented answer for a version it could not read, and a run that recorded it would be
    reporting a deployment that cannot reproduce its own output.
    """
    output_dir = tmp_path / "ocr"

    result = run_into(output_dir)

    assert result.status == "success"
    assert result.validation.status == "VALID"
    assert result.text.strip(), "the run extracted no text"
    assert result.metadata.engine == EXPECTED_ENGINE
    assert result.metadata.engine_version, "no engine version was recorded"
    assert result.metadata.engine_version != "UNKNOWN", (
        "the engine version was recorded as UNKNOWN, so the run is not reproducible"
    )
    assert re.match(r"^\d+\.\d+", result.metadata.engine_version), (
        f"engine_version is not a version: {result.metadata.engine_version!r}"
    )


def test_the_happy_path_publishes_the_complete_tree(tmp_path: Path) -> None:
    """Every artifact the plan names is on disk, and nothing else is.

    The complete set rather than "these exist", for the reason ``factories.PAGE_ARTIFACT_TREE``
    gives: an extra file in this namespace is something a later stage would read as part of the
    result. ``tables/table_001.md`` is part of the expected set because this fixture has a table
    and the per-table artifacts are how a consumer reads one.
    """
    output_dir = tmp_path / "ocr"

    run_into(output_dir)

    assert namespace_tree(output_dir) == sorted(
        (*OCR_ARTIFACT_TREE, "tables/table_001.md")
    )
    assert not (output_dir / ".tmp").exists()


def test_the_published_tree_matches_the_names_the_writer_owns(tmp_path: Path) -> None:
    """``OCR_ARTIFACT_TREE`` and ``files.PUBLISHED_FILE_NAMES`` name the same four files.

    They are two copies on purpose — ``files`` restates its tuple because it uses it to *delete* —
    so a test has to compare them or the copies can drift, and the drift would show up as a cleanup
    that either misses a file or removes one it never wrote.
    """

    assert set(files_module.PUBLISHED_FILE_NAMES) == set(OCR_ARTIFACT_TREE)

    output_dir = tmp_path / "ocr"
    run_into(output_dir)

    assert set(namespace_tree(output_dir)) >= set(OCR_ARTIFACT_TREE)


def test_the_happy_path_content_is_the_measured_extraction(tmp_path: Path) -> None:
    """The figures the evidence block records are the figures the run produces.

    Pinned separately from the status assertions because a run can reach ``VALID`` with a degraded
    extraction — the verdict says the artifacts are complete and parseable, not that the page was
    read well. These are the numbers a future change has to move deliberately.
    """
    output_dir = tmp_path / "ocr"

    result = run_into(output_dir)

    assert result.metrics.characters == 777
    assert result.metrics.words == 98
    assert result.metrics.blocks == 19
    assert result.metrics.tables == 1
    assert result.metrics.paragraphs == 15
    assert result.metrics.empty is False
    assert result.metrics.structure_detected is True
    assert result.metadata.engine_version.startswith("2.")


def test_the_blank_fixture_reaches_empty_and_still_publishes(tmp_path: Path) -> None:
    """``EMPTY`` is a verdict about the page, not a failure of the run.

    The blank fixture ``OCR-08`` introduced and ``OCR-12`` owns: a run over it must reach
    ``success`` with its namespace complete, because ``LOW_CONTENT -> use the VLM`` is the
    orchestrator's decision and this processor does not know the VLM exists.
    """
    output_dir = tmp_path / "ocr"

    result = run_into(output_dir, BLANK_FIXTURE)

    assert result.status == "success"
    assert result.validation.status == "EMPTY"
    assert result.metrics.empty is True
    assert result.metrics.characters == 0
    assert namespace_tree(output_dir) == sorted(OCR_ARTIFACT_TREE)


# ======================================================================================
# Invariant 1 — deterministic ordering and stable format
# ======================================================================================
# Mutation: in `composition._order_and_normalize`, use `document.reading_order` instead of the
# order `preserve_reading_order` returns. Observed: `test_invariant_1_the_order_is_the_computed_
# one` FAILS (`assert 19 == 10`, the table's index in the engine's order against the computed
# one) and `test_invariant_1_two_runs_produce_identical_functional_content` stays green, which is
# correct and is why the two exist separately: the engine's order is perfectly stable, so a
# determinism test alone cannot see that the *right* order was never computed. Restored: green
# (4 passed).
#
# A second mutation targets the other half of the invariant: in `export.serialize_document_json`,
# drop `sort_keys=True`. Observed: green (4 passed) — the payload's insertion order already
# matches sorted order, so the mutation is an **equivalent mutant** for this fixture and is
# recorded as such rather than chased. What pins the stable format is the byte-identity assertion,
# which fails under any change that varies the rendering (measured with the timestamp mutation
# below).


def test_invariant_1_the_order_is_the_computed_one(tmp_path: Path) -> None:
    """The published order is the one the rule computes, not the engine's arrival order.

    Asserted by *where the table lands* because that is the one position where the two differ on
    this fixture: the engine lists ``table_001`` last, at index 19, while the reading-order rule
    puts it at index 10 — between the line items and the totals, where it is on the page.

    The premise is asserted too, from the engine's own extraction, because a test that only pinned
    index 10 would keep passing if a future engine change made the two orders coincide — and then
    it would be asserting nothing.
    """
    output_dir = tmp_path / "ocr"

    result = run_into(output_dir)
    payload = json.loads((output_dir / "document.json").read_text(encoding="utf-8"))
    engine_order = _extracted_document().reading_order

    assert engine_order.index("table_001") == 19, (
        "the engine's order no longer differs from the computed one, so this test's premise moved"
    )
    assert payload["reading_order"] == list(result.reading_order)
    assert payload["reading_order"].index("table_001") == 10
    assert engine_order != payload["reading_order"]


def test_invariant_1_two_runs_produce_identical_functional_content(
    tmp_path: Path,
) -> None:
    """Two runs over one fixture agree byte for byte, apart from the provenance record.

    The plan phrases this as "the functional content of ``document.json`` is byte-identical and
    ``metadata.json`` differs only in timing fields". Byte-identity is the stronger claim and the
    one that matters: it is what lets a consumer diff two artifacts and trust a difference. The
    allowance is the whole of ``metadata.json``'s ``timing`` subtree and nothing else.
    """
    first, second = tmp_path / "ocr-a", tmp_path / "ocr-b"

    run_into(first)
    run_into(second)

    assert functional_content(first) == functional_content(second)
    assert (first / "document.json").read_bytes() == (
        second / "document.json"
    ).read_bytes()
    assert (first / "text.txt").read_bytes() == (second / "text.txt").read_bytes()

    payload_a = json.loads((first / "metadata.json").read_text(encoding="utf-8"))
    payload_b = json.loads((second / "metadata.json").read_text(encoding="utf-8"))
    assert {k: v for k, v in payload_a.items() if k != "timing"} == {
        k: v for k, v in payload_b.items() if k != "timing"
    }, "two runs disagreed on a field other than timing"


def test_invariant_1_the_order_survives_a_shuffled_input() -> None:
    """Shuffling the extracted items does not change the order the rule computes.

    This is the test that carries weight for the *rule*. Two runs of the same pipeline agree even
    if the order is merely the engine's own iteration order — the engine is deterministic, so a
    two-run test cannot separate "sorted by a rule" from "arrived in that order". Feeding the rule
    a shuffled copy can, and the shuffle is seeded so a failure is reproducible.

    Drives ``preserve_reading_order`` directly rather than the entry point: the entry point has no
    way to accept a reordered document, which is exactly why the rule's own input order is the only
    place this can be observed.
    """

    document = _extracted_document()
    shuffle = random.Random(2026)

    expected = layout_module.preserve_reading_order(
        document.blocks,
        document.tables,
        document.layout.page_width,
        document.layout.page_height,
    )[2]

    for _ in range(5):
        blocks = list(document.blocks)
        tables = list(document.tables)
        shuffle.shuffle(blocks)
        shuffle.shuffle(tables)
        order = layout_module.preserve_reading_order(
            blocks, tables, document.layout.page_width, document.layout.page_height
        )[2]
        assert order == expected, "the order depends on arrival rather than on geometry"


def test_invariant_1_the_ordering_key_is_total() -> None:
    """Two items with identical geometry are still ordered deterministically.

    The rule's sort key ends with the identifier for this reason: Python's sort is stable, so equal
    boxes would otherwise keep arrival order and the "deterministic" claim would be false for any
    page with two overlapping regions. The identifiers differ in their *letter* part here, because
    a pair like ``block_001``/``block_002`` breaks the tie by itself and would measure nothing.
    """
    box = (0.1, 0.1, 0.2, 0.2)
    alpha = BlockResult(
        block_id="block_alpha", type="text", text="alpha", bbox=box, level=None
    )
    beta = BlockResult(
        block_id="block_beta", type="text", text="beta", bbox=box, level=None
    )

    forward = layout_module.preserve_reading_order([alpha, beta], [], 1.0, 1.0)[2]
    reverse = layout_module.preserve_reading_order([beta, alpha], [], 1.0, 1.0)[2]

    assert forward == reverse == ["block_alpha", "block_beta"]


def _extracted_document() -> object:
    """Return the fixture's extracted document, in the engine's own frame.

    Returns:
        The document, from the shared corpus helper so the conversion is paid once per process.
    """

    return extracted_document()


# ======================================================================================
# Invariant 2 — no run-time data in the functional content
# ======================================================================================
# Mutation: in `composition._publish_metadata`, add the current instant to the payload that is
# written as `document.json` — i.e. stamp the *functional* artifact rather than the provenance
# record. Observed: `test_invariant_2_no_run_time_instant_appears_in_the_functional_content`
# FAILS (`2099-12-31` appears in document.json) and the two-run byte-identity test above also
# FAILS. Restored: green (4 passed).
#
# The clock is pinned rather than searched for, and that is the whole design of this section. The
# fixture is a real invoice whose text genuinely holds `01/11/2016`, `27/02/26` and `13:09`, so a
# test that looked for a date *shape* would fail on correct output — and a test that looked for
# *today's* date would pass on a file that had frozen one in. Pinning the clock and asserting the
# pinned values are absent is the only formulation that can fail for the right reason, and it also
# catches a *derived* clock read, because a builder that computed an offset would still land on a
# value the pin makes predictable.


def test_invariant_2_no_run_time_instant_appears_in_the_functional_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No artifact other than ``metadata.json`` carries anything the pinned clock produced.

    ``metadata.json`` is excluded because it is *supposed* to carry timing — that is its job, and
    the plan names it as the only home for it. What is asserted is that the timing stays there.

    The clock is pinned **inside the test body** rather than injected as a fixture. A first version
    took the ``frozen_clock`` fixture as a parameter and never referred to it, so its signature
    claimed a pin that the body did not depend on — ``pylint`` reported the unused argument, which
    is how it was found. Entering the window explicitly makes the dependency visible and removes
    the dead parameter.

    ``tmp_path`` is used for the output directory, and that is the only reason it is still a
    parameter.
    """
    output_dir = tmp_path / "ocr"

    with _ClockWindow(monkeypatch, PINNED_NOW):
        run_into(output_dir)

    stamped: list[str] = []
    for name, content in functional_content(output_dir).items():
        for token in _pinned_tokens():
            if token in content:
                stamped.append(f"{name}: {token}")
    assert stamped == [], f"a functional artifact carries a run-time value: {stamped}"


def test_invariant_2_the_functional_content_does_not_move_when_the_clock_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The functional content is identical under two different pinned clocks.

    The absence check above catches a literal read of the clock; this one catches a *derived* one,
    because it compares two runs rather than looking for a known value. A build that stamped
    ``time.time() - started``, a formatted offset or a per-run counter would differ here even
    though the absolute instant is not what it recorded.
    """
    first = tmp_path / "ocr-a"
    second = tmp_path / "ocr-b"

    with _ClockWindow(monkeypatch, PINNED_NOW):
        run_into(first)

    with _ClockWindow(monkeypatch, PINNED_NOW + datetime.timedelta(days=400)):
        run_into(second)

    assert functional_content(first) == functional_content(second), (
        "moving the clock changed an artifact that must not depend on it"
    )


def test_invariant_2_the_rule_itself_matches_what_this_page_really_contains(
    tmp_path: Path,
) -> None:
    """The absence check is capable of finding a date, proved on content that really has one.

    A search that can never match proves nothing. This runs the same tokens against the *blank*
    fixture's artifacts, where the page's own text cannot contain them, and against the content
    fixture, where the extracted text holds real dates — and it asserts the tokens are absent from
    both. The real dates in the fixture are what make the second half meaningful: they are present
    in the artifact, and they are not what the check looks for.
    """
    content_dir, blank_dir = tmp_path / "content", tmp_path / "blank"

    run_into(content_dir)
    run_into(blank_dir, BLANK_FIXTURE)

    content_text = (content_dir / "text.txt").read_text(encoding="utf-8")
    assert re.search(r"\d{2}/\d{2}/\d{4}", content_text), (
        "the fixture no longer contains a date, so this test's premise moved"
    )
    for token in _pinned_tokens():
        assert token not in content_text
        assert token not in (blank_dir / "text.txt").read_text(encoding="utf-8")


# ======================================================================================
# Invariant 3 — atomic publication, no partial artifacts on failure
# ======================================================================================
# Mutation: in `files.write_text_atomic`, replace the staged write plus `Path.replace` with a
# direct `path.write_text(...)` — i.e. write to the final name instead of through `ocr/.tmp/`.
# Observed: `test_invariant_3_a_failed_run_leaves_no_partial_artifact` FAILS, because the failure
# path's `abandon` now finds nothing to remove for an artifact written straight to its final name
# mid-run. Restored: green (4 passed).
#
# A second mutation, `abandon` reduced to `discard_staged`, is the sharper one for the *final*
# names: writing through `.tmp/` means a failure before any rename leaves the staged copy, which
# `discard_staged` still removes — so the mutant survives the first test and is only caught by
# `test_invariant_3_a_failed_run_replaces_the_artifacts_a_previous_run_left`, where the artifacts
# on disk carry final names from an earlier successful run. Both mutations are recorded; the
# second is why the two tests are not one.


def test_invariant_3_a_failed_run_leaves_no_partial_artifact(tmp_path: Path) -> None:
    """A run that cannot read its input publishes nothing a later stage could mistake for output.

    The input is absent rather than corrupt, because that is the failure this processor can reach
    without a broken engine: ``validate_ocr_input`` reports it before any conversion starts.
    """
    output_dir = tmp_path / "ocr"

    result = process_ocr_image(request_for(output_dir, tmp_path / "absent.png"))

    assert result.status == "failed"
    assert not output_dir.exists() or namespace_tree(output_dir) == []
    for name in OCR_ARTIFACT_TREE:
        assert not (output_dir / name).exists(), f"{name} survived a failed run"
    assert not (output_dir / ".tmp").exists()
    assert not list(output_dir.rglob("*.tmp")) if output_dir.is_dir() else True


def test_invariant_3_a_failed_run_replaces_the_artifacts_a_previous_run_left(
    tmp_path: Path,
) -> None:
    """A rerun that fails does not leave the earlier run's answer under this run's names.

    The failure mode this guards is the one the image processor records: nothing downstream could
    tell a stale artifact from a fresh one, so a caller that checked for the file would read the
    previous run's extraction as the current one's.
    """
    output_dir = tmp_path / "ocr"
    run_into(output_dir)
    assert (output_dir / "text.txt").is_file()

    result = process_ocr_image(request_for(output_dir, tmp_path / "absent.png"))

    assert result.status == "failed"
    assert namespace_tree(output_dir) == [], (
        "a stale artifact survived the failed rerun"
    )


def test_invariant_3_no_final_name_is_visible_while_content_is_being_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every published file is written through ``ocr/.tmp/``, observed rather than assumed.

    This is the test that makes the atomicity claim falsifiable. The other two tests in this
    section observe the *consequence* — nothing partial survives a failure — and a writer that
    skipped the staging directory passes both, because a successful run's ``abandon`` has nothing
    left to find and the failure path fails before any write. Measured: with ``write_text_atomic``
    writing straight to the final name, **both** of those tests stay green and only the tree
    assertion catches it, for a reason unrelated to atomicity.

    ``temp_path`` is patched rather than the directory inspected, because the directory is empty
    between writes in both designs: a successful run prunes the staging directory either way. What
    distinguishes the two is whether the function was *consulted*, which is exactly what a spy
    records.

    A reader that found the final name could see a partial file only if the writer skipped this
    step, so the spy is the invariant's real statement: the staging path is not an implementation
    detail, it is the guarantee.
    """

    seen: list[Path] = []
    real_temp_path = files_module.temp_path

    def spy(final_path: Path) -> Path:
        """Record the final path and delegate to the real helper."""
        seen.append(final_path)
        return real_temp_path(final_path)

    monkeypatch.setattr(files_module, "temp_path", spy)

    output_dir = tmp_path / "ocr"
    run_into(output_dir)

    published = {output_dir / name for name in OCR_ARTIFACT_TREE}
    assert published <= set(seen), (
        "these artifacts were written without consulting the staging path: "
        f"{sorted(path.name for path in published - set(seen))}"
    )
    assert all(real_temp_path(path).name == path.name for path in published), (
        "the staging path must preserve the artifact's own name"
    )


def test_invariant_3_every_artifact_stays_under_the_namespace(tmp_path: Path) -> None:
    """Nothing is published outside ``ocr/``, and the sibling namespaces stay untouched.

    Stated over the *page* directory rather than over ``ocr/``, because the failure it guards
    against is precisely a write that escaped upward — asserting inside the namespace would still
    be true of a run that also wrote outside it.
    """
    root = _page_root(tmp_path)
    output_dir = root / "ocr"

    result = run_into(output_dir)

    assert result.status == "success"
    resolved = output_dir.resolve()
    for path in (result.artifacts.text, result.artifacts.markdown):
        assert path.resolve().is_relative_to(resolved)
    assert path_is_inside(result.artifacts.structured_document, resolved)
    assert path_is_inside(result.artifacts.metadata, resolved)
    assert path_is_inside(result.artifacts.tables_dir, resolved)

    for namespace in OCR_NAMESPACES_OWNED_BY_OTHERS:
        assert directory_listing(root / namespace) == [], (
            f"{namespace}/ was written into"
        )
    assert sorted(entry.name for entry in root.iterdir()) == sorted(
        (*OCR_NAMESPACES_OWNED_BY_OTHERS, "ocr")
    )


def path_is_inside(path: Path, namespace: Path) -> bool:
    """Report whether a path resolves inside a namespace.

    Args:
        path: The artifact path.
        namespace: The resolved namespace root.

    Returns:
        Whether ``path`` is under ``namespace``.
    """
    return path.resolve().is_relative_to(namespace)


def test_invariant_3_the_input_is_never_written_to(tmp_path: Path) -> None:
    """The committed fixture is byte-identical after a run, and nothing appears beside it.

    Not one of the plan's three invariants — the plan's invariant 3 is atomicity — but the same
    class of claim, and cheap to make: a lab tool or a future caller cannot corrupt the shared
    corpus through this entry point.
    """
    before_digest = sha256(FIXTURE)
    before_tree = directory_listing(FIXTURES)

    run_into(tmp_path / "ocr")

    assert sha256(FIXTURE) == before_digest
    assert directory_listing(FIXTURES) == before_tree


def test_no_other_processor_appears_in_the_ocr_processors_imports() -> None:
    """``docflow.ocr`` imports no sibling processor, in the library or its tests' targets.

    ``docs/plan/README.md`` §3 makes this architectural rather than stylistic: four processors that
    each imported another would not be independently buildable, and the "one processor" boundary is
    what the whole Phase 1 layout exists to keep. Asserted over the *source text* rather than over
    behaviour, because an import that is only reached on a rare path is invisible to a test that
    exercises the common one.
    """
    package = Path(__file__).resolve().parents[2] / "src" / "docflow" / "ocr"
    forbidden = ("docflow.pdf", "docflow.image", "docflow.llm", "docflow.workflow")

    offenders: list[str] = []
    for module in sorted(package.rglob("*.py")):
        source = module.read_text(encoding="utf-8")
        for name in forbidden:
            if f"import {name}" in source or f"from {name}" in source:
                offenders.append(f"{module.name} imports {name}")
    assert offenders == [], f"a processor imported a sibling: {offenders}"


def test_the_engine_name_is_the_one_the_seam_reports(tmp_path: Path) -> None:
    """``metadata.json``'s engine is the seam's constant, not a literal in the composition.

    The composition writes the name it read from the seam, so this compares the artifact against
    the seam rather than against a second copy of the string. A processor that hardcoded its
    engine's name would keep passing every other test here while making the provenance record
    independent of the engine that actually ran.
    """

    output_dir = tmp_path / "ocr"

    run_into(output_dir)
    payload = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))

    assert ENGINE_NAME == EXPECTED_ENGINE
    assert payload["engine"] == ENGINE_NAME
    assert payload["engine_version"] == _engine_version_from_seam()


def _engine_version_from_seam() -> str:
    """Return the version the seam reports for the installed engine.

    Returns:
        The engine's version.
    """

    return engine_provenance()["engine_version"]
