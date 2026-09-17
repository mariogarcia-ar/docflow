"""K8 `Registry` - the port over versioned corpus data.

The registry is not a config file. It is versioned data whose identity is a hash,
and that hash is a cache-key term (`sad.md` §5). Two failures follow from taking
it seriously, and both are the reason this port exists:

- **A malformed asset stops the run.** Unusable data is not degraded, it is
  refused, with a typed reason (`asset_invalid`) rather than a warning.
- **A missing asset is never defaulted.** A missing prompt, pattern or schema
  silently substituted with an empty one produces a run that completes and
  extracts nothing — indistinguishable from a corpus that had nothing to extract
  (`kernel-cli.md` §9, K8). So no operation here has a default, a fallback, or an
  empty-asset path.

Why policy is read through this port and not through a flag
-----------------------------------------------------------

`ADR-009` places corpus policy — the thresholds a component compares its
measurements against — in the registry as versioned assets, with **no
override**: no CLI flag and no environment variable. The rule is not tidiness: a
threshold that arrived out of band would change a stage's output without entering
its cache key, and the ledger would then say ``done`` about a result produced
under a setting nothing recorded (`sad.md` §5.1).

That is also why this port has **no threshold-shaped member**. A policy value is
read as an ordinary asset lookup, so a kernel cannot acquire a threshold by
having a member for one.

Deliberately absent
-------------------

- **No per-asset hashing.** One hash today. Per-asset hashing would make
  ``--force --stage`` more precise **and would change the cache-key formula**,
  so it is `plan-01-kernels.md` §12 open decision #4, carried as `# TODO: [MVP]`
  rather than resolved here.
- **No cache-key formula.** The registry *produces* a hash; the key that consumes
  it is `E03-02`.
- **No registry content.** Patterns, prompts, schemas and policies are Plan 3's
  (`S3-T04`). This port describes the loader, not the data.
- **No domain noun.** A registry keyed by a document concept would be a component
  wearing the wrong name. **Never** (`kernel-cli.md` §10).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from docflow.kernels.types import Evidence, KernelResult

__all__ = ["Registry"]


@runtime_checkable
class Registry(Protocol):
    """The corpus's versioned data, named by capability rather than by vendor.

    ``root`` is a parameter of every method rather than state on the object, for
    the same reason it is on ``ArtifactStore``: the adapter stays thin and the
    ``--root`` flag has an unambiguous counterpart (`kernel-cli.md` §10).
    """

    def validate(self, root: Path) -> KernelResult[Evidence]:
        """Load the registry and check every asset against its schema.

        Args:
            root: The registry root.

        Returns:
            What was loaded and validated, or no value and a typed ``Reason``:
            ``asset_invalid`` for an asset that failed schema validation,
            ``asset_missing`` for one that is absent, both naming the asset. The
            failure stops the run — a registry that cannot be loaded is not
            partially usable.

        """

    def hash(self, root: Path) -> KernelResult[str]:
        """Compute the registry's identity as a single value.

        Args:
            root: The registry root.

        Returns:
            The registry hash, or no value and a typed ``Reason``. It is a
            function of the loaded asset **content**, never of paths, timestamps
            or file order, so the same registry yields the same hash across
            independent loads, and changing one prompt changes the hash. This is
            the term a caller reaches for when asking *why* a ``--force --stage``
            is needed: printing it makes a prompt change visible as the thing
            that invalidated the stages that read it.

        """

    def show(
        self, root: Path, asset: str, key: str
    ) -> KernelResult[Mapping[str, object]]:
        """Read one value out of one asset.

        Args:
            root: The registry root.
            asset: The asset to read, named by its path within the registry.
            key: The key to read out of that asset.

        Returns:
            A single-key mapping of ``key`` to its value, or no value and a typed
            ``Reason`` naming what was missing. A mapping rather than a bare
            scalar so that the port's return type stays one JSON object shape
            instead of a union across every value a registry may hold. A policy
            value is read through this same operation — it has no member of its
            own, because a member would let a kernel acquire a threshold without
            the registry being the sole source of it (`ADR-009`).

        """

    def list(self, root: Path, asset: str) -> KernelResult[Sequence[str]]:
        """List the keys an asset provides.

        Args:
            root: The registry root.
            asset: The asset to enumerate.

        Returns:
            The asset's key names, or no value and a typed ``Reason``. An asset
            that is absent is reported, never enumerated as empty: an empty list
            would read as *"this asset has no keys"*, which is the silent
            substitution this port refuses.

        """
