"""Fase A: the run process — stages, journal, resume, pause/stop, record.

These tests exercise the process over unreadable inputs: the documents are
tiny bytes no adapter can read, so the stages degrade fast and the test pays
nothing per run. A process test that needed a real model would prove the model,
not the process.

The invariant the whole Fase A exists for (`plan/README.md`): an operator can
answer — where did the document go, what was decided, how does it resume —
without looking at the code.
"""

from __future__ import annotations

import json
import pathlib

from flow import run
from flow.material import Material
from flow.record import read_run
from flow.run import _ran_detail
from flow.stages import STAGE_DECIDE, STAGE_HITL, STAGE_READ, STAGES, stage_artifact


def _doc(
    tmp_path: pathlib.Path, name: str = "factura.pdf", content: bytes = b"pdf"
) -> pathlib.Path:
    """A real document file, so its digest is a real fingerprint."""
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _work(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    return root


def _run(tmp_path: pathlib.Path, **kwargs: object) -> object:
    return run(_doc(tmp_path), {}, work_root=_work(tmp_path), **kwargs)


def test_a_full_run_writes_every_stage_artifact(tmp_path: pathlib.Path) -> None:
    """The four stages run and each leaves the artifact the contract names."""
    _run(tmp_path)

    root = _work(tmp_path)
    for stage in STAGES:
        paths = stage_artifact(root, stage)
        assert paths, f"{stage} declared no artifact"
        for path in paths:
            assert path.is_file(), f"{stage} did not write {path.name}"


def test_the_journal_records_only_done_stages(tmp_path: pathlib.Path) -> None:
    """Every stage is marked done after a full run, on disk."""
    _run(tmp_path)

    journal = json.loads((_work(tmp_path) / "journal.json").read_text("utf-8"))
    assert all(entry["done"] for entry in journal["stages"].values())


def test_a_second_run_reuses_every_stage(tmp_path: pathlib.Path) -> None:
    """A completed run is reused whole: no step runs twice."""
    _run(tmp_path)
    outcome = _run(tmp_path)

    assert len(outcome.steps) == 4
    assert all(step.action == "reused" for step in outcome.steps)


def test_redo_ignores_the_journal(tmp_path: pathlib.Path) -> None:
    """`redo` re-runs every stage even when the journal says done."""
    _run(tmp_path)
    outcome = _run(tmp_path, redo=True)

    assert len(outcome.steps) == 4
    assert all(step.action == "ran" for step in outcome.steps)


def test_pause_stops_after_the_first_stage(tmp_path: pathlib.Path) -> None:
    """A paused run finishes the stage in flight and marks it, then stops."""
    outcome = _run(tmp_path, pause=True)

    assert len(outcome.steps) == 1
    assert outcome.steps[0].name == STAGE_READ
    assert outcome.steps[0].action == "ran"

    journal = json.loads((_work(tmp_path) / "journal.json").read_text("utf-8"))
    assert journal["stages"]["read"]["done"] is True
    assert journal["stages"]["extract"]["done"] is False

    control = json.loads((_work(tmp_path) / "control.json").read_text("utf-8"))
    assert control["state"] == "paused"


def test_resume_continues_at_the_first_unfinished_stage(tmp_path: pathlib.Path) -> None:
    """A second run after a pause reuses the done stage and runs the rest."""
    _run(tmp_path, pause=True)
    outcome = _run(tmp_path)

    actions = [(step.name, step.action) for step in outcome.steps]
    assert actions[0] == (STAGE_READ, "reused")
    assert [name for name, action in actions if action == "ran"] == [
        "extract",
        "decide",
        "hitl",
    ]


def test_stop_leaves_a_stopped_control_state(tmp_path: pathlib.Path) -> None:
    """`stop` writes the state and the journal still names the boundary."""
    _run(tmp_path, stop=True)

    control = json.loads((_work(tmp_path) / "control.json").read_text("utf-8"))
    assert control["state"] == "stopped"
    journal = json.loads((_work(tmp_path) / "journal.json").read_text("utf-8"))
    assert journal["stages"]["read"]["done"] is True
    assert journal["stages"]["extract"]["done"] is False


def test_the_run_record_is_derived_and_complete(tmp_path: pathlib.Path) -> None:
    """`run.json` names the document, its digest and the four steps."""
    _run(tmp_path)

    record = read_run(_work(tmp_path))
    assert record is not None
    assert record.document == "factura.pdf"
    assert record.digest  # a real fingerprint, not an empty stand-in
    assert len(record.steps) == 4


def test_a_missing_artifact_is_not_reused(tmp_path: pathlib.Path) -> None:
    """A stage whose artifact is gone runs again: the mark alone is not trust.

    Deleting `decision.json` must defeat the journal for that stage, or a
    corrupted work root would read as a completed run.
    """
    _run(tmp_path)
    (_work(tmp_path) / "decision.json").unlink()

    outcome = _run(tmp_path)
    actions = {step.name: step.action for step in outcome.steps}
    assert actions[STAGE_READ] == "reused"
    assert actions[STAGE_DECIDE] == "ran"
    assert actions[STAGE_HITL] == "reused"


def test_a_changed_input_discards_the_journal(tmp_path: pathlib.Path) -> None:
    """A different document under the same work root is a different run.

    The journal carries the document's digest; editing the bytes makes the old
    marks untrustworthy, so every stage re-runs (`my_flow.md` B.5).
    """
    work = _work(tmp_path)
    run(_doc(tmp_path, "a.pdf", b"a"), {}, work_root=work)
    outcome = run(_doc(tmp_path, "a.pdf", b"b"), {}, work_root=work)

    assert all(step.action == "ran" for step in outcome.steps)


# --- The wiring of §2 and §3: what each stage *says* it did -----------------
#
# The circuits' own suites test `classify` and `needs_vision_lane` as pure
# functions; these test that `run` calls them in the right order and reports the
# right thing. A pure test cannot catch a caller that asks the wrong question —
# which is exactly how a degraded document came to be reported as a non-receipt.


def test_a_degraded_material_escalates_with_its_own_code(
    tmp_path: pathlib.Path,
) -> None:
    """A document nobody could read is not a document that is not a receipt.

    `my_flow.md` §2 sends a degraded material straight to the ladder; §3's gate
    is a question about *text*, and a degraded material has none. Asking it
    anyway answers "not a receipt" — a claim about a document that was never
    read (B.9: three different situations, three different names).
    """
    _run(tmp_path)  # `b"pdf"` is unreadable, so the read degrades

    notes = read_run(_work(tmp_path))
    assert notes is not None
    decisions = json.loads((_work(tmp_path) / "decision.json").read_text("utf-8"))
    assert "ESC_DEGRADED_MATERIAL" in decisions["notes"], decisions["notes"]
    assert not any(note.startswith("classified out:") for note in decisions["notes"]), (
        decisions["notes"]
    )


def test_the_read_step_reports_what_it_measured(tmp_path: pathlib.Path) -> None:
    """The `read` step names the tier or why it could not read (B.12).

    The literal fallback `"read ran"` is unmeasured, so a degraded read that
    reached it would be a silent cut — the artefact carries the reason, but
    nobody opens `material.json` to find it.
    """
    outcome = _run(tmp_path)

    read_step = outcome.steps[0]
    assert read_step.name == STAGE_READ
    assert read_step.detail != "read ran", "the placeholder is not a measurement"
    assert read_step.detail.startswith("degraded: "), read_step.detail


def test_a_readable_material_reports_its_tier_and_route(tmp_path: pathlib.Path) -> None:
    """A material that was read names its tier, route and page count."""
    del tmp_path
    material = Material(
        kind="pdf",
        tier="texto_nativo",
        text="x",
        route="layout_text",
        pages_read=1,
        pages_total=2,
        images=[],
        notes=[],
    )

    detail = _ran_detail(STAGE_READ, material)
    assert "texto_nativo" in detail
    assert "layout_text" in detail
    assert "1/2 page(s)" in detail


def test_an_unread_page_total_is_not_printed_as_a_measurement(
    tmp_path: pathlib.Path,
) -> None:
    """An unknown page count is omitted, never rendered as `1/None`."""
    del tmp_path
    material = Material(
        kind="pdf",
        tier="escaneado_ocr",
        text="x",
        route="render+ocr",
        pages_read=1,
        pages_total=None,
        images=[],
        notes=[],
    )

    detail = _ran_detail(STAGE_READ, material)
    assert "None" not in detail, detail
    assert "1 page(s)" in detail
