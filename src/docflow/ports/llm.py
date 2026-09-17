"""`LlmEngine` - the port over generation, for K5 (`llm.local`) and K6 (`llm.frontier`).

One interface, two kernels
--------------------------

`ADR-004` describes K5 and K6 as separate kernels because they differ in
determinism class, cost and failure modes — a local model is ``sampled`` and free,
a hosted one is ``external`` and metered (`sad.md` §4). That difference belongs to
the **adapter**, not to the caller: a caller asks for *a structured read of this
prompt*, and which of the two engines answered is a resolution decision recorded
in the evidence and the call record. One interface with two implementations is
therefore what keeps a caller from depending on which engine it reached.

Both implementations answer every operation below. ``judge`` is implemented by
both even though it is exercised only on the frontier path: it is generic
capability, and a local model is a legitimate judge for a hosted model's output —
what row 15 of the silent-failure matrix forbids is not a local judge but the
**same model** grading its own output.

The three rules this port exists to make reachable
--------------------------------------------------

**No fallback.** An unknown model or provider name fails with a reason naming it
— ``model_unknown``, ``provider_unknown`` — and no default is substituted. The
failure path is typed so that *"there is no fallback"* is a fact a test can reach
rather than an intention somebody stated (`kernel-cli.md` §5). There is no
``fallback`` or ``default_model`` parameter, and no environment variable
substitutes one.

**Absence, ``null`` and a value are three outcomes.** A model that returned
nothing, a model that returned ``null`` for a field, and a model that returned a
value are distinguishable from each other, and never collapsed into one reading.

**Secrets come from the environment.** No key is a parameter of any method here,
so no call path can take one from a command line or a descriptor.

Deliberately absent
-------------------

- **No ``model`` member.** The model is a parameter of every call, so *which*
  model answered is stated at the call site rather than defaulted on an object.
- **No token counting, no batch API, no second provider, no ``ps``/``pull``/
  ``generate``.** Documented targets, not Stage 1 scope (``# TODO: [MVP]``).
- **No retry until two answers agree.** Attempts are counted; agreement is never
  manufactured (`kernel-cli.md` §7). **Never**.
- **No domain noun.** **Never** (`kernel-cli.md` §10).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, runtime_checkable

from docflow.kernels.types import Bytes, Evidence, KernelResult

__all__ = ["LlmEngine"]


@runtime_checkable
class LlmEngine(Protocol):
    """A generation engine, named by capability rather than by vendor.

    Implementations live under ``docflow/adapters/`` — ``ollama.py`` for K5,
    ``frontier.py`` for K6 — and are imported only by the composition root. No
    module under ``docflow/ports/`` imports one (`ADR-004`).
    """

    def capabilities(self, model: str) -> KernelResult[Evidence]:
        """Report the model's identity and its parameters, without generating.

        Args:
            model: The model as the caller named it.

        Returns:
            The model's **revision** — a digest for a local model, a concrete
            model string for a hosted one — never the tag alone, because a tag
            such as ``qwen2.5`` moves and the digest is the identity. A name that
            resolves to no known model returns no value and ``model_unknown``,
            with the unknown name present in the reason; a prefix that names no
            provider returns ``provider_unknown``. **No default is substituted**
            in either case.

        """

    def warm(self, model: str) -> KernelResult[Evidence]:
        """Load or reach the model so that the first real call pays no cold-start.

        Args:
            model: The model to warm.

        Returns:
            Evidence that the model is resident, or no value and a typed
            ``Reason`` — ``model_not_pulled`` for a local model that is absent,
            naming the remedy; ``provider_unavailable`` for a hosted one that
            cannot be reached. Warm is a real call: a kernel cannot claim a model
            is ready without having asked.

        """

    def structured(
        self,
        model: str,
        prompt: str,
        schema: Mapping[str, object],
    ) -> KernelResult[Mapping[str, object]]:
        """Ask a model for a structured answer against a schema.

        Args:
            model: The model as the caller named it.
            prompt: The prompt text, exactly as it will be sent.
            schema: The schema the answer must satisfy, supplied by the caller
                from the registry. It is never defaulted or synthesized here.

        Returns:
            The parsed answer, or no value and a typed ``Reason``. A generation
            cut by the context window returns ``truncated_output`` and is
            **never** parsed as if it were complete — a cut that happens to land
            after the last complete field would otherwise parse cleanly and be
            reported as a full answer. A caller that needs the raw completion
            reads it from the evidence: the raw bytes are the artifact of record,
            and the parsed structure is derived from them.

        """

    def vision(
        self,
        model: str,
        prompt: str,
        images: Sequence[Bytes],
        schema: Mapping[str, object],
    ) -> KernelResult[Mapping[str, object]]:
        """Ask a model for a structured answer about images, against a schema.

        Args:
            model: The model as the caller named it.
            prompt: The prompt text, exactly as it will be sent.
            images: The images the prompt refers to.
            schema: The schema the answer must satisfy, supplied by the caller.

        Returns:
            The parsed answer, or no value and a typed ``Reason``, with the same
            truncation and raw-completion rules as ``structured``.

        """

    def judge(
        self,
        model: str,
        rubric: str,
        samples: Sequence[Mapping[str, object]],
        produced_by: str,
    ) -> KernelResult[Mapping[str, object]]:
        """Grade samples against a rubric.

        Args:
            model: The model as the caller named it, in the grading role.
            rubric: The grading criteria, supplied by the caller.
            samples: The samples to grade.
            produced_by: The model that produced the samples. It is a required
                parameter because the prohibition below is only checkable if the
                call site has to state it.

        Returns:
            The grades, or no value and a typed ``Reason``. Asking a model to
            grade samples it produced itself returns ``role_conflict`` and
            nothing else: the labeller role must not share a run with the
            governor role, because a model grading its own output measures its
            own habits rather than the answer's correctness (row 15 of the
            silent-failure matrix).

        """
