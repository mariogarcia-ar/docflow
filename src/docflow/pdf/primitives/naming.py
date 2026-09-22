"""Naming helpers shared by the PDF primitives.

Not a capability of its own: the artifact naming rules are stated once here so the split
and render primitives cannot disagree about what a page file is called.
"""

from __future__ import annotations

import re
from pathlib import Path

PAGE_PADDING = 3
"""Digits in a page index — ``page_001``, ``page_002``, … .

Three digits matches the layout fixed by ``subplan-procesador-pdf.md`` §3 and keeps the
names sortable as strings, which is what makes the artifact tree deterministic without a
sort step.
"""

_SPLIT_PATTERN = re.compile(r"^page_(\d+)\.pdf$")


def page_index_name(index: int) -> str:
    """Return the zero-padded page name for a 1-based index.

    Args:
        index: Page position, 1-based.

    Returns:
        The name, e.g. ``"page_001"``.
    """
    return f"page_{index:0{PAGE_PADDING}d}"


def image_index_name(index: int) -> str:
    """Return the zero-padded image name for a 1-based index.

    Args:
        index: Image position within the page, 1-based.

    Returns:
        The name, e.g. ``"image_001"``.
    """
    return f"image_{index:0{PAGE_PADDING}d}"


def engine_page_template(directory: Path) -> str:
    """Return the ``pdfseparate`` output template for a page directory.

    The template is what the engine is given, and the engine's own page numbering is used
    only to *find* what it wrote: the published name is decided by
    :func:`renumber_split_output`. Handing the engine a single-file path is not enough in
    general, because a range writes several files.

    Args:
        directory: Directory the split output goes into.

    Returns:
        The template path, using the C-style ``%0Nd`` directive the engine expects.
    """
    return str(directory / f"page_%0{PAGE_PADDING}d.pdf")


def split_output_paths(directory: Path) -> list[Path]:
    """Return the files a split wrote, in engine page order.

    Args:
        directory: Directory the split wrote into.

    Returns:
        The matching paths, ordered by the engine's page number.
    """
    matches: list[tuple[int, Path]] = []
    for path in directory.glob("page_*.pdf"):
        found = _SPLIT_PATTERN.match(path.name)
        if found is not None:
            matches.append((int(found.group(1)), path))
    return [path for _, path in sorted(matches)]


def renumber_split_output(
    directory: Path,
    first_page: int,
    expected_count: int,
) -> list[Path]:
    """Rename a split's raw engine output to ``page_001 … page_N``.

    ``pdfseparate`` numbers its output by the PDF's page number, so ``-f 2 -l 3`` of a
    three-page document writes ``…2.pdf`` and ``…3.pdf``. This maps those onto the range's
    own indexes, so a range split publishes ``page_001``, ``page_002`` — the page's
    position *in the output* — which is what makes a partial split comparable with a full
    one.

    Args:
        directory: Directory the split wrote into.
        first_page: First page of the requested range, 1-based.
        expected_count: How many files the range should have produced.

    Returns:
        The renamed files, in page order.

    Raises:
        ValueError: The engine wrote a different number of files than the range covers.
            Raised rather than tolerated: a short split would otherwise be published as a
            complete one, and a missing page is exactly the kind of silent gap
            ``README.md`` §7 forbids.
    """
    written = split_output_paths(directory)
    if len(written) != expected_count:
        raise ValueError(
            f"pdfseparate wrote {len(written)} page(s) for {expected_count} page(s) "
            f"from page {first_page}"
        )

    renumbered: list[Path] = []
    for offset, path in enumerate(written):
        target = directory / f"{page_index_name(offset + 1)}.pdf"
        if path != target:
            path.rename(target)
        renumbered.append(target)

    return renumbered
