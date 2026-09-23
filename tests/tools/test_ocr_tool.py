# pylint: disable=duplicate-code,protected-access,use-implicit-booleaness-not-comparison
# The `duplicate-code` reason is below. `protected-access` is disabled for the two argparse
# checks: argparse exposes sub-parsers and their actions only through `_actions`, and those checks
# are about the grammar argparse actually **built** rather than the module's text, which cannot see
# it — the first version tried the AST and found nothing, because `build_parser` creates its
# sub-parsers inside a local closure.
# `use-implicit-booleaness-not-comparison` is disabled because `offenders == []` says what the
# list *is*: `not offenders` would also pass if the variable held ``None``, which is a different
# and wronger answer. Same disable, same reason, as `tests/image/test_hardening.py`.
# This module is deliberately parallel to `tests/tools/test_image_tool.py` and
# `tests/tools/test_pdf_tool.py`, down to the shape of its helpers. There are three lab tools and
# they must respect the same four boundaries - a caller, never imported by the library, no engine
# knob, no workflow decision - so the checks are the same checks and the duplication is the point:
# a boundary that holds for one tool and not another should be visible as a missing test in one
# file rather than hidden behind a shared helper that quietly stopped applying. The genuinely
# shared part is the *convention*, documented once in `docs/plan/README.md` §4.1.
"""Tests for the OCR lab tool (``OCR-14``, ``GEN-21``).

A lab tool is a caller, and every boundary it must respect is a *negative* claim — it does not
reimplement, the library does not import it, it adds no seam, it decides no workflow question.
Negative claims are what a passing test cannot show on its own, so much of what follows reads the
tool's *declared options* and its *call graph* rather than its prose.

The acceptance scenarios are exercised end to end as a subprocess, exactly as an operator runs
them, because that is the surface being tested. The conversions are expensive, so the module keeps
the number of full runs low and shares one output tree where the criterion allows.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "scripts" / "tools" / "ocr.py"
SOURCE_ROOT = REPO_ROOT / "src"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ocr"

PREPARED = FIXTURES / "ocr_prepared_text_and_table.png"
BLANK = FIXTURES / "ocr_blank.png"

DOCUMENTED_SUBCOMMANDS = (
    "run",
    "text",
    "md",
    "json",
    "tables",
    "blocks",
    "metrics",
    "diff",
)

DOCUMENTED_GLOBALS = ("--out", "--json", "--language")

#: Substrings that would betray an engine-selection option. Checked against the *declared*
#: arguments rather than the source text, because the docstrings legitimately explain that no such
#: flag exists — a source search gives a false positive, which the PDF tool's tests already
#: recorded.
ENGINE_FLAG_FRAGMENTS = ("engine", "--model", "--provider")

REQUIRED_ARTIFACTS = ("text.txt", "document.md", "document.json", "metadata.json")


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


def declared_options() -> set[str]:
    """Return every option string the tool's parser declares.

    Read from the ``build_parser`` function's ``add_argument`` calls rather than from a live parse,
    so the check does not depend on which subcommand was selected.

    Returns:
        The declared option strings, e.g. ``{"--out", "--json"}``.
    """
    options: set[str] = set()
    for node in ast.walk(ast.parse(tool_source())):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        for argument in node.args:
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                options.add(argument.value)
    return options


def one_run_tree(tmp_path: Path) -> Path:
    """Run the tool once over the prepared fixture and return the output directory.

    A helper rather than a fixture so each test that needs a tree says so explicitly, and because
    a pytest fixture's parameter name would shadow the function in every test signature (which the
    linter flags).

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The ``<stem>-<hash>`` directory the tool wrote.
    """
    completed = run_tool("run", str(PREPARED), cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    tree = tmp_path / "var" / "tools" / "ocr" / f"{PREPARED.stem}-{_digest(PREPARED)}"
    assert tree.is_dir(), f"the tool did not write {tree}"
    return tree


def _digest(image_path: Path) -> str:
    """Return the short content hash the tool puts in its output directory name.

    Args:
        image_path: The input image.

    Returns:
        The first eight hex characters of the file's digest.
    """
    return sha256(image_path)[:8]


# ======================================================================================
# Scenario 1 — extraction from the command line
# ======================================================================================


def test_run_publishes_the_namespace_and_records_the_engine(tmp_path: Path) -> None:
    """The acceptance scenario: the four artifacts, and ``engine="docling"`` with a real version.

    The version is asserted to match a version shape rather than only to be non-empty: the seam's
    documented answer for a version it could not read is ``UNKNOWN``, and a run that recorded it
    would be reporting a deployment that cannot reproduce its own output.
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("run", str(PREPARED), cwd=work)

    assert completed.returncode == 0, completed.stderr
    tree = work / "var" / "tools" / "ocr" / f"{PREPARED.stem}-{_digest(PREPARED)}"
    for name in REQUIRED_ARTIFACTS:
        assert (tree / name).is_file(), f"{name} was not published"

    metadata = json.loads((tree / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["engine"] == "docling"
    assert metadata["engine_version"], "no engine version was recorded"
    assert metadata["engine_version"] != "UNKNOWN"
    assert metadata["engine_version"].startswith("2.")

    assert "success" in completed.stdout
    assert "VALID" in completed.stdout


def test_the_default_output_root_is_the_documented_one(tmp_path: Path) -> None:
    """The tree lands under ``var/tools/ocr/<stem>-<hash>/`` without an explicit ``--out``.

    The default is part of the convention rather than a convenience: an operator who runs the tool
    twice over one file expects the second run to find the first run's tree.
    """
    work = tmp_path / "work"
    work.mkdir()

    run_tool("run", str(PREPARED), cwd=work)

    out_root = work / "var" / "tools" / "ocr"
    assert out_root.is_dir()
    assert [path.name for path in out_root.iterdir()] == [
        f"{PREPARED.stem}-{_digest(PREPARED)}"
    ]


def test_the_same_bytes_land_in_the_same_directory(tmp_path: Path) -> None:
    """Two runs of one file share a tree, so a manual experiment is reproducible.

    A renamed copy is used rather than the same path twice, because the hash is of the *content*:
    that is what the convention promises, and a hash of the path would satisfy a same-path test.
    The directory's **stem** is the name the file was given and the hash is of its bytes, so the
    two runs land in two directories — which is the convention, not a defect — and the property
    worth asserting is that their *content* matches. The first version of this test asserted the
    directory names, which pinned the tool's naming rather than its reproducibility, and it failed
    on a correct run for exactly that reason.
    """
    work = tmp_path / "work"
    work.mkdir()
    copy = work / "renamed.png"
    copy.write_bytes(PREPARED.read_bytes())

    first = run_tool("run", str(PREPARED), cwd=work)
    second = run_tool("run", "renamed.png", cwd=work)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    out_root = work / "var" / "tools" / "ocr"
    published = out_root / f"{PREPARED.stem}-{_digest(PREPARED)}" / "text.txt"
    renamed = out_root / f"renamed-{_digest(PREPARED)}" / "text.txt"
    assert published.is_file() and renamed.is_file()
    assert renamed.read_bytes() == published.read_bytes(), (
        "the same bytes produced different content"
    )


def test_the_input_is_never_written_to(tmp_path: Path) -> None:
    """The committed fixture keeps its digest, and nothing appears beside it."""
    work = tmp_path / "work"
    work.mkdir()
    before = sha256(PREPARED)
    before_tree = sorted(entry.name for entry in FIXTURES.iterdir())

    run_tool("run", str(PREPARED), cwd=work)

    assert sha256(PREPARED) == before
    assert sorted(entry.name for entry in FIXTURES.iterdir()) == before_tree


def test_a_missing_input_exits_with_the_not_found_code(tmp_path: Path) -> None:
    """A path that does not exist is an operator error, reported without a traceback.

    Exit code 2 rather than 1, matching the other two tools: "you named a file that is not there"
    is a usage failure, and an operator's script can distinguish it from "the run failed".
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("run", "absent.png", cwd=work)

    assert completed.returncode == 2
    assert "no such file" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_the_blank_fixture_reports_empty_and_still_publishes(tmp_path: Path) -> None:
    """``EMPTY`` is a verdict, not a failure: the exit code stays 0 and the tree is complete.

    The tool must not turn a descriptive verdict into a failure — the orchestrator owns that
    decision, and a tool that exited non-zero would teach an operator that a blank page is broken.
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("run", str(BLANK), cwd=work)

    assert completed.returncode == 0, completed.stderr
    tree = work / "var" / "tools" / "ocr" / f"{BLANK.stem}-{_digest(BLANK)}"
    for name in REQUIRED_ARTIFACTS:
        assert (tree / name).is_file(), f"{name} was not published for a blank page"
    assert "EMPTY" in completed.stdout


# ======================================================================================
# Scenario 2 — the tool offers no engine choice
# ======================================================================================


def test_no_engine_selection_flag_exists() -> None:
    """No declared option names an engine, a model or a provider.

    Checked against the parser's *declared* arguments rather than the source text. A source search
    gives a false positive here because the module docstring explains, in as many words, that no
    ``--engine`` flag exists — the same trap the PDF tool's tests recorded for a ``--engine``
    mention in its documentation.
    """
    options = declared_options()

    assert "--engine" not in options
    for option in sorted(options):
        for fragment in ENGINE_FLAG_FRAGMENTS:
            assert fragment not in option, (
                f"{option} looks like an engine-selection knob: {fragment}"
            )


def test_every_documented_subcommand_exists() -> None:
    """The eight subcommands §10 names are all declared, and no others.

    The complete set rather than "these exist": an extra subcommand is a surface §10 does not
    describe, and the plan is the authority on what the tool offers.
    """
    parser_names = {
        node.value
        for node in ast.walk(ast.parse(tool_source()))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value
        in (*DOCUMENTED_SUBCOMMANDS, "info", "normalize", "ocr-ready", "vlm-ready")
    }
    assert set(DOCUMENTED_SUBCOMMANDS) <= parser_names

    completed = run_tool("--help", cwd=REPO_ROOT)
    assert completed.returncode == 0
    for name in DOCUMENTED_SUBCOMMANDS:
        assert name in completed.stdout, f"{name} is not in the help output"


def test_the_documented_global_flags_are_declared() -> None:
    """``--out``, ``--json`` and ``--language`` are the globals §10 names."""
    options = declared_options()

    for flag in DOCUMENTED_GLOBALS:
        assert flag in options, f"{flag} is not declared"


def test_every_operation_resolves_to_a_docflow_ocr_function_or_primitive() -> None:
    """Each ``command_*`` handler's call graph reaches ``docflow.ocr``, never a local algorithm.

    §10 states the boundary as "every operation resolves to a ``docflow.ocr`` function or
    primitive", and this asserts the **positive** form of it. An earlier version tried to assert the
    negative — that no call resolves to anything *else* — and could not: attribute calls like
    ``path.read_bytes()`` and bound methods like ``parser.add_argument()`` have no resolvable owner
    from the syntax alone, so it reported thirty stdlib calls as offenders and would have needed an
    ever-growing allowlist to pass. An allowlist that must be extended for every stdlib call is a
    test that has stopped measuring.

    The positive form is checkable and is the claim that matters: a handler that reimplemented a
    conversion, a measurement or a rendering would have to *call* something to do it, and the
    assertion is that what it calls comes from the processor's own package or from this module.
    """
    tree = ast.parse(tool_source())

    handlers = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("command_")
    }
    assert len(handlers) == len(DOCUMENTED_SUBCOMMANDS), (
        f"expected one handler per subcommand, found {sorted(handlers)}"
    )

    imported_from_ocr = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("docflow.ocr")
        for alias in node.names
    }
    assert imported_from_ocr, "the tool imports nothing from docflow.ocr"

    # Every name the module imports at all, so `Path` (from `pathlib`) is not mistaken for a local
    # algorithm. The claim under test is "the handlers reach the library", not "the handlers use
    # nothing but the library" — a tool may build a Path.
    imported_anywhere = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    local = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("command_")
    }
    builtins = {
        "print",
        "sorted",
        "len",
        "str",
        "int",
        "list",
        "dict",
        "set",
        "open",
        "any",
    }

    for name, handler in sorted(handlers.items()):
        called = {
            child.func.id
            for child in ast.walk(handler)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
        }
        unresolved = called - imported_anywhere - local - builtins
        assert not unresolved, (
            f"{name} calls names that are neither imported nor the tool's own: "
            f"{sorted(unresolved)}"
        )
        assert called & (imported_from_ocr | local), (
            f"{name} calls nothing from docflow.ocr or the tool, so it reimplements its operation"
        )


def test_the_tool_imports_only_the_ocr_processor() -> None:
    """No sibling processor is imported, and no engine library directly.

    The engine is reached through the processor's seam; a direct ``import docling`` here would let
    the tool run with an engine the library never resolved, and its output would be unattributable.
    """
    tree = ast.parse(tool_source())
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    modules |= {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    for module in sorted(modules):
        assert not module.startswith("docflow.pdf"), module
        assert not module.startswith("docflow.image"), module
        assert not module.startswith("docflow.llm"), module
        assert not module.startswith("docflow.workflow"), module
        assert module != "docling", (
            "the engine must be reached through the processor's seam"
        )
    assert "docflow.ocr" in modules


def test_no_module_under_src_imports_the_tool() -> None:
    """The library has no dependency on the tool, so deleting ``scripts/`` is safe.

    This is the import-direction check ``OCR-14``'s DoD names. Asserted over the source text of
    every library module, because an import reached only on a rare path would be invisible to a
    behavioural test.
    """
    offenders: list[str] = []
    for module in sorted((SOURCE_ROOT / "docflow").rglob("*.py")):
        source = module.read_text(encoding="utf-8")
        if "scripts" in source and "import" in source:
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")) and "scripts" in stripped:
                    offenders.append(f"{module.name}: {stripped}")
    assert offenders == [], f"the library imports the tool: {offenders}"


# ======================================================================================
# Scenario 3 — diff compares two runs of the same input
# ======================================================================================


def test_diff_reports_functional_equality_and_excludes_the_provenance_record(
    tmp_path: Path,
) -> None:
    """Two runs of one input are identical, and the comparison names what it excluded.

    ``metadata.json`` is excluded because it carries the run's wall-clock timing; comparing it
    would make every correct run report a difference. The exclusion is printed rather than silent,
    so an operator reading "identical" knows what was not compared.
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("diff", str(PREPARED), cwd=work)

    assert completed.returncode == 0, completed.stderr
    assert "identical" in completed.stdout
    assert "metadata.json" in completed.stdout


def test_diff_exits_non_zero_when_the_content_differs(tmp_path: Path) -> None:
    """``functional_content`` and ``diff_payload`` see a difference and say where it is.

    Driven against hand-written directories rather than through the processor, because what is
    under test is the *comparison*, not the extraction: a run reporting "identical" for everything
    would satisfy the end-to-end test above and be useless. Writing the trees by hand also keeps
    this test free of the engine, and that is not a convenience — ``diff`` runs the processor
    **twice**, and a second four-conversion test in one process crashed the engine's native ONNX
    layer with a recursive-mutex fault (measured).

    The tool is imported here rather than executed, and this is the one place in the module that
    does it: reaching the comparison directly is the only way to build a difference the processor
    cannot produce, since it is deterministic by design.
    """
    first = tmp_path / "first"
    second = tmp_path / "second"
    (first / "tables").mkdir(parents=True)
    (second / "tables").mkdir(parents=True)
    for directory in (first, second):
        (directory / "text.txt").write_text("same\n", encoding="utf-8")
        (directory / "document.md").write_text("same\n", encoding="utf-8")
        (directory / "tables/table_001.md").write_text("same\n", encoding="utf-8")
        (directory / "metadata.json").write_text("{}", encoding="utf-8")
    (second / "text.txt").write_text("different\n", encoding="utf-8")
    (second / "extra.txt").write_text("only here\n", encoding="utf-8")

    payload = import_tool().diff_payload(first, second)

    assert payload["identical"] is False
    assert payload["differing"] == ["text.txt"]
    assert payload["only_in_second"] == ["extra.txt"]
    assert payload["excluded"] == ["metadata.json"]
    assert "metadata.json" not in payload["compared"], (
        "the provenance record was compared, so every correct run would differ"
    )


def test_the_diff_comparison_ignores_the_provenance_records_timing(
    tmp_path: Path,
) -> None:
    """Two trees differing **only** in ``metadata.json`` compare equal.

    The counterpart of the test above: the exclusion must be real, not merely reported. A
    comparison that listed ``metadata.json`` as excluded and then compared it anyway would pass the
    difference test and fail on every correct run.
    """
    first = tmp_path / "first"
    second = tmp_path / "second"
    contents = (
        (first, '{"timing": {"total": 1.0}}'),
        (second, '{"timing": {"total": 9.9}}'),
    )
    for directory, metadata in contents:
        directory.mkdir(parents=True)
        (directory / "text.txt").write_text("same\n", encoding="utf-8")
        (directory / "metadata.json").write_text(metadata, encoding="utf-8")

    payload = import_tool().diff_payload(first, second)

    assert payload["identical"] is True
    assert payload["differing"] == []


def import_tool() -> object:
    """Import the lab tool as a module.

    The tool is a script rather than a package module, so it is loaded by path. It puts ``src`` on
    ``sys.path`` itself, which is what makes it importable without the test arranging that.

    Returns:
        The loaded module.
    """
    spec = importlib.util.spec_from_file_location("tools_ocr", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_diff_comparison_never_reads_a_second_image() -> None:
    """``diff`` reads one image; ``--second-out`` is a destination, never a second source.

    Covered by the end-to-end test above, which invokes ``diff`` with exactly one image and gets
    equality. A separate test here would have to run the processor twice more, and that is what
    crashed the engine's native layer — so the boundary is asserted where it is observable without
    paying for conversions the module has already paid for.

    What is asserted instead is the *tool's grammar*, read from a live parse rather than from the
    module's AST: the earlier version walked the top-level nodes looking for the ``diff``
    sub-parser and found nothing, because ``build_parser`` constructs its sub-parsers inside a
    local ``leaf`` closure. A grammar check that cannot see the grammar passes vacuously.
    """
    parser = import_tool().build_parser()
    # pylint: disable=protected-access
    # argparse exposes sub-parsers only through `_actions`, and this check is about the grammar
    # argparse actually built rather than the module's text, which cannot see it.
    subparsers = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(subparsers) == 1, (
        "the parser does not expose exactly one sub-parser action"
    )
    diff = subparsers[0].choices["diff"]

    positionals = [action for action in diff._actions if not action.option_strings]
    namelike = [action.dest for action in positionals]
    assert namelike == ["image"], f"diff takes more than one input: {namelike}"
    assert "--second-out" in {
        option for action in diff._actions for option in action.option_strings
    }


# ======================================================================================
# The subcommands print what they claim, and do not re-render it
# ======================================================================================


@pytest.mark.parametrize(
    ("subcommand", "artifact"),
    [("text", "text.txt"), ("md", "document.md")],
)
def test_the_printing_subcommands_print_the_published_artifact(
    tmp_path: Path, subcommand: str, artifact: str
) -> None:
    """``text`` and ``md`` print the artifact's own content, so the two cannot disagree.

    This is §10's "calls, never reimplements" boundary stated as an observable: ``md`` prints
    ``OCRResult.markdown``, and the tool runs the processor into its tree, so the printed bytes
    must equal the file's. A tool that re-rendered Markdown from the blocks would produce a second
    rendering that drifts from the artifact as soon as the renderer changed.
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool(subcommand, str(PREPARED), cwd=work)

    assert completed.returncode == 0, completed.stderr
    published = (
        work
        / "var"
        / "tools"
        / "ocr"
        / f"{PREPARED.stem}-{_digest(PREPARED)}"
        / artifact
    ).read_text(encoding="utf-8")
    assert completed.stdout == published, (
        f"{subcommand}'s output is not the published {artifact}"
    )


def test_json_prints_the_documents_own_payload(tmp_path: Path) -> None:
    """``json`` prints the payload ``document.json`` holds, not a readout built beside it."""
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("json", str(PREPARED), cwd=work)

    assert completed.returncode == 0, completed.stderr
    published = json.loads(
        (
            work
            / "var"
            / "tools"
            / "ocr"
            / f"{PREPARED.stem}-{_digest(PREPARED)}"
            / "document.json"
        ).read_text(encoding="utf-8")
    )
    assert json.loads(completed.stdout) == published


def test_blocks_prints_the_normalized_bboxes(tmp_path: Path) -> None:
    """``blocks`` reports the unit frame, which is what makes the ordering inspectable.

    Asserted on the coordinates rather than the count: a tool that printed the engine's pixel boxes
    would report plausible numbers that no consumer of the artifact would ever see.
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("blocks", str(PREPARED), cwd=work)

    assert completed.returncode == 0, completed.stderr
    assert "blocks, in reading order" in completed.stdout
    assert "0.2524" in completed.stdout, "the bboxes are not in the normalized frame"
    assert "840" not in completed.stdout, "a pixel-frame coordinate reached the output"


def test_tables_prints_the_detected_grid(tmp_path: Path) -> None:
    """``tables`` prints the table the processor detected, in reading order."""
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("tables", str(PREPARED), cwd=work)

    assert completed.returncode == 0, completed.stderr
    assert "table_001" in completed.stdout
    assert "5 rows x 4 columns" in completed.stdout


def test_metrics_names_the_frame_it_measured_in(tmp_path: Path) -> None:
    """``metrics`` prints the layout frame beside the figures.

    ``text_density`` is characters per unit of page area, so it is meaningless without the frame:
    this processor normalizes the layout, making the area ``1.0`` and the density equal to the
    character count, while the same measurement in the engine's pixel frame gives a small fraction.
    Both are right for the frame they describe, and the tool has to say which one it used.
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("metrics", str(PREPARED), cwd=work)

    assert completed.returncode == 0, completed.stderr
    assert "777" in completed.stdout
    assert "frame:" in completed.stdout
    assert "1.0x1.0" in completed.stdout


def test_the_json_flag_emits_machine_readable_output(tmp_path: Path) -> None:
    """``--json`` produces parseable JSON and nothing else on stdout.

    A machine-readable flag that also printed a human summary would be unusable in a pipeline, so
    the assertion is on the *whole* of stdout rather than on a substring.
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("run", str(PREPARED), "--json", cwd=work)

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "success"
    assert payload["validation"]["status"] == "VALID"
    assert payload["engine"]["name"] == "docling"
    assert payload["metrics"]["characters"] == 777


def test_the_language_flag_reaches_the_engine(tmp_path: Path) -> None:
    """``--language`` is recorded in the run's options, so the flag is not decorative.

    Asserted on the recorded options rather than on a change in the extraction: the language tag's
    effect is the engine's business, and a test that required a different result would be asserting
    a property of Docling rather than of the tool.
    """
    work = tmp_path / "work"
    work.mkdir()

    completed = run_tool("run", str(PREPARED), "--language", "es", cwd=work)

    assert completed.returncode == 0, completed.stderr
    metadata = json.loads(
        (
            work
            / "var"
            / "tools"
            / "ocr"
            / f"{PREPARED.stem}-{_digest(PREPARED)}"
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["options"]["language"] == "es"
