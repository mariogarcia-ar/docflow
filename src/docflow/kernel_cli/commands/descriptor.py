"""Read a descriptor file - the composition root's reader (`E07-02` / `S1-T21`).

`orchestrator.read_descriptor` takes an injected ``Callable[[Path], Mapping]``, and
this is that callable's implementation. The seam exists because the descriptor's
*format* is a vendor concern: the kernel layer imports no third party
(`docflow/kernels/store.py`'s isolation test states the rule for the layer), and
parsing YAML needs one.

The vendor is PyYAML, and it is **declared** in `pyproject.toml` rather than
vendored or hand-rolled. Two alternatives were rejected, and the reason matters:

- **A hand-rolled subset parser.** It would be real code with no owner, and it would
  mis-parse the thirteen pipeline descriptors Plan 3 commits (`S3-T01`). A parser
  that handles today's file and not tomorrow's is a latent silent failure - it would
  drop a stage rather than refuse the document.
- **A JSON-only descriptor.** `plans/README.md` §3 freezes *the descriptor shape*
  and names `descriptors/synthetic-3stage.yaml`; the format is part of the frozen
  contract, so this is not the composition root's to change.

The reader is deliberately **strict**: it refuses a document whose top level is not
a mapping, and it never invents a default for a missing key. A descriptor that
parses into something the kernel layer then refuses is a worse failure than one that
does not parse, because the first reports a graph problem when the real problem is
the file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__: list[str] = ["read_descriptor_mapping"]

#: The parser error type, imported lazily inside the function so that a missing
#: PyYAML arrives as a message naming the extra to install rather than as an
#: ImportError raised while the lab surface is starting up. An unreadable descriptor
#: format is a *configuration* problem, and it should be reportable as one.
_YAML_HINT: str = (
    "Reading a descriptor needs PyYAML, which `pyproject.toml` declares for this "
    "surface. Install the package's dependencies (pip install -e .) rather than "
    "converting the descriptor: the YAML shape is frozen by plans/README.md §3."
)


def read_descriptor_mapping(path: Path) -> dict[str, Any]:
    """Read a descriptor file into a mapping.

    A ``.json`` file is read as JSON and anything else as YAML - by suffix, not by
    sniffing the content. Sniffing would accept a file whose extension says one
    thing and whose bytes say another, and the descriptor's format is part of a
    frozen contract rather than something to be inferred.

    Args:
        path: The descriptor's path.

    Returns:
        The parsed mapping.

    Raises:
        ValueError: If the file does not exist, does not parse, or parses into
            something other than a mapping at the top level.

    """
    if not path.is_file():
        raise ValueError(
            f"No descriptor at {path}. A run needs a stage graph, and there is no "
            "default one to fall back to: a default graph would be this surface "
            "deciding what work to do."
        )

    text = path.read_text(encoding="utf-8")

    if path.suffix == ".json":
        parsed: Any = json.loads(text)
    else:
        try:
            import yaml  # pylint: disable=import-outside-toplevel
        except ImportError as exc:  # pragma: no cover - declared dependency
            raise ValueError(_YAML_HINT) from exc
        parsed = yaml.safe_load(text)

    if not isinstance(parsed, dict):
        raise ValueError(
            f"{path} must hold a mapping at the top level, not "
            f"{type(parsed).__name__}. A descriptor is a set of named keys - unit, "
            "units, stages - and a list or a scalar cannot express one."
        )
    return parsed
