"""Identity primitives of the orchestrator (``ORC-02``).

Reuse, resume and idempotency all reduce to one question — *is this the same unit of
work?* — and these four functions are the only place that question is answered.

The processing key is computed exactly as ``subplan-orquestador.md`` §3.4 fixes it::

    processing_key = hash(processor + processor_version + input_hashes + normalized_options)

Two properties follow from the formula and are worth stating, because both are tested:

* the **run identity is not an input**, so a new run over unchanged inputs reproduces the
  same key — otherwise reuse could never trigger;
* **options are normalized before hashing**, so two spellings of one configuration
  produce one key, and a changed value produces a different one.

An input is hashed **by content, not by name**: a ``Path`` that exists contributes the
digest of its bytes, so rewriting a file in place changes the key, while a path that does
not exist contributes its name and is not silently treated as empty.

# TODO: [MVP] the normalization is structural (key order, containers, dataclasses); a
# numeric tolerance for float options is not applied, so 0.1 and 0.10 stay distinct.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

#: Prefix of every run identity, so a value read out of context says what it names.
RUN_ID_PREFIX = "run-"


def file_digest(path: Path) -> str:
    """Return the SHA-256 of a file's bytes.

    Args:
        path: The file to digest.

    Returns:
        The digest, in hexadecimal.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value: Any) -> Any:  # pylint: disable=too-many-return-statements
    """Return a canonical, order-stable form of ``value``, ready to be serialized.

    # Reason for the suppression above: the function is a type dispatch, and one return per
    # handled type is what makes the handled set readable; a table lookup would move the
    # same branches behind an indirection without removing one.

    Args:
        value: Any value an option or an input may hold.

    Returns:
        The same value with mappings key-sorted, sets order-stable, dataclasses expanded
        and paths rendered as text. A value the normalizer does not know is rendered with
        ``str`` rather than dropped: a silent omission would make two different inputs
        hash alike.
    """
    if isinstance(value, Path):
        if value.is_file():
            return {"path": str(value), "sha256": file_digest(value)}
        return {"path": str(value)}
    if isinstance(value, Mapping):
        return {str(key): normalize(item) for key, item in sorted(value.items())}
    if is_dataclass(value) and not isinstance(value, type):
        return normalize(asdict(value))
    if isinstance(value, (frozenset, set)):
        items = [normalize(item) for item in value]
        return sorted(items, key=canonical_json)
    if isinstance(value, (list, tuple)):
        return [normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically: sorted keys, no incidental whitespace.

    Args:
        value: The value to serialize.

    Returns:
        Its canonical JSON text.
    """
    return json.dumps(normalize(value), sort_keys=True, separators=(",", ":"))


def input_hash(*values: Any) -> str:
    """Return the digest of one or more inputs.

    Args:
        *values: The inputs; paths are hashed by content, everything else canonically.

    Returns:
        The digest, in hexadecimal.
    """
    return hashlib.sha256(canonical_json(list(values)).encode("utf-8")).hexdigest()


def options_hash(options: Mapping[str, Any]) -> str:
    """Return the digest of a normalized option set.

    Args:
        options: The options in force; normalization is applied here, not by the caller.

    Returns:
        The digest, in hexadecimal.
    """
    return hashlib.sha256(canonical_json(dict(options)).encode("utf-8")).hexdigest()


def processing_key(
    processor: str,
    processor_version: str,
    input_hashes: Sequence[str],
    normalized_options: Mapping[str, Any],
) -> str:
    """Compute the key of one unit of work, exactly as the frozen formula states it.

    Args:
        processor: Name of the processor that owns the unit.
        processor_version: Version of that processor.
        input_hashes: Digests of everything the unit consumes, in order.
        normalized_options: The options in force, already in their canonical form.

    Returns:
        The key, in hexadecimal. No run identity participates, so the same inputs and the
        same options always produce the same key.
    """
    payload = canonical_json(
        {
            "processor": processor,
            "processor_version": processor_version,
            "input_hashes": list(input_hashes),
            "normalized_options": dict(normalized_options),
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_workflow_run_id() -> str:
    """Mint the identity of one run.

    Returns:
        A fresh run identity. It is minted, never derived: two runs of the same document
        are two runs, and neither may claim the other's identity.
    """
    return f"{RUN_ID_PREFIX}{uuid.uuid4().hex}"
