"""K2 `PdfSource` - the port over a PDF acquisition engine.

What this port owns is the *measurement*, never the decision. ``classify`` reports
which of the four shapes a page has and what it observed while deciding; it does
not report where the caller should route the page. Routing a stale-layer page
away from conversion is Diagnosis's decision at Stage 2, taken against registry
policy — a kernel that reads its own threshold has made that decision whether or
not it prints one (`kernel-cli.md` §3, guardrail 2; `prd.md` FR-15).

The four measurement procedures this port exposes
-------------------------------------------------

``probe``        What the file is: pages, producer metadata, encryption state.
``classify``     One page's shape, as a measurement with its evidence.
``tokens``       The text layer's positioned tokens, for a page range.
``render``       A page range as a bitmap, plus ``split`` to cut the file.

Two of the seventeen silent failures live behind this port and are stated here
because the port is where a caller can be misled by them:

- a scan with a **stale invisible OCR layer** behind it reads as a *text* PDF, so
  the page is never converted and the text on it is never seen — the
  classification must detect the invisible layer and report it as evidence
  rather than letting it decide the shape silently;
- a **150 DPI scan rendered at 300** is reported as satisfying the requested
  resolution — larger and no more legible — so ``render`` must refuse rather than
  upscale.

Neither rule is enforced by this file, which declares signatures only. They are
stated here because the port is the contract an adapter is held to, and
``kernel-cli.md`` §11 rows 3 and 4 are where they are asserted.

Deliberately absent
-------------------

- **No threshold member.** What counts as blank, or as too low a resolution, is
  the *caller's* value (`prd.md` FR-15). A constant here would be a routing
  decision in disguise.
- **No engine or reader setting.** A missing external binary is a typed
  ``Reason``, never a substitute reader (`wbs.md` §9).
- **No page-fact or embedded-image surface.** Beyond classification those are
  documented targets, not Stage 1 scope (`sad.md` §3, ``# TODO: [MVP]``).
- **No domain noun.** **Never** (`kernel-cli.md` §10).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from docflow.kernels.types import Bytes, Evidence, KernelResult, Token

__all__ = ["PdfSource"]


@runtime_checkable
class PdfSource(Protocol):
    """A PDF acquisition engine, named by capability rather than by vendor.

    An adapter implements this protocol and is imported only by the composition
    root. Nothing in ``docflow/ports/`` imports an adapter — that is the arrow
    this port exists to hold pointing down (`ADR-004`).
    """

    def probe(self, path: Path) -> KernelResult[Evidence]:
        """Report what the file is, without rendering anything.

        Args:
            path: The PDF to inspect.

        Returns:
            The file's page count, producer metadata and encryption state as
            observations. A file that cannot be opened returns no value and a
            typed ``Reason`` — ``encrypted`` or ``unsupported_format`` — never an
            empty observation set standing in for a successful probe.

        """

    def classify(self, path: Path, page: int) -> KernelResult[Evidence]:
        """Measure one page's shape and report how the measurement was taken.

        Args:
            path: The PDF to inspect.
            page: One-based page number.

        Returns:
            The measured shape and its observations. A scan carrying an invisible
            text layer must be reported as an image page **with**
            ``invisible_text`` set and any contradicting producer metadata
            present, so the hidden layer is evidence rather than a silent reading
            of the page as text. A page carrying no content at all returns no
            value and a ``blank_page`` reason: *blank* is a shape, and it is not
            the same statement as *a page with no text*.

        """

    def tokens(
        self, path: Path, pages: Sequence[int], dpi: int
    ) -> KernelResult[Sequence[Token]]:
        """Extract the text layer's positioned tokens for a page range.

        Args:
            path: The PDF to read.
            pages: The one-based page numbers to read.
            dpi: The resolution the boxes are expressed in.

        Returns:
            The tokens with their boxes and confidences, or no value and a typed
            ``Reason``. A reader that reports no confidence for a token leaves
            that token's confidence ``None`` — ``None`` is never reported as
            ``1.0`` (`sad.md` §6).

        """

    def render(self, path: Path, pages: Sequence[int], dpi: int) -> KernelResult[Bytes]:
        """Render a page range as a bitmap at a requested resolution.

        Args:
            path: The PDF to render.
            pages: The one-based page numbers to render.
            dpi: The resolution requested by the caller.

        Returns:
            The rendered bitmap, or no value and a typed ``Reason``. A request
            that exceeds what the source pixels hold returns
            ``insufficient_effective_resolution`` and produces **no larger
            file**: the effective resolution is measured from the embedded
            pixels, never taken from the request or from metadata.

        """

    def split(self, path: Path, pages: Sequence[int]) -> KernelResult[Bytes]:
        """Cut a page range out of the file as a new document.

        Args:
            path: The PDF to split.
            pages: The one-based page numbers the result must contain.

        Returns:
            The extracted document, or no value and a typed ``Reason``. The
            result preserves the source page count and page boxes for the
            requested range, and the mapping back to the source range is recorded
            in the evidence — a split that separates a document from its pages is
            row 5 of the silent-failure matrix.

        """
