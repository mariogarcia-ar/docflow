"""Provenance of an artifact — which processor, which version, which engine.

Owned by ``PDF-09`` because that is the first task that writes a ``metadata.json``; the
key set itself is fixed by :mod:`docflow.identities`.

Two of the seven required keys are answerable here — ``processor`` and
``processor_version`` — plus the engine pair the plan records per artifact. The other three
are identities: ``document_id`` and ``workflow_run_id`` come from the request's context, and
``processing_key`` is **not this processor's to compute**.

That last point is worth stating rather than working around. ``subplan-orquestador.md`` §3.4
defines ``processing_key = hash(processor + processor_version + input_hashes +
normalized_options)`` and ``ORC-02`` owns its computation, in Phase 2, precisely because the
formula needs normalized options and input hashes — orchestrator knowledge. A processor that
hashed its own key would be making a workflow decision, which ``subplan-procesador-pdf.md``
§2 puts out of bounds. So the entry points accept the key from their caller and record
``None`` until the orchestrator supplies one: an explicit "not yet computed" is honest,
whereas a self-computed hash would be a second, disagreeing implementation of a value the
reuse rule depends on being identical everywhere.
"""

from __future__ import annotations

from typing import Final

PROCESSOR_NAME: Final[str] = "pdf"
"""The processor's name, as it appears in every artifact it publishes."""

PROCESSOR_VERSION: Final[str] = "0.0.0"
"""Version of this processor's implementation.

Deliberately a module constant rather than ``importlib.metadata.version("docflow")``: the
package is not installed in the no-install test path ``pyproject.toml`` supports, so
querying distribution metadata would fail exactly where it is needed most. Bumping this
value must be part of any change to what a processor produces, because
``identities.PROCESSING_KEY_FORMULA`` puts the version in the key and an upgraded processor
must never reuse a previous version's output.

# TODO: [RELEASE] derive this from the package distribution once an installed deployment
# is the only supported mode, so a release cannot ship with a stale constant.
"""


def processor_name() -> str:
    """Return the processor's name.

    Returns:
        ``"pdf"``.
    """
    return PROCESSOR_NAME


def processor_version() -> str:
    """Return this processor's version.

    Returns:
        The version string recorded in every artifact's ``metadata.json``.
    """
    return PROCESSOR_VERSION


__all__ = [
    "PROCESSOR_NAME",
    "PROCESSOR_VERSION",
    "processor_name",
    "processor_version",
]
