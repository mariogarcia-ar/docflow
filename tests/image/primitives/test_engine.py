"""Tests for the image engine seam (``IMG-02``).

Two properties are load-bearing and each is guarded by a test that fails when the property is
broken:

* the seam is **lazy** - importing it, and even probing it, must load no engine, because
  ``GEN-01`` asserts a clean interpreter can import every sub-package;
* the engine is **explicit** - an unavailable engine raises a typed failure and the other engine
  is *not* used in its place.

The absent-engine tests **simulate** absence instead of skipping when an engine is installed: a
guard that only runs on a machine without OpenCV proves nothing on a machine that has it, and
this environment has both engines. :func:`with_engines_absent` is a context manager rather than
a fixture so each test states where the absence begins and ends, and a reader can see that the
seam is only ever asked to work with no engine behind it.
"""

from __future__ import annotations

import contextlib
import importlib
import subprocess
import sys
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from docflow.image.primitives.engine import (
    ARRAY_LIBRARY_NAME,
    OPENCV_ENGINE_NAME,
    PILLOW_ENGINE_NAME,
    EngineChoice,
    ImageEngineError,
    ImageEngineExecutionError,
    ImageEngineNotAvailableError,
    array_library_version,
    array_module,
    engine_module,
    engine_version,
    get_engine,
    get_provenance,
    is_engine_available,
    loaded_engines,
)

WORKSPACE = __file__.split("/tests/", maxsplit=1)[0]


@contextlib.contextmanager
def with_engines_absent() -> Iterator[None]:
    """Run the block as if no image library were installed.

    The seam's only route to a library is ``importlib.import_module``, so refusing that one call
    simulates a machine without an engine while leaving the rest of the module under test intact.

    Yields:
        Nothing; the block runs with every engine import failing.
    """

    def refuse(name: str, package: str | None = None) -> None:
        raise ImportError(f"no module named {name!r}")

    with patch.object(importlib, "import_module", refuse):
        yield


def test_the_engine_choices_are_named_and_have_no_automatic_member() -> None:
    """The caller names an engine; there is no "choose one for me" member."""
    assert [choice.value for choice in EngineChoice] == [
        OPENCV_ENGINE_NAME,
        PILLOW_ENGINE_NAME,
    ]
    assert not [choice for choice in EngineChoice if "AUTO" in choice.name]


def test_importing_the_seam_loads_no_engine() -> None:
    """The seam must be cheap and side-effect free to import."""
    assert loaded_engines() == []


def test_probing_for_an_engine_does_not_import_it() -> None:
    """Asking whether an engine exists must not pay for loading it."""
    assert is_engine_available(EngineChoice.OPENCV) in (True, False)
    assert loaded_engines() == []


def test_a_clean_interpreter_imports_the_seam_without_an_engine() -> None:
    """The strongest form of the laziness guard: a fresh process, engines absent.

    A module-level ``import cv2`` or ``from PIL import Image`` anywhere in the package shows up
    here as a leaked module, which is why this runs in a subprocess rather than in-process where
    an earlier test may already have loaded something.
    """
    program = (
        "import sys;"
        f"sys.path.insert(0, {WORKSPACE + '/src'!r});"
        "import docflow.image.primitives.engine as seam;"
        "leaked = [m for m in ('cv2', 'PIL') if m in sys.modules];"
        "print(leaked)"
    )
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


def test_a_missing_engine_raises_instead_of_substituting_the_other() -> None:
    """The core rule: no engine is silently swapped for another.

    Exact in both directions - OpenCV's failure names OpenCV and mentions only ``cv2``; Pillow's
    failure names Pillow and mentions only ``PIL``. An error naming the other library, or a
    returned module belonging to the other engine, would be the substitution the plan forbids.
    """
    with with_engines_absent(), pytest.raises(ImageEngineNotAvailableError) as raised:
        engine_module(EngineChoice.OPENCV)
    assert raised.value.engine is EngineChoice.OPENCV
    assert raised.value.library == "cv2"
    assert "PIL" not in str(raised.value)

    with (
        with_engines_absent(),
        pytest.raises(ImageEngineNotAvailableError) as pillow_raised,
    ):
        engine_module(EngineChoice.PILLOW)
    assert pillow_raised.value.engine is EngineChoice.PILLOW
    assert pillow_raised.value.library == "PIL"
    assert "cv2" not in str(pillow_raised.value)


def test_a_missing_engine_never_returns_a_module() -> None:
    """Refusing to substitute means refusing to answer, not answering with the other one."""
    with with_engines_absent():
        for choice in EngineChoice:
            with pytest.raises(ImageEngineNotAvailableError):
                engine_module(choice)


def test_a_missing_engine_failure_is_a_typed_error_not_a_bare_import_error() -> None:
    """Callers classify this; an untyped ImportError would defeat that."""
    with with_engines_absent(), pytest.raises(ImageEngineError):
        engine_module(EngineChoice.OPENCV)


def test_the_missing_engine_message_names_a_remedy() -> None:
    """The message has to say what to do, per the plan's failure contract."""
    with with_engines_absent(), pytest.raises(ImageEngineNotAvailableError) as raised:
        engine_module(EngineChoice.OPENCV)
    message = str(raised.value)
    assert "install" in message
    assert "no engine is substituted automatically" in message


def test_a_missing_array_library_raises_and_names_no_engine() -> None:
    """The array library is not an engine; its failure says so."""
    with with_engines_absent(), pytest.raises(ImageEngineNotAvailableError) as raised:
        array_module()
    assert raised.value.engine is None
    assert raised.value.library == ARRAY_LIBRARY_NAME
    assert "array library" in str(raised.value)


def test_a_version_lookup_propagates_the_absent_engine_failure() -> None:
    """Provenance depends on the engine, so it fails the same typed way."""
    with with_engines_absent():
        with pytest.raises(ImageEngineNotAvailableError):
            engine_version(EngineChoice.OPENCV)
        with pytest.raises(ImageEngineNotAvailableError):
            get_engine(EngineChoice.PILLOW)
        with pytest.raises(ImageEngineNotAvailableError):
            get_provenance(EngineChoice.OPENCV)


def test_an_installed_engine_reports_a_real_version() -> None:
    """A version is read, never fabricated - a blank one is an error, not a default."""
    installed = [choice for choice in EngineChoice if is_engine_available(choice)]
    assert installed, "this environment is expected to have at least one engine"

    for choice in installed:
        version = engine_version(choice)
        assert version != ""
        assert version[0].isdigit()


def test_a_library_that_reports_no_version_is_an_error_not_a_blank_string() -> None:
    """The "no silent stand-in" rule applied to a version field."""
    module = engine_module(EngineChoice.OPENCV)

    with (
        pytest.raises(ImageEngineExecutionError) as raised,
        patch.object(module, "__version__", "", create=True),
    ):
        engine_version(EngineChoice.OPENCV)
    assert "no __version__" in raised.value.detail


def test_get_engine_and_provenance_agree_with_the_version_lookup() -> None:
    """The provenance record is the same reading, not a second independent one."""
    engine = get_engine(EngineChoice.OPENCV)
    assert engine.name == OPENCV_ENGINE_NAME
    assert engine.version == engine_version(EngineChoice.OPENCV)

    provenance = get_provenance(EngineChoice.OPENCV)
    assert provenance.engine == engine
    assert provenance.array_library.name == ARRAY_LIBRARY_NAME
    assert provenance.array_library.version == array_library_version()


def test_provenance_never_carries_a_blank_version() -> None:
    """Guards the rule that a version is read, or the call fails."""
    provenance = get_provenance(EngineChoice.OPENCV)
    assert provenance.engine.version.strip() != ""
    assert provenance.array_library.version.strip() != ""


def test_the_two_engines_are_distinguishable_in_provenance() -> None:
    """A record has to say which engine produced the pixels."""
    opencv = get_engine(EngineChoice.OPENCV)
    pillow = get_engine(EngineChoice.PILLOW)
    assert opencv.name != pillow.name
    assert opencv.name == OPENCV_ENGINE_NAME
    assert pillow.name == PILLOW_ENGINE_NAME


def test_an_execution_failure_carries_its_operation_engine_and_detail() -> None:
    """The typed execution error keeps the engine's own words."""
    failure = ImageEngineExecutionError(
        "read the engine version", EngineChoice.OPENCV, "reports no __version__"
    )
    assert failure.operation == "read the engine version"
    assert failure.engine is EngineChoice.OPENCV
    assert failure.detail == "reports no __version__"
    assert "read the engine version" in str(failure)
    assert "opencv" in str(failure)
    assert "reports no __version__" in str(failure)


def test_an_execution_failure_with_no_detail_still_reads_as_a_sentence() -> None:
    """An empty detail must not leave a dangling colon."""
    failure = ImageEngineExecutionError("decode", EngineChoice.PILLOW, "")
    assert str(failure) == "decode failed under the pillow engine"


def test_the_typed_failures_share_one_base() -> None:
    """One base lets a caller catch the whole seam without naming each type."""
    assert issubclass(ImageEngineNotAvailableError, ImageEngineError)
    assert issubclass(ImageEngineExecutionError, ImageEngineError)
