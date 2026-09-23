"""Tests for the OCR engine seam (``OCR-02``).

Three properties are load-bearing, and each is guarded by a test that fails when it is broken:

* the seam is **lazy** - importing it, and even probing it, must load no engine, because
  ``GEN-01`` asserts a clean interpreter can import every sub-package;
* the engine is **explicit** - an unavailable engine raises a typed failure, and *nothing* is
  used in its place, because there is no alternative to substitute;
* the version is **recorded** - ``metadata.json`` carries a concrete ``engine_version``, which
  is what makes the determinism posture auditable.

The absent-engine tests **simulate** absence rather than skipping when the engine is present: a
guard that only runs on a machine without Docling proves nothing on a machine that has it, and
this environment has it. :func:`with_engine_absent` is a context manager rather than a fixture
so each test states where the absence begins and ends.
"""

from __future__ import annotations

import contextlib
import importlib
import subprocess
import sys
from collections.abc import Iterator
from unittest.mock import patch

import pytest

from docflow.ocr.primitives import engine as seam
from docflow.ocr.primitives.engine import (
    DOCLING_CONVERTER_ATTRIBUTE,
    DOCLING_CONVERTER_MODULE_NAME,
    DOCLING_MODULE_NAME,
    ENGINE_NAME,
    OCREngineNotAvailableError,
    converter_module,
    docling_module,
    engine_provenance,
    get_engine_version,
    is_engine_available,
    loaded_engines,
)

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[3]

CLEAN_INTERPRETER_ENV = {
    "PYTHONPATH": str(REPO_ROOT / "src"),
}


@contextlib.contextmanager
def with_engine_absent() -> Iterator[None]:
    """Make the engine unimportable for the duration of the block.

    Patches ``importlib.import_module`` rather than ``find_spec`` alone, so a test that calls a
    primitive directly sees the same absence the probe does.
    """
    real_import = importlib.import_module
    real_find_spec = importlib.util.find_spec

    def refuse(name: str, package: str | None = None):
        if name == DOCLING_MODULE_NAME or name.startswith(f"{DOCLING_MODULE_NAME}."):
            raise ImportError(f"no module named {name!r}")
        return real_import(name, package)

    with (
        patch("importlib.import_module", side_effect=refuse),
        patch(
            "importlib.util.find_spec",
            side_effect=lambda name, *positional, **keywords: (
                None
                if name == DOCLING_MODULE_NAME
                else real_find_spec(name, *positional, **keywords)
            ),
        ),
    ):
        yield


# ======================================================================================
# The seam is lazy
# ======================================================================================


def test_importing_the_seam_loads_no_engine() -> None:
    """``import docflow.ocr.primitives.engine`` must not pull Docling in.

    Run in a fresh interpreter, because the in-process answer would be a fact about what pytest
    had already imported rather than about the module under test.
    """
    code = (
        "import sys\n"
        "import docflow.ocr, docflow.ocr.primitives, docflow.ocr.primitives.engine\n"
        "print('docling' in sys.modules)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=CLEAN_INTERPRETER_ENV,
        cwd=REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "False", "importing the seam pulled Docling in"


def test_probing_for_the_engine_does_not_load_it() -> None:
    """``is_engine_available`` answers without paying Docling's import cost.

    A caller asking "is OCR possible here?" should not load the whole model stack to find out, and
    should not have the answer depend on the side effects of doing so.
    """
    assert not loaded_engines()

    available = is_engine_available()

    assert available is True
    assert not loaded_engines(), "probing loaded the engine"


def test_asking_for_the_version_loads_only_the_package() -> None:
    """The version comes from the distribution, not from importing the conversion stack."""
    assert not loaded_engines()

    version = get_engine_version()

    assert version
    assert DOCLING_CONVERTER_MODULE_NAME not in sys.modules


# ======================================================================================
# The engine is explicit, and nothing substitutes for it
# ======================================================================================


def test_a_missing_engine_raises_instead_of_substituting_something() -> None:
    """An absent engine is a typed failure, never an empty extraction.

    This is the failure the whole seam exists for. A processor that returned "no text found"
    when Docling was missing would put "this page has no text" and "this deployment has no OCR
    engine" in the same result, and a caller would reuse the second as if it were the first.
    """
    with with_engine_absent(), pytest.raises(OCREngineNotAvailableError) as raised:
        docling_module()

    assert raised.value.library == DOCLING_MODULE_NAME
    assert "no alternative engine" in str(raised.value)


def test_a_missing_engine_is_reported_by_the_probe_rather_than_raising() -> None:
    """The probe answers a question; it does not throw at the caller asking it."""
    with with_engine_absent():
        assert is_engine_available() is False


def test_a_missing_conversion_api_raises_naming_the_submodule() -> None:
    """A package that is present but has moved its API is reported as what is actually missing.

    Docling does not expose ``document_converter`` as an attribute of the package, so a caller
    that assumed it did would get a bare ``AttributeError`` naming neither Docling nor the seam.
    This asserts the seam reports the submodule it could not reach.
    """
    real_import = importlib.import_module

    def refuse(name: str, package: str | None = None):
        if name == DOCLING_CONVERTER_MODULE_NAME:
            raise ImportError(f"no module named {name!r}")
        return real_import(name, package)

    with (
        patch("importlib.import_module", side_effect=refuse),
        pytest.raises(OCREngineNotAvailableError) as raised,
    ):
        converter_module()

    assert raised.value.library == DOCLING_CONVERTER_MODULE_NAME


def test_the_engine_is_never_exposed_as_a_choice() -> None:
    """There is no engine enum, no engine parameter and no ``AUTO`` member.

    The image processor needed a choice because its two engines are interchangeable; this one has
    a single engine and the plan puts a selectable engine out of bounds. A test rather than a
    comment, because the natural refactor - copying the image seam's shape - would add one.
    """
    exported = set(seam.__all__)
    assert not [name for name in exported if "Choice" in name or name == "AUTO"]
    for name in ("EngineChoice", "AUTO", "engine_choice"):
        assert not hasattr(seam, name), f"the seam exposes {name}"


# ======================================================================================
# The version is recorded
# ======================================================================================


def test_the_engine_version_is_concrete_and_never_blank() -> None:
    """``metadata.json`` needs a real version, which is what makes a re-run comparable."""
    version = get_engine_version()

    assert version
    assert version != " "
    assert version == importlib.metadata.version(DOCLING_MODULE_NAME)


def test_the_provenance_names_the_engine_as_the_string_the_metadata_records() -> None:
    """``engine`` is always ``docling``, and both keys are present."""
    provenance = engine_provenance()

    assert set(provenance) == {"engine", "engine_version"}
    assert provenance["engine"] == ENGINE_NAME == "docling"
    assert provenance["engine_version"]


def test_an_engine_that_reports_no_version_says_so_rather_than_being_blank() -> None:
    """A library that will not say its version is recorded as ``UNKNOWN``, not as an empty string.

    A blank reads as "we did not bother to record it"; ``UNKNOWN`` reads as "we looked and there
    was nothing to find", which is the honest answer and the one a re-run comparison can act on.
    """
    with patch(
        "importlib.metadata.version",
        side_effect=importlib.metadata.PackageNotFoundError(DOCLING_MODULE_NAME),
    ):
        assert get_engine_version() == seam.DOCLING_VERSION_UNKNOWN

    assert seam.DOCLING_VERSION_UNKNOWN != ""


# ======================================================================================
# The API path the seam publishes is real
# ======================================================================================


def test_the_declared_conversion_module_and_class_exist() -> None:
    """The path the seam names is asserted against the installed engine.

    Without this the constants could name a module that moved in an upgrade, and ``OCR-03`` would
    discover it while trying to configure a pipeline rather than here.
    """
    module = converter_module()

    assert module.__name__ == DOCLING_CONVERTER_MODULE_NAME
    assert hasattr(module, DOCLING_CONVERTER_ATTRIBUTE)


def test_the_package_itself_does_not_expose_the_conversion_api() -> None:
    """The reason the seam names a *submodule* rather than an attribute.

    Run in a fresh interpreter, and that is not incidental. Docling imports its submodules lazily,
    so the package has no ``document_converter`` attribute *until something imports the submodule*
    - and importing it sets the attribute on the parent package as a side effect of Python's
    import machinery. The first version of this test ran in-process after another test had done
    that, so it asserted the opposite of what it was written to check and failed intermittently
    depending on test order. The claim is about a *fresh* interpreter, so it is measured in one.
    """
    code = (
        "import sys\n"
        "sys.path.insert(0, 'src')\n"
        "import docling\n"
        "has = hasattr(docling, 'document_converter')\n"
        "print(docling.document_converter if has else 'absent')\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "absent"


def test_loaded_engines_reports_what_is_actually_imported() -> None:
    """The probe the laziness tests rely on must be honest about its own answer.

    Asserted in the direction that is true in *any* interpreter, rather than as "the list is
    empty": whether Docling is already in ``sys.modules`` depends on what ran before this test,
    and a test that assumed emptiness would be a fact about pytest rather than about the probe.
    What the probe must do is report the truth about the current process.
    """
    before = loaded_engines()
    assert before == [name for name in before if name == DOCLING_MODULE_NAME]

    docling_module()

    assert DOCLING_MODULE_NAME in loaded_engines()
