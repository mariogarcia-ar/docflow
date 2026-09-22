"""The descriptive classification of an image, decided from its measurements alone.

``classify_image`` answers one question: what sort of thing is this page? It returns one of
``TEXT_IMAGE``, ``VISUAL_IMAGE``, ``MIXED_IMAGE`` or ``LOW_QUALITY``, and it does so from
:class:`~docflow.image.contracts.ImageMetrics` and nothing else - no option, no context, no workflow
flag. That restraint is deliberate and the plan states it twice: the classification is
*descriptive*,
so it never becomes a routing decision, and it never collapses the per-measurement evidence into an
aggregate confidence score.

The discriminator that carries the classification is **region height**, and it was measured rather
than assumed. A line of text is short and wide; a figure, a chart or a solid block is tall. Across
every case probed, lines of text produced regions 7 to 24 pixels tall while figures, logos and solid
bars produced regions 40 to 420 pixels tall, with nothing in between. The obvious alternatives were
tried first and did not work:

* **Ink density inside a region** does not separate them. Measured, lines of text ran from 0.28 to
  1.0 and a chart's bars gave 0.808 - the same range, so a threshold on it decides nothing.
* **Span or coverage alone** does not either: a page of widely spaced lines covers 0.013 of the
frame
  per region, exactly like a small detail inside a figure.
* **Colour** is unavailable in principle. ``ImageMetrics`` carries quality, orientation, skew and
  text regions; it has no saturation measure, so no rule may depend on one.

One consequence is worth stating plainly, because it is a property of the measurements rather than a
shortcoming of the code: the classifier sees *markings*, not *characters*. A page whose text was set
in a face so heavy that its lines merge into tall blocks will read as ``VISUAL_IMAGE``, and a dense
table of ruled lines will read as ``TEXT_IMAGE``. Both are the honest answer to "what does this page
look like", which is the question this function is entitled to answer. What the page *means* is the
OCR processor's business.
"""

from __future__ import annotations

from docflow.image.contracts import ImageClassification, ImageMetrics

MAX_TEXT_LINE_HEIGHT = 30.0
"""Tallest region still read as a line of text, in pixels.

Measured across every case probed: lines of text produced regions 7 to 24 pixels tall (7 for tight
leading, 9 for wide, 24 for the skewed fixture), while figures, logos and solid bars produced 40 to
420. The cut sits in the empty band between them with room on both sides.

The value is in pixels and therefore depends on the image's resolution. A page scanned at four times
the resolution would have four times the line height and would be misread as visual. That is
acceptable for this stage because the processor does not resample a page before measuring it, so the
metrics and this threshold always describe the same pixels; a resolution-aware threshold would be
the
fix if that ever changed.

# TODO: [MVP] provisional - set from the fixtures, not from a labelled corpus.
"""

MIN_REGION_INK = 0.10
"""Ink share a short region needs before it counts as text.

A short region that is almost entirely background is a sliver the closing step happened to produce
rather than a line of characters.

# TODO: [MVP] provisional - see :data:`MAX_TEXT_LINE_HEIGHT`.
"""

DOMINANT_REGION_SHARE = 0.40
"""Share of the frame a single region needs to be the page's subject.

Above this, one thing occupies the page and the classification says so regardless of what else is
present - the same shape of rule the PDF processor uses for a page-filling image.

# TODO: [MVP] provisional - see :data:`MAX_TEXT_LINE_HEIGHT`.
"""

MIN_ACCEPTABLE_SHARPNESS = 1000.0
"""Sharpness below which the page carries too little edge structure to be legible.

Measured: a page blurred beyond recognition scores 177, a clean figure scores 7072, and the
committed
fixtures score 35233 and above. The cut separates "the detail has been destroyed" from "the page is
simply a picture".

# TODO: [MVP] provisional - see :data:`MAX_TEXT_LINE_HEIGHT`.
"""

MIN_LEGIBLE_CONTRAST = 10.0
"""Luminance spread below which a page carries no markings to separate at all.

Set from **real images**, not only from synthetic ones, and the first draft of this value was wrong
for exactly that reason: it was 30, and four of the twelve extracted JPEGs in the corpus measure 18
to 28, all of which are ordinary pages that the classifier was calling unusable.

Measured: a blank page, a flat grey page and a fully black page all score 0; the lowest real
extracted image scores 18; a page blurred beyond recognition scores 30 to 38, which the sharpness
floor already catches. A floor of 10 separates "there is nothing here" from "there is a page here"
with room on both sides.

The threshold is deliberately far below
:data:`docflow.image.primitives.normalize.MIN_ACCEPTABLE_CONTRAST`, which is 45. That one answers
whether a *correction* is worth applying; this one answers whether the page is usable at all. A page
at 36 needs improvement and is not unusable, and the two figures are allowed to say different
things.

# TODO: [MVP] provisional - see :data:`MAX_TEXT_LINE_HEIGHT`.
"""

MAX_UNUSABLE_NOISE = 5.0
"""Noise above which grain has started to replace the page's own content.

Distinct from :data:`docflow.image.primitives.variants.MAX_ACCEPTABLE_NOISE`, which is 3.0 and
decides whether denoising is *worth a step*. A page with grain between the two is worth denoising
and
still usable, so the two figures answer different questions and are allowed to differ.

Measured: the fixtures score 0.21 to 1.48, grain at a standard deviation of 18 scores 8.16, and a
page of pure noise scores 39.

# TODO: [MVP] provisional - see :data:`MAX_TEXT_LINE_HEIGHT`.
"""

MIN_TEXT_AREA_SHARE = 0.60
"""Share of the covered area the text-like regions need for a page to read as text.

Measured reasoning rather than a tuned value: a page of text with a figure in the margin keeps
almost all of its area in short regions, while a page that is half chart does not. The cut sits
above
halfway because the page is being called a *text* page, which is the stronger claim.

# TODO: [MVP] provisional - see :data:`MAX_TEXT_LINE_HEIGHT`.
"""

MIN_USABLE_BRIGHTNESS = 40.0
MAX_USABLE_BRIGHTNESS = 245.0
"""Luminance range outside which a page carries no recoverable markings.

A page at either extreme has no contrast left to separate ink from background, whatever its standard
deviation says. Measured: a blank white page and a blank black page both score zero contrast and are
caught by the contrast test as well, so these bounds are a second line of defence rather than the
only one.

# TODO: [MVP] provisional - see :data:`MAX_TEXT_LINE_HEIGHT`.
"""


def classify_image(metrics: ImageMetrics) -> ImageClassification:
    """Classify an image descriptively from its measurements.

    The order of the tests is what makes the answer deterministic, and it is chosen so the clearest
    evidence wins:

    1. A page that failed its quality measurements is ``LOW_QUALITY`` whatever else it contains,
       because "this cannot be read" outranks "this is mostly text".
    2. A page with no text-like regions is ``VISUAL_IMAGE``. A blank page falls here: it has no
       regions at all, and calling it a text page would be a claim nothing supports.
    3. A page with one region occupying most of the frame is ``MIXED_IMAGE`` if it also carries
       text-like regions and ``VISUAL_IMAGE`` otherwise, since the dominant thing is the subject.
    4. A page whose markings are all short is ``TEXT_IMAGE``.
    5. Anything else is ``MIXED_IMAGE``.

    Args:
        metrics: The snapshot from ``analyze_image``. The only input: this function reads no option,
            no context and no file.

    Returns:
        Exactly one of the four classification literals.
    """
    if _is_low_quality(metrics):
        return "LOW_QUALITY"

    text_like = _text_like_regions(metrics)
    dominant_share = _dominant_region_share(metrics)

    if not text_like:
        return "VISUAL_IMAGE"

    if dominant_share >= DOMINANT_REGION_SHARE:
        return "MIXED_IMAGE"

    return "TEXT_IMAGE" if _is_text_dominant(metrics, text_like) else "MIXED_IMAGE"


def _is_low_quality(metrics: ImageMetrics) -> bool:
    """Report whether a page failed the measurements that decide legibility.

    Args:
        metrics: The snapshot to test.

    Returns:
        ``True`` when any measurement is outside its usable range.
    """
    quality = metrics.quality
    return (
        quality.sharpness < MIN_ACCEPTABLE_SHARPNESS
        or quality.contrast < MIN_LEGIBLE_CONTRAST
        or quality.noise > MAX_UNUSABLE_NOISE
        or not MIN_USABLE_BRIGHTNESS <= quality.brightness <= MAX_USABLE_BRIGHTNESS
    )


def _text_like_regions(metrics: ImageMetrics) -> list[object]:
    """Return the regions short enough to be lines of text and inked enough to be characters.

    Args:
        metrics: The snapshot whose regions to filter.

    Returns:
        The regions that read as text.
    """
    return [
        region
        for region in metrics.text_regions
        if region.bbox[3] <= MAX_TEXT_LINE_HEIGHT
        and region.text_coverage >= MIN_REGION_INK
    ]


def _dominant_region_share(metrics: ImageMetrics) -> float:
    """Return the share of the frame the largest region occupies.

    Args:
        metrics: The snapshot whose regions to measure.

    Returns:
        The largest region's area over the frame's, or ``0.0`` when there are no regions.
    """
    frame = metrics.dimensions.width * metrics.dimensions.height
    if not metrics.text_regions or frame <= 0:
        return 0.0
    largest = max(region.bbox[2] * region.bbox[3] for region in metrics.text_regions)
    return float(largest / frame)


def _is_text_dominant(metrics: ImageMetrics, text_like: list[object]) -> bool:
    """Report whether the text-like regions account for the page's markings.

    Compares the area the short regions cover with the area every region covers, so a page of text
    with a small diagram in the corner stays ``TEXT_IMAGE`` while a page that is half figure does
    not. Area is used rather than a count, because one wide figure contributes one region and a
    paragraph contributes many, and counting them would weight the paragraph far too heavily.

    Args:
        metrics: The snapshot being classified.
        text_like: The regions already filtered to lines of text.

    Returns:
        ``True`` when the text-like regions carry most of the covered area.
    """
    _ = metrics
    text_area = sum(region.bbox[2] * region.bbox[3] for region in text_like)
    all_area = sum(region.bbox[2] * region.bbox[3] for region in metrics.text_regions)
    if all_area <= 0:
        return False
    return text_area / all_area >= MIN_TEXT_AREA_SHARE


__all__ = [
    "DOMINANT_REGION_SHARE",
    "MAX_TEXT_LINE_HEIGHT",
    "MAX_UNUSABLE_NOISE",
    "MAX_USABLE_BRIGHTNESS",
    "MIN_ACCEPTABLE_SHARPNESS",
    "MIN_LEGIBLE_CONTRAST",
    "MIN_REGION_INK",
    "MIN_TEXT_AREA_SHARE",
    "MIN_USABLE_BRIGHTNESS",
    "classify_image",
]
