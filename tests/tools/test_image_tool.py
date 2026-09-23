# pylint: disable=duplicate-code
# This module is deliberately parallel to `tests/tools/test_pdf_tool.py`, down to the shape of
# its helpers. There are two lab tools and they must respect the same four boundaries - a caller,
# never imported by the library, no engine knob, no workflow decision - so the checks are the
# same checks and the duplication is the point: a boundary that holds for one tool and not the
# other should be visible as a missing test in one file rather than hidden behind a shared
# helper that quietly stopped applying. The genuinely shared part is the *convention*, and it is
# documented once in `docs/plan/README.md` §4.1.
"""Tests for the image lab tool (``IMG-15``, ``GEN-21``).

A lab tool is a caller, and every boundary it must respect is a *negative* claim — it does not
reimplement, the library does not import it, it adds no seam, it decides no workflow question.
Negative claims are what a passing test cannot show on its own, so much of what follows is
checked by reading the tool's *calls* rather than its prose.

The acceptance scenario is exercised end to end as a subprocess, exactly as an operator runs it,
because that is the surface being tested.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "scripts" / "tools" / "image.py"
SOURCE_ROOT = REPO_ROOT / "src"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "image"

SKEWED_TEXT = FIXTURES / "skewed_text.png"
COLOR_LAYOUT = FIXTURES / "color_layout.png"
CORRUPT = FIXTURES / "corrupt.png"

DOCUMENTED_SUBCOMMANDS = (
    "info",
    "metrics",
    "normalize",
    "ocr-ready",
    "vlm-ready",
    "classify",
    "crop",
    "run",
)


def run_tool(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the tool as an operator would.

    Args:
        *arguments: The command line arguments.
        cwd: The working directory, so the default output root lands in the test's tmp_path.

    Returns:
        The completed process.
    """
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def sha256(path: Path) -> str:
    """Return a file's hex digest.

    Args:
        path: The file to hash.

    Returns:
        The digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_source() -> str:
    """Return the tool's source.

    Returns:
        The source text.
    """
    return TOOL.read_text(encoding="utf-8")


def tool_calls() -> list[ast.Call]:
    """Return every call expression in the tool.

    Returns:
        The call nodes.
    """
    tree = ast.parse(tool_source())
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)]


# ======================================================================================
# Scenario — produce both variants from the command line
# ======================================================================================


def test_run_produces_two_distinct_variants_and_leaves_the_source_alone(
    tmp_path: Path,
) -> None:
    """The acceptance scenario: two distinct files, colour preserved, source untouched."""
    work = tmp_path / "work"
    work.mkdir()
    page = work / "page.png"
    page.write_bytes(SKEWED_TEXT.read_bytes())
    before = sha256(page)

    completed = run_tool(
        "run", "page.png", "--ocr-ready", "--vlm-ready", "--out", "out", cwd=work
    )

    assert completed.returncode == 0, completed.stderr
    run_dirs = [path for path in (work / "out").iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert run_dir.name.startswith("page-")
    assert run_dir.name.split("-")[-1] in sha256(SKEWED_TEXT)

    ocr = run_dir / "ocr_ready.png"
    vlm = run_dir / "vlm_ready.png"
    assert ocr.is_file()
    assert vlm.is_file()
    assert ocr.read_bytes() != vlm.read_bytes()
    assert sha256(page) == before, "the source image was modified"


def test_the_vlm_variant_keeps_colour_and_the_ocr_variant_does_not(
    tmp_path: Path,
) -> None:
    """The observable difference between the two representations, read from the files.

    This is what makes the second subcommand worth having: if both commands produced the same
    image, the split would be ceremony.
    """
    work = tmp_path / "work"
    work.mkdir()
    page = work / "page.png"
    page.write_bytes(SKEWED_TEXT.read_bytes())

    run_tool("run", "page.png", "--ocr-ready", "--vlm-ready", "--out", "out", cwd=work)
    run_dir = next(path for path in (work / "out").iterdir() if path.is_dir())

    probe = (
        "import sys;"
        f"sys.path.insert(0, {str(SOURCE_ROOT)!r});"
        "from pathlib import Path;"
        "from docflow.image.primitives.load import load_image;"
        "from docflow.image.primitives.engine import EngineChoice;"
        f"ocr = load_image(Path({str(run_dir / 'ocr_ready.png')!r}), EngineChoice.OPENCV);"
        f"vlm = load_image(Path({str(run_dir / 'vlm_ready.png')!r}), EngineChoice.OPENCV);"
        "print(ocr.ndim, vlm.ndim)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )

    assert completed.returncode == 0, completed.stderr
    ocr_ndim, vlm_ndim = completed.stdout.split()
    assert ocr_ndim == "2", "the OCR variant should be single-channel"
    assert vlm_ndim == "3", "the VLM variant lost its colour channels"


def test_the_two_variants_are_separate_subcommands(tmp_path: Path) -> None:
    """``ocr-ready`` and ``vlm-ready`` are distinct commands, never one with a flag.

    A single ``prepare`` command would teach that the OCR-optimal image equals the VLM-optimal
    one — the exact assumption the processor's design exists to prevent.
    """
    work = tmp_path / "work"
    work.mkdir()
    page = work / "page.png"
    page.write_bytes(SKEWED_TEXT.read_bytes())

    ocr = run_tool("ocr-ready", "page.png", "--out", "out", cwd=work)
    vlm = run_tool("vlm-ready", "page.png", "--out", "out", cwd=work)

    assert ocr.returncode == 0, ocr.stderr
    assert vlm.returncode == 0, vlm.stderr
    run_dir = next(path for path in (work / "out").iterdir() if path.is_dir())
    assert (run_dir / "ocr_ready.png").is_file()
    assert (run_dir / "vlm_ready.png").is_file()
    # And the OCR command did not write a VLM artifact, nor the reverse.
    assert "1 channel" in ocr.stdout
    assert "3 channel" in vlm.stdout


def test_the_run_directory_is_derived_from_the_content_not_the_clock(
    tmp_path: Path,
) -> None:
    """Two runs over the same bytes land in the same tree, which is what makes a bench usable.

    Mutation that breaks it: name the directory after the current time. The two runs diverge and
    the assertion fails.
    """
    work = tmp_path / "work"
    work.mkdir()
    page = work / "page.png"
    page.write_bytes(COLOR_LAYOUT.read_bytes())

    run_tool("info", "page.png", "--out", "out", cwd=work)
    first = sorted(path.name for path in (work / "out").iterdir())
    run_tool("info", "page.png", "--out", "out", cwd=work)
    second = sorted(path.name for path in (work / "out").iterdir())

    assert first == second
    assert len(first) == 1


# ======================================================================================
# The tool is a caller, not a component
# ======================================================================================


def test_nothing_in_the_library_imports_the_tool() -> None:
    """No module under ``src/docflow/`` reaches ``scripts/``."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in (SOURCE_ROOT / "docflow").rglob("*.py")
        if "scripts" in path.read_text(encoding="utf-8")
        and "import" in path.read_text(encoding="utf-8")
    ]

    assert not offenders, f"these library modules reference the tools: {offenders}"


def test_the_library_imports_cleanly_with_scripts_deleted() -> None:
    """The library is usable with ``scripts/`` removed, measured in a fresh interpreter."""
    probe = (
        "import sys;"
        "import docflow.image as image;"
        "assert not any('scripts' in name for name in sys.modules);"
        "print(sorted(m for m in sys.modules if m.startswith('docflow'))[:2])"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(SOURCE_ROOT)},
        cwd=REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert "scripts" not in completed.stdout


def test_every_operation_resolves_to_a_docflow_image_call() -> None:
    """The positive half: the tool really drives the library.

    A tool that imported nothing would satisfy every negative check while doing nothing at all.
    """
    imported: set[str] = set()
    tree = ast.parse(tool_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")

    assert any(name.startswith("docflow.image") for name in imported), imported
    # Every `docflow.*` import is from the image processor, never a sibling.
    siblings = {
        name
        for name in imported
        if name.startswith("docflow.") and not name.startswith("docflow.image")
    }
    assert siblings == set(), f"the tool imports a sibling processor: {siblings}"


def test_the_tool_never_shells_out_to_a_library_or_an_engine() -> None:
    """No subprocess is spawned: every operation is an in-process call.

    Checked against the tool's *calls*, not its prose — the module docstring names things it
    does not do, and forbidding the words would push the explanation out of the file.
    """
    spawns = [
        node
        for node in tool_calls()
        if isinstance(node.func, ast.Attribute)
        and node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}
    ]

    assert not spawns, "the tool spawns a process instead of calling the library"


def test_the_tool_exposes_no_engine_knob() -> None:
    """There is no ``--engine`` flag, because the seam is not an operator preference.

    A flag would let an operator produce a directory whose provenance the command line does not
    record — which is the same silent substitution ``EngineChoice`` exists to prevent.

    Checked against the **parser's declared arguments**, not the source text. The module
    docstring names ``--engine`` while explaining that it does not exist, and a text search
    would flag the explanation while missing a real flag — the same false positive the PDF
    tool's workflow check had to work around.
    """
    declared: set[str] = set()
    for node in ast.walk(ast.parse(tool_source())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
        ):
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(
                    argument.value, str
                ):
                    declared.add(argument.value)

    assert declared, "no arguments were found, so the check below proves nothing"
    assert "--engine" not in declared, (
        f"the tool exposes an engine knob: {sorted(declared)}"
    )

    completed = run_tool("run", "--help", cwd=REPO_ROOT)
    assert "--engine" not in completed.stdout


def code_without_prose() -> str:
    """Return the tool's source with docstrings and comments removed.

    The distinction matters here: the module docstring explains that the tool *does not* decide
    reuse, naming the words it avoids. A check that forbade those words outright would flag the
    explanation while missing an actual decision.
    """
    stripped: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(tool_source()).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        stripped.append(token.string)
    return " ".join(stripped)


def test_the_tool_decides_no_workflow_question() -> None:
    """No reuse, skip, force or resume logic appears in the tool's *code*.

    Those belong to the orchestrator. A lab tool executes unconditionally: that is what makes it
    a bench rather than a second implementation of the workflow.

    Mutation that breaks it: skip a stage whose artifact already exists, or branch on
    ``result.validation``. The check then finds the decision.
    """
    code = code_without_prose()

    for forbidden in ("REUSE", "SKIP", "FORCE", "RESUME", "processing_key"):
        assert forbidden not in code, f"the tool decides {forbidden}"
    for decision_input in (".validation ==", "if result.", "already exists"):
        assert decision_input not in code, f"the tool branches on {decision_input}"


def test_the_tool_adds_no_field_to_the_processors_metadata(tmp_path: Path) -> None:
    """The processor's ``metadata.json`` is its own contract; the tool writes its own file.

    A tool that merged its fields into ``metadata.json`` would be changing what the orchestrator
    reads, from outside the library.
    """
    work = tmp_path / "work"
    work.mkdir()
    page = work / "page.png"
    page.write_bytes(COLOR_LAYOUT.read_bytes())

    run_tool("run", "page.png", "--out", "out", cwd=work)
    run_dir = next(path for path in (work / "out").iterdir() if path.is_dir())

    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "tool" not in metadata
    assert "command" not in metadata
    # The tool's own record is a separate file.
    record = json.loads((run_dir / "tool-run.json").read_text(encoding="utf-8"))
    assert record["tool"].endswith("scripts/tools/image.py")
    assert record["command"] == "run"


# ======================================================================================
# The command surface
# ======================================================================================


def test_the_documented_subcommands_all_exist() -> None:
    """The eight subcommands ``subplan-procesador-image.md`` §10 fixes."""
    source = tool_source()

    for command in DOCUMENTED_SUBCOMMANDS:
        assert f'"{command}"' in source, f"the {command} subcommand is missing"


def test_an_unknown_subcommand_is_refused(tmp_path: Path) -> None:
    """The parser rejects what it does not implement rather than guessing."""
    completed = run_tool("frobnicate", str(COLOR_LAYOUT), cwd=tmp_path)

    assert completed.returncode != 0


def test_a_missing_input_is_reported_not_traced(tmp_path: Path) -> None:
    """A tool is an operator's surface: it prints a cause, not a stack trace."""
    completed = run_tool("info", str(tmp_path / "absent.png"), cwd=tmp_path)

    assert completed.returncode == 2
    assert "absent.png" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_an_unreadable_image_reports_its_typed_cause(tmp_path: Path) -> None:
    """A corrupt file reaches the operator with its classification, not a traceback."""
    work = tmp_path / "work"
    work.mkdir()
    page = work / "corrupt.png"
    page.write_bytes(CORRUPT.read_bytes())

    completed = run_tool("metrics", "corrupt.png", "--out", "out", cwd=work)

    assert completed.returncode == 1
    assert "DECODE_ERROR" in completed.stderr or "INVALID_INPUT" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_json_mode_emits_only_json(tmp_path: Path) -> None:
    """``--json`` must produce parseable output and nothing else."""
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool(
        "metrics", str(COLOR_LAYOUT), "--json", "--out", "out", cwd=work
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["format"] == "PNG"
    assert payload["dimensions"]["width"] > 0


def test_plain_mode_is_human_readable_and_not_json(tmp_path: Path) -> None:
    """Without ``--json`` the output is for a person, not a parser."""
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("metrics", str(COLOR_LAYOUT), "--out", "out", cwd=work)

    assert completed.returncode == 0, completed.stderr
    assert "sharpness" in completed.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(completed.stdout)


def test_a_global_flag_works_on_either_side_of_the_subcommand(tmp_path: Path) -> None:
    """``--out`` is accepted before and after the subcommand, and means the same thing.

    An operator writes whichever reads naturally. Declaring the flag on only one side makes the
    other position an error, or silently drops the value into a default.
    """
    work = tmp_path / "work"
    work.mkdir()

    before = run_tool("--out", "before", "info", str(COLOR_LAYOUT), cwd=work)
    after = run_tool("info", str(COLOR_LAYOUT), "--out", "after", cwd=work)

    assert before.returncode == 0, before.stderr
    assert after.returncode == 0, after.stderr
    assert (work / "before").is_dir()
    assert (work / "after").is_dir()


def test_metrics_and_classify_write_no_artifact(tmp_path: Path) -> None:
    """Reading a measurement must not publish anything.

    The output directory is still created — that is where a later command in the same experiment
    writes — but it holds no image.
    """
    work = tmp_path / "work"
    work.mkdir()

    run_tool("metrics", str(COLOR_LAYOUT), "--out", "out", cwd=work)
    run_tool("classify", str(COLOR_LAYOUT), "--out", "out", cwd=work)

    published = [
        path.name
        for path in (work / "out").rglob("*")
        if path.is_file() and path.suffix == ".png"
    ]
    assert published == []


def test_crop_publishes_only_the_requested_region(tmp_path: Path) -> None:
    """An explicit box produces exactly one artifact, under ``regions/``."""
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool(
        "crop", str(COLOR_LAYOUT), "--box", "10,20,60,40", "--out", "out", cwd=work
    )

    assert completed.returncode == 0, completed.stderr
    regions = sorted(path.name for path in (work / "out").rglob("regions/*.png"))
    assert len(regions) == 1
    assert "60x40" in completed.stdout


def test_a_box_that_leaves_the_image_is_refused_not_clipped(tmp_path: Path) -> None:
    """A degenerate or out-of-range box is an error, never a silently different region.

    Clipping would hand the operator an image that is not the one they asked for, with no way to
    tell — the "plausible wrong value" the plan's risk table names.

    A box with a negative coordinate is written ``--box=-5,0,10,10``. argparse reads a bare
    ``-5,...`` as the start of another option, so the ``=`` form is the one that reaches the
    primitive — and it is the *primitive's* refusal being tested here, not the parser's.
    """
    work = tmp_path / "work"
    work.mkdir()

    for box in ("--box=0,0,99999,99999", "--box=0,0,0,10", "--box=-5,0,10,10"):
        completed = run_tool("crop", str(COLOR_LAYOUT), box, "--out", "out", cwd=work)
        assert completed.returncode == 1, box
        assert "TRANSFORMATION_ERROR" in completed.stderr, box
        assert "Traceback" not in completed.stderr, box


def test_a_malformed_box_is_reported_not_traced(tmp_path: Path) -> None:
    """A box that is not four integers is an operator error with a message."""
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool(
        "crop", str(COLOR_LAYOUT), "--box", "10,20,30", "--out", "out", cwd=work
    )

    assert completed.returncode == 1
    assert "four comma-separated" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_no_run_leaves_a_staged_file_anywhere(tmp_path: Path) -> None:
    """Publication is atomic, so the tool's tree holds no residue."""
    work = tmp_path / "work"
    work.mkdir()
    page = work / "page.png"
    page.write_bytes(SKEWED_TEXT.read_bytes())

    run_tool("run", "page.png", "--ocr-ready", "--vlm-ready", "--out", "out", cwd=work)

    leftovers = [
        str(path.relative_to(work))
        for path in (work / "out").rglob("*")
        if path.name.endswith(".tmp") or path.name == ".tmp"
    ]
    assert leftovers == []
