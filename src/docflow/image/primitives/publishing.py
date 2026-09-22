"""Publication of one processed image, and the description that travels with it.

Every artifact this processor produces is written the same way: a directory that may not exist
yet, a file that may be left from a previous run, an encode through the engine, and a reference
file that may be left from a previous run, an encode through the engine, and a reference built from
the bytes that actually landed on disk rather than from what the caller intended to write. That is
one procedure, so it lives in one place.

Extracted once two pipelines needed it. Copying it would have meant two places to keep in step for
the destination check, the reference construction and the failure context - and the failure context
is the part that matters: ``metadata.json`` and a failure report both read it, so a second copy that
drifted would produce records that disagree about what a run did.

The rule this module enforces is the one the plan states for the whole processor: **an artifact
the destination check, the reference construction and the failure context - and the
failure context is the part that matters: ``metadata.json`` and a failure report both read
it, so a second copy that drifted would produce records that disagree about what a run
did.
the destination check, the reference construction and the failure context - and the failure
context is the part that matters: ``metadata.json`` and a failure report both read it, so a
second copy that drifted would produce records that disagree about what a run did.
"""

from __future__ import annotations

from pathlib import Path

from docflow.image.contracts import ArtifactRef
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

    # TODO: [MVP] writes in place; ``IMG-11`` routes this through ``image/.tmp/`` and a rename, so a
    # failure part-way leaves no artifact under its final name.
    """
    if image is None:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / file_name
    if destination.exists():
        # A previous run's artifact. Removed explicitly rather than relied upon to be overwritten,
        # because `save_image` refuses an occupied destination and that refusal is a real safety
        # property rather than an obstacle to route around.
        destination.unlink()

    try:
        save_image(image, destination, engine)
    except ImagePrimitiveError as failure:
        failure.detail[TRANSFORMATION_CONTEXT_KEY] = list(transformations)
        raise

    dimensions = get_image_dimensions(image, engine)
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
