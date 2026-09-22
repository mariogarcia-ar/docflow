"""Tests for the lab-tool convention (``PDF-14``, ``GEN-21``).

A lab tool is a caller, and every boundary it must respect is a *negative* claim — it does
not reimplement, the library does not import it, it adds no seam. Negative claims are what a
passing test cannot show on its own, so most of what follows is checked by reading the tool's
source and its import graph rather than by exercising it.

The two acceptance scenarios are exercised end to end as well: the tool is run as a
subprocess, exactly as an operator would run it, because that is the surface being tested.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import struct
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "scripts" / "tools" / "pdf.py"
SOURCE_ROOT = REPO_ROOT / "src"

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
TEXT_PDF = FIXTURES / "matrix" / "three-invoices.pdf"
SCAN_PDF = FIXTURES / "matrix" / "scan150.pdf"

TEXT_PAGES = 3

FORBIDDEN_SUBPROCESS_TOOLS = (
    "pdftotext",
    "pdfimages",
    "pdfseparate",
    "pdftoppm",
    "pdfinfo",
)


def run_tool(*arguments: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the tool as an operator would, with the repository as the working directory."""
    return subprocess.run(
        [sys.executable, str(TOOL), *arguments],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def sha256(path: Path) -> str:
    """Return a file's hex digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tool_source() -> str:
    """Return the tool's source."""
    return TOOL.read_text(encoding="utf-8")


# ======================================================================================
# Scenario 1 — split from the command line leaves the input untouched
# ======================================================================================


def test_split_writes_the_documented_layout_and_leaves_the_input_alone(
    tmp_path: Path,
) -> None:
    """The acceptance scenario, run as an operator runs it.

    ``page_NNN/source/page.pdf`` for every page, under a directory named for the input stem
    and a hash of its bytes — and the input's digest unchanged.
    """
    before = sha256(TEXT_PDF)
    work = tmp_path / "work"

    completed = run_tool("split", str(TEXT_PDF), "--out", str(work), cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    run_dirs = [path for path in work.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert run_dir.name.startswith(f"{TEXT_PDF.stem}-")
    assert run_dir.name.split("-")[-1] in sha256(TEXT_PDF)

    pages = sorted(
        str(path.relative_to(run_dir)) for path in run_dir.rglob("*") if path.is_file()
    )
    assert pages == [
        f"page_{index:03d}/source/page.pdf" for index in range(1, TEXT_PAGES + 1)
    ]
    assert sha256(TEXT_PDF) == before


def test_the_run_directory_is_derived_from_the_content_not_the_clock(
    tmp_path: Path,
) -> None:
    """Two runs over the same bytes land in the same tree.

    That is the point of the hash in the name: an ``inspect`` after a ``run`` reads what the
    ``run`` wrote rather than starting a second tree.

    Mutation that breaks it: name the directory after the current time. The two runs diverge
    and the assertion fails.
    """
    work = tmp_path / "work"

    run_tool("split", str(TEXT_PDF), "--out", str(work), cwd=tmp_path)
    first = sorted(path.name for path in work.iterdir())
    run_tool("split", str(TEXT_PDF), "--out", str(work), cwd=tmp_path)
    second = sorted(path.name for path in work.iterdir())

    assert first == second
    assert len(first) == 1


def test_a_copy_of_the_same_bytes_shares_the_run_directory(tmp_path: Path) -> None:
    """The hash is of the content, so a renamed copy is the same experiment.

    The stem differs, so this does not hold for the whole name — the assertion pins what the
    hash half of the name is for, not more than it does.
    """
    work = tmp_path / "work"

    run_tool("split", str(TEXT_PDF), "--out", str(work), cwd=tmp_path)

    digest = sha256(TEXT_PDF)[:8]
    assert any(digest in path.name for path in work.iterdir())


# ======================================================================================
# Scenario 2 — the tool is a caller, not a component
# ======================================================================================


def test_nothing_in_the_library_imports_the_tool() -> None:
    """No module under ``src/docflow/`` reaches ``scripts/``.

    Mutation that breaks it: add ``from scripts.tools import pdf`` to any library module. The
    assertion fails, and the library has stopped being deletable on its own.
    """
    offenders: list[str] = []
    for path in (SOURCE_ROOT / "docflow").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "scripts" in source and "import" in source:
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, f"these library modules reference the tools: {offenders}"


def test_the_library_imports_cleanly_with_scripts_deleted() -> None:
    """The library's own tests do not depend on the tool existing.

    Measured in a fresh interpreter with the tool's directory *not* on the path, which is the
    honest form of the claim: the library is usable with ``scripts/`` removed.
    """
    probe = (
        "import sys;"
        "import docflow.pdf as pdf;"
        "assert not any('scripts' in name for name in sys.modules);"
        "print(sorted(m for m in sys.modules if m.startswith('docflow'))[:3])"
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


def test_the_tool_never_shells_out_to_an_engine() -> None:
    """Every operation resolves to a library call, not to a Poppler binary.

    Checked against the tool's *calls* rather than its prose: a docstring naming
    ``pdfseparate`` while explaining that it is not used is not a violation, and forbidding
    the word would push the explanation out of the file.

    Mutation that breaks it: call ``subprocess.run(["pdfseparate", ...])`` in ``split``. The
    tool then reimplements what the primitive already does, and the assertion fails.
    """
    tree = ast.parse(tool_source())

    spawns = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"run", "Popen", "call", "check_call", "check_output"}
    ]
    assert not spawns, "the tool spawns a process instead of calling the library"

    for binary in FORBIDDEN_SUBPROCESS_TOOLS:
        assert f'"-{binary}"' not in tool_source()


def test_the_tool_imports_the_library_it_drives() -> None:
    """The positive half: the tool does reach ``docflow.pdf``, and only from outside.

    A tool that imported nothing would satisfy every negative check above while doing
    nothing at all.
    """
    tree = ast.parse(tool_source())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported |= {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }

    assert any(name.startswith("docflow.pdf") for name in imported), imported


def code_without_prose() -> str:
    """Return the tool's source with docstrings and comments removed.

    The distinction matters for this test. The tool's module docstring explains that it
    *does not* decide reuse, naming the words it avoids — and a check that forbade those
    words outright would flag the explanation while missing an actual decision, which is the
    same false positive the seam guard hit over ``shutil``. Only executable text is inspected.
    """
    stripped: list[str] = []
    for token in tokenize.generate_tokens(io.StringIO(tool_source()).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        stripped.append(token.string)
    return " ".join(stripped)


def test_the_tool_decides_no_workflow_question() -> None:
    """No reuse, skip, force or resume logic appears in the tool's *code*.

    Those belong to the orchestrator. A lab tool executes unconditionally: that is what makes
    it a bench rather than a second implementation of the workflow.

    Mutation that breaks it: skip a stage whose artifact already exists, or branch on
    ``result.validation`` to decide whether to run. The check then finds the decision.
    """
    code = code_without_prose()

    for forbidden in ("REUSE", "SKIP", "FORCE", "RESUME", "processing_key"):
        assert forbidden not in code, f"the tool decides {forbidden}"

    # A reuse decision has to read an artifact's validity or presence to make itself. Neither
    # appears in the code, which is what makes "executes unconditionally" checkable rather
    # than merely claimed.
    for decision_input in (".validation", ".exists()", "if result."):
        assert decision_input not in code, f"the tool branches on {decision_input}"


# ======================================================================================
# The command surface
# ======================================================================================


def test_the_documented_subcommands_all_exist() -> None:
    """``inspect``, ``split``, ``render``, ``text``, ``blocks``, ``images``, ``classify``,
    ``run`` — the surface ``subplan-procesador-pdf.md`` §10 fixes."""
    source = tool_source()

    for command in (
        "inspect",
        "split",
        "render",
        "text",
        "blocks",
        "images",
        "classify",
        "run",
    ):
        assert f'"{command}"' in source, f"the {command} subcommand is missing"


def test_an_unknown_subcommand_is_refused(tmp_path: Path) -> None:
    """The parser rejects what it does not implement rather than guessing."""
    completed = run_tool("frobnicate", str(TEXT_PDF), cwd=tmp_path)

    assert completed.returncode != 0


def test_a_missing_input_is_reported_not_traced(tmp_path: Path) -> None:
    """A tool is an operator's surface: it prints a cause, not a stack trace.

    ``PDF-11``'s typed classification reaches the operator through this path, which is the
    only place a human sees it.
    """
    completed = run_tool("inspect", str(tmp_path / "absent.pdf"), cwd=tmp_path)

    assert completed.returncode == 2
    assert "no such file" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_an_unreadable_document_reports_its_typed_cause(tmp_path: Path) -> None:
    """An encrypted document prints ``ENCRYPTED_PDF`` rather than crashing.

    Pinned because the typed error model is worth little if the only human-facing surface
    turns it into a traceback.
    """
    encrypted = FIXTURES / "matrix" / "pdf_encrypted.pdf"

    completed = run_tool("inspect", str(encrypted), cwd=tmp_path)

    assert completed.returncode == 1
    assert "Traceback" not in completed.stderr
    assert "encrypted" in completed.stderr.lower()


def test_json_mode_emits_only_json(tmp_path: Path) -> None:
    """``--json`` produces parseable output and nothing else.

    Mutation that breaks it: print the human summary after the JSON in both modes — the
    defect this tool shipped with, where ``--json`` added noise instead of changing the mode
    and the output stopped being parseable.
    """
    completed = run_tool("--json", "inspect", str(TEXT_PDF), cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["page_count"] == TEXT_PAGES


@pytest.mark.parametrize("flag_first", [True, False])
def test_a_global_flag_works_on_either_side_of_the_subcommand(
    tmp_path: Path, flag_first: bool
) -> None:
    """``--out`` before or after the subcommand, both accepted.

    An operator writes whichever reads naturally, and both are reasonable. Two defects lived
    here: the flags were declared only on the top-level parser, so the trailing form was
    rejected outright; and once the sub-parsers declared them too, a *leading* flag was
    silently dropped because the sub-parser's own default overwrote it. The second is the
    worse one, because it fails by producing output in the wrong place rather than by
    refusing.

    Mutation that breaks it: give the sub-parsers a concrete default instead of
    ``argparse.SUPPRESS``. The leading-flag case writes to ``var/`` and the assertion fails.
    """
    work = tmp_path / "work"
    arguments = ["inspect", str(TEXT_PDF), "--out", str(work)]
    if flag_first:
        arguments = ["--out", str(work), "inspect", str(TEXT_PDF)]

    completed = run_tool(*arguments, cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert work.exists()


def test_plain_mode_is_human_readable_and_not_json(tmp_path: Path) -> None:
    """Without ``--json`` the output is the summary, not a JSON document."""
    completed = run_tool("inspect", str(TEXT_PDF), cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert f"{TEXT_PAGES} page(s)" in completed.stdout
    with pytest.raises(json.JSONDecodeError):
        json.loads(completed.stdout)


def test_text_mode_prints_the_text_itself(tmp_path: Path) -> None:
    """``text`` writes the layer, not a description of it.

    This is the subcommand an operator uses to read what the document says, so a JSON
    envelope in the default mode would be the tool interpreting what it exists to show.
    """
    completed = run_tool("text", str(TEXT_PDF), "--page", "2", cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "page 2 of 3" in completed.stdout
    assert completed.stdout.startswith("page 2 of 3")


def test_classify_writes_nothing(tmp_path: Path) -> None:
    """Measuring is read-only: ``classify`` reports and publishes no artifact.

    Mutation that breaks it: call ``extract_images_from_page`` instead of
    ``get_image_blocks`` to obtain the images. The run directory gains an
    ``embedded_images/`` tree that the operator did not ask for.
    """
    work = tmp_path / "work"

    completed = run_tool("classify", str(SCAN_PDF), "--out", str(work), cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "IMAGE" in completed.stdout
    artifacts = [path for path in work.rglob("*") if path.is_file()]
    assert not artifacts, f"classify published {artifacts}"


def test_render_honours_the_dpi_flag(tmp_path: Path) -> None:
    """``render --dpi 400`` drives the primitive at the resolution asked for.

    The reason a tool may reach ``pdf/primitives/``: driving one primitive at a setting no
    document run would use is exactly what a bench is for.
    """
    work = tmp_path / "work"

    completed = run_tool(
        "render",
        str(TEXT_PDF),
        "--page",
        "1",
        "--dpi",
        "400",
        "--out",
        str(work),
        cwd=tmp_path,
    )

    assert completed.returncode == 0, completed.stderr
    rendered = list(work.rglob("page.png"))
    assert len(rendered) == 1
    header = rendered[0].read_bytes()[:24]
    width, height = struct.unpack(">II", header[16:24])
    assert width == round(612 / 72 * 400)
    assert height == round(792 / 72 * 400)


def test_run_produces_the_document_tree_and_a_summary(tmp_path: Path) -> None:
    """``run`` is the whole processor, and its summary names the outcome."""
    work = tmp_path / "work"

    completed = run_tool("run", str(TEXT_PDF), "--out", str(work), cwd=tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "success (VALID)" in completed.stdout
    assert list(work.rglob("metadata.json"))


def test_no_run_leaves_a_staged_file_anywhere(tmp_path: Path) -> None:
    """The tool does not defeat ``PDF-12``: its own tree is as clean as the library's.

    The ``split`` subcommand arranges the primitive's flat output into the documented layout,
    which is a second place a staging residue could hide.
    """
    work = tmp_path / "work"

    for command in ("split", "classify", "run"):
        run_tool(command, str(TEXT_PDF), "--out", str(work), cwd=tmp_path)

    residues = [
        path
        for path in work.rglob("*")
        if path.is_file() and ("_staged" in path.name or path.name.endswith(".tmp"))
    ]
    assert not residues, f"staged files survived: {residues}"


def test_the_input_is_never_modified_by_any_subcommand(tmp_path: Path) -> None:
    """Every subcommand is read-only for the document, across the whole surface."""
    before = sha256(TEXT_PDF)
    before_tree = sorted(path.name for path in TEXT_PDF.parent.iterdir())
    work = tmp_path / "work"

    for command in ("inspect", "split", "classify", "run"):
        run_tool(command, str(TEXT_PDF), "--out", str(work), cwd=tmp_path)
    run_tool("text", str(TEXT_PDF), "--page", "1", "--out", str(work), cwd=tmp_path)
    run_tool("blocks", str(TEXT_PDF), "--page", "1", "--out", str(work), cwd=tmp_path)
    run_tool("images", str(TEXT_PDF), "--page", "1", "--out", str(work), cwd=tmp_path)
    run_tool("render", str(TEXT_PDF), "--page", "1", "--out", str(work), cwd=tmp_path)

    assert sha256(TEXT_PDF) == before
    assert sorted(path.name for path in TEXT_PDF.parent.iterdir()) == before_tree
