"""Build the OCR fixture `subplan-procesador-ocr.md` §6 names.

The plan asks for `fixtures/ocr_prepared_text_and_table.png`: an image that is *already prepared*
and contains a heading, a paragraph and a table. Rather than hand-draw one, this takes a real
invoice from the committed corpus and prepares it with the *image* processor — which is what
"prepared" means in this project, and what the documented flow does (`PDF` → `image` → `ocr`).

**The preparation is grayscale only, and that was measured rather than assumed.** The image
processor's OCR-optimized variant ends with a binarization, and feeding that variant to Docling
collapses the table from 5 rows by 4 columns to **1 row by 1 column**: the table-structure model
needs the luminance detail a threshold throws away. Feeding the plain normalized colour image
loses the table entirely (0 detected). Grayscale keeps it at 5x4 with the cell text intact.

That is worth recording here rather than in a comment nobody reads, because it is an integration
fact between two processors: `ocr_ready.png` is the right input for a character-recognition engine
and the wrong one for Docling's table model. `subplan-procesador-ocr.md` §2 calls Docling the only
OCR engine; this file is where the two designs were found to disagree.

`OCR-12` owns the fixture set; this file exists because `OCR-04`'s acceptance criterion names the
fixture and the assertion cannot be made without it.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from docflow.image.primitives.engine import EngineChoice  # noqa: E402
from docflow.image.primitives.load import load_image, save_image  # noqa: E402
from docflow.image.primitives.transform import convert_to_grayscale  # noqa: E402

SOURCE = (
    ROOT
    / "tests"
    / "fixtures"
    / "expected-extraction"
    / "9e0fd65b-7db2-40a1-9959-ab13e7b030cd.jpg"
)
TARGET = ROOT / "tests" / "fixtures" / "ocr" / "ocr_prepared_text_and_table.png"


def main() -> int:
    """Prepare the source image and write the fixture.

    Returns:
        The process exit code.
    """
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # `save_image` refuses an occupied destination — a real safety property, since the file it
    # would otherwise replace may be the source. A fixture builder must be re-runnable, so it
    # removes its own previous output explicitly rather than asking the primitive to relax the
    # rule that protects it.
    TARGET.unlink(missing_ok=True)

    pixels = load_image(SOURCE, EngineChoice.OPENCV)
    prepared = convert_to_grayscale(pixels, EngineChoice.OPENCV)
    save_image(prepared, TARGET, EngineChoice.OPENCV)

    print(f"wrote {TARGET.relative_to(ROOT)} ({TARGET.stat().st_size} bytes)")
    print(
        f"source: {SOURCE.name} {pixels.shape} -> prepared {prepared.shape} (grayscale)"
    )
    print("transformations: convert_to_grayscale")
    print()
    print(
        "Why not `prepare_image_for_ocr`: its trailing binarization collapses the table to"
    )
    print("1x1 cells in Docling's table model. Measured, and pinned by a test in")
    print("tests/ocr/primitives/test_extraction.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
