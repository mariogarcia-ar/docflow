"""Structural guards and glue tests for the lab tools (``SCR-08``).

Two questions, answered separately on purpose:

* **the shape** — the tool set, the frontier in both directions, "calls, never
  reimplements", the orchestrator's own frontier on ``workflow.py``, and the parse surface;
* **the glue** — one ``run`` path per tool, driven through ``main()`` with the doubles the
  processors already ship, asserting that the tool built the request its flags describe and
  called the entry point exactly once.

No test here executes a tool subcommand that would reach a real engine: the guards read the
tree statically, and the glue tests install an in-memory double. The real seam is exercised
by hand (``SCR-07``) and recorded as an observation, never as a gate.
"""

from __future__ import annotations

import ast
import importlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.tools import _cli
from tests.fakes.engines.fake_poppler import FakePage, FakePoppler
from tests.fakes.processors import ProcessorDoubles
from tests.support import imported_modules, sha256_of

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "scripts" / "tools"
SRC_ROOT = REPO_ROOT / "src" / "docflow"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
FIXTURES_TXT = REPO_ROOT / "tests" / "fixtures-txt"

TOOLS = ("pdf", "image", "ocr", "llm", "workflow")
TOOL_FILES = {"_cli.py", *(f"{tool}.py" for tool in TOOLS)}

DOCUMENTED_SUBCOMMANDS: dict[str, tuple[str, ...]] = {
    "pdf": (
        "inspect",
        "split",
        "render",
        "text",
        "blocks",
        "images",
        "classify",
        "run",
    ),
    "image": (
        "info",
        "metrics",
        "normalize",
        "ocr-ready",
        "vlm-ready",
        "classify",
        "run",
    ),
    "ocr": ("run", "text", "md", "json", "tables", "blocks", "metrics"),
    "llm": ("call", "node", "graph", "resume", "status", "models", "tokens", "fake"),
    "workflow": (
        "run",
        "plan",
        "status",
        "resume",
        "force",
        "skip",
        "stop",
        "context",
    ),
}

#: The engine binaries a tool must never name: naming one would mean it had started
#: reimplementing the processor instead of calling it.
ENGINE_BINARIES = (
    "pdftoppm",
    "pdftotext",
    "pdfimages",
    "pdfseparate",
    "pdfinfo",
    "pdfunite",
    "pdftocairo",
)

#: The engine modules and provider SDKs a tool must never name, matched on whole words so a
#: symbol such as ``extract_docling_text`` is not mistaken for the engine's own module.
ENGINE_MODULES = (
    "cv2",
    "PIL",
    "docling",
    "subprocess",
    "httpx",
    "openai",
    "ollama",
    "anthropic",
)

FORBIDDEN_IN_TOOLS = re.compile(
    r"\b(" + "|".join(ENGINE_BINARIES + ENGINE_MODULES) + r")\b"
)

#: The frontier the library must never cross back over. ``var`` is matched only as a word
#: that is not a method access, so an engine call such as ``...Cv2.var()`` is not mistaken
#: for the bench's output directory.
FORBIDDEN_IN_SRC = re.compile(r"\bscripts\b|(?<![.\w])var\b")

SAMPLE_PDF = FIXTURES / "pdf" / "pdf_sample_mixed.pdf"
SAMPLE_IMAGE = FIXTURES / "image" / "color_layout.png"
SAMPLE_OCR = FIXTURES / "ocr" / "ocr_prepared_text_and_table.png"
CASE_TEXT = sorted((FIXTURES_TXT / "casos").glob("*.txt"))[0]


def tool_module(name: str) -> Any:
    """Import one tool module by its namespace-package path.

    Args:
        name: The tool's name, without its suffix.

    Returns:
        The imported module.
    """
    return importlib.import_module(f"scripts.tools.{name}")


def tool_paths() -> list[Path]:
    """Return the tool files, in a stable order."""
    return sorted(path for path in TOOLS_DIR.glob("*.py"))


# --- Guard 1: the tool set -----------------------------------------------------------


def test_the_tool_set_is_exactly_the_convention() -> None:
    """``scripts/tools/`` holds ``_cli.py`` and the five tools, and no other module."""
    found = {path.name for path in tool_paths()}

    assert found == TOOL_FILES, f"the tool set drifted: {sorted(found)}"


# --- Guard 2: the frontier, both directions ------------------------------------------


def test_no_module_under_src_mentions_the_tools_or_their_output() -> None:
    """Nothing under ``src/docflow/`` references ``scripts`` or ``var``."""
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in sorted(SRC_ROOT.rglob("*.py"))
        if FORBIDDEN_IN_SRC.search(path.read_text(encoding="utf-8"))
    ]

    assert not offenders, f"a source module reached for the bench: {offenders}"


def test_no_module_under_src_imports_the_test_tree() -> None:
    """Nothing under ``src/docflow/`` imports anything under ``tests/``."""
    offenders = [
        f"{path.name}:{line} imports {module}"
        for path in sorted(SRC_ROOT.rglob("*.py"))
        for line, module in imported_modules(path)
        if module == "tests" or module.startswith("tests.")
    ]

    assert not offenders, f"a source module imported the test tree: {offenders}"


# --- Guard 3: a tool calls, it never reimplements ------------------------------------


@pytest.mark.parametrize("tool", ("_cli", *TOOLS))
def test_no_tool_names_an_engine_or_a_provider_sdk(tool: str) -> None:
    """A tool's source names no engine binary, engine module or provider SDK."""
    source = (TOOLS_DIR / f"{tool}.py").read_text(encoding="utf-8")
    found = sorted({match.group(0) for match in FORBIDDEN_IN_TOOLS.finditer(source)})

    assert not found, f"{tool}.py names an engine or an SDK: {found}"


def test_the_shared_plumbing_holds_no_contract() -> None:
    """``_cli.py`` imports nothing from ``docflow`` and nothing from ``tests``."""
    imported = [module for _, module in imported_modules(TOOLS_DIR / "_cli.py")]
    offenders = [
        module
        for module in imported
        if module == "docflow"
        or module.startswith("docflow.")
        or module == "tests"
        or module.startswith("tests.")
    ]

    assert not offenders, f"the plumbing reached into the library: {offenders}"


# --- Guard 4: ``workflow.py`` carries the orchestrator's frontier ---------------------


def test_workflow_tool_imports_no_primitives_module() -> None:
    """``workflow.py`` imports no ``docflow.*.primitives`` module."""
    offenders = [
        f"line {line}: {module}"
        for line, module in imported_modules(TOOLS_DIR / "workflow.py")
        if module.startswith("docflow.") and ".primitives" in module
    ]

    assert not offenders, f"workflow.py reached a processor's internals: {offenders}"


# --- Guard 5: the library never calls ``sys.exit`` -----------------------------------


def test_no_module_under_src_calls_sys_exit() -> None:
    """No module under ``src/docflow/`` exits the process."""
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr == "exit"
                and isinstance(function.value, ast.Name)
                and function.value.id == "sys"
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert not offenders, f"a source module calls sys.exit: {offenders}"


# --- Guard 6: the parse surface ------------------------------------------------------


@pytest.mark.parametrize("tool", TOOLS)
def test_every_documented_subcommand_parses(tool: str) -> None:
    """Each tool exposes a parser builder and every documented subcommand parses."""
    parser = tool_module(tool).build_parser()

    for subcommand in DOCUMENTED_SUBCOMMANDS[tool]:
        assert parser.parse_args([subcommand]) is not None


@pytest.mark.parametrize("tool", TOOLS)
def test_help_exits_zero(tool: str) -> None:
    """``--help`` is part of the surface the runbook quotes and exits ``0``."""
    with pytest.raises(SystemExit) as exit_info:
        tool_module(tool).build_parser().parse_args(["--help"])

    assert exit_info.value.code == 0


# --- Guard 7: what the header claims about publishing ---------------------------------


#: The subcommands whose report is the stdout summary: they publish no file, so their run says so
#: instead of naming an output root no run creates. Restated on purpose — which subcommands write
#: is a property of the tools, not of the library, and the hand run that verified the sets is
#: recorded in ``docs/plan/bitacora.md`` (2026-09-27). A subcommand that moves between the two
#: sets, or is renamed, reddens this test.
REPORT_ONLY: dict[str, tuple[str, ...]] = {
    "pdf": ("inspect", "text", "blocks"),
    "image": ("info", "metrics", "classify"),
    "ocr": ("text", "md", "json", "tables", "blocks", "metrics"),
    "llm": ("node", "status", "models", "tokens"),
    "workflow": ("plan", "status", "context"),
}


@pytest.mark.parametrize("tool", TOOLS)
def test_every_tool_declares_the_subcommands_that_publish_nothing(tool: str) -> None:
    """Each tool declares its report-only subcommands, and names only documented ones."""
    declared = tool_module(tool).REPORT_ONLY

    assert declared == REPORT_ONLY[tool]
    assert set(declared) <= set(DOCUMENTED_SUBCOMMANDS[tool])


# --- SCR-01 unit tests: the shared plumbing -----------------------------------------


def test_output_root_is_stable_and_input_specific(tmp_path: Path) -> None:
    """The same input lands in the same directory; a different one does not."""
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    assert _cli.output_root("pdf", first) == _cli.output_root("pdf", first)
    assert _cli.output_root("pdf", first) != _cli.output_root("pdf", second)
    assert _cli.output_root("pdf", first).name.startswith("a-")


def test_output_root_honours_an_explicit_directory(tmp_path: Path) -> None:
    """``--out`` replaces the default root entirely."""
    source = tmp_path / "a.pdf"
    source.write_bytes(b"one")
    explicit = tmp_path / "elsewhere"

    assert _cli.output_root("pdf", source, out=explicit) == explicit.resolve()


def test_the_header_states_when_a_run_publishes_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """A subcommand that publishes no file says so instead of naming a run root."""
    source = tmp_path / "in.pdf"
    root = tmp_path / "out"

    _cli.print_header("pdf", "inspect", source, root, publishes=False)

    err = capsys.readouterr().err
    assert "publishes no file" in err
    assert str(root) not in err

    _cli.print_header("pdf", "render", source, root)

    assert f"output: {root}" in capsys.readouterr().err


def test_resolve_fixture_reports_an_absolute_path() -> None:
    """A bare fixture name resolves under a fixture root to an absolute path."""
    resolved = _cli.resolve_fixture("pdf/pdf_sample_text.pdf")

    assert resolved.is_absolute()
    assert resolved.is_file()
    assert resolved.is_relative_to(_cli.FIXTURES_ROOT)


def test_resolve_fixture_finds_a_bare_name_in_a_nested_root() -> None:
    """A bare name needs no subdirectory spelling: the fixture tree is searched for it."""
    resolved = _cli.resolve_fixture("pdf_sample_mixed.pdf")

    assert resolved == (FIXTURES / "pdf" / "pdf_sample_mixed.pdf").resolve()


def test_resolve_fixture_refuses_an_ambiguous_bare_name(tmp_path: Path) -> None:
    """A bare name that names two files is reported with both, never guessed."""
    for directory in ("inside", "outside"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "same.pdf").write_bytes(b"%PDF-1.7\n")

    with pytest.raises(_cli.FixtureNotFoundError) as ambiguous:
        _cli.resolve_fixture("same.pdf", fixtures_root=tmp_path)

    message = str(ambiguous.value)
    assert "ambiguous" in message
    assert "inside" in message
    assert "outside" in message


@pytest.mark.parametrize("name", ("pdf", str(FIXTURES / "pdf")))
def test_resolve_fixture_refuses_a_directory(name: str) -> None:
    """A directory is refused as a directory, never reported missing."""
    with pytest.raises(_cli.FixtureNotFoundError) as refusal:
        _cli.resolve_fixture(name)

    message = str(refusal.value)
    assert "is a directory, not a file" in message
    assert str(FIXTURES / "pdf") in message


def test_an_empty_input_name_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An empty name is refused as missing, never looked up as the working directory."""
    with pytest.raises(SystemExit) as exit_info:
        tool_module("pdf").main(["inspect", ""])

    assert exit_info.value.code == 2
    assert "an input is required" in capsys.readouterr().err


def test_resolve_fixture_refuses_an_unknown_name() -> None:
    """An unknown name is reported, never silently turned into a path."""
    with pytest.raises(_cli.FixtureNotFoundError):
        _cli.resolve_fixture("no-such-fixture.pdf")


def test_exit_code_is_one_for_a_failure_and_zero_otherwise() -> None:
    """The exit-code mapping reads the result's own status."""

    def result(status: str) -> SimpleNamespace:
        return SimpleNamespace(status=status)

    assert _cli.exit_code_for(result("success")) == 0
    assert _cli.exit_code_for(result("partial")) == 0
    assert _cli.exit_code_for(result("failed")) == 1


# --- Glue: the ``run`` path over the doubles the processors ship ----------------------


def test_pdf_run_builds_the_request_and_calls_the_processor_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``pdf.py run`` builds the options its flags describe and calls ``process_pdf``."""
    doubles = ProcessorDoubles().install(monkeypatch)

    code = tool_module("pdf").main(
        [
            "--out",
            str(tmp_path),
            "run",
            str(SAMPLE_PDF),
            "--dpi",
            "200",
            "--extract-text",
        ]
    )

    assert code == 0
    assert doubles.pdf.calls == 1
    request = doubles.pdf.requests[0]
    assert request.pdf_path == SAMPLE_PDF.resolve()
    assert request.options.dpi == 200
    assert request.options.extract_text is True
    assert request.options.render is False
    assert request.output_dir == tmp_path.resolve()


def test_image_run_calls_the_processor_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``image.py run`` builds the transformations its flags describe."""
    doubles = ProcessorDoubles().install(monkeypatch)

    code = tool_module("image").main(
        [
            "--out",
            str(tmp_path),
            "run",
            str(SAMPLE_IMAGE),
            "--normalize",
            "--prepare-for-ocr",
        ]
    )

    assert code == 0
    assert doubles.image.calls == 1
    request = doubles.image.requests[0]
    assert request.image_path == SAMPLE_IMAGE.resolve()
    assert request.options.normalize is True
    assert request.options.prepare_for_ocr is True
    assert request.options.prepare_for_vlm is False


def test_ocr_run_calls_the_processor_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``ocr.py run`` carries the OCR options its flags describe."""
    doubles = ProcessorDoubles().install(monkeypatch)

    code = tool_module("ocr").main(
        ["--out", str(tmp_path), "run", str(SAMPLE_OCR), "--layout", "--tables"]
    )

    assert code == 0
    assert doubles.ocr.calls == 1
    request = doubles.ocr.requests[0]
    assert request.image_path == SAMPLE_OCR.resolve()
    assert request.options.layout is True
    assert request.options.tables is True
    assert request.options.engine_options == {}


def test_workflow_plan_calls_no_processor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``workflow.py plan`` resolves the plan and invokes no processor."""
    doubles = ProcessorDoubles().install(monkeypatch)

    code = tool_module("workflow").main(
        [
            "--out",
            str(tmp_path),
            "--allow-ocr",
            "--no-allow-vlm",
            "--pdf-dpi",
            "200",
            "--pdf-extract-text",
            "--image-normalize",
            "--ocr",
            "--ocr-layout",
            "--task",
            "extract",
            "--provider",
            "example",
            "--model",
            "example-model",
            "--template",
            "simple_extract",
            "plan",
            str(FIXTURES / "pdf" / "pdf_sample_text.pdf"),
        ]
    )

    assert code == 0
    assert doubles.calls() == {"pdf": 0, "image": 0, "ocr": 0, "llm": 0}


def test_workflow_run_reports_a_named_configuration_refusal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing option key is refused by name, printed, and exits ``1``."""
    doubles = ProcessorDoubles().install(monkeypatch)

    code = tool_module("workflow").main(
        [
            "--out",
            str(tmp_path),
            "--allow-ocr",
            "--no-allow-vlm",
            "--image-normalize",
            "--ocr",
            "--task",
            "extract",
            "--provider",
            "example",
            "--model",
            "example-model",
            "--template",
            "simple_extract",
            "run",
            str(FIXTURES / "pdf" / "pdf_sample_text.pdf"),
        ]
    )

    assert code == 1
    assert doubles.calls() == {"pdf": 0, "image": 0, "ocr": 0, "llm": 0}
    printed = capsys.readouterr().out
    assert "CONFIGURATION_ERROR" in printed
    assert "pdf" in printed


# --- Glue: a typed failure is printed, never raised ----------------------------------


def test_pdf_inspect_prints_a_typed_failure_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corrupt document is reported as a typed record; the tool does not raise."""
    double = FakePoppler((), failures={"pdfinfo": (1, "Syntax Error")})
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)

    code = tool_module("pdf").main(
        [
            "--out",
            str(tmp_path),
            "inspect",
            str(FIXTURES / "pdf" / "pdf_corrupt.pdf"),
        ]
    )

    assert code == 1
    assert "ERROR CORRUPTED_PDF" in capsys.readouterr().out


def test_pdf_inspect_states_its_input_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The header states the resolved input; the human summary does not repeat it."""
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    fixture = FIXTURES / "pdf" / "pdf_sample_mixed.pdf"

    code = tool_module("pdf").main(["--out", str(tmp_path), "inspect", str(fixture)])

    assert code == 0
    captured = capsys.readouterr()
    assert captured.err.count(str(fixture)) == 1
    assert str(fixture) not in captured.out
    assert "page_count: 1" in captured.out


def test_json_keeps_the_input_the_header_states(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A ``--json`` body read on its own still names the file it describes."""
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    fixture = FIXTURES / "pdf" / "pdf_sample_mixed.pdf"

    code = tool_module("pdf").main(
        ["--json", "--out", str(tmp_path), "inspect", str(fixture)]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["input"] == str(fixture)


def test_the_pdf_header_states_whether_the_subcommand_publishes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``inspect`` reports only, so its header names no run root; ``render`` names one."""
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    fixture = str(SAMPLE_PDF)

    assert tool_module("pdf").main(["--out", str(tmp_path), "inspect", fixture]) == 0
    assert "publishes no file" in capsys.readouterr().err

    assert (
        tool_module("pdf").main(
            ["--out", str(tmp_path), "render", fixture, "--page", "1", "--dpi", "72"]
        )
        == 0
    )
    assert f"output: {tmp_path.resolve()}" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("subcommand", "flags"),
    (("inspect", ()), ("text", ("--page", "1")), ("blocks", ("--page", "1"))),
)
def test_a_report_only_pdf_subcommand_publishes_nothing(
    subcommand: str,
    flags: tuple[str, ...],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """What the header claims, the filesystem confirms: nothing was published."""
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)

    code = tool_module("pdf").main(
        ["--out", str(tmp_path), subcommand, str(SAMPLE_PDF), *flags]
    )

    assert code == 0
    assert not list(tmp_path.rglob("*")), f"{subcommand} published a file"


# --- Glue: a primitive subcommand through the engine double --------------------------


def test_pdf_render_calls_the_render_primitive_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``pdf.py render`` drives its own processor's primitive and publishes the PNG."""
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)

    code = tool_module("pdf").main(
        [
            "--out",
            str(tmp_path),
            "render",
            str(FIXTURES / "pdf" / "pdf_sample_text.pdf"),
            "--page",
            "1",
            "--dpi",
            "72",
        ]
    )

    assert code == 0
    published = sorted(tmp_path.glob("page_001_*.png"))
    assert len(published) == 1
    assert [argv[0].split("/")[-1] for argv in double.calls] == ["pdftoppm"]


def test_pdf_does_not_mutate_its_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run leaves the input fixture byte for byte as it was."""
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    before = sha256_of(SAMPLE_PDF)

    tool_module("pdf").main(
        [
            "--out",
            str(tmp_path),
            "render",
            str(SAMPLE_PDF),
            "--page",
            "1",
            "--dpi",
            "72",
        ]
    )

    assert sha256_of(SAMPLE_PDF) == before


# --- Glue: the inference surface over the scripted provider --------------------------


def test_llm_call_reaches_the_seam_and_prints_the_parsed_result(
    providers: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``llm.py call`` renders, calls the provider once and prints the parsed answer."""
    fake = providers()
    code = tool_module("llm").main(
        [
            "--fixture",
            f"casos/{CASE_TEXT.name}",
            "--out",
            str(tmp_path),
            "call",
            "--provider",
            "ollama",
            "--model",
            "example-model",
            "--task",
            "extract",
            "--template",
            "simple_extract",
            "--schema",
            "simple",
        ]
    )

    assert code == 0
    assert len(fake.calls) == 1
    payload = capsys.readouterr().out
    assert "schema_valid: True" in payload
    assert "parsed_response:" in payload


def test_llm_call_without_a_model_is_a_usage_error(
    providers: Any, tmp_path: Path
) -> None:
    """No inference is built without a stated provider and model."""
    fake = providers()
    with pytest.raises(SystemExit) as exit_info:
        tool_module("llm").main(
            [
                "--fixture",
                f"casos/{CASE_TEXT.name}",
                "--out",
                str(tmp_path),
                "call",
                "--provider",
                "ollama",
                "--task",
                "extract",
                "--template",
                "simple_extract",
            ]
        )

    assert exit_info.value.code == 2
    assert fake.calls == []


def test_llm_tokens_counts_offline(providers: Any, tmp_path: Path) -> None:
    """``llm.py tokens`` counts offline; the provider is asked only for the window."""
    fake = providers(context_window=4096)

    code = tool_module("llm").main(
        [
            "--fixture",
            f"casos/{CASE_TEXT.name}",
            "--out",
            str(tmp_path),
            "tokens",
            "--provider",
            "ollama",
            "--model",
            "example-model",
        ]
    )

    assert code == 0
    assert fake.calls == []
    assert len(fake.model_calls) == 1


def test_llm_fake_demonstrates_the_resume_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``llm.py fake`` runs the chain twice and the second run reuses every node."""
    code = tool_module("llm").main(
        [
            "--fixture",
            f"casos/{CASE_TEXT.name}",
            "--out",
            str(tmp_path),
            "--run-id",
            "lab-fake-run",
            "fake",
            "--provider",
            "ollama",
            "--model",
            "example-model",
            "--task",
            "extract",
            "--template",
            "simple_extract",
            "--schema",
            "simple",
        ]
    )

    assert code == 0
    printed = capsys.readouterr().out
    assert "REUSE" in printed
    assert (tmp_path / "state.json").is_file()


def test_a_fixture_name_before_the_subcommand_resolves_out_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The run header prints the resolved absolute path, and the request carries it."""
    doubles = ProcessorDoubles().install(monkeypatch)

    code = tool_module("pdf").main(
        [
            "--fixture",
            "pdf/pdf_sample_text.pdf",
            "--out",
            str(tmp_path),
            "run",
            "--dpi",
            "150",
            "--extract-images",
            "--layout",
        ]
    )

    assert code == 0
    resolved = FIXTURES / "pdf" / "pdf_sample_text.pdf"
    request = doubles.pdf.requests[0]
    assert request.pdf_path == resolved.resolve()
    assert request.options.dpi == 150
    assert request.options.extract_images is True
    assert request.options.layout is True
    assert str(resolved.resolve()) in capsys.readouterr().err
