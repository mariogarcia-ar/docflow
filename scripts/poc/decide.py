"""The routing decision, as a value — what to do about a measurement, and why.

`my_kernel_flow.md` §6 lists the steps a document goes through, and the two
behavioural ones are *"determine whether it is predominantly text or image"* and
*"validate by type"*. The drivers each did that **while doing the work**: `batch.py`
measured a shape and immediately called `layout_text` in the same `if`, and its
legibility gate sat beside the OCR call it was meant to prevent. Three consequences,
all of them measured:

- **There was nowhere to assert the decision.** "Given this measurement, the right
  route is X" could only be checked by paying for the route: the OCR on a page K3 had
  already called illegible cost **9.2 s** and returned nothing.
- **The rules were duplicated.** `batch_pdf.py` routes through `pdf.route_page` and
  says in a comment that a second `if shape in TEXT_SHAPES` would be *"a copy of a
  decision `route_page` already made"*. `batch.py` had exactly that copy.
- **A duplicated rule is what a mutation survives.** `batch.py` carried its own
  `RENDER_DPI = 200` — a second copy of a number the registry owns — and it asked a
  120-DPI page for a 200-DPI render, which returns **no image at all** for the one
  page being rendered *because* it has no text.

So this module is the decision on its own: it reads measurements and returns a
:class:`Decision`. It **executes nothing** — no adapter is imported here, and the
import list below is the proof. The caller performs the route, which is what keeps
the rule testable without paying for the work.

Why the three outcomes are two
------------------------------

`prd.md` FR-15 gives Diagnosis three outcomes: *route to conversion*, *adapt then
route to OCR*, and *route aside with a reason*. The middle one **is not
implementable, and that is a kernel-level fact rather than a missing feature**:

    rescale 120 -> 150 DPI : insufficient_effective_resolution
    rescale 120 -> 300 DPI : insufficient_effective_resolution

`RasterEngine.rescale` never enlarges — `kernel-cli.md` §14 lists "no upscale
reported as satisfied" as **Never**, and `kernels/image.py` says so in its own
header. A page that rendered at its own measured ceiling therefore has nothing to
adapt *to*: enlarging is refused, and shrinking cannot improve legibility. The
middle branch would be code that can never run, so this module does not carry it —
and says why, rather than leaving a reader to wonder whether it was forgotten.

What it does carry is the distinction FR-15 cares about underneath: *this is unusable*
is not the same answer as *this was never looked at*, and neither is the same as *this
has no content at all*. Every route below is one of those.

That is why the text/pixels boundary is **passed in** rather than written here.
Which shapes carry a text layer is a fact about K2's measurement vocabulary, and
`pdf.TEXT_SHAPES` is its one owner — a frozenset literal in this module would be
exactly the second copy this module was written to remove. The dependency runs one
way, by argument, and this module imports no adapter at all.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Final

__all__: list[str] = ["ASIDE", "PIXELS", "TEXT", "Decision", "decide"]


#: The document's text layer is readable, so read it. §1's first branch.
TEXT: Final[str] = "text"

#: There is no text layer, but there are pixels. Render and hand them to K4 - and
#: only after the pixels have been measured, which is what `decide` orders.
PIXELS: Final[str] = "pixels"

#: Stop, and record why. `illegible`, `blank` and an unmeasurable page all land
#: here, each with its own reason: they are different facts about a document and a
#: caller that needs to know *which* must not have to infer it from one word.
ASIDE: Final[str] = "aside"


@dataclasses.dataclass(frozen=True, slots=True)
class Decision:
    """What to do about one document, and the evidence it was decided from.

    The evidence travels **with** the decision rather than being re-measured by
    whoever acts on it. That is the same rule the drivers already follow for their
    attempts: a second measurement is a second answer, and on a `sampled` kernel it
    is also a second cost.

    Attributes:
        route: One of :data:`TEXT`, :data:`PIXELS` or :data:`ASIDE`.
        reason: Why, in words a console can print. Never empty: *no reason* and *a
            decided route* are different states, and a route without one is a route
            nobody can review.
        measured: The numbers the decision read — shape, legibility, DPI, character
            count — with the same names the advisories use. Recorded so a reader can
            check the rule against the evidence instead of trusting the verdict.
        adapt: Whether the pixels should be adapted before being read. ``False`` on
            every route this build can produce, and it is a **declared field rather
            than a missing branch** so that the day `rescale` can enlarge, the answer
            has somewhere to go. See the module docstring for why it is dead today.

    """

    route: str
    reason: str
    measured: Mapping[str, object]
    adapt: bool = False

    @property
    def proceeds(self) -> bool:
        """Whether this route leads to text.

        Returns:
            ``True`` for :data:`TEXT` and :data:`PIXELS`.

        """
        return self.route != ASIDE


def decide(
    *,
    shape: str,
    text_shapes: frozenset[str],
    legibility: str = "",
    sharpness: float | None = None,
    threshold: float | None = None,
    characters: int | None = None,
    measured_dpi: int | None = None,
    min_chars: int | None = None,
) -> Decision:
    """Choose a route for one page, from what was measured about it.

    Pure: no adapter, no file, no clock. Every argument is a number or a word some
    earlier call already produced, so a caller can state a case in a test that would
    otherwise cost a render and an OCR.

    The order of the tests is the argument of this function, and it is not the order
    they are listed in the signature:

    1. **A shape that could not be measured goes aside.** Nothing was learned, so
       there is no route to choose — and *unmeasurable* must not silently become
       *pixels*, which is the conservative-looking branch that costs the most.
    2. **`blank` goes aside.** It carries neither text nor an image, so both the
       other routes would ask a reader to read nothing.
    3. **Legibility is checked before anything is read, and only decides when the
       route needs pixels.** An `illegible` reading is what the flow's *validate by
       type* is for: measured, the OCR on such a page cost **9.2 s** and returned
       nothing. But a page with a text layer is read from its text, where legibility
       is not a property of anything — refusing it there would discard a perfectly
       good extraction because its *image* is blurred.
    4. **Text when the shape says text, else pixels.** The last test, because it is
       the fallback that costs money rather than the first thing to reach for.

    Args:
        shape: What `classify` measured: ``text``, ``mixed``, ``image``, ``blank``,
            or ``""`` when it was refused.
        text_shapes: The shapes whose content is the text layer — **injected rather
            than written here**. Which shapes carry text is a fact about K2's
            measurement vocabulary, and `pdf.TEXT_SHAPES` is its one owner; a
            frozenset literal in this module would be the second copy of it, which
            is the defect this module exists to remove (see the module docstring).
        legibility: The verdict K3 produced: ``ok``, ``illegible``, or a reason code.
            Empty when nothing measured it, which is a real state for a text page.
        sharpness: The laplacian variance K3 measured, or ``None``.
        threshold: The threshold it was compared against, or ``None``.
        characters: How many characters the text layer holds, or ``None``.
        measured_dpi: The page's own resolution, or ``None`` when unmeasurable.
        min_chars: The registry's character floor, or ``None``. Informational in this
            decision: it names the floor the reading is judged against, and the
            *reading* itself is K2's, which already applied it.

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

    # 1. Nothing was measured, so nothing is decided. `ASIDE` and not `PIXELS`:
    #    sending an unmeasured page to OCR treats *we could not look* as *it needs
    #    reading*, and the pixel route is the expensive one.
    if not shape:
        return Decision(
            ASIDE,
            "the page's shape could not be measured, so no route was chosen",
            measured,
        )

    # 2. A blank page holds no content: both remaining routes would read nothing.
    if shape == "blank":
        return Decision(
            ASIDE,
            "the page holds neither usable text nor an image",
            measured,
        )

    # 3. Legibility gates the **pixel** route only, and it is checked before any
    #    reading happens. Applying it to a text page would refuse a good extraction
    #    because the page's *image* is blurred, which is a fact about a picture
    #    nobody was going to look at.
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
        # A legibility reading that is neither `ok` nor `illegible` is a **refusal**
        # (`unsupported_format`, an unreadable file). It is a fact about the image
        # rather than about its quality, so it gets its own reason instead of being
        # folded into `illegible` — and it still goes aside, because the route it
        # would gate is the one that cannot run.
        return Decision(
            ASIDE,
            f"the page's pixels could not be measured ({legibility})",
            measured,
        )

    # 4. Text when the shape says so, pixels otherwise. `mixed` is text: the text
    #    layer is already there and needs nothing rendered.
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
