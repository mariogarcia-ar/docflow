"""Make a written PDF's bytes a function of its content, not of the run.

K2 is classified `deterministic` (`sad.md` §4, `kernel-cli.md` §7), and the
classification is load-bearing rather than descriptive: a deterministic artifact is
a **cache** that may be dropped and recomputed, the ledger records its hash as the
claim behind a `done` stage, an upstream artifact's hash is one of the seven terms
of the cache key, and K7 deduplicates by hash. Two runs over the same input must
produce the same artifact, or all four of those statements are false.

**The engine writes a fresh random file identifier on every save.** A PDF's trailer
carries an ``/ID`` — a pair of byte strings the specification describes as a
*file identifier*, and MuPDF generates freshly at each write. Nothing about the
document changes, and the bytes differ anyway:

    $ docflow-kernel pdf split doc.pdf --pages 1,2     # ten runs, ten hashes
    $ docflow-kernel pdf split doc.pdf --pages 1,2 --repeat 3
    repetitions: 9cf27b29… · 5628380b… · 098c2559…    # three different artifacts

That is the defect this module exists to fix, and it is a defect in the *measurement*
rather than in the document: the split produced the right pages every time, and the
hash that is supposed to identify those pages did not.

Why the repair lives here, and why it is a repair at all
--------------------------------------------------------

The identifier is *opaque*: the specification says only that the two byte strings
are equal in a newly created file, and no reader consults them to open or verify a
document. Rewriting it therefore changes no fact the document asserts — but it does
change the bytes, so the decision is recorded here, in a module of its own, rather
than folded into the adapter where it would read as incidental.

The alternative was to reclassify K2 as non-deterministic. That would have been
worse: `render`, `tokens`, `classify` and `probe` are deterministic already, and
declaring the whole kernel sampled would drop a working guarantee — and the cache
and dedup behaviour that depends on it — to accommodate one field of one operation.

What this module does not do
----------------------------

- **It does not re-encode the document.** The payload is edited in place, and the
  identifier's length is preserved, so every byte offset, cross-reference table and
  ``startxref`` in the file stays valid. Re-serialising through the engine is what
  produced the random identifier in the first place.
- **It does not fabricate an identifier for a document that has none.** A payload
  with no ``/ID`` is returned untouched: adding one would be inventing a fact.
- **It does not hash the document's meaning.** The digest is over the payload with
  the identifier *zeroed*, so it is a function of the bytes that are not the
  identifier — which is exactly what has to be stable.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

__all__: list[str] = ["stabilise_file_id"]

#: The trailer's file identifier: a ``/ID`` array holding two hexadecimal strings.
#:
#: The length is not anchored, because the engine's choice of length is not this
#: module's business — whatever it wrote is replaced by a value of the same length,
#: so the payload's size never changes and no offset can shift. An empty string is
#: matched too (``[0-9A-Fa-f]*``): a conforming writer may emit ``[]``, and leaving
#: that alone would make the payload non-deterministic for a different reason.
FILE_ID_PATTERN: Final[re.Pattern[bytes]] = re.compile(
    rb"(/ID\s*\[\s*<)([0-9A-Fa-f]*)(>\s*<)([0-9A-Fa-f]*)(>\s*\])"
)


def _zeroed(payload: bytes) -> bytes:
    """Return the payload with both identifier strings replaced by zeros.

    Zeroing is what makes the digest independent of the identifier it replaces. A
    digest taken over the payload *as written* would fold the random value into
    itself, and two runs would still disagree.

    Args:
        payload: The bytes the engine wrote.

    Returns:
        The same bytes, with the identifier fields zeroed and everything else intact.

    """
    return FILE_ID_PATTERN.sub(
        lambda found: (
            found.group(1)
            + b"0" * len(found.group(2))
            + found.group(3)
            + b"0" * len(found.group(4))
            + found.group(5)
        ),
        payload,
    )


def stabilise_file_id(payload: bytes) -> bytes:
    """Replace a written PDF's random file identifier with a content-derived one.

    The result is a function of the content: two runs over the same document produce
    the same bytes, and two runs over different documents produce different bytes.
    That is what makes K2's hash mean anything.

    The digest is written in upper-case hexadecimal because that is the form PDF
    writers use for these strings, and because the replacement should not be
    distinguishable from an ordinary identifier to a reader that does look at it.

    Args:
        payload: The bytes the engine wrote.

    Returns:
        The same bytes with a content-derived identifier — the same length, so no
        offset moves — or the payload unchanged when it carries no identifier to
        stabilise.

    """
    match = FILE_ID_PATTERN.search(payload)
    if match is None:
        return payload

    digest = hashlib.sha256(_zeroed(payload)).hexdigest().upper().encode("ascii")

    return FILE_ID_PATTERN.sub(
        lambda found: (
            found.group(1)
            + digest[: len(found.group(2))]
            + found.group(3)
            + digest[: len(found.group(4))]
            + found.group(5)
        ),
        payload,
    )
