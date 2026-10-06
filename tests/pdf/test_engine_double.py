"""The Poppler double's compliance with the engine-double convention (``PDF-14``).

The suite never reaches Poppler: the double is injected at the ``subprocess.run`` call
inside ``docflow.pdf.primitives`` and hands back the subprocess's own shape — files plus an
exit code and stderr (`README.md` §9.7). Two checks keep it honest:

* the **static** one, shared with the other processors, which reads the seam and requires
  the double to model every engine attribute the seam reaches;
* the **native-shape** one, which insists the double answers with the subprocess's types and
  never with our translated ones — a fake that returned a ``PDFPageResult`` would delete the
  translation layer it exists to exercise.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

from tests.fakes.engines.convention import missing_from_double
from tests.fakes.engines.fake_poppler import FakePoppler

#: The seam: the one module that reaches the engine, so the one whose calls the double
#: must model.
SEAM = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "docflow"
    / "pdf"
    / "primitives"
    / "__init__.py"
)


def test_the_double_models_every_engine_call_the_seam_can_make() -> None:
    """A seam that grows a call the double does not know turns this red, not silently green."""
    assert missing_from_double(SEAM, "subprocess", FakePoppler()) == set()


def test_the_seam_reaches_the_engine_module_and_not_a_python_engine() -> None:
    """The injection point is the subprocess call: Poppler is a binary, not an import."""
    source = SEAM.read_text(encoding="utf-8")

    assert "import subprocess" in source
    assert "subprocess.run(" in source
    for library in ("fitz", "pypdfium2", "pdf2image", "pdfminer"):
        assert f"import {library}" not in source


def test_the_double_answers_with_the_subprocess_shape_not_with_our_types() -> None:
    """What the double returns is what the CLI returns: no value, an exit code and stderr."""
    fake = FakePoppler()

    completed = fake.run(["pdfinfo", "-v"])

    assert isinstance(completed, subprocess.CompletedProcess)
    assert completed.returncode == 0
    assert completed.stdout
    assert not hasattr(fake, "PDFPageResult")
    assert not hasattr(fake, "PDFResult")


def test_the_double_does_not_import_our_contract_types() -> None:
    """A double that models our types is drifting into the layer it must exercise."""
    double_source = (
        Path(__file__).resolve().parents[2]
        / "tests"
        / "fakes"
        / "engines"
        / "fake_poppler.py"
    ).read_text(encoding="utf-8")
    imported = {
        alias.name
        for node in ast.walk(ast.parse(double_source))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(ast.parse(double_source))
        if isinstance(node, ast.ImportFrom)
    }

    assert not [module for module in imported if module.startswith("docflow")]


def test_an_unmodelled_call_is_reported_instead_of_answered() -> None:
    """The double never invents an answer for a call it does not know."""
    fake = FakePoppler()

    completed = fake.run(["pdftohtml", "file.pdf"])

    assert completed.returncode == 99
    assert fake.unhandled == [["pdftohtml", "file.pdf"]]
