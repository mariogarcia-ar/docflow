"""The shape check that keeps an engine double honest.

A double that no longer models the surface its seam uses is worse than no double: the suite
stays green while the translation breaks in production (`README.md` §9.7, `GEN-22`). This
module turns that drift into a failing assertion — read the seam statically, collect every
attribute it reaches on the engine, and compare that set with what the double provides.

The measure is deliberately blunt: it does not prove the double's *behaviour*, it proves the
double still knows about every call the seam can make, including one on a branch no test
walks. Each engine-double task calls it against its own seam (`PDF-14`, `IMG-15`, `OCR-14`,
`LLM-03`).
"""

from __future__ import annotations

import ast
from pathlib import Path


def engine_attributes_used_by(seam_path: Path, engine_name: str) -> set[str]:
    """Return the engine attributes a seam module reaches, e.g. ``{"imread", "imwrite"}``.

    The seam is read statically rather than executed, so a call on a branch no test walks is
    still counted: the double is supposed to model the engine the seam *can* call.

    Args:
        seam_path: Path to the module that owns the engine call.
        engine_name: The name the engine is bound to in that module, e.g. ``"cv2"``.

    Returns:
        The attribute names reached on that engine, dunder names excluded.
    """
    used: set[str] = set()
    tree = ast.parse(seam_path.read_text(encoding="utf-8"), filename=str(seam_path))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
            continue
        if node.value.id == engine_name and not node.attr.startswith("__"):
            used.add(node.attr)

    return used


def double_attributes_provided_by(double: object) -> set[str]:
    """Return the public attributes a double exposes.

    Args:
        double: The in-memory double under test.

    Returns:
        Every non-dunder attribute name ``dir`` reports for it.
    """
    return {name for name in dir(double) if not name.startswith("_")}


def missing_from_double(seam_path: Path, engine_name: str, double: object) -> set[str]:
    """Return the engine attributes the seam uses that the double does not provide.

    Args:
        seam_path: Path to the module that owns the engine call.
        engine_name: The name the engine is bound to in that module.
        double: The in-memory double that stands in for that engine.

    Returns:
        The missing attribute names; an empty set means the double still models the seam.
    """
    used = engine_attributes_used_by(seam_path, engine_name)
    provided = double_attributes_provided_by(double)
    return used - provided
