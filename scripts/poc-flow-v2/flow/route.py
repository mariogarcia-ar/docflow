"""The routing decision, as a value: what to do about a document, and why.

This is the pure half of `my_flow.md` §2. It reads measurements and returns a
:class:`Decision`; it **executes nothing** and imports no adapter, exactly as
`scripts/poc/decide.py` does — that is what keeps the rule testable without
paying for the route it chooses.

The rules (`my_flow.md` §2, in order):

1. A shape that could not be measured goes aside: *we could not look* is not *it
   needs reading*, and the pixel route is the expensive one.
2. A blank page goes aside with its own reason: it holds neither text nor an
   image, so both remaining routes would read nothing.
3. Legibility gates the **pixel** route only, and before anything is read. A
   text page is read from its text, where legibility is not a property of
   anything; refusing it there would discard a good extraction because its
   *image* is blurred.
4. Text when the shape says text, else pixels. `mixed` is text: the layer is
   already there.

The routes are exactly the `my_flow.md` §1 branches: ``text`` (native),
``pixels`` (OCR) and ``aside`` (escalate/degrade).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Final

__all__: list[str] = [
    "ASIDE",
    "PIXELS",
    "TEXT",
    "Decision",
    "decide",
]

#: The document's text layer is readable: read it.
TEXT: Final[str] = "text"

#: No text layer, but pixels: render and hand them to OCR.
PIXELS: Final[str] = "pixels"

#: Stop and record why. Illegible, blank and unmeasurable all land here, each
#: with its own reason.
ASIDE: Final[str] = "aside"

#: The shapes K2 reports that carry a text layer. Stated here rather than read
#: from an adapter, so this module stays adapter-free at import time; the pairing
#: with the adapter's own vocabulary is the caller's responsibility.
TEXT_SHAPES: Final[frozenset[str]] = frozenset({"text", "mixed"})


@dataclasses.dataclass(frozen=True, slots=True)
class Decision:
    """What to do about one page, and the evidence it was decided from.

    Attributes:
        route: One of :data:`TEXT`, :data:`PIXELS` or :data:`ASIDE`.
        reason: Why, in words a console can print. Never empty.
        measured: The numbers the decision read, recorded so a reader can check
            the rule against the evidence instead of trusting the verdict.

    """

    route: str
    reason: str
    measured: Mapping[str, object]

    @property
    def proceeds(self) -> bool:
        """Whether this route leads to text."""
        return self.route != ASIDE


def decide(  # pylint: disable=too-many-arguments
    *,
    shape: str,
    legibility: str = "",
    sharpness: float | None = None,
    threshold: float | None = None,
    characters: int | None = None,
    measured_dpi: int | None = None,
    min_chars: int | None = None,
    text_shapes: frozenset[str] = TEXT_SHAPES,
) -> Decision:
    """Choose a route for one page, from what was measured about it.

    Pure: every argument is a number or a word some earlier call produced.

    Args:
        shape: What `classify` measured: ``text``, ``mixed``, ``image``,
            ``blank``, or ``""`` when it was refused.
        legibility: The legibility verdict: ``ok``, ``illegible``, or a reason
            code. Empty when nothing measured it.
        sharpness: The measured sharpness, or ``None``.
        threshold: The threshold it was compared against, or ``None``.
        characters: How many characters the text layer holds, or ``None``.
        measured_dpi: The page's own resolution, or ``None``.
        min_chars: The character floor, or ``None``. Informational here.
        text_shapes: The shapes whose content is the text layer, injected rather
            than owned so the adapter's vocabulary keeps its single owner.

    Returns:
        The decision, carrying the evidence it was made from.

    """
    measured: dict[str, object] = {
        "shape": shape,
        "legibility": legibility,
        "sharpness": sharpness,
        "threshold": threshold,
        "characters": characters,
        "measured_dpi": measured_dpi,
        "min_chars": min_chars,
    }

    if not shape:
        return Decision(
            ASIDE,
            "the page's shape could not be measured, so no route was chosen",
            measured,
        )

    if shape == "blank":
        return Decision(
            ASIDE,
            "the page holds neither usable text nor an image",
            measured,
        )

    needs_pixels = shape not in text_shapes
    if needs_pixels and legibility == "illegible":
        detail = (
            f"sharpness {sharpness} below the threshold {threshold}"
            if sharpness is not None and threshold is not None
            else "the legibility reading came back illegible"
        )
        return Decision(
            ASIDE,
            f"the page's pixels cannot be read ({detail}); reading them would "
            "produce text nothing supports",
            measured,
        )

    if needs_pixels and legibility not in {"", "ok"}:
        return Decision(
            ASIDE,
            f"the page's pixels could not be measured ({legibility})",
            measured,
        )

    if not needs_pixels:
        return Decision(
            TEXT,
            f"shape {shape!r} carries a text layer; reading it needs no pixels",
            measured,
        )

    return Decision(
        PIXELS,
        f"shape {shape!r} has no text layer; the pixels must be read",
        measured,
    )
