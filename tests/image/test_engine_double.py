"""The OpenCV double's compliance with the engine-double convention (``IMG-15``).

The suite never reaches OpenCV: the double is installed at the module attribute
``docflow.image.primitives.cv2`` and hands back the library's own shape — decoded arrays and raw
readings (`README.md` §9.7). Three checks keep it honest:

* the **static** one, shared with the other processors, which reads the seam and requires the
  double to model every engine attribute the seam reaches;
* the **native-shape** one, which insists the double answers with arrays and booleans and never
  with our translated types — a fake that returned an ``ImageResult`` would delete the
  translation layer it exists to exercise;
* the **decode-failure** one, which pins the engine's silent habit: an undecodable file is
  ``None``, not an exception, so the seam's own check is what turns it into a typed failure.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.fakes.engines.convention import missing_from_double
from tests.fakes.engines.fake_opencv import FakeImage, FakeOpenCV
from tests.image.samples import COLOR_LAYOUT, CORRUPT

#: The seam: the one module that reaches the engine, so the one whose calls the double must
#: model.
SEAM = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "docflow"
    / "image"
    / "primitives"
    / "__init__.py"
)

#: The double itself, for the checks that read it rather than run it.
DOUBLE = Path(__file__).resolve().parents[1] / "fakes" / "engines" / "fake_opencv.py"


def test_the_double_models_every_engine_call_the_seam_can_make() -> None:
    """A seam that grows a call the double does not know turns this red, not silently green."""
    assert missing_from_double(SEAM, "cv2", FakeOpenCV()) == set()


def test_the_seam_resolves_the_engine_at_call_time_and_not_at_import() -> None:
    """The injection point is the module attribute: a module-level ``import cv2`` would break it."""
    source = SEAM.read_text(encoding="utf-8")

    assert "importlib.import_module(ENGINE_MODULE)" in source
    assert "import cv2" not in source
    assert 'ENGINE_MODULE: Final[str] = "cv2"' in source


def test_the_seam_reaches_no_other_array_or_engine_library() -> None:
    """The seam is OpenCV's, plus the standard library: no numpy, no Pillow, no second path."""
    source = SEAM.read_text(encoding="utf-8")

    for library in ("numpy", "PIL", "skimage", "scipy", "torch"):
        assert f"import {library}" not in source


def test_the_double_answers_with_the_engine_shape_not_with_our_types(
    tmp_path: Path,
) -> None:
    """What the double returns is what the library returns: an array, or a boolean."""
    fake = FakeOpenCV()

    decoded = fake.imread(str(COLOR_LAYOUT), fake.IMREAD_COLOR)
    written = fake.imwrite(
        str(tmp_path / "artifact.png"), decoded or FakeImage([1.0], 1, 1)
    )

    assert isinstance(decoded, FakeImage)
    assert written is True
    assert not hasattr(fake, "ImageResult")
    assert not hasattr(fake, "ImageMetrics")


def test_the_double_does_not_import_our_contract_types() -> None:
    """A double that models our types is drifting into the layer it must exercise."""
    imported = {
        alias.name
        for node in ast.walk(ast.parse(DOUBLE.read_text(encoding="utf-8")))
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(ast.parse(DOUBLE.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
    }

    assert not [module for module in imported if module.startswith("docflow")]


def test_an_undecodable_file_is_none_the_way_the_engine_reports_it() -> None:
    """The engine does not raise for a file it cannot read; the seam is what types that."""
    fake = FakeOpenCV()

    assert fake.imread(str(CORRUPT), fake.IMREAD_COLOR) is None
    assert fake.calls == ["imread"]
