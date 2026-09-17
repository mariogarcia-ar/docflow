"""K8 registry - versioned assets, validated at load, identified by one hash.

The registry is not a config file. It is versioned data whose identity is a hash,
and that hash is a term of every stage's cache key (`sad.md` §5). That is why
this module exists at all: if a prompt could be substituted, defaulted or read
from outside the registry root, a stage could be ``done`` under a setting nothing
recorded - output that changed without the key changing, and therefore a ``done``
nobody can check (`sad.md` §5.1).

Two failures it makes impossible
--------------------------------

- **A missing asset is never defaulted.** *"A missing asset silently substituted
  with an empty one produces a run that completes and extracts nothing, which is
  indistinguishable from a corpus with no extractable fields"*
  (`kernel-cli.md` §9, K8). So a declared-but-absent asset is a failure
  (``asset_missing``) and an empty file is a failure too (``asset_invalid``):
  absent and empty are different facts and neither is an asset.
- **A malformed asset stops the run.** The load returns no ``Registry`` at all,
  not a partially populated one, so there is nothing for a caller to proceed with.

The expected asset set is **data**
----------------------------------

The manifest (``registry/manifest.json``) declares which assets must be present.
It is data rather than a list in this module because the assets themselves -
patterns, prompts, schemas, policies - belong to the Data layer (`S3-T04`). This
module owns the loader and the hash, and knows no family names, no asset kinds and
no document concepts. That is also why nothing here is a domain noun: a registry
keyed by a document concept would be a component wearing the wrong name.

An asset on disk that the manifest does not declare is **refused**, not ignored.
An asset that does not count toward the hash is an asset whose change cannot
invalidate anything, which is the same silent failure one layer down (`sad.md`
§5.1). Refusing it is what keeps *"the registry is the sole source"* checkable
rather than merely stated.

The hash covers content, not location
-------------------------------------

:func:`registry_hash` composes each asset's own content hash, ordered by the
asset's declared key. It does not cover the root's absolute path, file
modification times, the directory's iteration order, or the manifest file's own
bytes - so the same registry content yields the same hash in a different checkout,
on a different filesystem, at a different time. :class:`Registry` deliberately
does **not** carry its root, which makes a path-dependent hash unrepresentable
rather than merely discouraged.

Deliberately out of scope
-------------------------

- **No per-asset hashing.** One hash today. Per-asset hashing would make
  ``--force --stage extract.p`` more precise **and would change the cache-key
  formula**, i.e. re-open Plan 1's gate - `plan-01-kernels.md` §12 open decision
  **#4**. Carried as ``# TODO: [MVP]``; not resolved here.
- **No cache key.** The registry *produces* a hash; the key that consumes it is
  `E03-02` (`S1-T05`).
- **No registry content.** Patterns, prompts, schemas and policies are Plan 3's
  (`S3-T04`). Nothing in this module names one.
- **No corpus policy semantics.** That policy lives in the registry with no CLI
  flag and no environment variable (ADR-009, `prd.md` NFR-06a). The rule is that
  this loader is the only way in; which values exist is not decided here.

PoC stage
---------

Each deliberate shortcut carries a marker naming what must replace it.

"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from docflow.kernels.types import Evidence, KernelResult, Reason

__all__: list[str] = [
    "ASSET_FORMAT_JSON",
    "ASSET_FORMAT_TEXT",
    "MANIFEST_NAME",
    "SUPPORTED_ASSET_FORMATS",
    "Problem",
    "Registry",
    "RegistryAsset",
    "load_registry",
    "registry_hash",
]

#: The manifest's file name inside a registry root. It declares the expected asset
#: set, so that "an asset is missing" is a checkable fact rather than an absence
#: nobody can see.
MANIFEST_NAME: Final[str] = "manifest.json"

#: An asset read as text and accepted when non-empty. The PoC default, because a
#: prompt or a pattern has no structure this layer can check.
ASSET_FORMAT_TEXT: Final[str] = "text"

#: An asset that must parse as JSON and carry its declared required keys.
ASSET_FORMAT_JSON: Final[str] = "json"

#: The formats a manifest may declare. A manifest naming anything else is invalid.
SUPPORTED_ASSET_FORMATS: Final[tuple[str, ...]] = (ASSET_FORMAT_JSON, ASSET_FORMAT_TEXT)

#: Names never treated as assets. A dot-prefixed entry is editor, OS or VCS debris
#: (``.DS_Store``, a ``.git`` directory, an editor swap file) rather than an asset,
#: and the convention is stated here because an undeclared *asset* is refused.
_IGNORED_NAME_PREFIX: Final[str] = "."

#: The two reason codes this module raises, from the closed set of
#: `kernel-cli.md` §5. Both exit ``3``: the call could not legitimately be made.
_CODE_ASSET_MISSING: Final[str] = "asset_missing"
_CODE_ASSET_INVALID: Final[str] = "asset_invalid"


@dataclasses.dataclass(frozen=True, slots=True)
class Problem:
    """One reason a registry cannot be used, before it is turned into a ``Reason``.

    A separate type from :class:`~docflow.kernels.types.Reason` because a load
    finds these *while checking* and reports exactly one of them as the outcome:
    the difference is between a finding on a list and the result of a call.

    It exists so the validators can report *all* their findings rather than
    stopping at the first. A union return such as ``Problem | None`` would have
    made "no problem found" a third state alongside "the loaded registry" and "the
    failure", which is the shape this codebase refuses everywhere else; a list has
    an unambiguous empty case.

    Attributes:
        code: The reason code to report, one of ``asset_missing`` /
            ``asset_invalid``.
        message: The human-readable explanation.
        key: The asset key the finding is about, so a caller can locate it
            without parsing prose.

    """

    code: str
    message: str
    key: str


@dataclasses.dataclass(frozen=True, slots=True)
class RegistryAsset:
    """One registry asset, as loaded.

    The content is kept alongside its hash because ``registry show`` prints the
    asset and ``registry ls`` does not, and re-reading the file to answer the
    first would put a second reader on the load path. The hash is what the
    registry's own identity is composed from.

    Attributes:
        key: The asset's identity, as the manifest declared it. It is a
            registry-root-relative path, which is why the hash can cover it
            without becoming location-dependent.
        content: The file's bytes, exactly as read, before any decoding.
        sha256: The lowercase hexadecimal SHA-256 digest of ``content``.
        format: The declared format, one of :data:`SUPPORTED_ASSET_FORMATS`.

    """

    key: str
    content: bytes
    sha256: str
    format: str


@dataclasses.dataclass(frozen=True, slots=True)
class Registry:
    """A unit of registry content: every declared asset, loaded and validated.

    There is no partially loaded registry. A load either returns this whole
    object or returns a ``Reason``, so a caller cannot proceed with half a
    registry - which is the shape a run that extracts nothing would take.

    The root is deliberately **not** a field: the hash must not depend on where
    the registry lives, and a stored root would make a path-dependent hash
    possible to write by accident.

    Attributes:
        assets: Asset key to :class:`RegistryAsset`, ordered by key so that
            reporting and hashing are both deterministic.

    """

    assets: Mapping[str, RegistryAsset]


def load_registry(root: Path) -> KernelResult[Registry]:
    """Load and validate a registry root, or explain why it cannot be used.

    The checks run in the order that makes the failure attributable: the manifest
    and its declarations, then every declared asset, then the root for assets the
    manifest did not declare. The **first** finding ends the call, because one
    usable outcome is what this function returns - but the validators collect all
    of their findings before that, so the message a caller sees is the first of a
    complete list rather than whichever check happened to run first.

    Args:
        root: The registry root directory, holding the manifest and the assets it
            declares. Nothing is read from outside it.

    Returns:
        A ``KernelResult`` carrying the loaded :class:`Registry` as its value; or,
        when the registry cannot be used, no value and a typed ``Reason`` whose
        code is ``asset_missing`` or ``asset_invalid`` and whose
        ``evidence.observed`` names the offending asset under ``asset_key``. The
        call never returns a partial registry, an empty asset or a stand-in.

    """
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        return _failure(
            Problem(
                _CODE_ASSET_MISSING,
                f"No manifest at {MANIFEST_NAME} under the registry root: without "
                "it there is no declared asset set, and an empty registry would be "
                "indistinguishable from a corpus with nothing extracted.",
                MANIFEST_NAME,
            )
        )

    declarations, manifest_problems = _read_manifest(manifest_path)
    if manifest_problems:
        return _failure(manifest_problems[0])

    assets: dict[str, RegistryAsset] = {}
    asset_problems = _load_assets(root, declarations, assets)
    if asset_problems:
        return _failure(asset_problems[0])

    undeclared = _undeclared_files(root, set(assets))
    if undeclared:
        return _failure(
            Problem(
                _CODE_ASSET_INVALID,
                f"The registry root holds {undeclared[0]!r}, which the manifest "
                "does not declare. An asset outside the manifest does not count "
                "toward the registry hash, so a change to it could not invalidate "
                "anything.",
                undeclared[0],
            )
        )

    ordered = MappingProxyType({key: assets[key] for key in sorted(assets)})
    return KernelResult(
        value=Registry(assets=ordered),
        evidence=_evidence(root, len(declarations), len(assets)),
        reason=None,
    )


def registry_hash(registry: Registry) -> str:
    """Return the one hash that identifies a registry's content.

    Composed from each asset's own content hash, ordered by the asset's declared
    key, so the result depends on the content and on the asset identities and on
    nothing else: not on the root's location, not on modification times, not on
    the order the filesystem returned entries in, and not on the manifest's own
    bytes.

    This is the value the cache key consumes as its ``registry_hash`` term, which
    is what makes an improved prompt show up as a key change instead of as a
    ``done`` stage that is quietly wrong (`sad.md` §5).

    Args:
        registry: The loaded registry to identify.

    Returns:
        The registry's hash as 64 hexadecimal characters.

    """
    digest = hashlib.sha256()
    for key in sorted(registry.assets):
        # Length-prefixed so that two asset keys cannot be confused for one:
        # without it, ("ab", "c") and ("a", "bc") would produce the same digest.
        for piece in (key, registry.assets[key].sha256):
            encoded = piece.encode("utf-8")
            digest.update(str(len(encoded)).encode("ascii"))
            digest.update(b":")
            digest.update(encoded)
    return digest.hexdigest()


def _read_manifest(path: Path) -> tuple[list[dict[str, object]], list[Problem]]:
    """Parse and structurally validate the manifest.

    Args:
        path: The manifest file.

    Returns:
        The asset declarations and every finding about them. An unusable manifest
        yields no declarations and at least one finding.

    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return [], [
            Problem(
                _CODE_ASSET_INVALID,
                f"The manifest is not readable JSON ({error}): a manifest that "
                "cannot be read declares no asset set, and defaulting to one would "
                "decide silently which assets matter.",
                MANIFEST_NAME,
            )
        ]

    if not isinstance(payload, dict) or not isinstance(payload.get("assets"), list):
        return [], [
            Problem(
                _CODE_ASSET_INVALID,
                'The manifest must be an object with an "assets" list.',
                MANIFEST_NAME,
            )
        ]

    declarations: list[dict[str, object]] = []
    problems: list[Problem] = []
    seen: set[str] = set()
    for entry in payload["assets"]:
        problems.extend(_check_declaration(entry, seen))
        if isinstance(entry, dict) and isinstance(entry.get("key"), str):
            declarations.append(entry)
            seen.add(entry["key"])
    return declarations, problems


def _check_declaration(  # pylint: disable=too-many-return-statements
    entry: object, seen: set[str]
) -> list[Problem]:
    """Validate one manifest entry.

    Each check returns its own finding the moment it fails, so the caller reads
    top to bottom and each reason is attributable to one condition. Collapsing the
    branches into one accumulated condition would make the returned message depend
    on the order of a boolean expression rather than on the check that found the
    problem.

    Args:
        entry: The declaration to check.
        seen: Keys already declared, so a duplicate is caught here rather than
            silently collapsing two declarations into one asset.

    Returns:
        The findings about this declaration; empty when it is usable.

    """
    if not isinstance(entry, dict):
        return [_declaration_problem(entry, "is not an object")]

    key = entry.get("key")
    if not isinstance(key, str) or not key:
        return [_declaration_problem(entry, 'has no non-empty string "key"')]

    if key in seen:
        return [_declaration_problem(key, "is declared twice")]

    # The traversal check comes *before* the hidden/absolute one, and the order is
    # load-bearing: ``"../outside.txt".startswith(".")`` is True, so a traversal
    # key was being reported as a hidden one and this branch was unreachable - a
    # caller doing something dangerous was told something merely untidy. Leaving
    # the root is the more serious violation and names the accurate remedy.
    if ".." in Path(key).parts:
        return [_declaration_problem(key, "must not leave the registry root")]

    if key.startswith(_IGNORED_NAME_PREFIX) or Path(key).is_absolute():
        return [
            _declaration_problem(
                key,
                "must be a registry-root-relative path, not an absolute or hidden one",
            )
        ]

    asset_format = entry.get("format", ASSET_FORMAT_TEXT)
    if asset_format not in SUPPORTED_ASSET_FORMATS:
        return [
            _declaration_problem(
                key, f"declares an unsupported format {asset_format!r}"
            )
        ]

    required_keys = entry.get("required_keys", [])
    if asset_format != ASSET_FORMAT_JSON and required_keys:
        return [
            _declaration_problem(
                key, "declares required_keys for an asset that is not JSON"
            )
        ]
    if not isinstance(required_keys, list) or not all(
        isinstance(name, str) and name for name in required_keys
    ):
        return [_declaration_problem(key, "declares required_keys that are not names")]

    return []


def _declaration_problem(entry: object, problem: str) -> Problem:
    """Build the finding for one unusable manifest entry.

    Args:
        entry: The declaration or key the problem is about.
        problem: What is wrong, as a clause.

    Returns:
        The finding.

    """
    return Problem(
        _CODE_ASSET_INVALID,
        f"The manifest entry {entry!r} {problem}.",
        str(entry),
    )


def _load_assets(
    root: Path, declarations: list[dict[str, object]], into: dict[str, RegistryAsset]
) -> list[Problem]:
    """Load and validate every declared asset, collecting the findings.

    Args:
        root: The registry root.
        declarations: The validated manifest declarations.
        into: The mapping to populate with the assets that loaded. Mutated rather
            than returned so that a finding does not have to be threaded through a
            union return.

    Returns:
        Every finding, in declaration order; empty when all assets loaded.

    """
    problems: list[Problem] = []
    for declaration in declarations:
        key = str(declaration["key"])
        path = root / key

        if not path.is_file():
            problems.append(
                Problem(
                    _CODE_ASSET_MISSING,
                    f"The registry declares {key!r} and it is not present under the "
                    "root. Nothing is substituted for it: an asset defaulted to an "
                    "empty one produces a run that completes and extracts nothing.",
                    key,
                )
            )
            continue

        content = path.read_bytes()
        if not content:
            problems.append(
                Problem(
                    _CODE_ASSET_INVALID,
                    f"The registry asset {key!r} is empty. An empty asset is not a "
                    "missing one, and neither is usable: both produce a run that "
                    "extracts nothing.",
                    key,
                )
            )
            continue

        asset_format = str(declaration.get("format", ASSET_FORMAT_TEXT))
        if asset_format == ASSET_FORMAT_JSON:
            json_problems = _check_json_asset(
                key, content, declaration.get("required_keys", [])
            )
            if json_problems:
                problems.extend(json_problems)
                continue

        into[key] = RegistryAsset(
            key=key,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            format=asset_format,
        )
    return problems


def _check_json_asset(key: str, content: bytes, required_keys: object) -> list[Problem]:
    """Check that a JSON asset parses and carries its declared keys.

    Args:
        key: The asset's key, for the failure message and the evidence.
        content: The asset's bytes.
        required_keys: The keys the manifest declares it must carry.

    Returns:
        The findings about this asset; empty when it is usable.

    """
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return [
            Problem(
                _CODE_ASSET_INVALID,
                f"The registry asset {key!r} is not readable JSON ({error}).",
                key,
            )
        ]

    if not isinstance(payload, dict):
        return [
            Problem(
                _CODE_ASSET_INVALID,
                f"The registry asset {key!r} must be a JSON object.",
                key,
            )
        ]

    missing = [
        name
        for name in (required_keys if isinstance(required_keys, list) else [])
        if name not in payload
    ]
    return [
        Problem(
            _CODE_ASSET_INVALID,
            f"The registry asset {key!r} does not carry the required key {name!r}. "
            "A declared key that is absent is not defaulted.",
            key,
        )
        for name in missing
    ]


def _undeclared_files(root: Path, declared: set[str]) -> list[str]:
    """Return the files under the root that the manifest did not declare.

    Args:
        root: The registry root.
        declared: The declared asset keys.

    Returns:
        The undeclared keys, sorted, excluding the manifest and hidden entries.

    """
    if not root.is_dir():
        return []

    found: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        key = str(path.relative_to(root))
        if key == MANIFEST_NAME or any(
            part.startswith(_IGNORED_NAME_PREFIX) for part in Path(key).parts
        ):
            continue
        if key not in declared:
            found.append(key)
    return sorted(found)


def _evidence(root: Path, declared: int, loaded: int) -> Evidence:
    """Build the observation record for one load.

    ``terms`` carries the manifest's own content hash - a real version term for
    this call - and never the root's path, because a path in a term that feeds a
    cache key would make the key location-dependent.

    Args:
        root: The registry root.
        declared: How many assets the manifest declared.
        loaded: How many assets were loaded.

    Returns:
        The evidence for this load.

    """
    manifest_path = root / MANIFEST_NAME
    manifest_sha256 = (
        hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if manifest_path.is_file()
        else ""
    )
    return Evidence(
        terms=MappingProxyType({"manifest_sha256": manifest_sha256}),
        measurements=MappingProxyType(
            {"assets_declared": float(declared), "assets_loaded": float(loaded)}
        ),
        observed=MappingProxyType({"asset_key": None}),
    )


def _failure(problem: Problem) -> KernelResult[Registry]:
    """Build a failed ``KernelResult`` from one finding.

    The offending asset is reported in ``evidence.observed`` as well as in the
    message, so a caller can locate it without parsing prose - assertions target
    the code, never the message (`kernel-cli.md` §5).

    Args:
        problem: The finding to report.

    Returns:
        A failed ``KernelResult`` carrying no value.

    """
    return KernelResult(
        value=None,
        evidence=Evidence(
            terms=MappingProxyType({}),
            measurements=MappingProxyType(
                {"assets_declared": 0.0, "assets_loaded": 0.0}
            ),
            observed=MappingProxyType({"asset_key": problem.key}),
        ),
        reason=Reason(code=problem.code, message=problem.message),
    )
    # TODO: [MVP] The manifest's own shape is validated by hand rather than
    # against a declared schema, and non-JSON assets are accepted as arbitrary
    # bytes because a YAML parser is a runtime dependency this stage does not
    # need. Both the schema and the asset formats belong to `S3-T04`, which owns
    # the content.
    # TODO: [MVP] Per-asset hashing is deliberately absent (plan §12 #4). One hash
    # means a prompt tweak invalidates a schema version: coarse but never wrong.
    # Resolving it toward per-asset changes the cache-key formula and re-opens
    # Plan 1's gate, so it is not a decision this module may take.
