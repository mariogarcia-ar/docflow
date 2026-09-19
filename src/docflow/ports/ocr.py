"""K4 `OcrEngine` - the port over the OCR engine, which is Docling and only Docling.

OCR output is the one place where the system cannot re-derive what it saw: a
sampled artifact is *evidence* and is never regenerated (`plans/README.md` §2
non-negotiable 3), so a lost OCR result makes that document permanently
unreproducible. Two consequences follow, and both are visible in the signatures
below.

**The engine is fixed, so the port has no engine setting.** There is no
``engine`` parameter and no engine member: a per-corpus engine choice would make
the OCR path a matrix of behaviours and would put a second adapter revision into
the cache key for no benefit (`ADR-001`, `prd.md` FR-16). A different project
takes this port and picks its own engine behind it.

**The boundary drops what it does not contract for.** Positioned tokens leave;
the engine's layout and reading order do not. A reading order injected here would
be a domain-level interpretation performed by a kernel, and ordering is the
Reconstructor's job at Stage 2 (`S2-T07`).

**A table's cells are kept or dropped, and the caller says which.** An engine's
document model gives a table no text of its own, so a boundary that keeps only
text-carrying items loses the whole construct. ``read(tables=True)`` reports each
cell as a token — its own box, the role ``table_cell`` — which is what lets a row
be read across a table the way a line is read across a page. It is **opt-in**
because `E04-04` froze this port with the cells dropped, and the *structure* is
still not here: the grid, the spans and the header association are the
Reconstructor's (`S2-T07`). Cells with boxes are not a table; they are the
material one is rebuilt from.

Silent failures this port exists to make unreachable
---------------------------------------------------

- A **blank page** returning invented text: the per-page status distinguishes
  ``read`` from ``blank`` from ``unreadable``, and a blank page reports ``blank``
  rather than ``read`` with a token list the engine dreamed up.
- **Missing confidence read as perfect**: a token's confidence is ``float | None``
  and ``None`` is never coerced to ``1.0`` (`sad.md` §6).
- A **truncated page read as a page with no text**: ``pages_requested`` and
  ``pages_read`` are both reported, so *the engine stopped early* and *the page
  held nothing* stay distinguishable.

Deliberately absent
-------------------

- **No engine parameter, no engine setting.** **Never** (`ADR-001`).
- **No reading order and no layout.** Dropped at the boundary; ordering is
  `S2-T07`'s. A table's **cells** may be kept (`tables=True`) and its
  **structure** never is — see above.
- **No "usable" / "route to OCR" style output and no aggregate score.** The
  kernel never emits a routing decision (`kernel-cli.md` §3, guardrail 2).
- **No threshold member.** **Never** (`prd.md` FR-15).
- **No domain noun.** **Never** (`kernel-cli.md` §10).
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from docflow.kernels.types import Evidence, KernelResult, Token

__all__ = ["TABLE_TOKEN_ROLE", "OcrEngine", "PageStatus", "ReadResult"]


class PageStatus(str, enum.Enum):
    """What the engine found on one page.

    Three values, because *the engine read this page and it held no tokens*,
    *there was nothing on this page to read* and *the engine could not read this
    page* are three different statements, and collapsing them is how a blank page
    comes back with invented text.

    A ``str``-valued enum, so the value serializes as the word a person reads in
    the ledger without a custom encoder.

    Attributes:
        READ: The engine read the page. The token list may legitimately be empty.
        BLANK: The page carries no content at all — not *a page with no text*.
        UNREADABLE: The engine could not read the page; the cause is local to it.

    """

    READ = "read"
    BLANK = "blank"
    UNREADABLE = "unreadable"


@dataclasses.dataclass(frozen=True, slots=True)
class ReadResult:
    """One OCR call's tokens, per-page, with the page accounting attached.

    No reading order is resolved here and no order field is carried: the tokens
    are in the order the engine returned them, and imposing an order is Stage 2's
    work. A caller that sorts them has performed the interpretation the port
    refuses to perform.

    Attributes:
        pages_requested: The one-based page numbers the caller asked for, in
            order. Reported so that a truncated read is visible as a difference.
        page_status: One status per page the engine reported on. A page absent
            from this mapping was never reached.
        tokens: The positioned tokens, in engine order.

    """

    pages_requested: tuple[int, ...]
    page_status: Mapping[int, PageStatus]
    tokens: tuple[Token, ...]

    @property
    def pages_read(self) -> tuple[int, ...]:
        """The pages the engine actually reported on, in ascending order.

        The difference between this and ``pages_requested`` is the truncation
        signal: a request for 200 pages that returns 40 statuses is a truncated
        call, and that is a different fact from a page that held no text.

        Returns:
            The one-based page numbers present in ``page_status``.

        """
        return tuple(sorted(self.page_status))


@runtime_checkable
class OcrEngine(Protocol):
    """The OCR engine, named by capability. Docling implements it; nothing chooses it.

    Implementations live under ``docflow/adapters/`` and are imported only by the
    composition root. No module under ``docflow/ports/`` imports one.
    """

    def capabilities(self) -> KernelResult[Evidence]:
        """Report what this engine can do, as observations about the engine.

        Returns:
            The engine's identity and revision terms, which is the material the
            cache key needs (`sad.md` §5, the *adapter revision* term).

        """

    def engine_info(self) -> KernelResult[Evidence]:
        """Report the engine's identity and revision as structured terms.

        Returns:
            The terms that feed the cache key. Reported separately from
            ``capabilities`` because a capability list is a description of what
            the engine does while these terms are what makes a stored artifact
            reproducible — the second is a contract, the first is documentation.

        """

    def read(
        self,
        path: Path,
        pages: Sequence[int],
        dpi: int,
        lang: str,
        *,
        tables: bool,
    ) -> KernelResult[ReadResult]:
        """Read a page range and return positioned tokens.

        Args:
            path: The document to read.
            pages: The one-based page numbers to read.
            dpi: The resolution the tokens' boxes are expressed in.
            lang: The language hint the engine should read with.
            tables: Whether to include a table's **cells** as tokens. ``False``
                drops them, which is what this port did before the parameter
                existed; ``True`` reports each cell as a token carrying its own
                box and the role ``table_cell``. **Required, with no default**:
                `E04-01` forbids a port member carrying one, and a default here
                would be an inclusion decision the caller never stated.

        Returns:
            The tokens with their per-page status and the page accounting, or no
            value and a typed ``Reason`` — ``engine_unavailable`` when the engine
            cannot be started, which is a precondition of the call rather than an
            answer about the document. A token the engine reported no confidence
            for keeps ``confidence=None``: ``None`` is never ``1.0``.

        """


# --- The table parameter -----------------------------------------------------

#: Why ``tables`` exists, why it defaults to ``False``, and what it does **not** do.
#:
#: A table is the one construct a text reader reports as *nothing*: an engine's
#: document model gives a table no ``text`` of its own, so a boundary that keeps
#: only text-carrying items drops the whole construct — measured on
#: ``casos/66cd35e9``, a 27-cell invoice table vanished entirely and the row that
#: named ``EZ9F34110`` was simply absent from the reading. That is the failure this
#: parameter closes.
#:
#: It defaults to ``False`` rather than ``True`` because ``E04-04`` froze this port
#: with the cells dropped and its criterion 3 asserts ``layout_dropped``. Inverting
#: the default would change what every existing caller receives without re-opening
#: that gate, so the inclusion is opt-in and the evidence says which way it went.
#:
#: **Cells, not a table.** This returns one token per cell, each with its own box, so
#: a caller can read a row across a table the way it reads a line across a page. It
#: does **not** return the table's structure — the grid, the spans, the header
#: association. Reassembling those is ``S2-T07``'s work (``prd.md`` FR-17), and a
#: token carrying a whole rendered table would be a token that is not one: it would
#: have the table's box and none of its cells' positions, which is exactly the
#: synthesis this layer refuses. The role says which cells came from a table, so a
#: consumer that wants the structure can group them without guessing.
TABLE_TOKEN_ROLE: Final[str] = "table_cell"
