"""The **committed** registry, checked against the code that consumes it.

`tests/kernels/test_registry.py` (49 tests) exercises K8's loader against registries
built in `tmp_path` — every branch of the manifest validation, on fixtures the test
itself writes. That is the right way to test a *loader*.

This file tests something the loader cannot: whether the assets this repository
actually **ships** are consistent with each other and with the drivers that read them.
A registry can pass all 49 of those tests and still carry a schema whose fields the
prompt never mentions — the loader checks shapes, not agreements.

The specific agreement worth a test is the one the extraction pair relies on: a prompt
and a schema are **two artifacts** (the prompt says what to look for, the schema says
what shape the answer must have), and nothing generates one from the other. So they
can drift, and the drift is silent — the model is asked for a field the schema forbids,
or a field the schema requires is never described.

Measured motivation: the pair replaced a hardcoded one-line prompt and a two-field
schema, under which the same document and model returned `1789830`, `1789830`, then
`17898` for a total the document prints as `$ 17.898,30`.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from docflow.kernels.registry import load_registry

# `redefined-outer-name` fires because every test takes the fixture below as a
# parameter with the fixture's own name — which is how pytest is meant to be used, and
# the same relaxation `tests/adapters/test_frontier.py` declares for the same reason.
# Suppressed here rather than project-wide: it is a genuine smell everywhere else.
# pylint: disable=redefined-outer-name

#: The committed registry root. Derived from this file's own location so the test
#: works from any working directory, the same rule `scripts/poc/_lib.py` follows.
ROOT = pathlib.Path(__file__).resolve().parents[2] / "registry"

PROMPT_KEY = "prompts/extraction/invoice.txt"
SCHEMA_KEY = "schemas/extraction/invoice.json"


@pytest.fixture(scope="module")
def loaded():
    """Load the committed registry once, as the drivers load it.

    Returns:
        Asset key to the loaded asset.

    """
    result = load_registry(ROOT)

    assert result.value is not None, (
        f"the committed registry does not load: "
        f"{result.reason.code if result.reason else '?'} "
        f"{result.reason.message if result.reason else ''}"
    )
    return result.value.assets


def test_the_committed_registry_loads(loaded) -> None:
    """The registry this repository ships is one K8 accepts."""
    assert PROMPT_KEY in loaded
    assert SCHEMA_KEY in loaded


def test_the_prompt_declares_every_field_the_schema_requires(loaded) -> None:
    """No field is required by the schema and absent from the prompt.

    This is the drift that costs most, because a schema's `required` is a
    **constraint the model must satisfy**: a name in there that the prompt never
    describes makes every call ask for something the instructions did not define, and
    the answer is a guess the caller cannot tell from a reading.

    """
    prompt = loaded[PROMPT_KEY].content.decode("utf-8")
    schema = json.loads(loaded[SCHEMA_KEY].content.decode("utf-8"))

    missing = sorted(name for name in schema["required"] if name not in prompt)

    assert not missing, (
        f"the schema requires {missing}, which the prompt never names. The two are "
        "separate artifacts on purpose, so this is the test that keeps them in step."
    )


def test_the_schema_and_the_prompt_agree_on_the_field_set(loaded) -> None:
    """The schema's properties and the prompt's list are the same set.

    The other direction from the test above: a field the *prompt* names but the schema
    does not declare is one the model may be asked for and then forbidden to answer —
    and with `additionalProperties: false` it is dropped, so it reads as *the model
    found nothing* rather than as *the schema refused it*.

    """
    prompt = loaded[PROMPT_KEY].content.decode("utf-8")
    schema = json.loads(loaded[SCHEMA_KEY].content.decode("utf-8"))

    undeclared = sorted(name for name in schema["properties"] if name not in prompt)

    assert not undeclared, (
        f"the schema declares {undeclared} that the prompt never names."
    )
    assert set(schema["properties"]) == set(schema["required"]), (
        "every field is required: a partial answer here would read as a document that "
        "lacks the field rather than as a model that stopped early"
    )


def test_the_amounts_are_strings_because_numbering_loses_the_printed_value(
    loaded,
) -> None:
    """Every amount is a `string`, and that is a measured decision.

    A receipt prints `17.898,30`. Declared as `number` the same model returns
    `17898.3` — the trailing zero gone and the separator normalised, so the value is
    no longer what the document shows. Declared as `string` it returns `17898.30` as
    printed.

    The assertion is on the **type of every money field**, not on one example, because
    the mistake is easy to reintroduce on a field-by-field basis and a single sample
    would not catch the next one.

    """
    schema = json.loads(loaded[SCHEMA_KEY].content.decode("utf-8"))
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
        assert schema["properties"][name]["type"] == "string", (
            f"{name!r} is declared "
            f"{schema['properties'][name]['type']!r}; a number drops the printed "
            "decimal separator and the trailing zeros"
        )


def test_the_prompt_carries_the_placeholder_the_driver_substitutes(loaded) -> None:
    """The prompt marks where the document goes, and the driver looks for it.

    `batch.py` refuses a prompt without this placeholder — a one-line prompt with the
    text appended is what the old hardcoded version did, and the delimiter is what
    lets the model tell the instructions from the material they are about.

    """
    prompt = loaded[PROMPT_KEY].content.decode("utf-8")

    assert "{text}" in prompt
