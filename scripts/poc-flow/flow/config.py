"""Configuration: the runtime dials a document flow needs.

Every value here is a **policy dial**, never a domain noun: no invoice field, no
extraction verdict and no pipeline code appear below. They are the point of
reference for the flow and can be overridden by the caller.

The values are the `my_flow.md` starting points (§6.5) and the models from §4.1.
They are **uncalibrated**, exactly as the document states: thresholds are chosen
so every (field, tier) pair has a path to CONFIRMED, not because they were
measured.
"""

from __future__ import annotations

import dataclasses
from typing import Final

__all__: list[str] = [
    "DEFAULT_CONFIG",
    "SEVERITY",
    "SEVERITY_ORDER",
    "Config",
    "FieldDial",
]

# `too-many-instance-attributes`: `Config` is a frozen bundle of the dials a run
# reads; its shape is the contract, and splitting it into sub-objects would move
# the same names one frame away. The same reasoning `types.py::CallRecord`
# states for its boundary shape.
# pylint: disable=too-many-instance-attributes


@dataclasses.dataclass(frozen=True, slots=True)
class FieldDial:
    """The decision dials for one field severity, per tier.

    Attributes:
        t_native: The confirmation score floor for a native-text tier.
        t_ocr: The confirmation score floor for an OCR tier.
        margin: The minimum gap between the winner and the runner-up.
        strong: The strong-evidence families this severity requires at the gate.
            Empty means *no gate* (`my_flow.md` §6.5, media/baja).

    """

    t_native: int
    t_ocr: int
    margin: int
    strong: tuple[str, ...]


#: The four severities, ordered most critical first. A field maps to one of
#: these; the mapping itself lives in `fields.py` because it names domain
#: fields, and a config module stays free of them.
SEVERITY_ORDER: Final[tuple[str, ...]] = ("critica", "alta", "media", "baja")

#: Per-severity dials, `my_flow.md` §6.5.
SEVERITY: Final[dict[str, FieldDial]] = {
    "critica": FieldDial(5, 5, 2, ("DETERMINISTIC", "CROSS_MODAL")),
    "alta": FieldDial(3, 5, 2, ("DETERMINISTIC", "CROSS_MODAL", "NATIVE_ANCHOR")),
    "media": FieldDial(3, 4, 1, ()),
    "baja": FieldDial(3, 4, 1, ()),
}

#: The score floor below which a field escalates outright (`my_flow.md` §6.5).
#: TODO: [MVP] Uncalibrated, as the document states.
ESCALATE_FLOOR: Final[int] = 2

#: Maximum resolver → engine re-entries (`my_flow.md` §7).
MAX_LOOPS: Final[int] = 2

#: Which family points are worth. `my_flow.md` §6.2.
FAMILY_POINTS: Final[dict[str, int]] = {
    "DETERMINISTIC": 3,
    "DOCUMENT_CONTENT": 2,
    "CROSS_MODAL": 2,
    "SAME_MATERIAL": 1,
    "LAYOUT_HISTORY": 1,
    "SOFT_REFUTATION": -2,
    "CONTRARY_EVIDENCE": -3,
}

#: Families whose presence satisfies the strong-evidence gate. Layout history is
#: worth +1 and, by `my_flow.md` §9, is deliberately **not** strong evidence, so
#: it is absent from this set.
STRONG_FAMILIES: Final[frozenset[str]] = frozenset(
    {"DETERMINISTIC", "CROSS_MODAL", "NATIVE_ANCHOR"}
)

#: The hard-veto list is closed (`my_flow.md` §6.3). Every veto a validator can
#: produce must be one of these names, or the engine treats it as UNKNOWN.
VETO_CODES: Final[frozenset[str]] = frozenset(
    {
        "CUITS_CHECKSUM_INVALID",
        "CUITS_OWN_AS_EMISOR",
        "DATE_NONEXISTENT",
        "ARITHMETIC_INCONSISTENT",
    }
)

#: The local model for the text lane, as the caller names it to the adapter
#: (`my_flow.md` §4.1: primary extractor). The reviewer model differs, which is
#: what makes the A/B contrast meaningful.
TEXT_MODEL_A: Final[str] = "deepseek-r1:1.5b"
TEXT_MODEL_B: Final[str] = "gemma3"

#: The vision lane models (`my_flow.md` §4.1). ``None`` means *no local vision
#: model is configured*: the lane is then skipped rather than silently faked.
VISION_MODEL_A: Final[str] = "qwen2.5vl"
VISION_MODEL_B: Final[str] = "granite-vision:2b"

#: The frontier model the flow escalates to (`my_flow.md` §8).
FRONTIER_MODEL: Final[str] = "anthropic:claude-sonnet-4-6"

#: Routing dials (`my_flow.md` §2). A text layer with fewer characters than the
#: floor is not treated as content; a render is capped by the page's own
#: measured resolution because the adapter refuses to upscale.
MIN_CHARS: Final[int] = 40
RENDER_DPI: Final[int] = 150

#: The sharpness an image must reach to be read (`my_flow.md` §2, `illegible`).
#: Required with no default by the adapter, which is why it is a dial here.
LEGIBILITY_THRESHOLD: Final[float] = 100.0

#: The resolution OCR boxes are expressed at, and the row tolerance in **PDF
#: points at 72 DPI** — the legacy's own unit, scaled by the DPI the boxes use.
#: Both are OCR geometry, not policy: they decide what "one row" means.
OCR_DPI: Final[int] = 150
OCR_LINE_TOLERANCE_POINTS: Final[float] = 25.0

#: The OCR language hint. The installed engine does not expose a per-call
#: language setting and reports the request in its evidence instead.
OCR_LANG: Final[str] = "es"

#: TODO: [MVP] The per-(field, tier) reachability table of Anexo A is not yet
#: enforced. It belongs to a build-time test, not to a runtime dial.


@dataclasses.dataclass(frozen=True, slots=True)
class Config:
    """The dials one run uses, bundled so a caller can override them wholesale.

    Attributes:
        text_model_a: Primary text extractor (lane A).
        text_model_b: Text reviewer (lane B).
        vision_model_a: Primary vision extractor, or ``None`` to skip the lane.
        vision_model_b: Vision reviewer, or ``None`` to skip the lane.
        frontier_model: The model `resolve` escalates to.
        min_chars: The text-layer floor, `my_flow.md` §2.
        render_dpi: The render target, capped by the page's own resolution.
        legibility_threshold: The sharpness an image must reach to be read.
        ocr_dpi: The resolution OCR boxes are expressed at.
        ocr_line_tolerance_points: The row tolerance, in PDF points at 72 DPI.
        ocr_lang: The OCR language hint.
        escalate_floor: The score below which a field escalates outright.
        max_loops: Resolver → engine re-entry cap.
        severity: Per-severity dials; the defaults are :data:`SEVERITY`.
        family_points: Per-family points; the defaults are :data:`FAMILY_POINTS`.
        veto_codes: The closed veto list; the defaults are :data:`VETO_CODES`.

    """

    text_model_a: str = TEXT_MODEL_A
    text_model_b: str = TEXT_MODEL_B
    vision_model_a: str | None = VISION_MODEL_A
    vision_model_b: str | None = VISION_MODEL_B
    frontier_model: str = FRONTIER_MODEL
    min_chars: int = MIN_CHARS
    render_dpi: int = RENDER_DPI
    legibility_threshold: float = LEGIBILITY_THRESHOLD
    ocr_dpi: int = OCR_DPI
    ocr_line_tolerance_points: float = OCR_LINE_TOLERANCE_POINTS
    ocr_lang: str = OCR_LANG
    escalate_floor: int = ESCALATE_FLOOR
    max_loops: int = MAX_LOOPS
    severity: dict[str, FieldDial] = dataclasses.field(
        default_factory=lambda: dict(SEVERITY)
    )
    family_points: dict[str, int] = dataclasses.field(
        default_factory=lambda: dict(FAMILY_POINTS)
    )
    veto_codes: frozenset[str] = VETO_CODES


#: The default configuration every entry point builds from.
DEFAULT_CONFIG: Final[Config] = Config()
