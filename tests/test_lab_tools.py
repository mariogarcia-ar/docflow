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

# One module holds every tool's guard and glue: the convention it asserts is cross-tool, so
# splitting it by tool would scatter the one thing it exists to prove. The length is the harness,
# not duplication.
# pylint: disable=too-many-lines

from __future__ import annotations

import ast
import importlib
import json
import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from docflow.llm import primitives as llm_primitives
from scripts.tools import _cli, _llm
from tests.fakes.engines.fake_docling import (
    FakeConversionStatus,
    FakeDocling,
    FakeDoclingDocument,
    footer_document,
    prepared_document,
)
from tests.fakes.engines.fake_opencv import FakeOpenCV
from tests.fakes.engines.fake_poppler import FakeImage, FakePage, FakePoppler
from tests.fakes.processors import ProcessorDoubles
from tests.support import imported_modules, sha256_of

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "scripts" / "tools"
SRC_ROOT = REPO_ROOT / "src" / "docflow"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
FIXTURES_TXT = REPO_ROOT / "tests" / "fixtures-txt"

TOOLS = (
    "pdf",
    "batch_pdf",
    "image",
    "batch_image",
    "ocr",
    "batch_ocr",
    "llm",
    "batch_llm",
    "workflow",
)
TOOL_FILES = {
    "_cli.py",
    "_batch.py",
    "_pdf.py",
    "_image.py",
    "_ocr.py",
    "_llm.py",
    *(f"{tool}.py" for tool in TOOLS),
}

#: The tools whose input is a folder. Their documented invocation names the folder *and* the
#: command, so a probe that passes only one of the two proves nothing about the other.
BATCH_TOOLS = ("batch_pdf", "batch_image", "batch_ocr", "batch_llm")

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
    "batch_pdf": (
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
    "batch_image": (
        "info",
        "metrics",
        "normalize",
        "ocr-ready",
        "vlm-ready",
        "classify",
        "run",
    ),
    "ocr": ("run", "text", "mixed", "md", "json", "tables", "blocks", "metrics"),
    "batch_ocr": ("run", "text", "mixed", "md", "json", "tables", "blocks", "metrics"),
    "llm": (
        "call",
        "prompt",
        "node",
        "graph",
        "resume",
        "status",
        "models",
        "tokens",
        "fake",
    ),
    "batch_llm": ("call", "graph", "node", "tokens", "prompt"),
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

#: The page image the vision path reads: the receipt whose OCR text ``CASE_TEXT`` is the twin of.
CASE_IMAGE = FIXTURES / "casos" / "66cd35e9-a0a2-4342-b4f9-4c7e7c39d6b0.jpg"


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


@pytest.mark.parametrize(
    "tool", ("_cli", "_batch", "_pdf", "_image", "_ocr", "_llm", *TOOLS)
)
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
        arguments = [str(FIXTURES), subcommand] if tool in BATCH_TOOLS else [subcommand]
        assert parser.parse_args(arguments) is not None


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
    "pdf": ("inspect", "blocks"),
    "batch_pdf": (),
    "batch_image": (),
    "image": ("info", "metrics", "classify"),
    "ocr": ("md", "json", "tables", "blocks", "metrics"),
    "batch_ocr": (),
    "llm": ("prompt", "node", "status", "models", "tokens"),
    "batch_llm": (),
    "workflow": ("plan", "status", "context"),
}


@pytest.mark.parametrize("tool", TOOLS)
def test_every_tool_declares_the_subcommands_that_publish_nothing(tool: str) -> None:
    """Each tool declares its report-only subcommands, and names only documented ones."""
    declared = tool_module(tool).REPORT_ONLY

    assert declared == REPORT_ONLY[tool]
    assert set(declared) <= set(DOCUMENTED_SUBCOMMANDS[tool])


# --- The batch driver: a folder in, a mirrored tree out -------------------------------


def build_corpus(tmp_path: Path, *relative_pdfs: str) -> Path:
    """Write an empty PDF per relative path under ``<tmp>/corpus`` and return the folder."""
    corpus = tmp_path / "corpus"
    for relative in relative_pdfs:
        target = corpus / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"%PDF-1.7\n")
    return corpus


def test_batch_pdf_mirrors_the_folder_it_walked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every PDF gets its own directory under ``--out``, mirroring the tree it came from."""
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    corpus = build_corpus(tmp_path, "sub1/a.pdf", "sub2/deeper/b.pdf", "notes.txt")
    out = tmp_path / "mirror"

    code = tool_module("batch_pdf").main(["--out", str(out), str(corpus), "inspect"])

    assert code == 0
    records = sorted(out.rglob("inspect.json"))
    assert [record.parent.relative_to(out).as_posix() for record in records] == [
        "sub1/a",
        "sub2/deeper/b",
    ]
    assert json.loads(records[0].read_text(encoding="utf-8"))["page_count"] == 1
    printed = capsys.readouterr().out
    assert "files: 2" in printed
    assert "notes.txt" not in printed


def test_batch_pdf_states_the_command_it_defaulted_to(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no subcommand the run says which one it made, and still publishes its records."""
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    corpus = build_corpus(tmp_path, "a.pdf")
    out = tmp_path / "mirror"

    code = tool_module("batch_pdf").main(["--out", str(out), str(corpus)])

    assert code == 0
    assert "inspect (default, none stated)" in capsys.readouterr().err
    assert (out / "a" / "inspect.json").is_file()


def test_batch_pdf_keeps_one_record_per_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two commands over one input keep both records: neither overwrites the other.

    Both used to be filed as ``result.json`` in the input's own directory, so running
    ``classify`` after ``inspect`` silently replaced the first record with the second.
    """
    double = FakePoppler((FakePage(lines=("A line of text.",)),))
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    corpus = build_corpus(tmp_path, "a.pdf")
    out = tmp_path / "mirror"

    inspect_code = tool_module("batch_pdf").main(
        ["--out", str(out), str(corpus), "inspect"]
    )
    classify_code = tool_module("batch_pdf").main(
        ["--out", str(out), str(corpus), "classify", "--page", "1"]
    )

    assert (inspect_code, classify_code) == (0, 0)
    assert (out / "a" / "inspect.json").is_file()
    assert (out / "a" / "classify.json").is_file()
    record = json.loads((out / "a" / "inspect.json").read_text(encoding="utf-8"))
    assert record["page_count"] == 1


def test_batch_pdf_counts_every_failure_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corpus has bad files: the run reports each one instead of stopping at the first."""
    double = FakePoppler((), failures={"pdfinfo": (1, "Syntax Error")})
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    corpus = build_corpus(tmp_path, "a.pdf", "sub/b.pdf")
    out = tmp_path / "mirror"

    code = tool_module("batch_pdf").main(["--out", str(out), str(corpus), "inspect"])

    assert code == 1
    printed = capsys.readouterr().out
    assert printed.count("ERROR CORRUPTED_PDF") == 2
    assert "failed: 2" in printed
    assert not list(out.rglob("inspect.json"))


def test_batch_pdf_refuses_a_folder_that_is_not_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A file where a folder belongs is a usage error, named as one."""
    not_a_folder = tmp_path / "corpus.txt"
    not_a_folder.write_text("not a folder", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        tool_module("batch_pdf").main([str(not_a_folder)])

    assert exit_info.value.code == 2
    assert "is not a folder" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("subcommand", "flags", "missing"),
    (("render", ("--page", "1"), "--dpi"), ("run", (), "--dpi")),
)
def test_a_batch_refuses_a_missing_required_flag_before_it_walks(
    subcommand: str,
    flags: tuple[str, ...],
    missing: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing flag is refused once, before the run announces itself.

    The folder is empty on purpose. Validating per input calls no method when there is no
    input to run, so this is the corpus over which the gap used to go unnoticed: the run
    reported ``files: 0`` and exited ``0`` for a command that could not have run at all.

    ``--dpi`` is the only flag left in that position. ``--page`` is not required any more:
    a page command that states none reads every page, so there is no gap to refuse.
    """
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(SystemExit) as exit_info:
        tool_module("batch_pdf").main(
            ["--out", str(tmp_path / "mirror"), str(empty), subcommand, *flags]
        )

    assert exit_info.value.code == 2
    printed = capsys.readouterr().err
    assert f"{subcommand} requires {missing}" in printed
    assert f"== batch_pdf.py {subcommand} ==" not in printed


@pytest.mark.parametrize(
    ("subcommand", "flags", "missing"),
    (("render", ("--page", "1"), "--dpi"), ("run", (), "--dpi")),
)
def test_pdf_refuses_a_missing_required_flag_before_its_header(
    subcommand: str,
    flags: tuple[str, ...],
    missing: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The single-input tool refuses the same gap, before it names the run it would make."""
    with pytest.raises(SystemExit) as exit_info:
        tool_module("pdf").main([subcommand, str(SAMPLE_PDF), *flags])

    assert exit_info.value.code == 2
    printed = capsys.readouterr().err
    assert f"{subcommand} requires {missing}" in printed
    assert f"== pdf.py {subcommand} ==" not in printed


def _page_double(
    monkeypatch: pytest.MonkeyPatch,
    *pages: FakePage,
    failures: dict[Any, Any] | None = None,
) -> FakePoppler:
    """Install a Poppler double over ``pages`` and return it."""
    double = FakePoppler(pages, failures=failures)
    monkeypatch.setattr("docflow.pdf.primitives.subprocess.run", double.run)
    return double


def _binaries_called(double: FakePoppler) -> list[str]:
    """Return the engine binaries a run reached, in call order."""
    return [Path(call[0]).name for call in double.calls]


def test_a_page_command_reads_every_page_when_no_page_is_stated(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Omitting ``--page`` reads the whole document, and the payload says which scope it read."""
    double = _page_double(
        monkeypatch, *(FakePage(lines=(f"Line {number}.",)) for number in range(1, 4))
    )

    code = tool_module("pdf").main(
        ["--json", "--out", str(tmp_path), "text", str(SAMPLE_PDF)]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "all pages (3)"
    assert [entry["page"] for entry in payload["pages"]] == [1, 2, 3]
    assert (payload["status"], payload["errors"]) == ("success", [])
    reads = [call for call in double.calls if "-tsv" in call]
    assert len(reads) == 3


def test_a_one_page_document_is_a_scope_of_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A one-page document needs no branch: the scope is simply the whole document."""
    _page_double(monkeypatch, FakePage(lines=("The only line.",)))

    code = tool_module("pdf").main(
        ["--json", "--out", str(tmp_path), "text", str(SAMPLE_PDF)]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "all pages (1)"
    assert [entry["page"] for entry in payload["pages"]] == [1]


def test_a_stated_page_keeps_its_payload_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--page`` returns one page's own keys, gaining the scope it states and its files."""
    _page_double(monkeypatch, *(FakePage(lines=("A line.",)) for _ in range(3)))

    code = tool_module("pdf").main(
        ["--json", "--out", str(tmp_path), "text", str(SAMPLE_PDF), "--page", "2"]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "page 2"
    assert payload["page"] == 2
    assert "pages" not in payload
    assert payload["text"].strip()
    assert Path(payload["output"]).name == "page_002.txt"
    assert Path(payload["layout_output"]).name == "page_002_layout.txt"


def test_a_stated_page_inspects_nothing_it_did_not_before(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A stated page needs no page count, so the path keeps its engine-call count."""
    double = _page_double(monkeypatch, FakePage(lines=("A line.",)))

    tool_module("pdf").main(
        ["--json", "--out", str(tmp_path), "text", str(SAMPLE_PDF), "--page", "1"]
    )

    assert "pdfinfo" not in _binaries_called(double)


def test_every_page_gets_its_own_images_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two pages' images cannot collide: the processor names them per call, not per page."""
    _page_double(monkeypatch, *(FakePage(images=(FakeImage(),)) for _ in range(2)))
    out = tmp_path / "run"

    code = tool_module("pdf").main(
        ["--json", "--out", str(out), "images", str(SAMPLE_PDF)]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "all pages (2)"
    written = sorted(path.relative_to(out).as_posix() for path in out.rglob("*.png"))
    assert written == [
        "page_001/images/image_001.png",
        "page_002/images/image_001.png",
    ]


def test_pdf_text_publishes_two_files_per_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``text`` publishes each page's text twice over: the reconstruction and the layout."""
    _page_double(
        monkeypatch, *(FakePage(lines=(f"Line {number}.",)) for number in range(1, 3))
    )
    out = tmp_path / "run"

    code = tool_module("pdf").main(
        ["--json", "--out", str(out), "text", str(SAMPLE_PDF)]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    entries = payload["pages"]
    assert [entry["page"] for entry in entries] == [1, 2]
    for entry, name in zip(entries, ("page_001.txt", "page_002.txt"), strict=True):
        written = out / name
        laid_out = out / name.replace(".txt", "_layout.txt")
        assert written.is_file() and laid_out.is_file()
        assert written.read_text(encoding="utf-8") == entry["text"]
        assert Path(entry["output"]).name == name
        assert Path(entry["layout_output"]).name == laid_out.name
        # Two reads, not one published twice: same words, different spacing.
        layout_text = laid_out.read_text(encoding="utf-8")
        assert layout_text != entry["text"]
        assert layout_text.split() == entry["text"].split()
        assert "  " in layout_text


def test_one_failing_page_does_not_end_the_document(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A page that fails is reported beside the pages that did not, and the run still reports."""
    _page_double(
        monkeypatch,
        *(FakePage(lines=("A line.",)) for _ in range(2)),
        failures={("pdftotext", 2): (1, "Syntax Error")},
    )

    code = tool_module("pdf").main(
        ["--json", "--out", str(tmp_path), "text", str(SAMPLE_PDF)]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "partial"
    assert [entry["page"] for entry in payload["pages"]] == [1]
    assert [error["page_number"] for error in payload["errors"]] == [2]
    assert payload["errors"][0]["type"]


def test_a_document_that_cannot_be_inspected_fails_before_the_loop(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No page count, no scope: the typed record is printed and no payload claims otherwise."""
    _page_double(monkeypatch, FakePage(), failures={"pdfinfo": (1, "Syntax Error")})

    code = tool_module("pdf").main(["--json", "text", str(SAMPLE_PDF)])

    assert code == 1
    printed = capsys.readouterr()
    assert "ERROR CORRUPTED_PDF" in printed.out
    assert "pages" not in printed.out


def test_batch_pdf_reports_a_partial_document_as_failed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The frame counts a payload-recorded error as a failure, records and all."""
    _page_double(
        monkeypatch,
        *(FakePage(lines=("A line.",)) for _ in range(2)),
        failures={("pdftotext", 2): (1, "Syntax Error")},
    )
    corpus = build_corpus(tmp_path, "a.pdf")
    out = tmp_path / "mirror"

    code = tool_module("batch_pdf").main(["--out", str(out), str(corpus), "text"])

    assert code == 1
    printed = capsys.readouterr().out
    assert "a.pdf: FAILED ->" in printed
    assert "failed: 1" in printed
    record = json.loads((out / "a" / "text.json").read_text(encoding="utf-8"))
    assert record["status"] == "partial"
    assert record["errors"][0]["page_number"] == 2


def test_batch_pdf_reads_every_page_of_each_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The batch carries no page flag of its own: each input is read whole."""
    _page_double(
        monkeypatch, *(FakePage(lines=(f"Line {number}.",)) for number in range(1, 3))
    )
    corpus = build_corpus(tmp_path, "a.pdf", "b.pdf")
    out = tmp_path / "mirror"

    code = tool_module("batch_pdf").main(["--out", str(out), str(corpus), "text"])

    assert code == 0
    for name in ("a", "b"):
        record = json.loads((out / name / "text.json").read_text(encoding="utf-8"))
        assert record["scope"] == "all pages (2)"
        assert [entry["page"] for entry in record["pages"]] == [1, 2]
    assert "files: 2" in capsys.readouterr().out


def test_write_payload_creates_the_directories_it_writes_through(
    tmp_path: Path,
) -> None:
    """The file half of the payload printer writes canonical JSON, parents and all."""
    written = _cli.write_payload(tmp_path / "a" / "b" / "payload.json", {"n": 1})

    assert json.loads(written.read_text(encoding="utf-8")) == {"n": 1}
    assert written.read_text(encoding="utf-8").endswith("\n")


def test_batch_image_mirrors_the_folder_it_walked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The image batch walks images, mirrors them, and states the command it made."""
    monkeypatch.setattr("docflow.image.primitives.cv2", FakeOpenCV())
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    shutil.copy(FIXTURES / "image" / "color_layout.png", corpus / "sub" / "a.png")
    shutil.copy(FIXTURES / "image" / "skewed_text.png", corpus / "b.png")
    (corpus / "notes.txt").write_text("not an image", encoding="utf-8")
    out = tmp_path / "mirror"

    code = tool_module("batch_image").main(["--out", str(out), str(corpus)])

    assert code == 0
    assert sorted(
        record.parent.relative_to(out).as_posix() for record in out.rglob("info.json")
    ) == ["b", "sub/a"]
    assert "info (default, none stated)" in capsys.readouterr().err


def test_image_reads_through_the_shared_layer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``image.py`` still builds its payload in the layer the batch tool shares."""
    monkeypatch.setattr("docflow.image.primitives.cv2", FakeOpenCV())

    code = tool_module("image").main(
        ["info", str(FIXTURES / "image" / "color_layout.png")]
    )

    assert code == 0
    assert "resolution:" in capsys.readouterr().out


def test_batch_image_writes_the_container_a_stated_quality_implies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The bench's ``--quality`` reaches the processor, and the record agrees with the file."""
    monkeypatch.setattr("docflow.image.primitives.cv2", FakeOpenCV())
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(FIXTURES / "image" / "color_layout.png", corpus / "a.png")
    out = tmp_path / "mirror"

    code = tool_module("batch_image").main(
        ["--out", str(out), str(corpus), "normalize", "--quality", "85"]
    )

    assert code == 0
    assert sorted(path.name for path in out.rglob("*") if path.is_file()) == [
        "normalize.json",
        "normalized.jpg",
    ]
    record = json.loads(next(out.rglob("normalize.json")).read_text(encoding="utf-8"))
    assert record["representation"]["format"] == "jpg"
    assert record["representation"]["kind"] == "normalized"


def install_ocr_engine(monkeypatch: pytest.MonkeyPatch) -> FakeDocling:
    """Install the Docling double at the seam the OCR layer calls and return it."""
    double = FakeDocling()
    monkeypatch.setattr("docflow.ocr.primitives.convert_image_with_docling", double)
    return double


def test_ocr_reads_through_the_shared_layer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``ocr.py`` builds its payload in the layer ``batch_ocr.py`` drives."""
    install_ocr_engine(monkeypatch)

    code = tool_module("ocr").main(["--out", str(tmp_path), "text", str(SAMPLE_OCR)])

    assert code == 0
    assert "Quarterly report" in capsys.readouterr().out
    assert "Quarterly report" in (tmp_path / "text.txt").read_text(encoding="utf-8")


def test_ocr_tables_asks_for_the_detection_it_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``tables`` asks the engine for tables with no flag stated; ``--no-tables`` still refuses.

    Detection is engine work, so a command whose whole answer *is* the detected tables has to ask
    for it. With ``--tables`` off by default that command reported the empty list — the truth about
    a document nobody asked the engine to look at, printed as if the image held no table at all,
    which is how a run over a real invoice reads "no tables" when it read nothing. The flag is
    still the flag: ``--no-tables`` states the opposite and is honoured.
    """
    install_ocr_engine(monkeypatch)

    code = tool_module("ocr").main(
        ["--json", "--out", str(tmp_path), "tables", str(SAMPLE_OCR)]
    )
    reported = json.loads(capsys.readouterr().out)

    assert code == 0
    assert [table["cells"] for table in reported["tables"]] == [
        [["Region", "Revenue"], ["North", "120"]]
    ]

    code = tool_module("ocr").main(
        ["--json", "--out", str(tmp_path), "tables", str(SAMPLE_OCR), "--no-tables"]
    )
    refused = json.loads(capsys.readouterr().out)

    assert code == 0
    assert not refused["tables"]


@pytest.mark.parametrize("command", DOCUMENTED_SUBCOMMANDS["batch_ocr"])
def test_only_the_two_table_commands_claim_the_detection(command: str) -> None:
    """``tables`` and ``mixed`` ask for the detection with no flag stated; the other six do not.

    Detection is engine work that only a stated flag starts, so a command whose answer *needs* the
    tables has to claim them itself or answer with less than it promises: ``tables`` would report
    an empty list, and ``mixed`` would publish the flat text under a name that says otherwise. The
    other six are left alone — claiming a capability a caller did not ask for is its own defect.
    """
    args = tool_module("batch_ocr").build_parser().parse_args([str(FIXTURES), command])

    assert args.tables is (command in {"tables", "mixed"})


def test_ocr_mixed_renders_a_page_footer_instead_of_dropping_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A page's footer is part of the page: ``mixed`` renders it, and ``text`` publishes it.

    The engine files a footer in its own content layer and reads the body alone unless the layers
    are stated, so a reading that never stated them loses the line without a word — on an invoice
    that is the ``CAE``. Both readings ask for the whole page.
    """
    monkeypatch.setattr(
        "docflow.ocr.primitives.convert_image_with_docling",
        FakeDocling(document=footer_document),
    )

    code = tool_module("ocr").main(
        ["--json", "--out", str(tmp_path), "mixed", str(SAMPLE_OCR)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["text"].endswith("CAE N°: 86327284406071")
    assert (tmp_path / "mixed.txt").read_text(encoding="utf-8") == payload["text"]

    assert (
        tool_module("ocr").main(["--out", str(tmp_path), "text", str(SAMPLE_OCR)]) == 0
    )
    assert "CAE N°: 86327284406071" in (tmp_path / "text.txt").read_text(
        encoding="utf-8"
    )


def test_ocr_mixed_renders_the_pages_rows_and_publishes_them(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``mixed`` publishes the page's rows as ``mixed.txt``, a table as its Markdown in place.

    The engine's own export states one region per line, so a form's label and its value arrive one
    under the other even where the page sets them side by side. This is the rendering that reads
    the page's *rows* instead, and it is ours rather than the engine's: one method under a name of
    its own — ``text.txt`` is the engine's export and stays that — holding exactly what the
    payload reports. The rows run top to bottom, and the table keeps its place in the reading.
    """
    install_ocr_engine(monkeypatch)

    code = tool_module("ocr").main(
        ["--json", "--out", str(tmp_path), "mixed", str(SAMPLE_OCR)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    published = (tmp_path / "mixed.txt").read_text(encoding="utf-8")
    assert published == payload["text"]
    assert Path(payload["output"]).read_text(encoding="utf-8") == published
    assert published == (
        "Quarterly report\n\n"
        "Revenue grew by twelve percent\n\n"
        "across every region.\n\n"
        "| Region | Revenue |\n| --- | --- |\n| North | 120 |\n\n"
        "Source: internal ledger"
    )
    assert not (tmp_path / "text.txt").exists()

    code = tool_module("ocr").main(
        ["--json", "--out", str(tmp_path), "mixed", str(SAMPLE_OCR), "--no-layout"]
    )
    unplaced = json.loads(capsys.readouterr().out)

    assert code == 0
    assert unplaced["text"] == (
        "Source: internal ledger\n\n"
        "| Region | Revenue |\n| --- | --- |\n| North | 120 |\n\n"
        "across every region.\n\n"
        "Quarterly report\n\n"
        "Revenue grew by twelve percent"
    )


def _trailing_space_document(width: float, height: float) -> FakeDoclingDocument:
    """Return the prepared document, with the engine's text carrying what normalization removes."""
    prepared = prepared_document(width, height)
    return FakeDoclingDocument(
        prepared.items,
        prepared.export_to_text() + "   \n\n",
        prepared.export_to_markdown(),
        width,
        height,
    )


def test_ocr_text_publishes_the_reading_run_gives_the_same_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``text`` publishes ``text.txt``, holding exactly what a ``run`` would have written there.

    One name means one reading: the two commands leave the same bytes for the same image, so an
    operator comparing a ``text`` run with a ``run`` cannot be reading two different things under
    one name. The bytes are the *normalized* text — the form the processor both publishes and
    reports — and the payload states the same string, because an artifact and the record of the
    same reading may not disagree.
    """
    monkeypatch.setattr(
        "docflow.ocr.primitives.convert_image_with_docling",
        FakeDocling(document=_trailing_space_document),
    )
    reported = tmp_path / "reported"
    contract = tmp_path / "contract"

    code = tool_module("ocr").main(
        ["--json", "--out", str(reported), "text", str(SAMPLE_OCR)]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert (
        tool_module("ocr").main(["--out", str(contract), "run", str(SAMPLE_OCR)]) == 0
    )

    published = (reported / "text.txt").read_text(encoding="utf-8")
    assert published == payload["text"]
    assert Path(payload["output"]).read_text(encoding="utf-8") == published
    assert published == (contract / "text.txt").read_text(encoding="utf-8")
    assert published.endswith("Source: internal ledger")
    assert "   \n" not in published


def test_batch_ocr_mirrors_the_folder_it_walked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The OCR batch walks images, mirrors them, and states the command it made."""
    install_ocr_engine(monkeypatch)
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    shutil.copy(SAMPLE_OCR, corpus / "sub" / "a.png")
    shutil.copy(SAMPLE_OCR, corpus / "b.png")
    (corpus / "notes.txt").write_text("not an image", encoding="utf-8")
    out = tmp_path / "mirror"

    code = tool_module("batch_ocr").main(["--out", str(out), str(corpus)])

    assert code == 0
    assert sorted(
        record.parent.relative_to(out).as_posix() for record in out.rglob("text.json")
    ) == ["b", "sub/a"]
    assert sorted(
        text_file.parent.relative_to(out).as_posix()
        for text_file in out.rglob("text.txt")
    ) == ["b", "sub/a"]
    assert "text (default, none stated)" in capsys.readouterr().err


def test_batch_ocr_types_an_engine_throw_and_keeps_going(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An input the engine refuses fails its own record; the rest of the corpus still runs."""
    install_ocr_engine(monkeypatch)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(SAMPLE_OCR, corpus / "good.png")
    (corpus / "bad.png").write_bytes(b"a .png that is not a PNG")
    out = tmp_path / "mirror"

    code = tool_module("batch_ocr").main(["--out", str(out), str(corpus)])

    assert code == 1
    printed = capsys.readouterr().out
    assert "ERROR ENGINE_ERROR" in printed
    assert "failed: 1" in printed
    assert [record.parent.name for record in out.rglob("text.json")] == ["good"]


def test_batch_ocr_reports_a_returned_failure_as_a_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A contract that *returned* a failed status is not reported as ``ok``.

    The failure never reaches the frame as an exception: ``run`` contains it and returns a
    ``FAILED`` result, so the line the run prints has to agree with the summary it ends with — and
    the typed record the payload states has to be shown, since no exception carried it.
    """
    refused = FakeDocling(
        status=FakeConversionStatus.FAILURE, errors=["no model available"]
    )
    monkeypatch.setattr("docflow.ocr.primitives.convert_image_with_docling", refused)
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(SAMPLE_OCR, corpus / "a.png")
    out = tmp_path / "mirror"

    code = tool_module("batch_ocr").main(["--out", str(out), str(corpus), "run"])

    assert code == 1
    printed = capsys.readouterr().out
    assert ": FAILED ->" in printed
    assert ": ok ->" not in printed
    assert "ERROR OCR_ERROR:" in printed
    assert "failed: 1" in printed
    assert (
        json.loads((out / "a" / "run.json").read_text(encoding="utf-8"))["status"]
        == "failed"
    )


def build_text_corpus(tmp_path: Path) -> Path:
    """Write a small text corpus and return the folder, with one file of each kind."""
    corpus = tmp_path / "corpus"
    (corpus / "sub").mkdir(parents=True)
    (corpus / "sub" / "a.txt").write_text("one case", encoding="utf-8")
    (corpus / "b.md").write_text("# another case", encoding="utf-8")
    (corpus / "template.json").write_text("{}", encoding="utf-8")
    return corpus


def build_page_corpus(tmp_path: Path) -> Path:
    """Write a small corpus of page images and return the folder."""
    corpus = tmp_path / "pages"
    corpus.mkdir()
    shutil.copy(CASE_IMAGE, corpus / "receipt.jpg")
    shutil.copy(FIXTURES / "image" / "skewed_text.png", corpus / "page.png")
    return corpus


#: A token count with the window stated by the caller: the one LLM command that reaches no provider
#: at all, which is what keeps these tests offline and independent of a served model.
OFFLINE_TOKENS: tuple[str, ...] = (
    "tokens",
    "--provider",
    "ollama",
    "--model",
    "llama3.1",
    "--context-window",
    "4096",
)


def test_llm_reads_through_the_shared_layer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``llm.py`` still builds its payload in the layer ``batch_llm.py`` drives."""
    code = tool_module("llm").main([*OFFLINE_TOKENS, str(CASE_TEXT)])

    assert code == 0
    assert "tokens:" in capsys.readouterr().out


def test_llm_call_files_step_artifacts_named_after_the_schema(
    providers: Any, tmp_path: Path
) -> None:
    """A ``call`` files its answer alone, and the run that produced it, under the step's names.

    The library's ``final_result.json`` is keyed by the run directory alone, so the detection gate
    and the base reading over one input would overwrite each other. ``call`` adds ``<stem>.json``
    (the answer alone — the object a later step reads back through ``--extra KEY=@FILE``) and
    ``<stem>_full.json`` (the run's result, the payload ``final_result.json`` holds) — here under
    the nested identifier ``extraction/invoice_detection``, whose last component is the file stem.
    """
    providers()
    assets = tmp_path / "assets"
    (assets / "schema" / "extraction").mkdir(parents=True)
    (assets / "template" / "extraction").mkdir(parents=True)
    shutil.copy(
        FIXTURES / "llm" / "schema" / "simple.schema.json",
        assets / "schema" / "extraction" / "invoice_detection.schema.json",
    )
    shutil.copy(
        FIXTURES / "llm" / "template" / "simple_extract.md",
        assets / "template" / "extraction" / "invoice_deteccion.md",
    )
    out = tmp_path / "run"

    code = tool_module("llm").main(
        [
            "--assets-dir",
            str(assets),
            "--out",
            str(out),
            "call",
            str(CASE_TEXT),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--task",
            "detection",
            "--template",
            "extraction/invoice_deteccion",
            "--schema",
            "extraction/invoice_detection",
        ]
    )

    assert code == 0
    final = json.loads((out / "final_result.json").read_text(encoding="utf-8"))
    answer = json.loads((out / "invoice_detection.json").read_text(encoding="utf-8"))
    full = json.loads((out / "invoice_detection_full.json").read_text(encoding="utf-8"))
    assert answer == final["parsed_response"]
    assert full == final


def test_llm_call_names_its_step_artifacts_when_the_caller_pins_one(
    providers: Any, tmp_path: Path
) -> None:
    """``--name`` is the pencil on the stem, so two steps can share one schema's last component.

    ``extraction/invoice`` and ``review/invoice`` both end in ``invoice``, so the review would
    overwrite the very answer it was handed. Naming the step is the smaller statement of the same
    remedy ``--out`` is.
    """
    providers()
    out = tmp_path / "run"

    code = tool_module("llm").main(
        [
            "--fixture",
            f"casos/{CASE_TEXT.name}",
            "--out",
            str(out),
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
            "--name",
            "review.json",
        ]
    )

    assert code == 0
    assert (out / "review.json").is_file()
    assert (out / "review_full.json").is_file()
    assert not (out / "simple.json").exists()


def test_llm_call_publishes_no_answer_when_the_provider_never_answered_in_json(
    providers: Any, tmp_path: Path
) -> None:
    """An answer the processor could not parse leaves the run's record and no answer file.

    The library keeps an answer's text only once it has parsed, so a non-JSON answer is a typed
    ``INVALID_JSON`` failure with nothing to publish as the answer. ``<stem>_full.json`` still
    holds the run — and the failure it carries — and the exit code is the failure's.
    """
    fake = providers(answers=["no json here", "no json either"])
    out = tmp_path / "run"

    code = tool_module("llm").main(
        [
            "--fixture",
            f"casos/{CASE_TEXT.name}",
            "--out",
            str(out),
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

    assert code == 1
    assert len(fake.calls) == 2
    assert not (out / "simple.json").exists()
    assert not (out / "simple.txt").exists()
    full = json.loads((out / "simple_full.json").read_text(encoding="utf-8"))
    assert full["status"] == "FAILED"
    assert full["errors"][0]["type"] == "INVALID_JSON"


def test_llm_call_streams_the_answer_to_stderr_and_files_the_same_run(
    providers: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--stream`` shows the answer arriving and records the body a waiting call would have got.

    The deltas go to stderr under their channel's header while stdout stays the payload, so a pipe
    keeps working, and the two step artifacts are the ones the same call writes without the switch.
    """
    providers()
    out = tmp_path / "run"

    code = tool_module("llm").main(
        [
            "--json",
            "--fixture",
            f"casos/{CASE_TEXT.name}",
            "--out",
            str(out),
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
            "--stream",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "[content]" in captured.err
    assert "schema_valid" in captured.out
    streamed = json.loads((out / "simple.json").read_text(encoding="utf-8"))
    assert (
        streamed
        == json.loads((out / "final_result.json").read_text(encoding="utf-8"))[
            "parsed_response"
        ]
    )


def test_llm_prompt_renders_what_a_call_would_send_and_reaches_no_provider(
    providers: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``prompt`` is the ask, not the answer: what it prints is the message a call carries.

    The comparison is not against a second copy of the template — the test renders, then *calls*
    with the scripted provider, and weighs the two against each other. A render that drifted from
    the call (a placeholder resolved differently, an extra dropped, the schema rendered or not)
    would agree with a copy and disagree with the call, which is the drift worth catching.
    """
    fake = providers()
    out = tmp_path / "run"
    tool_flags = ["--fixture", f"casos/{CASE_TEXT.name}", "--out", str(out)]
    command_flags = [
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
        "--extra",
        "source=native_text",
    ]

    code = tool_module("llm").main(["--json", *tool_flags, "prompt", *command_flags])

    rendered = json.loads(capsys.readouterr().out)
    assert code == 0
    assert fake.calls == []
    assert not out.exists()

    code = tool_module("llm").main([*tool_flags, "call", *command_flags])

    capsys.readouterr()
    assert code == 0
    assert len(fake.calls) == 1
    assert fake.calls[0].messages == [{"role": "user", "content": rendered["prompt"]}]
    assert rendered["prompt_tokens"] > 0


def test_llm_prompt_weighs_the_ask_against_a_stated_window_and_probes_none(
    providers: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """The window a render measures against is the one stated — an unstated one is not evidence.

    ``tokens`` reads the window from the provider when the caller states none; a render may not,
    because a probe is exactly the reach a render is meant not to make. So ``context_window`` is
    ``None`` and no overflow is claimed, and a stated window is honoured instead.
    """
    fake = providers(context_window=4096)
    tool_flags = ["--fixture", f"casos/{CASE_TEXT.name}"]
    command_flags = [
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

    code = tool_module("llm").main(["--json", *tool_flags, "prompt", *command_flags])

    unstated = json.loads(capsys.readouterr().out)
    assert code == 0
    assert unstated["context_window"] is None
    assert unstated["overflows"] is False
    assert fake.model_calls == []

    code = tool_module("llm").main(
        ["--json", *tool_flags, "prompt", *command_flags, "--context-window", "10"]
    )

    stated = json.loads(capsys.readouterr().out)
    assert code == 0
    assert stated["context_window"] == 10
    assert stated["overflows"] is True
    assert fake.model_calls == []


def test_llm_call_reads_a_page_image_as_the_document(
    providers: Any, tmp_path: Path
) -> None:
    """An image input **is** the document: the pixels are attached and no text is stated.

    The vision half of the registry — ``extraction/invoice_vision*`` and its reviewers — is made of
    templates with no ``<doc>``, so the call has to carry the page and nothing else. The template
    run here is the committed pixel fixture, the twin of ``simple_extract``: it says in its own text
    that the page is the source.
    """
    fake = providers()
    out = tmp_path / "run"

    code = tool_module("llm").main(
        [
            "--out",
            str(out),
            "call",
            str(CASE_IMAGE),
            "--provider",
            "ollama",
            "--model",
            "qwen2.5vl:7b",
            "--task",
            "vision",
            "--template",
            "simple_read_pixels",
            "--schema",
            "simple",
            "--name",
            "reading",
        ]
    )

    assert code == 0
    sent = fake.calls[-1]
    assert sent.images == [str(CASE_IMAGE.resolve())]
    assert "carries no text this request could quote" in sent.messages[0]["content"]
    assert (out / "reading.json").is_file()


def test_llm_call_refuses_a_page_for_a_template_that_asks_for_a_document(
    providers: Any, tmp_path: Path
) -> None:
    """The page's bytes are never handed to ``<doc>``: the placeholder is refused, not filled.

    A template that quotes a document is the text flow's, and running it over an image is a
    caller's mistake. The library types it ``DEPENDENCY_ERROR`` before the provider is reached,
    where rendering an empty document would have asked the model a different question.
    """
    fake = providers()
    out = tmp_path / "run"

    code = tool_module("llm").main(
        [
            "--out",
            str(out),
            "call",
            str(CASE_IMAGE),
            "--provider",
            "ollama",
            "--model",
            "qwen2.5vl:7b",
            "--task",
            "extract",
            "--template",
            "simple_extract",
            "--schema",
            "simple",
        ]
    )

    assert code == 1
    assert fake.calls == []
    assert not (out / "simple.json").exists()
    full = json.loads((out / "simple_full.json").read_text(encoding="utf-8"))
    assert full["status"] == "FAILED"
    assert full["errors"][0]["type"] == "DEPENDENCY_ERROR"
    assert "asks for a document" in full["errors"][0]["message"]


def test_llm_call_attaches_the_flag_images_beside_the_text_input(
    providers: Any, tmp_path: Path
) -> None:
    """``--image`` sends pixels *with* the document — the library's ``TEXT_PLUS_VLM`` call.

    A page photographed beside its own OCR text is one call that carries both, and the order the
    images are written in is the order they are attached. The template here carries ``<doc>``, so
    the text reaching it is the proof that the document was read rather than replaced by a page.
    """
    fake = providers()
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "page_and_text.md").write_text(
        "text:\n<doc>\n", encoding="utf-8"
    )
    document = tmp_path / "case.txt"
    document.write_text("the receipt's own OCR text", encoding="utf-8")
    second_page = FIXTURES / "image" / "skewed_text.png"

    code = tool_module("llm").main(
        [
            "--assets-dir",
            str(assets),
            "--out",
            str(tmp_path / "run"),
            "call",
            str(document),
            "--provider",
            "ollama",
            "--model",
            "qwen2.5vl:7b",
            "--task",
            "vision",
            "--template",
            "page_and_text",
            "--image",
            str(CASE_IMAGE),
            "--image",
            str(second_page),
        ]
    )

    assert code == 0
    sent = fake.calls[-1]
    assert "the receipt's own OCR text" in sent.messages[0]["content"]
    assert sent.images == [str(CASE_IMAGE.resolve()), str(second_page.resolve())]


def test_llm_prompt_states_the_pages_a_call_would_attach(
    providers: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """A render states the images it would send, and still reaches no provider.

    The pixels are part of the ask, so a render that named no image would be evidence about a
    different call than the one it claims to describe. The paths are stated; the bytes are never
    read, which is what keeps a render free.
    """
    fake = providers()

    code = tool_module("llm").main(
        [
            "--json",
            "prompt",
            str(CASE_IMAGE),
            "--provider",
            "ollama",
            "--model",
            "qwen2.5vl:7b",
            "--task",
            "vision",
            "--template",
            "simple_read_pixels",
            "--schema",
            "simple",
        ]
    )

    rendered = json.loads(capsys.readouterr().out)
    assert code == 0
    assert rendered["images"] == [str(CASE_IMAGE.resolve())]
    assert fake.calls == []


def test_llm_prompt_weighs_a_page_the_way_the_processor_does(
    providers: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """A render of a vision call carries the processor's own verdict, so a page is never blessed.

    ``count_tokens`` measures text, and a page costs thousands of tokens no text measurement sees,
    so a render comparing the prompt alone would report *it fits* for a call the processor refuses.
    ``--image-tokens`` is the caller's measurement of one image; without it the verdict is
    ``unmeasured`` — never ``fits`` — exactly as the pre-flight reports it.
    """
    fake = providers()
    flags = [
        "--json",
        "prompt",
        str(CASE_IMAGE),
        "--provider",
        "ollama",
        "--model",
        "qwen2.5vl:7b",
        "--task",
        "vision",
        "--template",
        "simple_read_pixels",
        "--schema",
        "simple",
    ]

    code = tool_module("llm").main([*flags, "--context-window", "4096"])

    unstated = json.loads(capsys.readouterr().out)
    assert code == 0
    assert unstated["prompt_tokens"] < 4096
    assert unstated["context_verdict"] == "unmeasured"
    assert unstated["overflows"] is False

    code = tool_module("llm").main(
        [*flags, "--context-window", "4096", "--image-tokens", "2800"]
    )

    sized = json.loads(capsys.readouterr().out)
    assert code == 0
    assert sized["context_verdict"] == "fits"

    code = tool_module("llm").main(
        [*flags, "--context-window", "512", "--image-tokens", "2800"]
    )

    exceeding = json.loads(capsys.readouterr().out)
    assert code == 0
    assert exceeding["context_verdict"] == "exceeds"
    assert exceeding["overflows"] is True
    assert fake.calls == []


def test_llm_tokens_refuses_a_page_image(capsys: pytest.CaptureFixture[str]) -> None:
    """`tokens` counts text: a page has no offline count, and a substituted one is not an answer."""
    with pytest.raises(SystemExit) as exit_info:
        tool_module("llm").main([*OFFLINE_TOKENS, str(CASE_IMAGE)])

    assert exit_info.value.code == 2
    assert "no offline token count" in capsys.readouterr().err


def test_llm_call_fills_named_extra_placeholders_from_a_flag_and_a_file(
    providers: Any, tmp_path: Path
) -> None:
    """``--extra`` is the CLI's only door onto ``extra_context``.

    Without it the tool states ``extra_context={}``, so a template carrying ``<extra:proposal>``
    cannot resolve and the run stops before the provider. ``KEY=@FILE`` is how one step's answer
    reaches the next over the shell; ``KEY=VALUE`` covers the rest. Two keys, two sections.
    """
    fake = providers()
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "review.md").write_text(
        "proposal:\n<extra:proposal>\nrubro:\n<extra:rubro>\nreceipt:\n<doc>\n",
        encoding="utf-8",
    )
    proposal = tmp_path / "invoice.json"
    proposal.write_text('{"moneda":"ARS"}', encoding="utf-8")
    out = tmp_path / "run"

    code = tool_module("llm").main(
        [
            "--assets-dir",
            str(assets),
            "--out",
            str(out),
            "call",
            str(CASE_TEXT),
            "--provider",
            "ollama",
            "--model",
            "qwen3.5:9b",
            "--task",
            "review",
            "--template",
            "review",
            "--extra",
            f"proposal=@{proposal}",
            "--extra",
            "rubro=Restaurante",
        ]
    )

    assert code == 0
    prompt = fake.calls[-1].messages[0]["content"]
    assert '{"moneda":"ARS"}' in prompt
    assert "Restaurante" in prompt
    assert "<extra:proposal>" not in prompt
    assert "<extra:rubro>" not in prompt


def test_dotenv_reads_the_configuration_file_and_skips_the_rest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The parser is small on purpose: comments, blanks, quotes, and a value carrying ``=``.

    A file that is not there is an empty mapping, not an error: the bench runs on its flags alone.
    """
    config = tmp_path / "config.env"
    config.write_text(
        "# a comment\n"
        "\n"
        "DOCFLOW_LLM_NUM_CTX=16384\n"
        'DOCFLOW_LLM_BASE_URL="http://localhost:11434"\n'
        "DOCFLOW_LLM_API_KEY='sk-not-a-number'\n"
        "DOCFLOW_LLM_SEED=7=allowed-in-a-value\n"
        "  DOCFLOW_LLM_TIMEOUT = 600  \n"
        "#DOCFLOW_LLM_PROVIDER=ollama\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(config))

    assert _cli.dotenv() == {
        "DOCFLOW_LLM_NUM_CTX": "16384",
        "DOCFLOW_LLM_BASE_URL": "http://localhost:11434",
        "DOCFLOW_LLM_API_KEY": "sk-not-a-number",
        "DOCFLOW_LLM_SEED": "7=allowed-in-a-value",
        "DOCFLOW_LLM_TIMEOUT": "600",
    }

    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(tmp_path / "gone.env"))
    assert _cli.env_value("DOCFLOW_LLM_NUM_CTX") is None


def test_a_real_environment_variable_beats_the_configuration_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The narrower statement wins: this run's variable over the bench's file."""
    config = tmp_path / "config.env"
    config.write_text("DOCFLOW_LLM_TIMEOUT=600\n", encoding="utf-8")
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(config))
    monkeypatch.setenv("DOCFLOW_LLM_TIMEOUT", "60")

    assert _cli.env_value("DOCFLOW_LLM_TIMEOUT") == "60"
    assert _cli.dotenv()["DOCFLOW_LLM_TIMEOUT"] == "600"


def test_llm_call_takes_its_decoding_options_from_the_configuration_file(
    providers: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The context knob has to reach the request without being retyped on every command.

    ``num_ctx`` is the one that gives a reasoning reviewer room; ``timeout`` is the processor's own
    control and lands on the call rather than in the passthrough options. The header says what the
    file contributed, because the file is not an artifact field.
    """
    fake = providers()
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "plain.md").write_text("<doc>\n", encoding="utf-8")
    config = tmp_path / "config.env"
    config.write_text(
        "DOCFLOW_LLM_NUM_CTX=16384\n"
        "DOCFLOW_LLM_TIMEOUT=600\n"
        "DOCFLOW_LLM_API_KEY=sk-abc\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(config))

    code = tool_module("llm").main(
        [
            "--assets-dir",
            str(assets),
            "--out",
            str(tmp_path / "run"),
            "call",
            str(CASE_TEXT),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--task",
            "extract",
            "--template",
            "plain",
        ]
    )

    assert code == 0
    sent = fake.calls[-1]
    assert sent.options["num_ctx"] == 16384
    assert sent.api_key == "sk-abc"
    assert sent.timeout == 600
    assert "config:" in capsys.readouterr().err


def test_an_option_flag_beats_the_configuration_file(
    providers: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--option`` is about this run and the file is about the bench; the narrower one wins."""
    fake = providers()
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "plain.md").write_text("<doc>\n", encoding="utf-8")
    config = tmp_path / "config.env"
    config.write_text("DOCFLOW_LLM_NUM_CTX=16384\n", encoding="utf-8")
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(config))

    code = tool_module("llm").main(
        [
            "--assets-dir",
            str(assets),
            "--out",
            str(tmp_path / "run"),
            "call",
            str(CASE_TEXT),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--task",
            "extract",
            "--template",
            "plain",
            "--option",
            "num_ctx=4096",
        ]
    )

    assert code == 0
    assert fake.calls[-1].options["num_ctx"] == 4096


def test_no_configuration_sends_no_decoding_options(
    providers: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file with blank values states nothing, so no sampling default is invented for the call.

    The bench adds a key only when a source spells a non-blank value, and a blank placeholder is
    nothing stated — which is what keeps the provider on the model's own defaults.
    """
    fake = providers()
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "plain.md").write_text("<doc>\n", encoding="utf-8")
    config = tmp_path / "config.env"
    config.write_text(
        "DOCFLOW_LLM_NUM_CTX=\n"
        "DOCFLOW_LLM_TEMPERATURE=\n"
        "DOCFLOW_LLM_TOP_P=\n"
        "DOCFLOW_LLM_THINK=\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(config))

    code = tool_module("llm").main(
        [
            "--assets-dir",
            str(assets),
            "--out",
            str(tmp_path / "run"),
            "call",
            str(CASE_TEXT),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--task",
            "extract",
            "--template",
            "plain",
        ]
    )

    assert code == 0
    assert fake.calls[-1].options == {}


def test_the_sampling_knobs_reach_the_call_from_the_configuration_file(
    providers: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``think``, ``min_p`` and the card's sampling values are stated once in the file.

    ``think=false`` is the loop brake for a reasoning reviewer, ``min_p`` is the sampling floor, and
    ``top_p``/``repeat_penalty``/``presence_penalty`` are what a reviewer model's card publishes;
    none has a flag of its own, so the file is where an operator states them once.
    """
    fake = providers()
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "plain.md").write_text("<doc>\n", encoding="utf-8")
    config = tmp_path / "config.env"
    config.write_text(
        "DOCFLOW_LLM_THINK=false\n"
        "DOCFLOW_LLM_MIN_P=0.05\n"
        "DOCFLOW_LLM_TOP_P=0.95\n"
        "DOCFLOW_LLM_REPEAT_PENALTY=1.0\n"
        "DOCFLOW_LLM_PRESENCE_PENALTY=0.0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(config))

    code = tool_module("llm").main(
        [
            "--assets-dir",
            str(assets),
            "--out",
            str(tmp_path / "run"),
            "call",
            str(CASE_TEXT),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--task",
            "extract",
            "--template",
            "plain",
        ]
    )

    assert code == 0
    options = fake.calls[-1].options
    assert options["think"] is False
    assert options["min_p"] == 0.05
    assert options["top_p"] == 0.95
    assert options["repeat_penalty"] == 1.0
    assert options["presence_penalty"] == 0.0


def test_the_asset_root_defaults_to_the_configuration_file(
    providers: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``DOCFLOW_ASSETS_DIR`` is what makes the real registry usable without restating the flag —
    and a blank value states nothing, which is what keeps the built-in chain's fixture root."""
    providers()
    (tmp_path / "assets" / "template").mkdir(parents=True)
    (tmp_path / "assets" / "template" / "plain.md").write_text(
        "<doc>\n", encoding="utf-8"
    )
    config = tmp_path / "config.env"
    config.write_text(f"DOCFLOW_ASSETS_DIR={tmp_path / 'assets'}\n", encoding="utf-8")
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(config))

    def run(template: str, schema: str | None = None) -> str:
        """Run one call with no ``--assets-dir`` and return the header the run printed."""
        flags = [
            "--out",
            str(tmp_path / "run"),
            "call",
            str(CASE_TEXT),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--task",
            "extract",
            "--template",
            template,
        ]
        if schema is not None:
            flags += ["--schema", schema]
        capsys.readouterr()
        assert tool_module("llm").main(flags) == 0
        return capsys.readouterr().err

    assert f"assets_dir: {tmp_path / 'assets'}" in run("plain")

    config.write_text("DOCFLOW_ASSETS_DIR=\n", encoding="utf-8")
    assert f"assets_dir: {_llm.DEFAULT_ASSETS_DIR}" in run("simple_extract", "simple")


def test_the_configuration_file_cannot_supply_a_provider_or_a_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file may state an endpoint or a window; it may not become the default model refused since
    ``SCR-05`` — ``--provider`` and ``--model`` stay required flags."""
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "plain.md").write_text("<doc>\n", encoding="utf-8")
    config = tmp_path / "config.env"
    config.write_text(
        "DOCFLOW_LLM_PROVIDER=ollama\nDOCFLOW_LLM_MODEL=llama3.1\n", encoding="utf-8"
    )
    monkeypatch.setenv(_cli.ENV_FILE_VARIABLE, str(config))

    with pytest.raises(SystemExit) as exit_info:
        tool_module("llm").main(
            [
                "--assets-dir",
                str(assets),
                "call",
                str(CASE_TEXT),
                "--task",
                "extract",
                "--template",
                "plain",
            ]
        )

    assert exit_info.value.code == 2


def test_llm_call_reads_an_option_value_as_json_and_leaves_text_alone(
    providers: Any, tmp_path: Path
) -> None:
    """A decoding option is typed on the way out, because the provider types it on the way in.

    ``--option temperature=0`` used to arrive as the *string* ``"0"``, which Ollama refuses with
    HTTP 500 (*option "temperature" must be of type float32*) — the readme's own seed example did
    not run. A value that is not JSON stays the text it is, so nothing needs quoting to stay one.
    """
    fake = providers()
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "plain.md").write_text("<doc>\n", encoding="utf-8")

    code = tool_module("llm").main(
        [
            "--assets-dir",
            str(assets),
            "--out",
            str(tmp_path / "run"),
            "call",
            str(CASE_TEXT),
            "--provider",
            "ollama",
            "--model",
            "llama3.1",
            "--task",
            "extract",
            "--template",
            "plain",
            "--option",
            "temperature=0",
            "--option",
            "keep_alive=5m",
        ]
    )

    assert code == 0
    sent = fake.calls[-1].options
    assert sent["temperature"] == 0
    assert not isinstance(sent["temperature"], str)
    assert sent["keep_alive"] == "5m"


def test_llm_call_refuses_an_extra_value_file_that_is_not_there(
    providers: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A path that cannot be read is a usage error, not a placeholder rendered as nothing."""
    providers()
    assets = tmp_path / "assets"
    (assets / "template").mkdir(parents=True)
    (assets / "template" / "review.md").write_text(
        "<extra:proposal>\n<doc>\n", encoding="utf-8"
    )

    with pytest.raises(SystemExit) as exit_info:
        tool_module("llm").main(
            [
                "--assets-dir",
                str(assets),
                "call",
                str(CASE_TEXT),
                "--provider",
                "ollama",
                "--model",
                "qwen3.5:9b",
                "--task",
                "review",
                "--template",
                "review",
                "--extra",
                f"proposal=@{tmp_path / 'missing.json'}",
            ]
        )

    assert exit_info.value.code == 2
    assert "proposal" in capsys.readouterr().err


def test_batch_llm_mirrors_the_folder_it_walked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The LLM batch walks text inputs, mirrors them, and states the asset root it used."""
    corpus = build_text_corpus(tmp_path)
    out = tmp_path / "mirror"

    code = tool_module("batch_llm").main(
        ["--out", str(out), str(corpus), *OFFLINE_TOKENS]
    )

    assert code == 0
    assert sorted(
        record.parent.relative_to(out).as_posix() for record in out.rglob("tokens.json")
    ) == ["b", "sub/a"]
    assert "assets_dir:" in capsys.readouterr().err


def test_batch_llm_walks_page_images_too(providers: Any, tmp_path: Path) -> None:
    """A folder of pages runs the same command: each walked image is its own input's document.

    The walk takes the LLM layer's whole input set, so the vision flow over a corpus is one command
    exactly as the text flow is — and no ``--image`` is needed, because each input *is* the page it
    is run over.
    """
    fake = providers()
    corpus = build_page_corpus(tmp_path)
    out = tmp_path / "mirror"

    code = tool_module("batch_llm").main(
        [
            "--out",
            str(out),
            str(corpus),
            "call",
            "--provider",
            "ollama",
            "--model",
            "qwen2.5vl:7b",
            "--task",
            "vision",
            "--template",
            "simple_read_pixels",
            "--schema",
            "simple",
        ]
    )

    assert code == 0
    assert sorted(Path(image).name for call in fake.calls for image in call.images) == [
        "page.png",
        "receipt.jpg",
    ]
    assert sorted(
        record.parent.relative_to(out).as_posix() for record in out.rglob("simple.json")
    ) == ["page", "receipt"]


def test_batch_llm_requires_a_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bare run is a usage error: this tool has no flag-free command to fall back on."""
    with pytest.raises(SystemExit) as exit_info:
        tool_module("batch_llm").main([str(build_text_corpus(tmp_path))])

    assert exit_info.value.code == 2
    assert "SUBCOMMAND" in capsys.readouterr().err


def test_batch_llm_refuses_a_command_that_is_not_about_an_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``status`` is not registered here: asking about a run directory is not a corpus question."""
    with pytest.raises(SystemExit) as exit_info:
        tool_module("batch_llm").main([str(build_text_corpus(tmp_path)), "status"])

    assert exit_info.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_batch_llm_installs_the_scripted_provider_only_when_asked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``--fake`` replaces the provider seam; without it the flag's work is never done.

    The seam is patched **by name** rather than through this file's own import of the layer: a tool
    invoked by path imports its siblings as top-level modules (``import _llm``), while this file
    imports them as ``scripts.tools._llm``. Those are two module objects, and patching the wrong one
    would leave the tool's own copy of the function in place — so the test would pass whether or not
    the flag worked.
    """
    installed: list[int] = []
    monkeypatch.setattr("_llm.install_fake", lambda: installed.append(1))
    corpus = build_text_corpus(tmp_path)
    out = tmp_path / "mirror"

    code = tool_module("batch_llm").main(
        ["--out", str(out), str(corpus), *OFFLINE_TOKENS]
    )

    assert code == 0
    assert not installed

    code = tool_module("batch_llm").main(
        ["--fake", "--out", str(out), str(corpus), *OFFLINE_TOKENS]
    )

    assert code == 0
    assert installed == [1]


def test_batch_llm_keeps_going_when_the_provider_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refused call fails its own record; the rest of the corpus still runs."""
    refused = llm_primitives.typed_failure("PROVIDER_ERROR", "no model is served")

    def refuse(text: str) -> int:
        raise refused

    monkeypatch.setattr("docflow.llm.primitives.count_tokens", refuse)
    corpus = build_text_corpus(tmp_path)
    out = tmp_path / "mirror"

    code = tool_module("batch_llm").main(
        ["--out", str(out), str(corpus), *OFFLINE_TOKENS]
    )

    assert code == 1
    printed = capsys.readouterr().out
    assert "ERROR PROVIDER_ERROR" in printed
    assert "failed: 2" in printed
    assert not list(out.rglob("tokens.json"))


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
    (("inspect", ()), ("blocks", ("--page", "1"))),
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


# --- The LLM credential names ---------------------------------------------------------------


def test_a_named_provider_reads_its_own_credential_from_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One ``.env`` may hold every hosted provider's key: a provider-scoped name is read for it."""
    # pylint: disable=protected-access
    # Reason: the credential lookup is the layer's own option assembler; driving it directly is
    # what this case is about, and a public wrapper would be a second name for one behaviour.
    env_file = tmp_path / ".env"
    env_file.write_text("DEEPSEEK_API_KEY=provider-scoped\n", encoding="utf-8")
    monkeypatch.delenv("DOCFLOW_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DOCFLOW_ENV_FILE", str(env_file))

    parser = tool_module("llm").build_parser()

    def options_for(provider: str) -> dict[str, Any]:
        args = parser.parse_args(
            ["prompt", "a.txt", "--provider", provider, "--model", "m"]
        )
        return _llm._options(args, parser)

    assert options_for("deepseek")["api_key"] == "provider-scoped"
    assert "api_key" not in options_for("ollama")


def test_the_neutral_credential_name_outranks_a_provider_scoped_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``DOCFLOW_LLM_API_KEY`` is the bench's own name: when it states something, it wins."""
    # pylint: disable=protected-access
    # Reason: same as the case above — the layer's option assembler is the unit under test.
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DOCFLOW_LLM_API_KEY=neutral\nDEEPSEEK_API_KEY=provider-scoped\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("DOCFLOW_LLM_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("DOCFLOW_ENV_FILE", str(env_file))

    parser = tool_module("llm").build_parser()
    args = parser.parse_args(
        ["prompt", "a.txt", "--provider", "deepseek", "--model", "m"]
    )

    assert _llm._options(args, parser)["api_key"] == "neutral"
