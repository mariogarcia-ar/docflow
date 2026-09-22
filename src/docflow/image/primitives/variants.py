"""The two purpose-specific preparation pipelines, and the publication of their artifacts.

The plan's central claim about this task is a negative one: **the OCR-optimal image is not assumed
to be the VLM-optimal image**. Everything here follows from taking that seriously.

An OCR engine reads marks, so it wants the page reduced to the fewest possible levels with the
strokes as crisp as they can be: colour is noise to it. A vision-language model reads the page as a
picture and reasons about layout, emphasis and diagrams, so colour and the original contrast carry
meaning that grayscale would throw away.

The two functions therefore share no steps except the geometric correction, and they are written as
two separate functions rather than one function with a flag. A flag would have made it easy to
"unify" them later - and unifying them is precisely the failure the plan names as
``IMG-13`` invariant 2, with its own mutation.

Neither function writes. Publication is a third function, so both pipelines stay testable without a
temporary directory and there is one place that touches the filesystem for ``IMG-11`` to make
atomic.
"""

from __future__ import annotations

from pathlib import Path

from docflow.image.contracts import (
    ImageMetrics,
    ImageOptions,
    ImageVariants,
)
from docflow.image.primitives.engine import EngineChoice, ImageArray
from docflow.image.primitives.publishing import publish_artifact
from docflow.image.primitives.transform import (
    binarize_image,
    convert_to_grayscale,
    denoise_image,
    deskew_image,
)

OCR_FILE_NAME = "ocr_ready.png"
VLM_FILE_NAME = "vlm_ready.png"
"""Names of the two artifacts inside the ``image/`` namespace.

Distinct constants rather than one name built from a label, so that a change to either is a visible
edit to a specific line rather than a change to a template that silently moves both.
"""

OCR_ARTIFACT_KIND = "ocr_ready"
VLM_ARTIFACT_KIND = "vlm_ready"
"""Artifact kinds recorded for them, from the contract's ``ImageArtifactKind`` values."""

MAX_ACCEPTABLE_NOISE = 3.0
"""Noise estimate above which the OCR pipeline denoises before thresholding.

Calibrated by measurement. The committed fixtures measure 0.57, 1.48 and 0.21, so a clean page stays
well below. Synthetic grain gives 1.51, 2.33, 3.15, 4.82, 6.48, 8.16 and 11.07 for standard
deviations of 2 to 25, so a cut at 3.0 intervenes from roughly the fourth step onwards.

The value matters because denoising is not free and not always wanted: on a noisy page it is the
step that keeps the text regions detectable, and on a clean one it is a cost with a measurable
downside - it lowers the blur score, which is the sharpness the OCR engine reads.

# TODO: [MVP] provisional - set from the fixtures, not from a labelled corpus.
"""

TRANSFORMATION_GRAYSCALE = "convert_to_grayscale"
TRANSFORMATION_DENOISE = "denoise_image"
TRANSFORMATION_BINARIZE = "binarize_image"
TRANSFORMATION_DESKEW = "deskew_image"
"""Names recorded in ``ImageResult.transformations``, taken from the primitives themselves."""


def prepare_image_for_ocr(
    image: ImageArray,
    metrics: ImageMetrics,
    options: ImageOptions,
    engine: EngineChoice,
) -> tuple[ImageArray | None, tuple[str, ...]]:
    """Build the OCR-optimized variant: one channel, straightened, denoised and binarized.

    The order is fixed and each step is placed where it is for a reason that was measured:

    1. **Grayscale**, first because every later step is a luminance operation and denoising three
       channels costs three times as much to produce the same result.
    2. **Denoise**, before the threshold rather than after it. Measured on a grained page at a
       standard deviation of 18, the raw image yields a single merged region covering 0.249 of the
       frame, while the denoised one yields two regions covering 0.210 - essentially the clean
       page's 0.202. After binarization the difference disappears, because the threshold already
       discards the grain, so this step earns its place only ahead of it.
    3. **Deskew**, before binarization so the rotation interpolates eight-bit pixels rather than
       two-valued ones, which is both better geometrically and cheaper.
    4. **Binarize**, last, because it is terminal: it is the only step here that destroys
       information, and the plan's risk table names that destruction as the thing to guard against.

    Args:
        image: The decoded pixels, in RGB order or grayscale. Not modified.
        metrics: The snapshot from ``analyze_image``, used to decide and never re-measured.
        options: The caller's explicit request.
        engine: The engine to transform with.

    Returns:
        The prepared pixels and the names of the transformations applied, in order. Both are empty
        when ``prepare_for_ocr`` is false: the pixels arrive as ``None``, which is this module's
        encoding of "not requested" and the only thing :func:`publish_variants` will refuse to
        write. Returning the input image instead would be indistinguishable from a prepared
        variant, and a caller could then publish an artifact nobody asked for.

    Raises:
        ImageEngineNotAvailableError: The engine or array library is missing.
        ImageEngineCapabilityError: The engine lacks a required operation.
        ImagePrimitiveError: A step cannot be applied.
    """
    if not options.prepare_for_ocr:
        return None, ()

    working = convert_to_grayscale(image, engine)
    applied = [TRANSFORMATION_GRAYSCALE]

    if metrics.quality.noise > MAX_ACCEPTABLE_NOISE:
        working = denoise_image(working, engine)
        applied.append(TRANSFORMATION_DENOISE)

    if options.deskew and metrics.skew:
        working = deskew_image(working, metrics.skew, engine)
        applied.append(TRANSFORMATION_DESKEW)

    # The engine derives the cut from this image's own histogram, which matters because the
    # pipeline has already changed the histogram twice by now; a fixed cut chosen before either
    # step would be a guess about a page that no longer exists.
    working = binarize_image(working, engine)
    applied.append(TRANSFORMATION_BINARIZE)

    return working, tuple(applied)


def prepare_image_for_vlm(
    image: ImageArray,
    metrics: ImageMetrics,
    options: ImageOptions,
    engine: EngineChoice,
) -> tuple[ImageArray | None, tuple[str, ...]]:
    """Build the VLM-optimized variant: the page as a picture, straightened but otherwise intact.

    **One step, and the restraint is the point.** A vision-language model reads layout, emphasis,
    colour coding and diagrams; every pixel-level operation that does not correct a geometric
    fault risks removing meaning it would have used. So the pipeline corrects the one fault that is
    unambiguously a fault - a tilt that makes the page harder to read - and changes nothing else.

    Deliberately absent, each for a reason:

    * **No grayscale.** The plan says the VLM variant preserves colour channels, and colour is
      information: a red stamp, a highlighted clause, a chart's legend.
    * **No binarization.** It is destructive by design, and this variant is the one whose purpose
      is to keep the page intact.
    * **No denoising.** Measured, it lowers the blur score - the sharpness the model reads edges
      with - and it costs time. On a clean page it is all cost.
    * **No contrast stretch.** Measured on the washed-out fixture it moves contrast from 39.05 to
      39.70, so it buys nothing; on a good page it would only alter pixels the model did not
      complain about.
    * **No whole-page brightness shift.** A page is bright because most of it is paper, and
      re-centring the mean would turn paper grey.

    Args:
        image: The decoded pixels, in RGB order or grayscale. Not modified.
        metrics: The snapshot from ``analyze_image``, used to decide and never re-measured.
        options: The caller's explicit request.
        engine: The engine to transform with.

    Returns:
        The prepared pixels and the names of the transformations applied, in order. Both are empty
        when ``prepare_for_vlm`` is false, with the pixels arriving as ``None`` - see
        :func:`prepare_image_for_ocr` for why the input is not passed through instead.

    Raises:
        ImageEngineNotAvailableError: The engine or array library is missing.
        ImageEngineCapabilityError: The engine lacks a required operation.
        ImagePrimitiveError: The correction cannot be applied.
    """
    if not options.prepare_for_vlm:
        return None, ()

    if options.deskew and metrics.skew:
        return deskew_image(image, metrics.skew, engine), (TRANSFORMATION_DESKEW,)

    # The page needs no correction, but the variant *was* requested, so the source pixels are what
    # to publish. Distinct from the not-requested case above, which returns nothing at all.
    return image, ()


def publish_variants(
    ocr_ready: ImageArray | None,
    ocr_transformations: tuple[str, ...],
    vlm_ready: ImageArray | None,
    vlm_transformations: tuple[str, ...],
    output_dir: Path,
    engine: EngineChoice,
) -> ImageVariants:
    """Publish whichever variants were prepared, and describe them.

    Takes the prepared arrays rather than the request, so a variant that was not prepared arrives as
    ``None`` and the contract's "``None`` means not requested" convention holds by construction: the
    only way to publish ``ocr_ready.png`` is to bring pixels for it.

    Args:
        ocr_ready: The prepared OCR variant, or ``None`` when it was not requested.
        ocr_transformations: What the OCR pipeline applied.
        vlm_ready: The prepared VLM variant, or ``None`` when it was not requested.
        vlm_transformations: What the VLM pipeline applied.
        output_dir: The ``image/`` directory to write into. This module never chooses it, so
            ownership of the namespace stays with the caller.
        engine: The engine to encode with.

    Returns:
        Both references, each ``None`` when its variant was not requested.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImagePrimitiveError: A write fails, with the transformations that run applied carried into
            the failure's context.
        ValueError: Both variants were prepared and would resolve to the same path. That is the
            aliasing ``IMG-13`` invariant 2 names, and it is refused here rather than left to a
            test, so a caller who never runs the tests still cannot publish one file as two.

    # TODO: [MVP] writes in place; ``IMG-11`` routes this through ``image/.tmp/`` and a rename.
    """
    if ocr_ready is not None and vlm_ready is not None:
        _require_distinct_paths(output_dir)

    return ImageVariants(
        ocr_ready=publish_artifact(
            ocr_ready,
            output_dir,
            OCR_FILE_NAME,
            OCR_ARTIFACT_KIND,
            ocr_transformations,
            engine,
        ),
        vlm_ready=publish_artifact(
            vlm_ready,
            output_dir,
            VLM_FILE_NAME,
            VLM_ARTIFACT_KIND,
            vlm_transformations,
            engine,
        ),
    )


def _require_distinct_paths(output_dir: Path) -> None:
    """Refuse a configuration in which the two variants would be the same file.

    Args:
        output_dir: The directory both would be written into.

    Raises:
        ValueError: The two names resolve to one path.
    """
    if output_dir / OCR_FILE_NAME == output_dir / VLM_FILE_NAME:
        raise ValueError(
            f"the OCR and VLM variants resolve to the same path ({OCR_FILE_NAME}); they are "
            "independent artifacts and one must never stand in for the other"
        )


__all__ = [
    "MAX_ACCEPTABLE_NOISE",
    "OCR_ARTIFACT_KIND",
    "OCR_FILE_NAME",
    "TRANSFORMATION_BINARIZE",
    "TRANSFORMATION_DENOISE",
    "TRANSFORMATION_DESKEW",
    "TRANSFORMATION_GRAYSCALE",
    "VLM_ARTIFACT_KIND",
    "VLM_FILE_NAME",
    "prepare_image_for_ocr",
    "prepare_image_for_vlm",
    "publish_variants",
]
