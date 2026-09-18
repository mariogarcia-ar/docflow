"""K8's commands - `registry` (`E07-02` / `S1-T21`).

Four `now` commands. `validate` is matrix row 17: a registry with an asset removed
must exit `3` naming the missing asset, and **no default may be substituted** -
*"a missing asset silently substituted with an empty one produces a run that completes
and extracts nothing, which is indistinguishable from a corpus with no extractable
fields."*

K8 is the one kernel bound directly to its kernel module rather than to an adapter.
That is the epic's own sentence for `Registry`, and it is the position the store path
took the opposite of - recorded in `E04-01` as a contradiction the user owns, not one
this module resolves. What matters here is the *mapping*: four commands, four methods,
and the flags are the port's parameters (`--root`, `--asset`, `--key`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from docflow.kernel_cli.commands.policy import DEFAULT_ROOT
from docflow.kernel_cli.commands.refusals import refusal
from docflow.kernel_cli.main import Call, Handler
from docflow.kernels import registry as k8
from docflow.kernels.types import Evidence, KernelResult, Reason

#: What each refusal in this module was blocked by. One value for the module,
#: because every refusal here is the same kind of event: a command whose
#: parameters do not name a call this surface can make.
_BLOCKED: Final[str] = "missing_parameter"

__all__: list[str] = []


def validate(*, root: str = DEFAULT_ROOT, **_: object) -> Call:
    """Load and schema-validate a registry root.

    The value reported is a **description** of the loaded registry, not the `Registry`
    object. The envelope carries the seven boundary types, mappings and sequences and
    nothing else - `E01-01`'s encoder refuses an unknown type rather than stringifying
    it - and `Registry` is a kernel-layer value that is not on that list. Returning it
    would make the command unrunnable for a reason nothing in the kernel's contract
    explains, which is what happened the first time this was wired.

    A description is also the more useful answer: `registry validate` exists to report
    *what validated*, and the asset keys with their hashes are that report. The full
    object stays a library value, reachable through K8 directly.

    Args:
        root: The registry root.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call. A malformed or missing asset is a typed reason, never a partial
        registry.

    """
    loaded = k8.load_registry(Path(root))
    if loaded.reason is not None or loaded.value is None:
        return Call(result=loaded)

    registry = loaded.value
    assets = {
        key: {
            "sha256": asset.sha256,
            "format": asset.format,
            "bytes": len(asset.content),
        }
        for key, asset in registry.assets.items()
    }
    return Call(
        result=KernelResult(
            value={"root": root, "assets": assets, "asset_count": len(assets)},
            evidence=Evidence(
                terms={"registry_root": root},
                measurements={"assets": float(len(assets))},
                observed={"validated": "true"},
            ),
            reason=None,
        )
    )


def registry_hash(*, root: str = DEFAULT_ROOT, **_: object) -> Call:
    """Report the registry's content hash, which is a cache-key term.

    Args:
        root: The registry root.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, or the reason the registry is unusable - a hash over a registry
        that could not be loaded would key work on content nobody read.

    """
    loaded = k8.load_registry(Path(root))
    if loaded.reason is not None or loaded.value is None:
        return Call(result=loaded)
    digest = k8.registry_hash(loaded.value)
    return Call(
        result=KernelResult(
            value=digest,
            evidence=Evidence(
                terms={"registry_root": root},
                measurements={},
                observed={"assets": str(len(loaded.value.assets))},
            ),
            reason=None,
        )
    )


def show(
    *, root: str = DEFAULT_ROOT, asset: object = None, key: object = None, **_: object
) -> Call:
    """Read one value out of one asset.

    Args:
        root: The registry root.
        asset: The asset's key within the registry.
        key: The key to read out of it.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call, or a typed refusal naming which flag is missing.

    """
    if asset is None or key is None:
        return Call(
            result=refusal(
                Reason(
                    code="asset_missing",
                    message=(
                        "registry show needs both --asset and --key: an asset with no "
                        "key names no value, and a key with no asset names no place "
                        "to look."
                    ),
                ),
                blocked_by=_BLOCKED,
            )
        )
    loaded = k8.load_registry(Path(root))
    if loaded.reason is not None or loaded.value is None:
        return Call(result=loaded)
    found = loaded.value.assets.get(str(asset))
    if found is None:
        return Call(
            result=refusal(
                Reason(
                    code="asset_missing",
                    message=(
                        f"The registry declares no asset {asset!r}. Refusing rather "
                        "than reporting an empty value: a missing asset is not an "
                        "asset that is empty."
                    ),
                ),
                blocked_by=_BLOCKED,
            )
        )
    import json  # pylint: disable=import-outside-toplevel

    values = json.loads(found.content.decode("utf-8"))
    if not isinstance(values, dict) or str(key) not in values:
        return Call(
            result=refusal(
                Reason(
                    code="asset_missing",
                    message=f"Asset {asset!r} declares no key {key!r}.",
                ),
                blocked_by=_BLOCKED,
            )
        )
    return Call(
        result=KernelResult(
            value={str(key): values[str(key)]},
            evidence=Evidence(
                terms={"registry_root": root, "asset": str(asset), "key": str(key)},
                measurements={},
                observed={"sha256": found.sha256},
            ),
            reason=None,
        )
    )


def ls(*, root: str = DEFAULT_ROOT, asset: object = None, **_: object) -> Call:
    """List the keys one asset provides.

    Args:
        root: The registry root.
        asset: The asset to enumerate.
        **_: Accepted, so an unknown flag reaches the dispatcher.

    Returns:
        The call.

    """
    if asset is None:
        return Call(
            result=refusal(
                Reason(
                    code="asset_missing",
                    message=(
                        "registry ls needs --asset: the keys of no asset is no list."
                    ),
                ),
                blocked_by=_BLOCKED,
            )
        )
    loaded = k8.load_registry(Path(root))
    if loaded.reason is not None or loaded.value is None:
        return Call(result=loaded)
    found = loaded.value.assets.get(str(asset))
    if found is None:
        return Call(
            result=refusal(
                Reason(
                    code="asset_missing",
                    message=f"The registry declares no asset {asset!r}.",
                ),
                blocked_by=_BLOCKED,
            )
        )
    import json  # pylint: disable=import-outside-toplevel

    values = json.loads(found.content.decode("utf-8"))
    keys = sorted(values) if isinstance(values, dict) else []
    return Call(
        result=KernelResult(
            value=list(keys),
            evidence=Evidence(
                terms={"registry_root": root, "asset": str(asset)},
                measurements={"keys": float(len(keys))},
                observed={"sha256": found.sha256},
            ),
            reason=None,
        )
    )


#: What this module declares, as data. Each entry is
#: ``(operation, handler, positional, flags)``: ``handler=None`` is an ``MVP``
#: command, ``positional`` is the argument a bare token binds to, and ``flags`` are
#: the port parameters the command reads. The contract test compares ``flags``
#: against the signature of the port method named in `_PORT_METHOD`.
COMMANDS: Final[tuple[tuple[str, Handler | None, str | None, tuple[str, ...]], ...]] = (
    ("validate", validate, "", ("--root",)),
    ("hash", registry_hash, "", ("--root",)),
    ("show", show, "", ("--root", "--asset", "--key")),
    ("ls", ls, "", ("--root", "--asset")),
)
