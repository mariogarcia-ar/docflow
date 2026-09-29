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
from scripts.tools import _cli
from tests.fakes.engines.fake_docling import FakeConversionStatus, FakeDocling
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
    "ocr": ("run", "text", "md", "json", "tables", "blocks", "metrics"),
    "batch_ocr": ("run", "text", "md", "json", "tables", "blocks", "metrics"),
    "llm": ("call", "node", "graph", "resume", "status", "models", "tokens", "fake"),
    "batch_llm": ("call", "graph", "node", "tokens"),
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
    "ocr": ("text", "md", "json", "tables", "blocks", "metrics"),
    "batch_ocr": (),
    "llm": ("node", "status", "models", "tokens"),
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
    assert _binaries_called(double).count("pdftotext") == 3


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
    """``--page`` returns one page's own keys, gaining the scope it states and its file."""
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


def test_pdf_text_publishes_one_file_per_page(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``text`` publishes each page's text, the way ``render`` publishes each page's PNG."""
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
    names = ("page_001.txt", "page_002.txt")
    assert [entry["page"] for entry in entries] == [1, 2]
    for entry, name in zip(entries, names, strict=True):
        written = out / name
        assert written.is_file()
        assert written.read_text(encoding="utf-8") == entry["text"]
        assert Path(entry["output"]).name == name


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


def install_ocr_engine(monkeypatch: pytest.MonkeyPatch) -> FakeDocling:
    """Install the Docling double at the seam the OCR layer calls and return it."""
    double = FakeDocling()
    monkeypatch.setattr("docflow.ocr.primitives.convert_image_with_docling", double)
    return double


def test_ocr_reads_through_the_shared_layer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``ocr.py`` builds its payload in the layer ``batch_ocr.py`` drives."""
    install_ocr_engine(monkeypatch)

    code = tool_module("ocr").main(["text", str(SAMPLE_OCR)])

    assert code == 0
    assert "Quarterly report" in capsys.readouterr().out


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
