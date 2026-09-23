"""Publication of one processed image, and the description that travels with it.

Every artifact this processor produces is written the same way: staged under ``image/.tmp/``, then
renamed into place, so a reader that finds the final name finds a complete file. The reference that
describes it is built from the bytes that actually landed on disk rather than from what the caller
intended to write.

Extracted once two pipelines needed it. Copying it would have meant two places to keep in step for
the destination check, the reference construction and the failure context - and the failure context
is the part that matters, because ``metadata.json`` and a failure report both read it, so a second
copy that drifted would produce records that disagree about what a run did.

The rule this module enforces is the one the plan states for the whole processor: **an artifact
nobody asked for is never written**. ``image`` is ``None`` when a variant was not requested, and
that is the only thing that returns ``None`` here rather than a reference.
"""

from __future__ import annotations

from pathlib import Path

from docflow.image.contracts import ArtifactRef
from docflow.image.primitives.atomic import prune_staging_directory, temp_path
from docflow.image.primitives.engine import EngineChoice, ImageArray
from docflow.image.primitives.failures import ImagePrimitiveError
from docflow.image.primitives.load import get_image_dimensions, save_image

TRANSFORMATION_CONTEXT_KEY = "transformations"
"""Key under which the applied steps are attached to a write failure.

A key rather than a sentence, so a caller can read the list back rather than parse it out of a
message.
"""


def publish_artifact(
    image: ImageArray | None,
    output_dir: Path,
    file_name: str,
    kind: str,
    transformations: tuple[str, ...],
    engine: EngineChoice,
) -> ArtifactRef | None:
    """Write one image into a namespace directory and describe it.

    Args:
        image: The pixels to write, or ``None`` when the artifact was not requested.
        output_dir: The directory to write into. Never chosen here, so ownership of the namespace
            stays with the caller.
        file_name: Name of the artifact inside that directory.
        kind: Artifact kind to record, from the contract's ``ImageArtifactKind`` values.
        transformations: The steps that produced these pixels, attached to a failure so the report
            points at the run rather than only at the file.
        engine: The engine to encode with.

    Returns:
        A reference to the written file, or ``None`` when ``image`` was ``None``.

    Raises:
        ImageEngineNotAvailableError: The engine is missing.
        ImagePrimitiveError: The write fails, carrying the applied transformations in its context.
    """
    if image is None:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / file_name
    # Staged inside the namespace and renamed into place (`IMG-11`), so a failure part-way leaves
    # no artifact under its final name for a later stage to mistake for a result.
    staged = temp_path(destination)
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.unlink(missing_ok=True)

    try:
        save_image(image, staged, engine)
    except ImagePrimitiveError as failure:
        failure.detail[TRANSFORMATION_CONTEXT_KEY] = list(transformations)
        staged.unlink(missing_ok=True)
        prune_staging_directory(staged.parent)
        raise

    # The dimensions are measured before the rename, while the bytes are still staged: the rename
    # itself can fail, and an artifact whose metadata was never read should not be published.
    dimensions = get_image_dimensions(image, engine)
    staged.replace(destination)
    prune_staging_directory(staged.parent)
    return ArtifactRef(
        path=destination,
        kind=kind,
        width=dimensions.width,
        height=dimensions.height,
        format=destination.suffix.lstrip(".").upper(),
        size=destination.stat().st_size,
    )


__all__ = [
    "TRANSFORMATION_CONTEXT_KEY",
    "publish_artifact",
]
