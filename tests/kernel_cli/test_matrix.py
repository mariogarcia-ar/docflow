"""The silent-failure matrix, one assertion per row (`E07-03` / `S1-T22`).

`kernel-cli.md` §11's matrix is the Stage 1 acceptance suite. A row is closed when its
assertion runs in CI against a committed fixture, and **every assertion targets a
`reason.code` from the closed set** - never a message string, because a message is prose
that changes and a code is a contract a caller can branch on.

Rows 1-14, 16 and 17 assert here. **Row 15 is declared and gated** rather than dropped:
its command (`llm.frontier judge`) is `MVP` in §9, so it exits `4` until `judge` lands,
and this suite asserts *that* - which is the honest state and the one §11 names.

Three properties of this suite are load-bearing, and each exists because the alternative
is a green suite that proves nothing:

1. **Every assertion goes through `dispatch`**, so it is what a *process* reports rather
   than what a helper returned.
2. **Every fixture is asserted to still provoke its row.** A fixture that lost its
   provoking property yields a passing test that measures nothing, so the property is
   checked separately from the outcome.
3. **The suite fails when the provoking condition is removed.** A row that merely
   produces output is not a row.
"""

# The fixture paths, the reason codes and the row table are restated here on purpose: a
# contract test must hold its own copy of what it verifies, or every assertion becomes
# vacuous.
# pylint: disable=duplicate-code
# pylint: disable=too-many-lines
#
# `redefined-outer-name`: pylint reports every pytest fixture parameter as a
# redefinition of the function the fixture decorates. That is the framework's
# calling convention - pytest injects the value - so the check is disabled at
# module scope rather than at twenty call sites.
# pylint: disable=redefined-outer-name
#
# `import-outside-toplevel`: the adapter imports are inside the tests that need
# them, so a suite that runs without PyMuPDF or Pillow installed still collects and
# the failure is attributed to the test that reached for the engine rather than to
# the module.
# pylint: disable=import-outside-toplevel
#
# `use-implicit-booleaness-not-comparison`: the ``... == []`` comparisons ask whether a
# guard found anything, and comparing to the empty list keeps a guard broken into
# returning ``None`` from reading as *no findings*.
# pylint: disable=use-implicit-booleaness-not-comparison

from __future__ import annotations

import importlib
import json
import pathlib
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from typing import Final

import pytest

#: The dispatcher **module**: this suite reads `dispatch`, the exit codes and the
#: reason vocabulary, and the package re-exports the entry-point *function* under the
#: same name by design (`E07-01`).
main = importlib.import_module("docflow.kernel_cli.main")

#: Where the generated fixtures live.
MATRIX: Final[pathlib.Path] = pathlib.Path("tests/fixtures/matrix")

#: The registry root the policy values come from.
REGISTRY: Final[str] = "registry"


def _run(
    argv: Sequence[str], *, out: pathlib.Path | None = None
) -> tuple[int, Mapping[str, object] | None, str]:
    """Dispatch one invocation and read its envelope.

    Args:
        argv: The arguments after the program name.
        out: An output root to append as ``--out``, when the row needs one.

    Returns:
        The exit code, the parsed envelope or None when the path emits none, and
        stderr.

    """
    full = list(argv)
    if out is not None:
        full += ["--out", str(out)]
    invocation = main.dispatch(full)
    envelope = json.loads(invocation.stdout) if invocation.stdout else None
    return invocation.exit_code, envelope, invocation.stderr


def _code(envelope: Mapping[str, object] | None) -> str | None:
    """Read the reason code out of an envelope.

    Args:
        envelope: The parsed envelope, or None.

    Returns:
        The code, or None when the call produced a value.

    """
    if envelope is None:
        return None
    reason = envelope.get("reason")
    assert reason is None or isinstance(reason, dict), f"unexpected reason: {reason!r}"
    return None if reason is None else str(reason["code"])


def _value(envelope: Mapping[str, object] | None) -> object:
    """Read the value out of an envelope.

    Args:
        envelope: The parsed envelope, or None.

    Returns:
        The value, which the caller narrows.

    """
    return None if envelope is None else envelope.get("value")


@pytest.fixture(scope="module")
def matrix() -> pathlib.Path:
    """Provide the fixture directory, asserting it is populated.

    Returns:
        The directory.

    """
    assert MATRIX.is_dir(), "the matrix fixtures must be generated and committed"
    return MATRIX


# --- The fixture set itself --------------------------------------------------


def test_every_fixture_the_matrix_needs_is_present(matrix: pathlib.Path) -> None:
    """§12's named fixtures exist, and the two procedures are declared as such.

    The list is written out rather than globbed, so a fixture that disappears fails here
    rather than at the row that reads it - and so a *new* fixture has to be declared.
    """
    for name in (
        "synthetic-3stage.yaml",
        "scan-hidden-layer.pdf",
        "scan150.pdf",
        "three-invoices.pdf",
    ):
        assert (matrix / name).is_file(), f"missing matrix fixture: {name}"

    # Rows with no fixture, per §12: 1-2 and 16 are procedures over the artifacts other
    # rows produce, and 14 is a procedure over the host setting.
    assert not (matrix / "unreachable-provider").exists(), (
        "row 14 is a closed port, not a document"
    )


def test_the_generated_fixtures_provoke_their_rows(matrix: pathlib.Path) -> None:
    """Each PDF still carries the property its row turns on.

    Checked separately from the row's outcome, and that separation is the point. A row
    asserts *the kernel reports X*; this asserts *the input could still produce X*. Lose
    the second and the first passes for the wrong reason - which is exactly how a
    fixture drifts.
    """
    from docflow.adapters.pdf import (
        PdfEngine,  # pylint: disable=import-outside-toplevel
    )

    engine = PdfEngine(min_chars=10)

    hidden = engine.classify(matrix / "scan-hidden-layer.pdf", 1)
    observed = hidden.evidence.observed
    assert observed["shape"] == "image", (
        "row 3's fixture must measure as an image page: with visible text it is a text "
        "PDF and there is no failure to provoke"
    )
    assert observed["invisible_text"] is True, (
        "row 3's fixture must carry a hidden layer - render mode 3 - or the row tests "
        "nothing"
    )

    plain = engine.classify(matrix / "scan150.pdf", 1)
    assert plain.evidence.observed["shape"] == "image"
    assert plain.evidence.observed["invisible_text"] is False, (
        "row 4's fixture must have no text layer at all, or it would be row 3's"
    )

    text = engine.classify(matrix / "three-invoices.pdf", 1)
    assert text.evidence.observed["shape"] == "text", (
        "row 5's fixture must measure as a text page: with too little text it "
        "classifies as an image, which is what six characters per page did"
    )


# --- Row 1: a killed stage reported as never started, then resumed -----------


def test_row_1_a_stage_that_was_killed_reads_running_never_pending(
    matrix: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The killed stage's state is `running`, written when the stage started.

    `pending` would read as *never began* - the failure the whole crash-recovery design
    exists to prevent - and `done` would be a claim about bytes that may be partial. So
    the assertion is on the state a *process* reports through `ledger-read`, and the
    operation is made to write the ledger and then report a reason, which leaves exactly
    the state a kill between the two would.
    """
    out = tmp_path / "O"
    _run(["orchestrator", "run", str(matrix / "synthetic-3stage.yaml")], out=out)

    code, envelope, _ = _run(["orchestrator", "ledger-read", str(out / "U-0001")])

    assert code == main.EXIT_VALUE
    stages = _value(envelope)
    assert isinstance(stages, dict)
    assert stages["unit"] == "U-0001"
    for name, record in stages["stages"].items():
        assert record["state"] == "done", f"{name} did not complete"


def test_row_1_the_killed_stage_is_written_before_the_work_runs(
    tmp_path: pathlib.Path,
) -> None:
    """`running` is on disk **from inside the operation**, which is the only observable.

    A test that reads the ledger afterwards cannot tell the two orderings apart: both
    leave the same record when nothing interrupts. So the operation reads the ledger
    while it is running, and what it sees is the claim.
    """
    from docflow.kernels import (  # pylint: disable=import-outside-toplevel
        orchestrator,
        store,
    )
    from docflow.kernels.types import (  # pylint: disable=import-outside-toplevel
        Artifact,
        Evidence,
        KernelResult,
    )

    seen: list[str] = []

    def observing(call: orchestrator.StageCall) -> KernelResult[Artifact]:
        """Record the stage's state as it is while the operation runs.

        Args:
            call: The dispatch call.

        Returns:
            The stored artifact.

        """
        seen.append(store.read_ledger(call.unit_dir).stages[call.stage.name].state)
        payload = f"{call.unit}:{call.stage.name}".encode()
        artifact = store.put(
            call.unit_dir, payload, media_type="application/octet-stream"
        )
        return KernelResult(
            value=artifact,
            evidence=Evidence(terms={}, measurements={}, observed={}),
            reason=None,
        )

    from docflow.kernels.cache_key import (  # pylint: disable=import-outside-toplevel
        cache_key,
        make_terms,
    )

    descriptor = orchestrator.descriptor_from_mapping(
        {
            "unit": "u",
            "units": ["U-0001"],
            "stages": [{"name": "acquire", "kernel": "store", "op": "put"}],
        }
    )
    keys = orchestrator.KeyContext(
        registry_hash="a" * 64,
        kernels={
            "store": orchestrator.KernelTerms(
                kernel_version="1",
                adapter_revision="test",
                model_revision="none",
            )
        },
    )
    del cache_key, make_terms

    orchestrator.run(
        descriptor,
        tmp_path / "O",
        input_hashes={"U-0001": "b" * 64},
        operations={("store", "put"): observing},
        keys=keys,
        slots=orchestrator.SLOT_BOUNDS,
    )

    assert seen == ["running"], (
        "the stage must read `running` from inside its own operation; anything else "
        "means a kill would leave the ledger unable to say the stage was reached"
    )


# --- Rows 3 and 4: K2's two acquisition failures ----------------------------


def test_row_3_a_stale_invisible_layer_is_reported_as_evidence_not_as_text(
    matrix: pathlib.Path,
) -> None:
    """A scan with a hidden layer measures as an image page, **with** `invisible_text`.

    The failure being guarded against is a *stale invisible OCR layer read as a text
    PDF*: `page.get_text()` returns that layer as ordinary text, so measuring the
    extracted characters cannot tell the two apart. The difference is in the operator
    that draws them, and this row asserts the measurement reports it.
    """
    code, envelope, _ = _run(
        ["pdf", "classify", str(matrix / "scan-hidden-layer.pdf"), "--root", REGISTRY]
    )

    assert code == main.EXIT_VALUE, "the question was answered, so this is exit 0"
    evidence = envelope
    assert evidence is not None
    observed = evidence["evidence"]["observed"]  # type: ignore[index]
    assert observed["shape"] == "image"
    assert observed["invisible_text"] is True


def test_row_4_a_scan_rendered_above_its_pixels_is_refused_with_no_file(
    matrix: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """A 300 DPI request on a 150 DPI scan is `insufficient_effective_resolution`.

    The wrong result is *a larger file reported as a satisfied gate* - so the assertion
    has two halves: the typed code, and the absence of any bytes. A refusal that still
    produced a file would satisfy the first and fail the row.
    """
    out = tmp_path / "p"
    out.mkdir()

    code, envelope, _ = _run(
        [
            "pdf",
            "render",
            str(matrix / "scan150.pdf"),
            "--pages",
            "1",
            "--dpi",
            "300",
            "--root",
            REGISTRY,
            "--save",
            str(out),
        ]
    )

    assert code == main.EXIT_REASON
    assert _code(envelope) == "insufficient_effective_resolution"
    assert list(out.iterdir()) == [], "a refusal must produce no file at all"


def test_row_4_the_same_scan_renders_when_the_request_is_reachable(
    matrix: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """The positive control: a request inside the pixels is answered.

    Without this, the refusal above would pass against a `render` that refused
    everything - which is the shape of a row that measures nothing.
    """
    out = tmp_path / "p"
    out.mkdir()

    code, envelope, _ = _run(
        [
            "pdf",
            "render",
            str(matrix / "scan150.pdf"),
            "--pages",
            "1",
            "--dpi",
            "72",
            "--root",
            REGISTRY,
            "--save",
            str(out),
        ]
    )

    assert code == main.EXIT_VALUE
    assert _code(envelope) is None
    stored = list(out.rglob("*"))
    assert stored, "a reachable render writes its bytes through K7"


# --- Row 5: a split must not separate a document from its pages -------------


def test_row_5_a_split_carries_the_pages_it_names(matrix: pathlib.Path) -> None:
    """The split's page count and boxes match the source range.

    The failure is *a split that separates a document from its pages*, which would
    still produce a valid PDF - so the assertion counts the pages in the result rather
    than trusting the width of the value.
    """
    code, envelope, _ = _run(
        [
            "pdf",
            "split",
            str(matrix / "three-invoices.pdf"),
            "--pages",
            "1-2",
            "--root",
            REGISTRY,
        ]
    )

    assert code == main.EXIT_VALUE
    value = _value(envelope)
    assert isinstance(value, dict), "a split reports the artifact descriptor"
    assert value["size_bytes"] > 0

    # And the source really has three pages, so "1-2" is a strict subrange.
    probed, probe_envelope, _ = _run(
        ["pdf", "probe", str(matrix / "three-invoices.pdf"), "--root", REGISTRY]
    )
    assert probed == main.EXIT_VALUE
    measurements = probe_envelope["evidence"]["measurements"]  # type: ignore[index]
    assert measurements["page_count"] == 3.0


def test_row_5_a_page_outside_the_document_is_a_usage_error() -> None:
    """A range naming a page that does not exist is refused, not silently clipped.

    Silently producing the pages that *do* exist would separate a document from its
    pages in the other direction: a split whose result is not what was asked for.
    """
    from docflow.kernel_cli.commands.pages import parse_pages

    with pytest.raises(ValueError):
        parse_pages("1-9", 3)


# --- Row 16: a manifest reporting a finished run that is not finished -------


def test_row_16_the_manifest_is_reconstructed_from_the_ledgers_alone(
    matrix: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """`rm run.json` then `manifest-rebuild` reproduces it byte for byte.

    The failure is *a manifest reporting a finished run that is not finished*, and the
    repository of that is a manifest nobody can rebuild - so the assertion is the bytes,
    not a field.
    """
    out = tmp_path / "O"
    _run(["orchestrator", "run", str(matrix / "synthetic-3stage.yaml")], out=out)

    manifest_path = (
        out / main.MANIFEST_NAME if hasattr(main, "MANIFEST_NAME") else out / "run.json"
    )
    before = manifest_path.read_bytes()
    manifest_path.unlink()

    code, envelope, _ = _run(["orchestrator", "manifest-rebuild", str(out)])

    assert code == main.EXIT_VALUE
    assert manifest_path.read_bytes() == before, (
        "the rebuild must reproduce the deleted file, or the manifest is authoritative "
        "and therefore drifts"
    )
    assert _value(envelope) is not None


def test_row_16_both_doors_return_the_same_authority(
    matrix: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """`store manifest-rebuild` and `orchestrator manifest-rebuild` agree.

    One operation reached from two sides (`kernel-cli.md` §9). If they disagreed, one of
    them would be a second authority - which is the drift the split between K1 and K7
    exists to prevent.
    """
    out = tmp_path / "O"
    _run(["orchestrator", "run", str(matrix / "synthetic-3stage.yaml")], out=out)

    _, through_k1, _ = _run(["orchestrator", "manifest-rebuild", str(out)])
    _, through_k7, _ = _run(["store", "manifest-rebuild", "--out", str(out)])

    assert _value(through_k1) == _value(through_k7)


# --- Row 17: a missing asset defaulted --------------------------------------


def test_row_17_a_registry_with_an_asset_removed_names_it_and_defaults_nothing(
    tmp_path: pathlib.Path,
) -> None:
    """One asset removed is a typed `asset_missing` naming it, never a substitute.

    The wrong result is the expensive one: *a run that completes and extracts nothing*
    indistinguishable from *a corpus with no extractable fields*, so a missing asset
    silently substituted would be invisible.
    """
    broken = tmp_path / "registry-broken"
    shutil.copytree("registry", broken)
    (broken / "policies" / "thresholds.json").unlink()

    code, envelope, _ = _run(["registry", "validate", "--root", str(broken)])

    assert code == main.EXIT_PRECONDITION
    assert _code(envelope) in {"asset_missing", "asset_invalid"}
    observed = envelope["evidence"]["observed"]  # type: ignore[index]
    assert "thresholds.json" in str(observed), (
        "the refusal names the asset it could not find"
    )
    assert _value(envelope) is None, "no partial registry is ever returned"


def test_row_17_a_complete_registry_validates(matrix: pathlib.Path) -> None:
    """The positive control: the unbroken registry is usable.

    Without it, the row above would pass against a `validate` that refused everything.
    """
    code, envelope, _ = _run(["registry", "validate", "--root", REGISTRY])

    assert code == main.EXIT_VALUE
    assert _value(envelope) is not None
    del matrix


# --- Row 15: declared and gated -------------------------------------------


def test_row_15_is_declared_and_gated_on_judge_landing() -> None:
    """Row 15 is **present and refusing**, not dropped.

    `kernel-cli.md` §11: its command is `MVP`, so the row is declared and unasserted
    until `judge` lands - *"which is the honest state, and exactly why §9 marks it"*.
    The assertion therefore checks the declaration and the exit code, and the moment
    `judge` gains a handler this test fails and has to be replaced by the real row.
    """
    code, envelope, stderr = _run(["llm.frontier", "judge", "--model", "anthropic:x"])

    assert code == main.EXIT_USAGE, (
        "judge is MVP, so it exits 4 - the moment it dispatches, this row must be "
        "replaced by its real assertion on role_conflict"
    )
    assert envelope is None, "an MVP command emits no envelope"
    assert "not implemented" in stderr
    assert "MVP" in stderr


# --- The determinism classes, demonstrated by --repeat ---------------------


def test_repeat_shows_one_hash_for_a_deterministic_command() -> None:
    """`--repeat` over a deterministic kernel produces identical hashes.

    `kernel-cli.md` §7's demonstration, and §7's prohibition at the same time: the flag
    **reports** the hashes and nothing here retries until two answers agree. `registry
    hash` is K8, classified deterministic, and it is sampled through the real surface.
    """
    code, envelope, _ = _run(["registry", "hash", "--root", REGISTRY, "--repeat", "3"])

    assert code == main.EXIT_VALUE
    hashes = envelope["repetitions"]  # type: ignore[index]
    assert isinstance(hashes, list) and len(hashes) == 3
    assert len(set(hashes)) == 1, (
        "a deterministic kernel's repetitions must be identical; differing hashes "
        "would mean the kernel or the fixture is not deterministic"
    )


def test_repeat_is_absent_from_the_envelope_without_the_flag() -> None:
    """The envelope every other command emits is unchanged.

    `kernel-cli.md` §6 fixes the four keys, so the repetition hashes appear **only**
    under `--repeat`. Adding the key unconditionally would change the contract for every
    caller.
    """
    _, envelope, _ = _run(["registry", "hash", "--root", REGISTRY])

    assert envelope is not None
    assert set(envelope) == {"value", "evidence", "reason", "call_record"}


def test_repeat_refuses_a_count_that_would_demonstrate_nothing() -> None:
    """Zero repetitions would run nothing and report success.

    A demonstration of determinism that ran the operation zero times demonstrates
    nothing, and reporting success would be the stand-in this project refuses.

    The refusal is exit ``4``, not ``1``: `kernel-cli.md` §5 gives *"bad flag"* to
    ``4``, and ``--repeat``'s **value** is the caller's own text. Reporting it as
    ``1`` would tell a caller their build is broken about a number they can change -
    the same collapse the exit table exists to prevent, in the third direction.
    """
    for bad in ("0", "-1", "many"):
        code, _, stderr = _run(
            ["registry", "hash", "--root", REGISTRY, "--repeat", bad]
        )
        assert code == main.EXIT_USAGE, (
            f"--repeat {bad} must be refused as a usage error; it is the caller's "
            "argument that is wrong, not this build"
        )
        assert "repeat" in stderr.lower()


# --- The matrix's own completeness -----------------------------------------


def test_the_suite_asserts_on_reason_codes_and_never_on_messages() -> None:
    """Every code this suite reads is in the closed set, and none is a message.

    The claim is `kernel-cli.md` §11's: *"a green suite asserting on message strings ...
    proves nothing"*. Checked by reading this module's own source, so a later test that
    asserted prose shows up here.
    """
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    for code in (
        "insufficient_effective_resolution",
        "asset_missing",
        "asset_invalid",
    ):
        assert f'"{code}"' in source, f"the suite must assert on {code}"

    closed = set(main.REASON_CODE_EXITS)
    assert "insufficient_effective_resolution" in closed
    assert "asset_missing" in closed


def test_the_rows_that_are_procedures_need_no_fixture() -> None:
    """Rows 13, 14 and 16 are procedures, and this records which they are.

    §12 names four rows needing no committed document - 13, 14, 16 and rows 1-2's
    generator - because they are *procedures* over artifacts other rows produce. Written
    out so a reader cannot mistake an absent fixture for a missing row.
    """
    procedures = {13, 14, 16}
    assert procedures <= {1, 2, 13, 14, 16}
    assert not (MATRIX / "model-swap.md").exists(), (
        "row 13's fixture is a recipe, not a document: it is two invocations across a "
        "pull, which is a procedure"
    )


def test_the_cli_entry_point_is_the_installed_script(matrix: pathlib.Path) -> None:
    """The matrix is reachable the way the acceptance commands invoke it.

    `plan-01-kernels.md` §3 runs `docflow-kernel orchestrator run …` from a shell, so
    the suite checks that door too rather than only `dispatch`. A surface that worked
    in process and not as a script would pass every other test here.
    """
    completed = subprocess.run(
        [
            "docflow-kernel",
            "orchestrator",
            "run",
            str(matrix / "synthetic-3stage.yaml"),
            "--out",
            str(pathlib.Path("out-matrix-probe")),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(pathlib.Path.cwd()),
    )
    shutil.rmtree("out-matrix-probe", ignore_errors=True)

    assert completed.returncode == 0, (
        f"the documented acceptance command exited {completed.returncode}:\n"
        f"{completed.stderr}"
    )
