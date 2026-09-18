"""Tests for the fixture manifest generator (``tests/fixtures/build_manifest.py``).

Two jobs, kept separate:

- The **generator** is tested on synthetic trees in ``tmp_path``, so its rules
  are provable without touching the committed fixtures or rewriting the real
  manifest.
- The **committed manifest** is checked against the folder on disk. That check
  is the point of the whole thing: a manifest nobody re-verifies is a stale list
  that reads like an inventory.

The manifest records **no expected content** — no field values, no page counts,
no verdicts. ``docs/plans/README.md`` §6 defers the golden set proper over
deviation D4 (a set labelled by the model that produced it is circular), so this
is verified material and nothing more.

The assertions that carry the design, each of which must fail when the rule it
guards is broken:

- ``test_debris_does_not_enter_the_manifest`` — a cache directory appearing
  between two builds must not change the file. Recording debris would make the
  manifest differ between two runs and between a macOS and a Linux checkout,
  which turns regenerate-and-diff from a check into noise.
- ``test_a_cached_source_file_is_attributed_to_the_cache`` — the cache and
  suffix rules overlap, so the order between them decides which reason a file
  gets. The reverse order labels a cached ``.py`` as ``python_source``, a claim
  about what the file is, made about a file in a cache directory.
- ``test_the_manifest_output_is_skipped_without_a_record`` — the manifest is a
  file in the folder it inventories. Without the skip it lists its own previous
  contents, and every regeneration changes the file for a reason that has
  nothing to do with the fixtures.
- ``test_the_inventory_is_not_empty`` — the control for the whole suite. A
  filter bug that excluded everything would satisfy every other assertion here.

Three Pylint relaxations are declared, each because the rule contradicts what
this suite is for: temporary trees are arguably similar to each other
(``duplicate-code``), every record field and every committed entry costs an
assertion (``too-many-lines``), a pytest fixture is injected by name so a test
parameter necessarily shadows the fixture function — that shadowing *is* the
wiring (``redefined-outer-name``) — and ``(entry,) = ...`` against a list Pylint
cannot prove non-empty *is* the assertion, not a slip (each unpacking site says
so).
"""

# pylint: disable=duplicate-code
# pylint: disable=redefined-outer-name
# pylint: disable=too-many-lines
# pylint: disable=unbalanced-tuple-unpacking

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
from collections import Counter

import pytest

from .build_manifest import (
    _DETECTOR,
    EXCLUDED_DIRECTORIES,
    EXCLUDED_SUFFIXES,
    PDF_TYPES,
    FixtureRecord,
    # Private on purpose: the precedence between the two exclusion rules is the
    # property under test, and it has no public surface to exercise instead.
    _exclusion_reason,
    _pdf_type,
    _record,
    _type_tally,
    build,
    main,
)

_HERE = pathlib.Path(__file__).resolve().parent
_MANIFEST_PATH = _HERE / "manifest.json"
_REPO_ROOT = _HERE.parents[1]

#: What the manifest may say about a path it deliberately leaves out. ``hidden``
#: and ``cache`` name debris and are therefore never recorded.
_DECLARED_REASONS = frozenset(EXCLUDED_SUFFIXES.values())


@pytest.fixture(name="manifest")
def manifest_fixture() -> dict:
    """Return the committed manifest, skipping when it has not been generated."""
    if not _MANIFEST_PATH.is_file():
        pytest.skip("manifest.json is absent; run the generator first")
    return json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))


def _tree(root: pathlib.Path, **files: str) -> pathlib.Path:
    """Create a small file tree.

    Args:
        root: Directory to create the files under.
        **files: Relative path mapped to its text content. A ``__`` in the key
            becomes a path separator, so ``sub__a.jpg`` writes ``sub/a.jpg``.

    Returns:
        ``root``, for chaining.
    """
    for name, content in files.items():
        target = root / name.replace("__", "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def _paths(manifest: dict) -> set[str]:
    """Return the inventoried paths of ``manifest`` as a set."""
    return {entry["path"] for entry in manifest["entries"]}


def _reasons(manifest: dict) -> dict[str, str]:
    """Return the recorded exclusions of ``manifest`` mapped to their reason."""
    return {item["path"]: item["reason"] for item in manifest["excluded"]}


def _accounted_paths() -> set[str]:
    """Return every path on disk the generator is expected to account for.

    Mirrors the generator's two skip rules: debris is left out (it is skipped
    without a record, so demanding it here would assert the opposite of the
    rule), and so is the manifest's own output.

    Returns:
        Relative posix paths of the files that must appear in ``entries`` or in
        ``excluded``.
    """
    accounted: set[str] = set()
    for path in _HERE.rglob("*"):
        if not path.is_file() or path.resolve() == _MANIFEST_PATH:
            continue
        reason = _exclusion_reason(path, _HERE)
        if reason is None or reason in _DECLARED_REASONS:
            accounted.add(path.relative_to(_HERE).as_posix())
    return accounted


# --- The generator, over synthetic trees -------------------------------------


def test_every_source_file_on_disk_is_inventoried(tmp_path: pathlib.Path) -> None:
    """Nothing outside the exclusion rules is dropped or invented."""
    root = _tree(
        tmp_path / "fx", **{"a.pdf": "a", "sub__b.jpg": "bb", "sub__c.txt": "c"}
    )
    result = build(root, tmp_path / "out.json")
    assert _paths(result) == {"a.pdf", "sub/b.jpg", "sub/c.txt"}
    # Compared to ``[]`` on purpose: ``assert not result["excluded"]`` would also
    # pass if the key were missing and read as ``None``, which is a different bug.
    assert result["excluded"] == []  # pylint: disable=use-implicit-booleaness-not-comparison


def test_the_record_shape_is_fixed(tmp_path: pathlib.Path) -> None:
    """Six fields per record, and each one describes the file it came from."""
    root = _tree(tmp_path / "fx", **{"sub__b.JPG": "bb"})
    (entry,) = build(root, tmp_path / "out.json")["entries"]
    assert entry == {
        "path": "sub/b.JPG",
        "folder": "sub",
        "name": "b",
        "extension": "jpg",
        "bytes": 2,
        "sha256": hashlib.sha256(b"bb").hexdigest(),
    }


def test_no_recorded_field_is_an_empty_stand_in(tmp_path: pathlib.Path) -> None:
    """Every string field is populated; ``""`` would read as data."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a"})
    (entry,) = build(root, tmp_path / "out.json")["entries"]
    for field in ("path", "folder", "name", "extension", "sha256"):
        assert entry[field] != "", field


def test_case_in_the_extension_does_not_split_a_class(tmp_path: pathlib.Path) -> None:
    """``.JPG`` and ``.jpg`` are the same class of file."""
    root = _tree(tmp_path / "fx", **{"a.JPG": "a", "b.jpg": "bb"})
    result = build(root, tmp_path / "o")
    assert {entry["extension"] for entry in result["entries"]} == {"jpg"}


def test_the_digest_matches_an_independently_written_hash(
    tmp_path: pathlib.Path,
) -> None:
    """The chunked digest equals a one-shot digest over the whole file.

    Compared against a second, differently shaped computation rather than
    against a stored constant: a constant only proves the constant is unchanged,
    and would hide a change to how the digest is fed.
    """
    payload = b"una" * 400_000  # Larger than the chunk size.
    root = _tree(tmp_path / "fx", **{"a.bin": ""})
    (root / "a.bin").write_bytes(payload)
    (entry,) = build(root, tmp_path / "out.json")["entries"]
    assert entry["sha256"] == hashlib.sha256(payload).hexdigest()


def test_one_changed_byte_changes_the_digest(tmp_path: pathlib.Path) -> None:
    """The digest is sensitive to content, not only to length."""
    root = _tree(tmp_path / "fx", **{"a.bin": ""})
    (root / "a.bin").write_bytes(b"AAAA")
    before = build(root, tmp_path / "out.json")["entries"][0]["sha256"]
    (root / "a.bin").write_bytes(b"AAAB")
    after = build(root, tmp_path / "out.json")["entries"][0]["sha256"]
    assert before != after


def test_identical_content_in_two_files_hashes_the_same(
    tmp_path: pathlib.Path,
) -> None:
    """The digest is of the bytes, so two copies are detectable as one."""
    root = _tree(tmp_path / "fx", **{"a.jpg": "same", "sub__b.png": "same"})
    digests = {
        entry["path"]: entry["sha256"]
        for entry in build(root, tmp_path / "o")["entries"]
    }
    assert digests["a.jpg"] == digests["sub/b.png"]


def test_counts_and_totals_are_derived_from_the_entries(
    tmp_path: pathlib.Path,
) -> None:
    """No count or total is a literal that can drift from the records."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a", "sub__b.jpg": "bbb"})
    result = build(root, tmp_path / "out.json")
    assert result["files"] == len(result["entries"]) == 2
    assert result["bytes"] == sum(entry["bytes"] for entry in result["entries"]) == 4


def test_the_folder_buckets_account_for_every_byte(tmp_path: pathlib.Path) -> None:
    """Per-folder totals sum to the whole, so no file is counted twice."""
    root = _tree(
        tmp_path / "fx", **{"a.pdf": "a", "sub__b.jpg": "bbb", "sub__c.jpg": "cc"}
    )
    result = build(root, tmp_path / "out.json")
    assert result["by_folder"] == {
        ".": {"files": 1, "bytes": 1},
        "sub": {"files": 2, "bytes": 5},
    }
    assert sum(b["bytes"] for b in result["by_folder"].values()) == result["bytes"]
    assert sum(b["files"] for b in result["by_folder"].values()) == result["files"]


def test_the_entries_are_in_path_order(tmp_path: pathlib.Path) -> None:
    """Order is fixed by the generator, so a diff means the folder changed."""
    root = _tree(tmp_path / "fx", **{"z.pdf": "z", "a.pdf": "a", "sub__m.jpg": "m"})
    paths = [entry["path"] for entry in build(root, tmp_path / "o")["entries"]]
    assert paths == sorted(paths)


def test_a_file_added_after_a_build_appears_in_the_next_one(
    tmp_path: pathlib.Path,
) -> None:
    """A later build re-reads the disk; the inventory is not a cached scan."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a"})
    first = build(root, tmp_path / "out.json")
    (root / "b.pdf").write_text("bb", encoding="utf-8")
    second = build(root, tmp_path / "out.json")
    assert _paths(first) == {"a.pdf"}
    assert _paths(second) == {"a.pdf", "b.pdf"}


def test_a_deleted_file_disappears_from_the_next_build(tmp_path: pathlib.Path) -> None:
    """The inventory shrinks with the folder, not only grows with it."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a", "b.pdf": "bb"})
    first = build(root, tmp_path / "out.json")
    (root / "b.pdf").unlink()
    second = build(root, tmp_path / "out.json")
    assert _paths(first) == {"a.pdf", "b.pdf"}
    assert _paths(second) == {"a.pdf"}


def test_the_recorded_root_is_repository_relative(tmp_path: pathlib.Path) -> None:
    """``root`` is a repository-relative posix path, not a machine's location.

    An absolute path would record where this checkout happens to live, so the
    same fixtures would produce a different manifest on every machine — and the
    diff, which is the check, would stop meaning anything.
    """
    result = build(_tree(tmp_path / "fx", **{"a.pdf": "a"}), tmp_path / "o")
    assert not pathlib.PurePosixPath(result["root"]).is_absolute()
    assert "\\" not in result["root"]


def test_the_committed_root_is_the_fixture_folder(manifest: dict) -> None:
    """The documented value, pinned: the reader is told where this file lives."""
    assert manifest["root"] == "tests/fixtures"


def test_two_builds_of_the_same_tree_are_identical(tmp_path: pathlib.Path) -> None:
    """Determinism: nothing time-, order- or path-dependent is recorded.

    This is what makes regenerate-and-diff a usable check. A timestamp or an
    mtime would make every diff non-empty for a reason that is not a fixture
    change.
    """
    root = _tree(tmp_path / "fx", **{"a.pdf": "a", "sub__b.jpg": "bb"})
    assert build(root, tmp_path / "o1.json") == build(root, tmp_path / "o2.json")


# --- The exclusion rules -----------------------------------------------------


def test_the_manifest_output_is_skipped_without_a_record(
    tmp_path: pathlib.Path,
) -> None:
    """The output is absent from both lists, including when it already exists."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a"})
    output = root / "manifest.json"
    output.write_text("previous contents", encoding="utf-8")
    result = build(root, output)
    assert _paths(result) == {"a.pdf"}
    assert _reasons(result) == {}


def test_the_manifest_output_is_matched_through_a_path_alias(
    tmp_path: pathlib.Path,
) -> None:
    """The skip holds when the output path is spelled with a ``..`` segment.

    ``Path.resolve`` normalisation is the only reason this works; comparing the
    literal paths would let an alias through and the manifest would inventory
    itself.
    """
    root = _tree(tmp_path / "fx", **{"a.pdf": "a"})
    output = root / "manifest.json"
    output.write_text("previous contents", encoding="utf-8")
    aliased = tmp_path / "fx" / ".." / "fx" / "manifest.json"
    assert _paths(build(root, aliased)) == {"a.pdf"}


def test_a_generator_is_excluded_as_python_source(tmp_path: pathlib.Path) -> None:
    """The script that writes the manifest is not itself a fixture."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a", "build_manifest.py": "x = 1"})
    result = build(root, tmp_path / "out.json")
    assert _paths(result) == {"a.pdf"}
    assert _reasons(result) == {"build_manifest.py": "python_source"}


def test_exclusion_is_by_suffix_not_by_name(tmp_path: pathlib.Path) -> None:
    """A new generator does not have to be remembered in a list of names."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a", "some_future_gen.py": "x"})
    result = build(root, tmp_path / "out.json")
    assert _reasons(result) == {"some_future_gen.py": "python_source"}


def test_a_cached_source_file_is_attributed_to_the_cache() -> None:
    """A source file inside a cache directory is reported as cache, not source.

    Both rules match this file, so the assertion names *which* one answered.
    """
    reason = _exclusion_reason(pathlib.Path("sub/__pycache__/x.py"), pathlib.Path("."))
    assert reason == "cache"


def test_cache_and_hidden_directory_exclusions_are_skipped_not_recorded(
    tmp_path: pathlib.Path,
) -> None:
    """Debris has no reason recorded, because it is not a claim about fixtures."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a"})
    cache = root / "sub" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "m.cpython-313.py").write_text("bytecode", encoding="utf-8")
    (cache / "m.cpython-313.pyc").write_bytes(b"\x00")
    result = build(root, tmp_path / "out.json")
    assert _paths(result) == {"a.pdf"}
    assert _reasons(result) == {}


def test_debris_does_not_enter_the_manifest(tmp_path: pathlib.Path) -> None:
    """A cache entry appearing between two builds must not change the file.

    This is the load-bearing consequence of skipping debris: the manifest has to
    be stable across environments, and ``__pycache__`` exists on one machine and
    not the next.
    """
    root = _tree(tmp_path / "fx", **{"a.pdf": "a"})
    before = build(root, tmp_path / "out.json")
    cache = root / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"\x00")
    (root / ".DS_Store").write_text("junk", encoding="utf-8")
    assert build(root, tmp_path / "out.json") == before


def test_a_hidden_file_is_skipped(tmp_path: pathlib.Path) -> None:
    """Editor and OS debris is skipped, and is not recorded as a fixture rule."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a", ".DS_Store": "junk"})
    result = build(root, tmp_path / "out.json")
    assert _paths(result) == {"a.pdf"}
    assert _reasons(result) == {}


def test_a_hidden_directory_is_skipped_whole(tmp_path: pathlib.Path) -> None:
    """A dot-directory takes its contents with it, not only its own name."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a", ".cache__x.pdf": "junk"})
    assert _paths(build(root, tmp_path / "out.json")) == {"a.pdf"}


def test_a_hidden_entry_is_recognised_below_the_root() -> None:
    """The hidden rule reads every path part, not only the file's own name."""
    found = _exclusion_reason(pathlib.Path("sub/.keep/x.pdf"), pathlib.Path("."))
    assert found == "hidden"


def test_the_recorded_reasons_are_a_closed_set() -> None:
    """A recorded reason is drawn from the declared values, never invented.

    The two declarations are stated rather than derived, so a value quietly added to one
    of the mappings fails here instead of becoming a third kind of exclusion nobody
    agreed to.

    ``silent_failure_fixtures`` is `E07-03`'s, and it is a **different kind** of
    exclusion from ``cache``: a cache is skipped without a record because it is debris,
    while ``matrix/`` is skipped because its contents are a different *set* of
    documents - the silent-failure harness's inputs, not corpus fixtures. Both are
    directory-level, which is why they share the mapping.
    """
    assert {"python_source"} == _DECLARED_REASONS
    assert set(EXCLUDED_DIRECTORIES.values()) == {
        "cache",
        "silent_failure_fixtures",
    }


# --- The command line --------------------------------------------------------


def test_main_writes_the_manifest_and_reports_a_summary(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The entry point writes valid JSON and prints one line."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a"})
    output = tmp_path / "out" / "manifest.json"
    output.parent.mkdir()
    assert main(["--root", str(root), "--out", str(output)]) == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["files"] == 1
    assert "1 files" in capsys.readouterr().out


def test_main_called_twice_writes_the_same_bytes(
    tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regenerating an unchanged folder produces no diff."""
    root = _tree(tmp_path / "fx", **{"a.pdf": "a"})
    output = tmp_path / "manifest.json"
    main(["--root", str(root), "--out", str(output)])
    first = output.read_bytes()
    main(["--root", str(root), "--out", str(output)])
    capsys.readouterr()
    assert output.read_bytes() == first


def test_the_script_runs_under_a_plain_interpreter(tmp_path: pathlib.Path) -> None:
    """The documented invocation works: no install, no pytest, no import path.

    The docstring tells a reader to run this from the repository root as a
    script. That only holds while the module imports nothing from ``docflow``,
    which is the property asserted here.
    """
    output = tmp_path / "manifest.json"
    completed = subprocess.run(
        [sys.executable, str(_HERE / "build_manifest.py"), "--out", str(output)],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["files"] > 0


# --- The committed manifest against the folder on disk -----------------------


def test_the_inventory_is_not_empty(manifest: dict) -> None:
    """The control for this suite: an empty inventory is self-consistent.

    A filter bug that excluded everything would satisfy every other assertion in
    this section, so the size is asserted before any property of the contents.
    """
    assert manifest["files"] > 0
    assert manifest["entries"]


def test_the_committed_manifest_lists_exactly_the_files_on_disk(
    manifest: dict,
) -> None:
    """The gate: the two lists account for the folder, and nothing is left over.

    Debris is subtracted before comparing, mirroring the generator (see
    ``_accounted_paths``); anything else unexplained fails here. This is what
    makes the exclusion list load-bearing rather than a place to hide a file.
    """
    assert _paths(manifest) | set(_reasons(manifest)) == _accounted_paths()


def test_the_committed_manifest_is_regenerable_without_a_diff(manifest: dict) -> None:
    """The whole file — entries, counts, buckets and exclusions — is current."""
    assert build(_HERE, _MANIFEST_PATH) == manifest


def test_every_committed_digest_matches_the_file(manifest: dict) -> None:
    """The recorded digest is of the file that is actually there.

    Recomputed here with a different call shape than the generator's, so a
    manifest written from a different content tree is caught rather than
    confirmed.
    """
    for entry in manifest["entries"]:
        path = _HERE / entry["path"]
        assert path.is_file(), entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry[
            "path"
        ]


def test_every_committed_size_matches_the_file(manifest: dict) -> None:
    """Size is recorded from the filesystem, and still agrees with it."""
    for entry in manifest["entries"]:
        assert (_HERE / entry["path"]).stat().st_size == entry["bytes"], entry["path"]


def test_the_committed_totals_sum_to_the_committed_whole(manifest: dict) -> None:
    """The headline counts are the records, not literals beside them."""
    assert manifest["files"] == len(manifest["entries"])
    assert manifest["bytes"] == sum(entry["bytes"] for entry in manifest["entries"])


def test_no_committed_path_is_recorded_twice(manifest: dict) -> None:
    """A duplicate would double a folder's bytes without changing the count."""
    paths = [entry["path"] for entry in manifest["entries"]]
    assert len(paths) == len(set(paths))


def test_no_committed_removal_is_recorded_twice(manifest: dict) -> None:
    """The same, for the exclusion list."""
    paths = [item["path"] for item in manifest["excluded"]]
    assert len(paths) == len(set(paths))


def test_no_committed_entry_is_also_declared_excluded(manifest: dict) -> None:
    """The two lists are disjoint: a path is either a fixture or explained."""
    assert not _paths(manifest) & set(_reasons(manifest))


def test_the_committed_exclusions_are_exactly_the_python_sources(
    manifest: dict,
) -> None:
    """Every non-fixture in the folder is declared as one, and only those.

    They are present on disk, so they must appear as exclusions rather than
    being silently absent — that is what makes the two lists add up to the
    folder. A ``.pyc`` cache entry is deliberately *not* here; it is skipped.

    The set is written out by hand rather than globbed, so a *fourth* source
    arriving fails here until it is declared. ``verify_k2.py`` is such an
    arrival: it verifies the PDF kernel against this folder, it is a tool rather
    than a fixture, and it is excluded for the same reason as the other three.
    """
    assert _reasons(manifest) == {
        "__init__.py": "python_source",
        "build_manifest.py": "python_source",
        "test_manifest.py": "python_source",
        "verify_k2.py": "python_source",
    }


def test_the_committed_manifest_records_no_expected_content(manifest: dict) -> None:
    """This is an inventory, not a golden set.

    ``docs/plans/README.md`` §6 defers the labelled golden set over deviation D4.
    A fixture folder named ``expected-extraction`` invites the reading that the
    values are expected somewhere, so the *shape* is asserted: the top level and
    every record carry exactly the declared fields. A measurement added later —
    pages, DPI, an expected value — fails here rather than reading as inventory
    data nobody agreed to. Scanning the serialized file for words would not do:
    the folder names are legitimate content and colliding with them is not a
    finding.

    ``pdf_type`` is allowed and is not a violation of this: it is a *detected*
    type with its detector named beside it, not an expected extraction value. The
    distinction is the field's presence in the allowed set, deliberately written
    down rather than left to judgement.
    """
    assert set(manifest) == {
        "root",
        "files",
        "bytes",
        "pdf_detector",
        "by_folder",
        "excluded",
        "entries",
    }
    base_fields = {"path", "folder", "name", "extension", "bytes", "sha256"}
    assert manifest["entries"]
    for entry in manifest["entries"]:
        expected = base_fields | (
            {"pdf_type"} if entry["extension"] == "pdf" else set()
        )
        assert set(entry) == expected, entry["path"]
    for item in manifest["excluded"]:
        assert set(item) == {"path", "reason"}, item["path"]
    for bucket in manifest["by_folder"].values():
        assert set(bucket) == {"files", "bytes"}


# --- The detected PDF types --------------------------------------------------


def _pdf_entries(manifest: dict) -> list[dict]:
    """Return the committed PDF records."""
    return [entry for entry in manifest["entries"] if entry["extension"] == "pdf"]


def test_the_committed_manifest_detected_at_least_one_pdf(manifest: dict) -> None:
    """Control for this section: a section of no PDFs would assert nothing.

    The folder labels below are only meaningful if there are files under them, so
    the population is stated before any property of it.
    """
    assert _pdf_entries(manifest)


def test_every_committed_pdf_carries_a_detected_type(manifest: dict) -> None:
    """Every PDF has a ``pdf_type``; the detection was not partial.

    A record missing the key would be indistinguishable from a non-PDF record,
    and a PDF that silently went undetected is the failure this makes visible.
    """
    for entry in _pdf_entries(manifest):
        assert entry.get("pdf_type"), entry["path"]


def test_no_committed_non_pdf_carries_a_pdf_type(manifest: dict) -> None:
    """The key is PDF-only: a JPEG is not text or a scan, it is an image.

    Applying the PDF vocabulary to an image would make the same two words mean
    two different things depending on which record reads them.
    """
    for entry in manifest["entries"]:
        if entry["extension"] != "pdf":
            assert "pdf_type" not in entry, entry["path"]


def test_every_detected_type_is_in_the_detectors_vocabulary(manifest: dict) -> None:
    """The values are ``voucherflow``'s own, not a new vocabulary invented here.

    Asserted against the detector's declared set rather than against a literal
    pair, so a value the detector could never return is caught as a value this
    file made up.
    """
    from voucherflow.processing.type_detector import (  # pylint: disable=import-outside-toplevel
        TIPOS_VALIDOS,
    )

    for entry in _pdf_entries(manifest):
        assert entry["pdf_type"] in TIPOS_VALIDOS, entry["path"]
        assert entry["pdf_type"] in PDF_TYPES, entry["path"]


def test_the_committed_detector_is_recorded(manifest: dict) -> None:
    """The file names the detector that produced the types.

    Without it, ``pdf_texto`` is an unattributed assertion; with it, a change of
    detector is visible in the diff rather than hidden behind unchanged values.
    """
    assert manifest["pdf_detector"] == _DETECTOR


def test_the_detected_types_agree_with_the_curated_folders(manifest: dict) -> None:
    """The gate: the detector reproduces the human's folder labels.

    ``pdf_aptos_layout`` and ``pdf_escaneados`` are the one axis a person
    labelled by hand, so they are the only ground truth available. This is what
    the recorded type is worth checking against — without it, the field could be
    populated with any consistent answer.
    """
    labels = {"pdf_aptos_layout": "pdf_texto", "pdf_escaneados": "pdf_escaneado"}
    checked = 0
    for entry in _pdf_entries(manifest):
        expected = labels.get(entry["folder"])
        if expected is not None:
            assert entry["pdf_type"] == expected, entry["path"]
            checked += 1
    assert checked == len(labels) * 5


def test_the_type_split_is_stated_in_full(manifest: dict) -> None:
    """Both answers are present, so neither branch is untested by the fixtures.

    A corpus of only text PDFs would leave the scanned branch never exercised
    against real data, and the count would not say so.
    """
    tally: Counter[str] = Counter(entry["pdf_type"] for entry in _pdf_entries(manifest))
    assert set(tally) == set(PDF_TYPES), tally
    assert sum(tally.values()) == len(_pdf_entries(manifest))


def test_detection_is_skipped_without_the_detector(tmp_path: pathlib.Path) -> None:
    """Without the detector the key is absent, not guessed.

    This is the difference between an absence and a stand-in: ``detect=False``
    records no ``pdf_type`` at all, so a reader can tell "not detected" from
    "detected as text".
    """
    root = _tree(tmp_path / "fx", **{"a.pdf": "not a real pdf"})
    result = build(root, tmp_path / "out.json", detect=False)
    assert result["pdf_detector"] == "absent"
    assert "pdf_type" not in result["entries"][0]


def test_the_detector_answers_with_the_declared_pair() -> None:
    """``PDF_TYPES`` is the two answers a PDF can get, and no others."""
    assert set(PDF_TYPES) == {"pdf_texto", "pdf_escaneado"}


def test_a_detector_answer_outside_the_pair_is_refused() -> None:
    """A PDF detected as something else is a broken assumption, not a new type.

    The stub returns ``imagen`` — a real answer from the detector's vocabulary,
    just not one a PDF can get. Recording it would put a value in the manifest
    that the field does not mean.
    """

    class _Answer:  # pylint: disable=too-few-public-methods
        """A stub detector answer: the field ``_pdf_type`` reads."""

        tipo = "imagen"

    with pytest.raises(ValueError, match="answered 'imagen' for a PDF"):
        _pdf_type(pathlib.Path("a.pdf"), lambda _: _Answer())


def test_the_detectors_answer_is_what_reaches_the_record(
    tmp_path: pathlib.Path,
) -> None:
    """The recorded value is the detector's answer, not a constant beside it.

    Driven through ``_record`` with a stub, so the case is provable without a
    real PDF on disk. A hardcoded ``pdf_texto`` passes every assertion about the
    committed file while making the detection decorative; this is the assertion
    that fails instead.
    """
    scanned = tmp_path / "fx" / "a.pdf"
    scanned.parent.mkdir(parents=True)
    scanned.write_bytes(b"%PDF-1.4 stub")

    class _Answer:  # pylint: disable=too-few-public-methods
        """A stub detector answer carrying the type it was built with."""

        def __init__(self, tipo: str) -> None:
            self.tipo = tipo

    for answer in PDF_TYPES:
        record = _record(scanned, scanned.parent, lambda _, a=answer: _Answer(a))
        assert record["pdf_type"] == answer


def test_a_non_pdf_never_reaches_the_detector(tmp_path: pathlib.Path) -> None:
    """The detector is not called for a JPEG: the vocabulary is PDF-specific."""
    image = tmp_path / "fx" / "a.jpg"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"\xff\xd8\xff")
    called: list[pathlib.Path] = []

    def _spy(path: pathlib.Path) -> object:
        called.append(path)
        raise AssertionError("the detector must not be asked about an image")

    record = _record(image, image.parent, _spy)
    assert "pdf_type" not in record
    # Compared to ``[]`` on purpose: ``assert not called`` would also pass if the
    # spy replaced the list with ``None``, which is a different bug.
    assert called == []  # pylint: disable=use-implicit-booleaness-not-comparison


def test_the_tally_counts_each_type_from_the_records() -> None:
    """The run's summary line is read back from the records, not assembled apart.

    A tally that names a type the entries do not hold would make the console
    report disagree with the file it just wrote.
    """
    entries = [
        FixtureRecord(path="a.pdf", pdf_type="pdf_texto"),
        FixtureRecord(path="b.pdf", pdf_type="pdf_texto"),
        FixtureRecord(path="c.pdf", pdf_type="pdf_escaneado"),
        FixtureRecord(path="d.jpg"),
    ]
    assert _type_tally(entries) == "pdf_escaneado=1 pdf_texto=2"


def test_the_tally_says_undetected_when_nothing_was_detected() -> None:
    """An empty tally says so, rather than reading as zero of every type."""
    entries = [FixtureRecord(path="a.pdf"), FixtureRecord(path="b.jpg")]
    assert _type_tally(entries) == "undetected"


def test_the_tally_names_every_type_it_counts() -> None:
    """Both vocabulary values can appear, so neither branch is dead code."""
    entries = [
        FixtureRecord(path="a.pdf", pdf_type="pdf_texto"),
        FixtureRecord(path="b.pdf", pdf_type="pdf_escaneado"),
    ]
    tally = _type_tally(entries)
    for answer in PDF_TYPES:
        assert answer in tally
