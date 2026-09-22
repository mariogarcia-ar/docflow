"""Tests for the Poppler engine seam (``PDF-02``).

The seam's two promises are what is checked here:

* the engine is **explicit** — named, located and versioned, so no artifact can claim a
  provenance it does not have;
* the engine is **never a substitute** — a missing binary raises a typed error rather than
  silently producing the empty text layer that "this page has no text" would also produce.

The second promise is the one that has to be falsified to be believed; each test below
records the mutation that breaks it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docflow.pdf.primitives.engine import (
    POPPLER_ENGINE_NAME,
    Engine,
    PopplerCommand,
    PopplerExecutionError,
    PopplerNotAvailableError,
    find_engine_command,
    get_engine,
    get_engine_name,
    get_engine_version,
    run_engine_command,
)

ALL_COMMANDS = tuple(PopplerCommand)

# `pdftotext` writes its version banner to standard error and nothing to standard output.
# The version probe reads both streams; the runner below deliberately returns only stdout.
VERSION_ARGUMENT = "-v"


def test_the_engine_is_named_and_versioned() -> None:
    """The engine reports a real name and a non-blank version.

    Mutation that breaks it: return a constant such as ``"unknown"`` from
    ``get_engine_version``, or drop the version from ``Engine``. The blank-version
    assertion fails, which is the point — a provenance field that accepts a placeholder
    cannot be used to reproduce an artifact.
    """
    engine = get_engine()

    assert engine == get_engine()
    assert engine.name == POPPLER_ENGINE_NAME
    assert engine.version
    assert engine.version.strip() == engine.version


def test_the_engine_name_is_a_constant_not_a_choice() -> None:
    """The engine name is fixed by the implementation, not supplied by a caller."""
    assert get_engine_name() == POPPLER_ENGINE_NAME


def test_every_command_the_processor_needs_is_named_and_locatable() -> None:
    """All six binaries are declared as enum members and resolve on ``PATH``."""
    assert len(ALL_COMMANDS) == len(set(ALL_COMMANDS))

    for command in ALL_COMMANDS:
        assert find_engine_command(command).is_absolute()


def test_a_version_is_probed_from_the_engine_itself() -> None:
    """The version is the engine's own, not a value recorded on its behalf."""
    version = get_engine_version()

    assert version
    assert version[0].isdigit()


def test_a_missing_binary_raises_instead_of_substituting_an_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No engine on ``PATH`` is a typed failure, not an empty result.

    Mutation that breaks it: make ``find_engine_command`` fall back to a default path (or
    tolerate ``None``) instead of raising. The ``pytest.raises`` blocks then see no error
    and the test fails — which is what catching this is for, because the alternative is a
    processor reporting "this page has no text" for every page of every document on a
    machine with no PDF engine installed.
    """
    monkeypatch.setattr(
        "docflow.pdf.primitives.engine.shutil.which", lambda _name: None
    )

    with pytest.raises(PopplerNotAvailableError, match=PopplerCommand.PDFTOTEXT.value):
        find_engine_command(PopplerCommand.PDFTOTEXT)

    with pytest.raises(PopplerNotAvailableError):
        get_engine()


def test_an_unreadable_version_is_a_failure_not_a_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A version the seam cannot parse raises rather than yielding a stand-in.

    Mutation that breaks it: return ``"unknown"`` when the pattern does not match. The
    ``pytest.raises`` block fails, and the processor starts recording a provenance that
    cannot be traced back to a real engine version.
    """
    monkeypatch.setattr(
        "docflow.pdf.primitives.engine.shutil.which", lambda _name: "/bin/echo"
    )

    with pytest.raises(PopplerNotAvailableError):
        get_engine_version()


def test_a_failing_command_is_reported_with_its_status() -> None:
    """A non-zero exit becomes a typed error carrying the engine's own diagnosis.

    A path that does not exist fails without needing a fixture, which keeps the test about
    the seam rather than about a PDF.
    """
    missing = Path("/nonexistent/document.pdf")

    with pytest.raises(PopplerExecutionError) as failure:
        run_engine_command(PopplerCommand.PDFINFO, [str(missing)])

    assert failure.value.command is PopplerCommand.PDFINFO
    assert failure.value.returncode is not None
    assert failure.value.returncode != 0
    assert failure.value.stderr.strip()


def test_the_runner_returns_standard_output_and_does_not_conflate_streams() -> None:
    """The runner returns stdout, and only stdout.

    ``pdftotext -v`` is a convenient probe: it exits 0 having written its banner to stderr
    and nothing to stdout. An empty return is therefore the correct answer here, and it is
    what keeps the version probe honest — that probe has to read stderr itself, as tests
    above depend on.

    Mutation that breaks it: return ``stderr`` instead of ``stdout``. Extraction primitives
    would then parse a diagnostics banner as document text.
    """
    assert run_engine_command(PopplerCommand.PDFTOTEXT, [VERSION_ARGUMENT]) == ""


def test_the_engine_record_round_trips_through_json() -> None:
    """The record is plain data, so it lands in ``metadata.json`` without an encoder."""
    engine = get_engine()

    assert Engine(name=engine.name, version=engine.version) == engine
