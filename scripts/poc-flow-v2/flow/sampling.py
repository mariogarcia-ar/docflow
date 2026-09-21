"""Sampling dials: what the caller asks the runtime for, per call.

`config.py` holds the **domain** dials — severities, thresholds, model names.
This module holds the other category: the *sampling* parameters, which describe
how a model is asked rather than what the flow decides. They are separate files
because they change for different reasons and at different moments, exactly as
`my_flow.md` B.11 separates the prompt from the schema.

Why this module exists at all — the defect it closes:

The adapter reads every sampling option from ``DOCFLOW_OLLAMA_<OPTION>`` and
falls back to the runtime's own default when nothing is declared. Measured
against this runtime, that default is **4096**, and the model declares far more:

```
/api/show  deepseek-r1:1.5b -> qwen2.context_length = 131072
/api/ps    no num_ctx sent  -> context_length = 4096
/api/ps    num_ctx = 8192   -> context_length = 8192
```

So *not declaring* a window is not a neutral act: it silently halves the
generation budget, and a `deepseek-r1` step spends part of that budget on
reasoning tokens before it emits a single field. Measured on the `desglose`
step, a generation spent 1824 characters on reasoning against 290 of answer,
`done_reason` came back `length`, and the step's nine fields were lost whole —
the critical amount among them, because the arithmetic rule that settles it
reads its components from that step. `my_flow.md` B.10 lists exactly this
failure: *a prompt larger than the window — the answer describes the beginning
of the document*.

The value is the one `docs/artifacts/kernel-cli.md` §5 uses for K5's own
evidence sample (`"num_ctx": 8192`), so the flow and the lab bench ask for the
same window.
"""

from __future__ import annotations

import os
from typing import Final

__all__: list[str] = [
    "NUM_CTX",
    "SAMPLING_ENV_PREFIX",
    "apply_sampling",
]

#: The window the flow asks for, in tokens.
#:
#: 8192 rather than the runtime's 4096 default: measured, the heaviest step's
#: prompt is ~1850 tokens and the flow's own prompt tokens 452-1090, so every
#: step fits in 4096 — but `deepseek-r1`'s reasoning tokens are *variable*
#: (measured 396-1011 tokens of generation on five identical calls, and one
#: `done_reason: length` on the run that mattered). The margin is what absorbs
#: that variance; 8192 costs VRAM and buys the headroom, and it is a dial so an
#: operator can raise it for a larger document rather than editing code.
NUM_CTX: Final[int] = 8192

#: The prefix the adapter reads its sampling options under.
#:
#: This is a **contract with the adapter**, not a local choice: the name is
#: `docflow/adapters/ollama.py::_options_from_environment`, and the flow can
#: only speak it because the adapter declares it. Kept as a named constant so
#: the coupling is greppable from either side.
SAMPLING_ENV_PREFIX: Final[str] = "DOCFLOW_OLLAMA_"


def apply_sampling(*, num_ctx: int = NUM_CTX) -> None:
    """Declare the sampling options the flow's model calls run under.

    The adapter reads its options from the environment **at call time**
    (`_options_from_environment`), and the port's ``structured`` / ``vision``
    signatures take no options — so the environment is the one channel a caller
    has. This function is that channel, in one place: the flow asks for a window
    **explicitly** instead of inheriting whatever the runtime picked.

    It writes only when the operator has not: an exported
    ``DOCFLOW_OLLAMA_NUM_CTX`` wins, because the environment is where an
    operator tunes a run without editing code, and a library that overwrote it
    would make its own dial unreachable. That precedence is the same one
    `.env.example` states (`CLI flag → environment → file → default`).

    Args:
        num_ctx: The context window to ask for, in tokens.

    """
    name = f"{SAMPLING_ENV_PREFIX}NUM_CTX"
    if os.environ.get(name):
        return
    os.environ[name] = str(num_ctx)
