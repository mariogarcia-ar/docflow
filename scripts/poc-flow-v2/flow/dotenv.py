"""Load `.env` into the process environment, once, without overriding it.

The flow's sampling options reach the adapter through ``os.environ`` at call
time — the port's ``structured`` / ``vision`` signatures take no options — so a
``.env`` a caller wrote is invisible unless something parses it into the
environment. The CLI does that for its own settings; this module does it for the
libraries, which is what makes a client like ``myllmlocal.py`` honour the file.

Why this exists, as a measurement rather than a preference
---------------------------------------------------------

``myllmlocal.py`` planted distinct values in ``.env`` and none of them reached
the request: the only ``num_ctx`` on the wire was the flow's own 8192, declared
by :func:`flow.sampling.apply_sampling`. The file was read by nothing. Measured
with the same values exported instead:

    .env alone        num_ctx 8192  (the flow's default, not the file)
    values exported   num_ctx 2048, temperature 0.99, num_predict 77

``scripts/poc/_lib.py`` had already solved this for the kernel bench, after the
same symptom — a driver drove a live adapter and found nothing. This module is
the flow's own copy of that fix rather than an import of it: ``scripts/poc/`` is
a separate surface, and a library that reached into one bench to serve another
would couple two things that are meant to move apart.

The precedence, and why the order of the two writes matters
-----------------------------------------------------------

    exported variable  >  `.env`  >  the module's own default

:func:`load_env` uses ``setdefault`` semantics, so an exported variable wins —
the order ``NFR-06`` declares, and the reason ``DOCFLOW_OLLAMA_NUM_CTX=2048
python client.py`` cannot be silently ignored. It must also run **before**
:func:`flow.sampling.apply_sampling`, which writes ``num_ctx`` only when the
variable is unset: loading the file first is what lets a ``.env`` outrank the
flow's default, and loading it afterwards would leave the file unable to say
anything about the one option the flow already declares.

An empty value is skipped, for the reason the CLI's resolver skips it too: a
commented-out ``KEY=`` in a template is not a setting.
"""

from __future__ import annotations

# `wrong-import-position`: `docflow` is only importable once `_bootstrap` has put
# `src/` on `sys.path`, and the import is deliberately function-local so this
# module stays importable before that — the same constraint `scripts/poc/_lib.py`
# documents for its own reuse of the parser.
# pylint: disable=wrong-import-position
import os
import pathlib
from typing import Final

from ._bootstrap import REPO_ROOT, ensure_docflow_importable

__all__: list[str] = [
    "DOTENV_PATH",
    "load_env",
]

#: The `.env` file, at the repository root. Absent is the normal case for a fresh
#: checkout, and :func:`load_env` treats it as *nothing to load* rather than as an
#: error.
DOTENV_PATH: Final[pathlib.Path] = REPO_ROOT / ".env"


def load_env(path: pathlib.Path | None = None) -> int:
    """Load a ``.env`` into ``os.environ``, without overriding what is exported.

    The parser is **not** reimplemented: it imports ``docflow.cli.read_dotenv``,
    the one owner of the ``.env`` format. A second parser would be a second
    answer to *what does this line mean*, and the two would drift on the first
    quoting rule either of them learned.

    Reusing it is not the library going *through* the CLI: the CLI is a caller of
    the library, and what is shared here is a pure function over a file.

    Args:
        path: The file to read, defaulting to :data:`DOTENV_PATH`. An absent file
            loads nothing, because a checkout without a ``.env`` is the normal
            case rather than an error.

    Returns:
        How many variables this call set. A count rather than a print, so a
        caller that wants to report it can and one that does not is not made
        noisy.

    """
    ensure_docflow_importable()

    from docflow.cli import read_dotenv

    values = read_dotenv(DOTENV_PATH if path is None else path)

    set_count = 0
    for name, value in values.items():
        if value == "" or os.environ.get(name) is not None:
            continue
        os.environ[name] = value
        set_count += 1

    return set_count
