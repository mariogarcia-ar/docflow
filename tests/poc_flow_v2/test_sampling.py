"""The sampling dials, and the wiring that makes them reach the adapter.

Split out of `test_gates.py` because the subject is different: those gates check
the **registry** (prompts, schemas, drift), and these check the **call**.

Two directions, both needed:

- the dial must be **declared before the calls are made**, because the adapter
  reads the environment at call time — a dial set afterwards changes nothing;
- the name must be the one the **adapter actually reads**. A constant that
  spells the prefix correctly but drifts from `_options_from_environment` would
  set a variable nothing consumes and read as configured.
"""

from __future__ import annotations

import os
import pathlib

import pytest
from flow.artifacts import load_artifacts
from flow.config import DEFAULT_CONFIG
from flow.extract import extract
from flow.material import TIER_NATIVE, Material
from flow.sampling import NUM_CTX, SAMPLING_ENV_PREFIX, apply_sampling

from docflow.adapters import ollama
from docflow.kernels.types import Bytes, Evidence, KernelResult

#: The variable both sides must agree on. Read from the prefix the flow exports,
#: so the test names what the flow names.
_NUM_CTX_VARIABLE = f"{SAMPLING_ENV_PREFIX}NUM_CTX"


class _RecordingEngine:
    """A stand-in engine that records the environment each call runs under.

    It answers with an empty object, so every lane parses a value and the caller
    walks its whole path. It records ``num_ctx`` **at call time** — not at
    construction — because that is when the adapter reads it, and a test that
    sampled the environment once could not tell a dial applied at wiring time
    from one applied afterwards.
    """

    def __init__(self) -> None:
        self.windows: list[str | None] = []

    def _answer(self) -> KernelResult[dict[str, object]]:
        self.windows.append(os.environ.get(_NUM_CTX_VARIABLE))
        return KernelResult(
            value={},
            evidence=Evidence(terms={}, measurements={}, observed={}),
            reason=None,
        )

    def structured(self, _model, _prompt, _schema):
        """Answer one structured call, recording the window in force."""
        return self._answer()

    def vision(self, _model, _prompt, _images, _schema):
        """Answer one vision call, recording the window in force."""
        return self._answer()


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from *no* declared window.

    Without this, a developer's own exported ``DOCFLOW_OLLAMA_NUM_CTX`` would
    decide what these tests observe, and the precedence test in particular would
    pass or fail by machine.
    """
    monkeypatch.delenv(_NUM_CTX_VARIABLE, raising=False)


def _material() -> Material:
    """A text document with one image, so every lane has reason to run."""
    return Material(
        kind="pdf",
        tier=TIER_NATIVE,
        text="FACTURA A 0001-00000001 EMISOR S.A. CUIT 20-22087601-3",
        route="layout_text",
        pages_read=1,
        pages_total=1,
        images=[Bytes(b"x", "image/png")],
        notes=[],
    )


def test_every_model_call_runs_under_a_declared_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every model call runs under a declared window, not the runtime's default.

    The defect this guards, measured: undeclared, this runtime loads the model at
    **4096** — while the model declares 131072 for its family, so the number in
    force was neither the model's nor the caller's. Measured on the `desglose`
    step, a reasoning generation came back `done_reason: length`, the adapter
    reported `truncated_output`, and all nine of the step's fields were lost —
    the critical amount among them, because §6.4's arithmetic reads its
    components from that same step.

    The mutation this test is built against is **removing the declaration** —
    the state the flow was in. Measured: the gate fails with every call under
    ``None``, the runtime's own window. It asserts on what each **call** saw and
    not on the fact that a variable was set, because the adapter reads its
    options at call time: a dial set *after* the calls would leave it satisfied
    and the run unchanged. (Moving the call after the constructor, by contrast,
    does **not** fail it — correctly, since the adapter does not read the
    environment at construction. An earlier version of this test claimed
    otherwise in prose; the mutation showed the prose was wrong.)
    """
    engine = _RecordingEngine()
    monkeypatch.setattr("flow.extract.OllamaEngine", lambda: engine)

    extract(_material(), DEFAULT_CONFIG, load_artifacts())

    assert engine.windows, "no model was called, so the wiring is unproven"
    assert all(window == str(NUM_CTX) for window in engine.windows), (
        f"a call ran under {engine.windows} instead of {NUM_CTX}: the dial is "
        "never declared, or declared after the calls were made"
    )


def test_an_operators_window_is_not_overwritten(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exported value wins, so the dial stays reachable from outside.

    `.env.example` states the precedence — *CLI flag → environment → file →
    default* — and a library that overwrote the environment would invert it: the
    one place an operator tunes a run without editing code would be silently
    clobbered by the flow's own default.
    """
    monkeypatch.setenv(_NUM_CTX_VARIABLE, "2048")

    apply_sampling()

    assert os.environ[_NUM_CTX_VARIABLE] == "2048"


def test_the_declared_prefix_is_the_one_the_adapter_reads() -> None:
    """The constant is a contract with the adapter, so it is read from it.

    The flow can only name this variable because `_options_from_environment`
    declares it. Spelling the prefix here independently would let the two drift:
    the flow would set a variable with no consumer, every call would run at the
    runtime's default, and *configured* would read exactly like *not
    configured*. Reading the adapter's own option tuple is what keeps the
    coupling honest.
    """
    read_names = {
        f"{SAMPLING_ENV_PREFIX}{name.upper()}"
        # `protected-access`: the point of this test is to read the adapter's own
        # declaration, so the private member is the subject, not an accident. A
        # public accessor would be a second thing to keep in step, and this test
        # exists precisely because the two sides must not be kept in step by hand.
        for name in ollama._FORWARDED_OPTIONS  # pylint: disable=protected-access
    }

    assert _NUM_CTX_VARIABLE in read_names, (
        f"the flow declares {_NUM_CTX_VARIABLE}, but the adapter reads "
        f"{sorted(read_names)} — one of the two moved"
    )


def test_a_value_written_to_dotenv_reaches_the_engine(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `.env` a caller wrote reaches the adapter, and not only `num_ctx`.

    Measured before the fix: `myllmlocal.py` planted distinct values in `.env`
    and **none** reached the request — the only window on the wire was the flow's
    own 8192, declared by `apply_sampling`, which read enough like an answer to
    hide that the file had been read by nothing.

    The assertion is on the *engine's own environment*, not on a variable being
    present: `load_env` is what stands between the file and the adapter, and a
    gate that only checked `os.environ` would pass with the load wired to nothing.

    It also pins the **order** of the two writes inside `_engine`. `apply_sampling`
    writes only when the variable is unset, so loading the file *after* it would
    leave `.env` unable to say anything about `num_ctx` — the one option the flow
    already declares, and so the one a reader would most expect to be settable.
    ``NUM_PREDICT`` is asserted beside it because it is a variable the flow never
    touches: it can only arrive from the file.
    """
    planted = f"{SAMPLING_ENV_PREFIX}NUM_CTX=2048\n{SAMPLING_ENV_PREFIX}NUM_PREDICT=77\n"
    dotenv = tmp_path / ".env"
    dotenv.write_text(planted, encoding="utf-8")
    monkeypatch.setattr("flow.dotenv.DOTENV_PATH", dotenv)

    engine = _RecordingEngine()

    def _observed_engine() -> _RecordingEngine:
        """Record the environment in force *when the engine was built*.

        `_engine` is where the two writes happen, so reading it here is reading
        the state the adapter would then see at call time.
        """
        seen["num_ctx"] = os.environ.get(_NUM_CTX_VARIABLE)
        seen["num_predict"] = os.environ.get(f"{SAMPLING_ENV_PREFIX}NUM_PREDICT")
        return engine

    seen: dict[str, str | None] = {}
    monkeypatch.setattr("flow.extract.OllamaEngine", _observed_engine)

    extract(_material(), DEFAULT_CONFIG, load_artifacts())

    assert seen.get("num_ctx") == "2048", (
        f"`.env` declares num_ctx=2048 but the engine ran under {seen.get('num_ctx')!r}: "
        "the file is either not loaded, or loaded after the window was declared"
    )
    assert seen.get("num_predict") == "77", (
        f"`.env` declares num_predict=77 but the engine ran under "
        f"{seen.get('num_predict')!r}: nothing read the file"
    )


def test_an_exported_value_still_beats_the_file(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The file is the *third* layer, never an override of the environment.

    `NFR-06`'s chain is *CLI flag → environment → file → default*, so
    `DOCFLOW_OLLAMA_NUM_CTX=4096 myllmlocal.py …` must not be silently ignored by
    a `.env` that says something else. This is the direction a `load_env` written
    with plain assignment would break — and it would break it invisibly, because
    the file would still appear to work.
    """
    dotenv = tmp_path / ".env"
    dotenv.write_text(f"{_NUM_CTX_VARIABLE}=2048\n", encoding="utf-8")
    monkeypatch.setattr("flow.dotenv.DOTENV_PATH", dotenv)
    monkeypatch.setenv(_NUM_CTX_VARIABLE, "4096")

    from flow.dotenv import load_env  # pylint: disable=import-outside-toplevel

    load_env()

    assert os.environ[_NUM_CTX_VARIABLE] == "4096"
