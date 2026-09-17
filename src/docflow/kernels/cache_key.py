"""The 7-term cache key - what makes a stage's result a pure function of its key.

Frozen by `plans/README.md` §3 (Plan 1 row): *the 7-term cache key*. Plan 2's
escalation ladder is expressed entirely in these terms and may not change the
formula, so this module is a contract, not an implementation detail.

The seven terms are the seven slots of `sad.md` §5:

$$key = H(\\;\\text{input hash} \\;\\|\\; \\text{kernel id} \\;\\|\\;
\\text{kernel version} \\;\\|\\; \\text{adapter revision} \\;\\|\\;
\\text{params} \\;\\|\\; \\text{registry hash} \\;\\|\\;
\\text{model revision}\\;)$$

(``sad.md``'s term table prints six rows because its *"kernel id / version"* row
covers two slots of the formula. The count the plan fixes and the tests assert is
**seven**, and each slot is a field below.)

Why two of them are load-bearing
--------------------------------

``sad.md`` §5 names them: *"The last two are the ones usually missing, and they
are the ones that produce the failure this design exists to prevent: a stage that
is ``done`` and no longer correct."*

- **registry hash** — an improved prompt changes the registry hash, so every
  affected key changes and the ledger's completion claims become *visibly* stale
  instead of quietly wrong (`sad.md` §5.1).
- **model revision** — ``qwen2.5`` is a **moving tag**; the digest is the
  identity. Keying on the tag would let a swapped model reuse the previous
  model's answers under a key that never changed.

Both are mandatory and neither has a default. Dropping either as *"always the
same"* produces a correct-looking run that reuses an answer computed under
different prompts or a different model, which is why the two get their own tests
rather than being covered by the general one.

No construction path defaults a term
------------------------------------

:class:`CacheKeyTerms` declares seven fields with **no defaults**, so a missing
term is a ``TypeError`` from the generated ``__init__`` rather than a substituted
value. ``__post_init__`` then refuses an empty string on any of the seven,
because ``""`` is the shape a silent stand-in takes and there is no such thing as
an empty hash, an empty kernel id or an empty model revision. Params alone may be
an empty mapping: a stage with no settings is a real state, and an empty mapping
is not the same fact as an absent one.

There is no ``default_terms()``, no ``with_fallback()`` and no module constant
holding a key. A caller that cannot produce a term cannot produce a key.

The encoding is canonical, and the key is stable
------------------------------------------------

Each piece enters the digest length-prefixed, so two different term sets cannot
encode to the same bytes: without the prefix, the input hash ``"ab"`` with kernel
id ``"c"`` would collide with input hash ``"a"`` and kernel id ``"bc"``. Params
are ordered by name, so a mapping's iteration order cannot change the key.

The digest is SHA-256 over those bytes, never Python's ``hash()``: ``hash()`` is
salted per process for strings, so a key built on it would differ between runs of
the same program. Stability across processes is an acceptance criterion here, and
it is a property of the primitive rather than of care taken at the call site.

Deliberately out of scope
-------------------------

- **No forced invalidation.** ``--force``, ``--stage``, ``--only`` and their
  downstream invalidation are `S3-T08` (Plan 3). This module produces the key; the
  override that consults it is not here. No ``--rebuild``-shaped flag exists:
  ``# TODO: [MVP]`` (`prd.md` §7).
- **No engine, model or threshold term as a setting.** No default or fallback
  model, engine or threshold exists anywhere (`plans/README.md` §2), so no term
  can resolve to one. **Never.**
- **No caching layer.** The key decides *when* work is skipped; K7 holds the
  bytes. A caching layer as infrastructure is ``# TODO: [RELEASE]``.
- **No hashing of registry assets.** How K8 turns its own content into a hash is
  `E03-01`; this module consumes the result.
- **No domain noun.** **Never**.

"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

__all__: list[str] = [
    "CACHE_KEY_TERM_NAMES",
    "CacheKeyTerms",
    "cache_key",
    "make_terms",
    "terms_as_mapping",
]

#: The seven term names, in the order `sad.md` §5's formula composes them. A
#: declaration of the set, so the count the plan fixes can be read without
#: counting fields, and so the encoding order has one stated source.
CACHE_KEY_TERM_NAMES: Final[tuple[str, ...]] = (
    "input_hash",
    "kernel_id",
    "kernel_version",
    "adapter_revision",
    "params",
    "registry_hash",
    "model_revision",
)

#: The terms that are single string values. Derived from the tuple above, so a
#: name added there cannot silently escape the empty-string check.
_STRING_TERM_NAMES: Final[tuple[str, ...]] = tuple(
    name for name in CACHE_KEY_TERM_NAMES if name != "params"
)


@dataclasses.dataclass(frozen=True, slots=True)
class CacheKeyTerms:
    """The seven terms one stage's key is composed from.

    Every field is required and none has a default, so a term cannot be omitted.
    Each string term must be non-empty, so a term cannot be neutralized with a
    stand-in either.

    Attributes:
        input_hash: The upstream artifact's sha256, as K7 addresses it. The same
            stage on different bytes is different work.
        kernel_id: The kernel's identity, e.g. "pdf".
        kernel_version: The kernel's version. A bug fix must invalidate what the
            bug produced, which is why this is separate from ``kernel_id``.
        adapter_revision: The engine's revision, e.g. "docling 2.14.0". The same
            call on a different engine version is a different computation.
        params: The stage's own settings, e.g. ``{"dpi": "300"}``. Ordered by
            name when encoded, so iteration order cannot change the key.
        registry_hash: K8's hash over the registry content, from
            :func:`docflow.kernels.registry.registry_hash`. The prompt, the
            pattern, the schema - a corpus tuning change is a key change.
        model_revision: The resolved immutable model identity, e.g. an Ollama
            digest. **Not** the tag: a tag such as ``qwen2.5`` moves, so keying on
            it would let a swapped model reuse the previous model's answers.

    Raises:
        ValueError: If any string term is the empty string, or if ``params`` is
            not a mapping of string to string.

    """

    input_hash: str
    kernel_id: str
    kernel_version: str
    adapter_revision: str
    params: Mapping[str, str]
    registry_hash: str
    model_revision: str

    # The same PoC property ``Evidence`` carries, stated rather than discovered:
    # ``params`` holds a mapping, so a term set is **not hashable**. It is still
    # frozen and comparable by value, which is all a cache key needs - the key is
    # a string, and that is what gets stored and compared.
    # TODO: [MVP] If a term set ever needs to be a dict key or a set member, freeze
    # ``params`` into an immutable mapping type rather than adding ``__hash__``
    # over a mutable one.

    def __post_init__(self) -> None:
        """Refuse an empty or ill-typed term.

        Called by the generated ``__init__``, and still reachable on a frozen
        slotted dataclass: the fields are already set, so raising here means no
        key can ever be composed from a neutralized term.

        Raises:
            ValueError: On an empty string term, a non-string term, or params that
                are not a mapping of string to string.

        """
        for name in _STRING_TERM_NAMES:
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"The cache-key term {name!r} must be a non-empty string "
                    f"(got {value!r}). Every one of the seven terms is required: a "
                    "term dropped as 'always the same' produces a correct-looking "
                    "run that reuses an answer computed under different inputs."
                )

        if not isinstance(self.params, Mapping):
            raise ValueError(
                f"params must be a mapping of string to string (got {self.params!r})"
            )

        for name, value in self.params.items():
            if not isinstance(name, str) or not name:
                raise ValueError(f"params has a non-string name: {name!r}")
            if not isinstance(value, str):
                raise ValueError(
                    f"params[{name!r}] must be a string (got {value!r}): a "
                    "non-string would need a canonical encoding this module does "
                    "not define, and a silent repr is not one."
                )


def cache_key(terms: CacheKeyTerms) -> str:
    """Compose the key from exactly the seven terms.

    Pure and total: the same terms always produce the same key, in any process and
    on any machine, because the digest is taken over a canonical byte encoding
    rather than over Python's per-process-salted ``hash()``.

    Args:
        terms: The seven terms. There is no second parameter and no keyword with a
            default, so there is no way to compose a key with a term omitted.

    Returns:
        The key as 64 hexadecimal characters.

    """
    digest = hashlib.sha256()
    for name in CACHE_KEY_TERM_NAMES:
        if name == "params":
            # The count is absorbed too: an empty mapping and a mapping whose
            # entries are all empty cannot encode to the same bytes.
            _absorb(digest, str(len(terms.params)))
            for param_name in sorted(terms.params):
                _absorb(digest, param_name)
                _absorb(digest, terms.params[param_name])
        else:
            _absorb(digest, getattr(terms, name))
    return digest.hexdigest()


def terms_as_mapping(terms: CacheKeyTerms) -> dict[str, object]:
    """Return the terms as a plain, JSON-encodable mapping.

    This is what makes the key inspectable *before* any expensive call: the
    ``--resolve-only`` envelope reports ``cache_key_terms`` without executing
    anything (`kernel-cli.md` §8), and that is how a caller answers *which
    revision answered, and therefore which key*.

    A plain ``dict`` rather than the frozen mapping the dataclass holds:
    ``MappingProxyType`` has no default JSON encoder (`E01-01` recorded that
    obligation), and an envelope that cannot be serialized is not an inspection
    surface.

    Args:
        terms: The terms to expose.

    Returns:
        Term name to value, with ``params`` as a plain mapping, in the formula's
        order.

    """
    exposed: dict[str, object] = {}
    for name in CACHE_KEY_TERM_NAMES:
        value = getattr(terms, name)
        exposed[name] = dict(value) if name == "params" else value
    return exposed


def make_terms(  # pylint: disable=too-many-arguments
    *,
    input_hash: str,
    kernel_id: str,
    kernel_version: str,
    adapter_revision: str,
    params: Mapping[str, str] | None = None,
    registry_hash: str,
    model_revision: str,
) -> CacheKeyTerms:
    """Build the seven terms, with params the only optional field.

    The seven parameters *are* the contract: the formula has seven terms, so a
    builder with fewer would be a builder that supplies one. The count is the
    point rather than an accumulation, which is why the default argument ceiling
    does not apply here.

    Exists so that the two terms that must never be defaulted cannot be reached
    through a signature that makes them look optional: ``registry_hash`` and
    ``model_revision`` are keyword-only and have no default, so omitting either is
    a ``TypeError`` at the call site rather than a substitute somewhere inside.

    Args:
        input_hash: The upstream artifact's sha256.
        kernel_id: The kernel's identity.
        kernel_version: The kernel's version.
        adapter_revision: The engine's revision.
        params: The stage's own settings, or None for a stage with none. None
            becomes an empty mapping, which is a real value, not a stand-in.
        registry_hash: K8's registry hash.
        model_revision: The resolved immutable model identity, never the tag.

    Returns:
        The composed terms.

    """
    return CacheKeyTerms(
        input_hash=input_hash,
        kernel_id=kernel_id,
        kernel_version=kernel_version,
        adapter_revision=adapter_revision,
        params=MappingProxyType(dict(params)) if params is not None else _NO_PARAMS,
        registry_hash=registry_hash,
        model_revision=model_revision,
    )


#: The empty params mapping, shared so that two stages with no settings compare
#: equal by value rather than by identity.
_NO_PARAMS: Final[Mapping[str, str]] = MappingProxyType({})


def _absorb(digest: hashlib._Hash, piece: str) -> None:
    """Feed one length-prefixed piece into a digest.

    Length-prefixed so that two different term sets cannot encode to the same
    bytes: without the prefix, an input hash of ``"ab"`` with kernel id ``"c"``
    would collide with an input hash of ``"a"`` with kernel id ``"bc"``, and two
    genuinely different computations would share a key.

    Args:
        digest: The digest to feed.
        piece: The string to absorb.

    """
    encoded = piece.encode("utf-8")
    digest.update(str(len(encoded)).encode("ascii"))
    digest.update(b":")
    digest.update(encoded)
    # TODO: [MVP] There is no formula version constant. The seven terms are the
    # frozen contract, so an eighth would breach it; but a change to this
    # encoding after Plan 1's gate would change every key without changing any
    # term. If the encoding ever needs to change, add a version and re-open the
    # gate deliberately rather than editing silently.
