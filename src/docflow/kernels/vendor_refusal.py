"""The refusal a vendor raises, shared by every seam that has one.

Two seams exist — K2's :class:`~docflow.kernels.pdf_vendor.PdfVendor` and K3's
:class:`~docflow.kernels.image_vendor.RasterVendor` — and both need the same thing: an
exception carrying a ``Reason`` from the closed set of `kernel-cli.md` §5, plus
whatever was measured before the refusal.

The *shape* is identical and belongs in one place. What differs is only the prose each
seam uses to describe its own domain, so each seam subclasses this rather than
restating the constructor:

    class PdfVendorError(VendorRefusal):
        \"\"\"A reader that cannot serve a call...\"\"\"

Why an exception rather than a ``(None, Reason)`` pair
-------------------------------------------------------

These are raised from inside a loop and across several frames. A return value would
have to be checked at every one of them, and the check that gets forgotten is the one
that lets a refusal be reported as a measurement.

Why the measurements travel with the reason
--------------------------------------------

A refusal frequently *is* the measurement: ``insufficient_effective_resolution`` is
only diagnosable if the page's actual DPI comes with it. A failure with no evidence
cannot be diagnosed, and the caller has no second way to ask.
"""

from __future__ import annotations

from collections.abc import Mapping

from docflow.kernels.types import Reason

__all__: list[str] = ["VendorRefusal"]


class VendorRefusal(Exception):
    """A vendor that cannot serve a call, carrying the ``Reason`` that says why.

    Subclassed per seam so each one's docstring names its own domain. The subclass
    inherits the constructor, and the two attributes are what a caller reads: a
    ``reason`` to match on, and the evidence taken before the refusal.
    """

    def __init__(
        self,
        reason: Reason,
        measurements: Mapping[str, float] | None = None,
        observed: Mapping[str, object] | None = None,
    ) -> None:
        """Store the reason and whatever was measured before refusing.

        Args:
            reason: Why no value could be produced.
            measurements: The numeric measurements taken before the refusal.
            observed: The remaining observations taken before the refusal.

        """
        super().__init__(reason.message)
        self.reason = reason
        self.measurements: dict[str, float] = dict(measurements or {})
        self.observed: dict[str, object] = dict(observed or {})
