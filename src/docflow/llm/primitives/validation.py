# pylint: disable=duplicate-code
# Reason: this module is a deliberate sibling of ``docflow.ocr.primitives.validation``. Two
# processors may not import each other's internals (`README.md` §7), so the same short rules — the
# fail-fast request check, the typed failure for a missing asset — are written once per processor
# on purpose and neither copy is the other's default.
"""Fail-fast validation of the request, the assets, and what was produced.

Three jobs, one rule: nothing is guessed.

* :func:`validate_llm_input` runs **before any provider call**, so a request that does not name
  its provider, model or template is reported as a typed failure instead of being sent somewhere
  by a default;
* :func:`load_template` and :func:`load_schema` resolve the identifiers against the asset root
  the request declares, and :func:`load_schema` refuses a schema whose rules this processor does
  **not** enforce — a schema with a ``pattern`` this validator ignored would let an invalid answer
  be reported valid, which is the one outcome the whole validation exists to prevent;
* :func:`validate_schema` enforces the supported subset and returns the violations, and
  :func:`validate_llm_result` checks that the assembled result does not contradict itself.

The supported subset is stated rather than implied: ``type``, ``required``, ``properties``,
``additionalProperties``, ``items`` and ``enum``, plus the annotation keywords ``title``,
``description`` and ``default``, which carry no rule. Anything else is reported by name. A
``type`` is a name or a union of names (``["string", "null"]`` is how a nullable field is
declared), and a value satisfies it when it satisfies any one of them.

Failure kinds: a request or an asset that does not resolve is a ``DEPENDENCY_ERROR``; a schema
this processor cannot enforce and an answer that violates one are both ``SCHEMA_ERROR``.

# TODO: [MVP] the subset above is replaced by a real JSON Schema engine when the schema assets
# stop being fixtures; the refusal of unknown keywords is what makes the subset honest until then.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from docflow.llm.contracts import LLMResult
from docflow.llm.primitives.composition import (
    SCHEMA_SUBDIR,
    TEMPLATE_SUBDIR,
)
from docflow.llm.primitives.errors import typed_failure
from docflow.states import StageState

#: Suffix appended to a template identifier to find its asset.
TEMPLATE_SUFFIX: Final[str] = ".md"

#: Suffix appended to a schema identifier to find its asset, as the subplan §6 names it.
SCHEMA_SUFFIX: Final[str] = ".schema.json"

#: The schema keywords this processor enforces. The first six carry a rule; the last three are
#: annotations and cannot be violated.
ENFORCED_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"type", "required", "properties", "additionalProperties", "items", "enum"}
)
ANNOTATION_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"title", "description", "default"}
)
SUPPORTED_KEYWORDS: Final[frozenset[str]] = ENFORCED_KEYWORDS | ANNOTATION_KEYWORDS


def validate_llm_input(request: Any) -> None:
    """Fail fast when the request does not name what it needs, before any provider call.

    Args:
        request: The inference request, typed loosely so the check is about its *content*.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when the provider, the model or the template
            is missing or blank. There is no default provider and no default model: a call sent to
            a guessed one would answer a question nobody asked.
    """
    missing = [
        field
        for field in ("provider", "model", "template")
        if not str(getattr(request, field, "") or "").strip()
    ]
    if missing:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            "the request does not name everything the call needs",
            recoverable=False,
            metadata={"missing": missing},
        )


def load_template(template: str, assets_dir: Path) -> str:
    """Return the template asset's text.

    Args:
        template: The template identifier, e.g. ``"simple_extract"``, without its suffix.
        assets_dir: The asset root the request declares.

    Returns:
        The template text, verbatim.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when the asset is missing or cannot be read.
    """
    path = assets_dir / TEMPLATE_SUBDIR / f"{template}{TEMPLATE_SUFFIX}"
    try:
        return path.read_text(encoding="utf-8")
    except OSError as unreadable:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"the template {template!r} does not resolve to a readable asset",
            recoverable=False,
            metadata={
                "template": template,
                "path": str(path),
                "os_error": str(unreadable),
            },
        ) from unreadable


def load_schema(schema: str | None, assets_dir: Path) -> dict[str, Any] | None:
    """Return the loaded schema, or ``None`` when the request names no schema.

    Args:
        schema: The schema identifier, e.g. ``"simple"``, or ``None``.
        assets_dir: The asset root the request declares.

    Returns:
        The schema document, once its own shape and its keyword set have been checked.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when the asset is missing or is not a JSON
            object, and ``SCHEMA_ERROR`` when it uses a keyword this processor does not enforce.
    """
    if schema is None:
        return None
    path = assets_dir / SCHEMA_SUBDIR / f"{schema}{SCHEMA_SUFFIX}"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except OSError as unreadable:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"the schema {schema!r} does not resolve to a readable asset",
            recoverable=False,
            metadata={"schema": schema, "path": str(path), "os_error": str(unreadable)},
        ) from unreadable
    except json.JSONDecodeError as malformed:
        raise typed_failure(
            "SCHEMA_ERROR",
            f"the schema {schema!r} is not valid JSON",
            recoverable=False,
            metadata={
                "schema": schema,
                "path": str(path),
                "json_error": str(malformed),
            },
        ) from malformed
    if not isinstance(document, dict):
        raise typed_failure(
            "SCHEMA_ERROR",
            f"the schema {schema!r} is not a JSON object",
            recoverable=False,
            metadata={"schema": schema, "path": str(path)},
        )
    _refuse_unsupported_keywords(document, schema=schema, path="$")
    return document


def _refuse_unsupported_keywords(
    document: Mapping[str, Any], *, schema: str, path: str
) -> None:
    """Fail by name when a schema uses a keyword this processor does not enforce.

    A validator that ignored a rule would report an answer valid under a schema it never applied.
    Refusing is the only honest option: the request has to change, not the verdict.

    Raises:
        LLMPrimitiveError: With ``SCHEMA_ERROR`` naming the keyword and where it was used.
    """
    unsupported = sorted(set(document) - SUPPORTED_KEYWORDS)
    if unsupported:
        raise typed_failure(
            "SCHEMA_ERROR",
            f"the schema {schema!r} uses keywords this processor does not enforce",
            recoverable=False,
            metadata={
                "schema": schema,
                "path": path,
                "unsupported": unsupported,
            },
        )
    for name, sub_schema in (document.get("properties") or {}).items():
        if isinstance(sub_schema, Mapping):
            _refuse_unsupported_keywords(
                sub_schema, schema=schema, path=f"{path}.properties.{name}"
            )
    items = document.get("items")
    if isinstance(items, Mapping):
        _refuse_unsupported_keywords(items, schema=schema, path=f"{path}.items")


def validate_schema(value: Any, schema: Mapping[str, Any]) -> list[str]:
    """Return the ways ``value`` violates ``schema``; an empty list means it satisfies it.

    The subset :data:`ENFORCED_KEYWORDS` names is applied recursively, and a violation always
    names the path it was found at, because "the response was invalid" is not a usable verdict.

    Args:
        value: The parsed response.
        schema: The loaded schema.

    Returns:
        One message per violation, in path order.
    """
    return _violations(value, schema, path="$")


def _violations(value: Any, schema: Mapping[str, Any], *, path: str) -> list[str]:
    """Return the violations of ``schema`` at ``path``, recursion included."""
    found: list[str] = []
    expected = schema.get("type")
    if expected is not None and not _matches_declared_type(value, expected):
        return [f"{path}: expected {_type_label(expected)}, got {_type_name(value)}"]
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{path}: {value!r} is not one of {schema['enum']!r}")
    if isinstance(value, Mapping):
        found.extend(_mapping_violations(value, schema, path=path))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = schema.get("items")
        if isinstance(items, Mapping):
            for index, item in enumerate(value):
                found.extend(_violations(item, items, path=f"{path}[{index}]"))
    return found


def _mapping_violations(
    value: Mapping[str, Any], schema: Mapping[str, Any], *, path: str
) -> list[str]:
    """Return the violations of an object against ``required`` and ``properties``."""
    found = [
        f"{path}: required property {name!r} is missing"
        for name in schema.get("required", [])
        if name not in value
    ]
    properties = schema.get("properties") or {}
    for name, sub_schema in properties.items():
        if name in value and isinstance(sub_schema, Mapping):
            found.extend(_violations(value[name], sub_schema, path=f"{path}.{name}"))
    extra = sorted(set(value) - set(properties))
    if extra and schema.get("additionalProperties") is False:
        found.extend(
            f"{path}: property {name!r} is not allowed by the schema" for name in extra
        )
    return found


def _is_array(value: Any) -> bool:
    """Return whether ``value`` is a JSON array rather than a string or an object."""
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _is_integer(value: Any) -> bool:
    """Return whether ``value`` is a JSON integer; a ``bool`` is not one."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    """Return whether ``value`` is a JSON number; a ``bool`` is not one."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


#: How each JSON type name is recognised. A table rather than a chain of ``if``s: the mapping is
#: the whole content of the check, so a reader sees every type it knows at once.
_TYPE_CHECKS: Final[dict[str, Callable[[Any], bool]]] = {
    "string": lambda value: isinstance(value, str),
    "boolean": lambda value: isinstance(value, bool),
    "integer": _is_integer,
    "number": _is_number,
    "object": lambda value: isinstance(value, Mapping),
    "array": _is_array,
    "null": lambda value: value is None,
}

#: The names :func:`_type_name` reports, in the order they are tried. Order matters: a ``bool`` is
#: an ``int`` in Python and a JSON ``integer`` is also a JSON ``number``, so the narrower name has
#: to come first.
_TYPE_NAMES: Final[tuple[tuple[str, Callable[[Any], bool]], ...]] = (
    ("null", lambda value: value is None),
    ("boolean", lambda value: isinstance(value, bool)),
    ("object", lambda value: isinstance(value, Mapping)),
    ("array", _is_array),
    ("integer", lambda value: isinstance(value, int)),
    ("number", lambda value: isinstance(value, float)),
)


def _matches_type(value: Any, expected: str) -> bool:
    """Return whether ``value`` has the JSON type ``expected`` names.

    A name the table does not know constrains nothing, which is safe only because
    :func:`load_schema` refuses a schema using a keyword this processor does not enforce before
    any call is made.
    """
    check = _TYPE_CHECKS.get(expected)
    return True if check is None else check(value)


def _matches_declared_type(value: Any, expected: Any) -> bool:
    """Return whether ``value`` has a JSON type the schema's ``type`` declares.

    A ``type`` is a name or a union of names, and a union is satisfied by any one of them — so
    ``["string", "null"]`` admits a string and the real JSON ``null``, and nothing else.
    """
    if isinstance(expected, str):
        return _matches_type(value, expected)
    if isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        return any(_matches_type(value, name) for name in expected)
    return True


def _type_label(expected: Any) -> str:
    """Return the schema's ``type`` as a violation message reads it."""
    if isinstance(expected, str):
        return expected
    return " or ".join(str(name) for name in expected)


def _type_name(value: Any) -> str:
    """Return a readable JSON type name for ``value``."""
    for name, matches in _TYPE_NAMES:
        if matches(value):
            return name
    return "string"


def validate_llm_result(result: LLMResult) -> None:
    """Check that an assembled result does not contradict itself.

    Args:
        result: The result about to be returned.

    Raises:
        LLMPrimitiveError: With ``INTERNAL_ERROR`` when a success carries no attempt, when the
            schema verdict disagrees with the schema violations, or when a failure carries no
            typed error. Each of those would make the result read as an answer nothing produced.
    """
    contradictions: list[str] = []
    if result.status == StageState.SUCCESS and not result.attempts:
        contradictions.append("a successful run recorded no attempt")
    if result.schema_valid and result.validation_errors:
        contradictions.append("a valid schema verdict carries violations")
    if not result.schema_valid and not result.validation_errors:
        contradictions.append("an invalid schema verdict names no violation")
    if result.status == StageState.FAILED and not result.errors:
        contradictions.append("a failed run recorded no typed error")
    if contradictions:
        raise typed_failure(
            "INTERNAL_ERROR",
            "the assembled result contradicts itself",
            recoverable=False,
            metadata={"contradictions": contradictions},
        )
