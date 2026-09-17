"""Parse a page selection - shared by K2 and K4 (`E07-02` / `S1-T21`).

`pdf tokens --pages`, `pdf render --pages`, `pdf split --pages` and `ocr read --pages`
all take the same syntax (`kernel-cli.md` §9: ``1-3``, ``1,4,7`` or ``all``), and the
two kernels' commands had two copies of the parser. That is why this module exists:
the duplication was **real** rather than superficial - both copies had the same
off-by-one risk and the same refusal - so it is extracted rather than suppressed, the
same call `E04-03` made for the two vendor-refusal classes.

The parser is deliberately **strict**, and it is the place a wrong page range becomes a
usage error rather than an empty read. ``pdf`` validates the range against the
document's own page count, because only it has a probe to ask; this module cannot and
does not invent one.
"""

from __future__ import annotations

from typing import Final

__all__: list[str] = ["SELECT_ALL", "parse_pages"]

#: The word that means *every page*. A recorded constant so the two surfaces cannot
#: disagree about it.
SELECT_ALL: Final[str] = "all"


def parse_pages(text: object, total: int | None = None) -> list[int]:
    """Parse a page selection into one-based page numbers.

    Args:
        text: The selection, or None for every page when ``total`` is known.
        total: How many pages the document has, when a probe could report it. None
            means the caller cannot check the range, and the numbers are returned
            unvalidated rather than guessed at.

    Returns:
        The page numbers, in the order given and with no duplicates removed: asking
        for a page twice is a caller's choice, not an error.

    Raises:
        ValueError: If a piece is not a number or a range, if the selection is empty,
            or if a page lies outside a document whose length is known. A page that
            does not exist is a usage error, not an empty read.

    """
    if text is None or str(text) == SELECT_ALL:
        if total is None:
            raise ValueError(
                f"{SELECT_ALL!r} needs a page count to expand into, and none was "
                "available: refusing rather than expanding to nothing, which would "
                "read as a document with no pages."
            )
        return list(range(1, total + 1))

    chosen: list[int] = []
    for part in str(text).split(","):
        piece = part.strip()
        if not piece:
            continue
        if "-" in piece:
            low, _, high = piece.partition("-")
            if not low.strip().isdigit() or not high.strip().isdigit():
                raise ValueError(
                    f"page range {piece!r} must be 'low-high' with two page numbers"
                )
            chosen.extend(range(int(low), int(high) + 1))
        elif piece.isdigit():
            chosen.append(int(piece))
        else:
            raise ValueError(f"page {piece!r} is not a number or a range")

    if not chosen:
        raise ValueError(f"the page selection {text!r} selected no page")

    if total is not None:
        beyond = sorted({page for page in chosen if page < 1 or page > total})
        if beyond:
            raise ValueError(
                f"page(s) {beyond} are outside the document, which has {total} page(s)."
            )
    return chosen
