"""Verify the `scripts/poc-flow/artifacts/` pair against each other.

A tool, not a test: it reports, it does not assert. The suite's assertions live in
the repo's `tests/`; this script runs the same checks over the artifacts the flow
ships, and is the port of `tests/kernels/test_committed_registry.py`'s agreement
rules to the `poc-flow` tree — which is **not** in `testpaths`, so no pytest suite
collects it.

The agreement worth checking is the one the extraction pair relies on: a prompt and
a schema are two artifacts (the prompt says what to look for, the schema says what
shape the answer must have), and nothing generates one from the other. They drift
silently — the model is asked for a field the schema forbids, or a field the schema
requires is never described.

Usage:
    python tests/fixtures/verify_pocflow.py
"""

from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parents[2]

ARTIFACTS = ROOT / "scripts" / "poc-flow" / "artifacts"

EXTRACTION_PROMPT = ARTIFACTS / "prompts" / "extract_texto.txt"
EXTRACTION_SCHEMA = ARTIFACTS / "schema" / "extraction.json"
REVIEW_PROMPT = ARTIFACTS / "prompts_reviews" / "review_texto.txt"
REVIEW_SCHEMA = ARTIFACTS / "schema_review" / "review.json"

#: The placeholders each prompt must declare, or the driver's substitution cannot
#: place the material it is about.
PROMPT_PLACEHOLDERS = {
    EXTRACTION_PROMPT: ["{text}"],
    REVIEW_PROMPT: ["{text}", "{proposal}"],
}


def _problems() -> list[str]:  # pylint: disable=too-many-locals
    problems: list[str] = []

    schema = json.loads(EXTRACTION_SCHEMA.read_text(encoding="utf-8"))
    prompt = EXTRACTION_PROMPT.read_text(encoding="utf-8")

    # 1. The prompt names every field the schema requires.
    missing = sorted(name for name in schema["required"] if name not in prompt)
    if missing:
        problems.append(f"schema requires {missing} that the prompt never names")

    # 2. The schema declares every field the prompt names.
    undeclared = sorted(name for name in schema["properties"] if name not in prompt)
    if undeclared:
        problems.append(f"schema declares {undeclared} that the prompt never names")

    # 3. Every field is required: a partial answer reads as a missing field, not
    #    as a model that stopped early.
    if set(schema["properties"]) != set(schema["required"]):
        problems.append("properties and required are not the same set")

    # 4. Every amount is a string.
    amounts = [
        "subtotal",
        "iva",
        "impuestos_internos",
        "percepcion_iibb",
        "otros_impuestos",
        "monto_no_gravado",
        "importe_total_facturado",
    ]
    for name in amounts:
        if (
            name in schema["properties"]
            and schema["properties"][name]["type"] != "string"
        ):
            problems.append(f"{name!r} is not declared a string")

    # 5. Each prompt carries the placeholder its driver substitutes.
    for prompt_path, placeholders in PROMPT_PLACEHOLDERS.items():
        text = prompt_path.read_text(encoding="utf-8")
        for placeholder in placeholders:
            if placeholder not in text:
                problems.append(f"{prompt_path.name} carries no {placeholder!r}")

    # 6. The review schema exposes the verdicts the engine reads.
    review = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
    verdicts = review.get("properties", {}).get("field_verdicts", {})
    enum = (
        verdicts.get("items", {})
        .get("properties", {})
        .get("verdict", {})
        .get("enum", [])
    )
    if set(enum) != {"agree", "disagree", "uncertain"}:
        problems.append(
            f"review schema enum is {enum}, expected agree|disagree|uncertain"
        )

    # 7. The schema-visual templates are placeholders, never keys.
    for directory in ("schema-visual", "schema-visual_reviews"):
        for path in sorted((ARTIFACTS / directory).glob("*.json")):
            if not path.stem.startswith("_"):
                problems.append(
                    f"{path.name} in {directory} is not a _placeholder; a real "
                    "key must be (emisor, tipo, fingerprint)"
                )

    return problems


def main() -> int:
    """Report the prompt↔schema agreement and exit non-zero on any drift."""
    problems = _problems()
    if not problems:
        print("poc-flow artifacts agree: every prompt↔schema pair is in step.")
        return 0
    print(f"{len(problems)} problem(s):")
    for problem in problems:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
