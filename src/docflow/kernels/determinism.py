"""Determinism classes, and what a missing artifact means for each.

`E05-03` / `S1-T08`. Some artifacts can be recomputed and some cannot, and the
difference decides what the system may do when one goes missing. Recomputing a
**deterministic** artifact is free and produces the identical bytes. Recomputing a
**sampled** one produces a *different* answer, reported as ``done`` - so the run
silently changes its result while claiming success. That is the failure this module
exists to make impossible to express.

The class is declared here, once per kernel, and **read** rather than guessed
-----------------------------------------------------------------------------

`kernel-cli.md` §7 fixes the mapping and `sad.md` §4 gives the consequences. The
declaration lives in one table, keyed by kernel id, because there is nowhere else for
it to live: an adapter cannot carry it (the port declares no such member, and adding
one would re-open `E04-01`'s gate), and a descriptor must not carry it (a class set per
run is exactly the *"guessed or set per run"* the criterion forbids). So it is a fact
about the **kernel**, which is what `sad.md` §4 says it is.

`class_of` **refuses** an unknown kernel rather than defaulting. A defaulted class is
the worst possible one to default: assuming `deterministic` makes the system regenerate
a sampled artifact, and assuming `sampled` makes it discard recomputable work.

The three consequences, and why they differ
-------------------------------------------

| Class | Missing artifact means | What happens |
|---|---|---|
| **deterministic** | the cache lost a copy | **recompute**; identical bytes |
| **sampled** | the **evidence** is gone | ``failed``, ``evidence_missing`` |
| **external** | the record is gone | ``failed``, ``evidence_missing`` |

A sampled artifact is **evidence**, not a cache: it may be kept, and it may never be
regenerated to fill a gap. The test that guards this fails if regeneration occurs,
because a stage that re-samples and reports ``done`` is indistinguishable from one that
succeeded - except that the result changed.

What this module deliberately does not do
-----------------------------------------

- **No detection on ledger read.** *When* the check runs is `E05-05`
  (`S1-T10`, ADR-006): every read, no flag. This module supplies the *consequence
  per class*; that issue makes the check universal. They meet at
  :func:`artifact_is_present`, the one place a class decision needs a fact.
- **No regeneration policy change.** Stage 1 fixes *"never regenerate"*. Relaxing it is
  a **policy** decision that would change this issue's done-when and re-open the gate -
  it cannot be taken from Plan 2 (`plan-01-kernels.md` §12 open decision **#6**).
- **No reclassification of Docling.** K4 reports `sampled`; whether a pinned Docling is
  in fact deterministic is open decision **#5**, carried and **not resolved** here.
- **No retry policy.** *Retrying to obtain agreement* is **forbidden**; the
  attempt count is recorded so the pattern is visible (`E05-02`). This module
  never retries.
- **No escalation ladder.** *"Could not"* escalation is the Validator's, `S2-T09`.
- **No pipeline, field or document noun.** **Never** (`kernel-cli.md` §10).

PoC stage
---------

The lifecycle stage is **PoC**: close the flow, keep the shortcuts visible. Each
deliberate shortcut carries a marker naming what must replace it.

"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

from docflow.kernels import store
from docflow.kernels.types import Reason

__all__: list[str] = [
    "CLASS_NAMES",
    "DETERMINISTIC",
    "EXTERNAL",
    "KERNEL_CLASSES",
    "REASON_EVIDENCE_MISSING",
    "SAMPLED",
    "MissingEvidence",
    "artifact_is_present",
    "class_of",
    "consequence_for",
    "declared_classes",
    "resume_decision",
]

#: The three classes, exactly, as `sad.md` §4 declares them. The set is frozen by
#: `plans/README.md` §3 (Plan 1 row) and Plan 2's escalation ladder is expressed
#: entirely in these terms.
DETERMINISTIC: Final[str] = "deterministic"
SAMPLED: Final[str] = "sampled"
EXTERNAL: Final[str] = "external"

#: The three names. A fourth would be a class nothing consumes; a missing one would be
#: a kernel whose resume behaviour is undefined.
CLASS_NAMES: Final[tuple[str, ...]] = (DETERMINISTIC, SAMPLED, EXTERNAL)

#: The reason code a missing sampled or external artifact produces. In the closed set
#: (`kernel-cli.md` §5), exit `2` - an expected negative, not a precondition failure.
REASON_EVIDENCE_MISSING: Final[str] = "evidence_missing"

#: Kernel id to its class, from `kernel-cli.md` §7 and `sad.md` §4. **This table is the
#: whole declaration**: a kernel absent from it has no resume behaviour, and
#: :func:`class_of` refuses rather than defaulting.
#:
#: K4 is `sampled` by `sad.md` §4's mapping of *"model-dependent"*; open decision #5
#: carries whether a pinned Docling is in fact deterministic.
KERNEL_CLASSES: Mapping[str, str] = MappingProxyType(
    {
        "orchestrator": DETERMINISTIC,
        "pdf": DETERMINISTIC,
        "image": DETERMINISTIC,
        "ocr": SAMPLED,
        "llm.local": SAMPLED,
        "llm.frontier": EXTERNAL,
        "store": DETERMINISTIC,
        "registry": DETERMINISTIC,
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class MissingEvidence:
    """What a run must do about a terminal stage whose artifact is gone.

    A decision, not an action: K1 takes the action, and keeping the two apart is what
    lets the consequence be asserted without running a graph.

    Attributes:
        determinism_class: The class the decision was taken under.
        recompute: Whether the stage may be run again. **True only for
            ``deterministic``** - the one class whose result is a function of its key,
            so re-running reproduces the bytes rather than replacing them.
        reason: Why the stage reports ``failed``, or None when it may recompute. The
            code is ``evidence_missing``, never a message: an assertion targets a code
            (`kernel-cli.md` §5).

    """

    determinism_class: str
    recompute: bool
    reason: Reason | None

    @property
    def failed(self) -> bool:
        """Report whether this decision makes the stage ``failed``.

        Returns:
            True when the stage cannot be recomputed and must report a reason.

        """
        return not self.recompute


def declared_classes() -> Mapping[str, str]:
    """Return the kernel-to-class table.

    Returns:
        A read-only mapping from kernel id to class name.

    """
    return KERNEL_CLASSES


def class_of(kernel: str) -> str:
    """Return the determinism class of a kernel.

    Args:
        kernel: The kernel's id, e.g. ``"llm.local"``.

    Returns:
        The class name.

    Raises:
        ValueError: If the kernel is not declared. An unknown kernel is refused rather
            than defaulted, because both available defaults are wrong in a way that
            changes results: `deterministic` makes the system regenerate a sampled
            artifact, and `sampled` makes it discard recomputable work.

    """
    determinism = KERNEL_CLASSES.get(kernel)
    if determinism is None:
        raise ValueError(
            f"No determinism class is declared for kernel {kernel!r}. The declared "
            f"kernels are {sorted(KERNEL_CLASSES)}. A kernel outside the table has no "
            "resume behaviour, and defaulting one would either regenerate evidence or "
            "throw away a recomputable artifact."
        )
    return determinism


def consequence_for(
    determinism_class: str, *, present: bool, stage: str
) -> MissingEvidence | None:
    """Decide what a terminal stage's missing artifact means for its class.

    Args:
        determinism_class: The class of the kernel that produced the artifact.
        present: Whether the artifact is on disk and hashes to the recorded digest.
        stage: The stage's name, for the reason's message.

    Returns:
        The decision, or None when the artifact is present and nothing must happen. All
        three classes answer *nothing* for a present artifact - the class only changes
        what an absence means.

    Raises:
        ValueError: If ``determinism_class`` is not one of the three. An unrecognised
            class would otherwise take the ``deterministic`` branch and regenerate
            something nobody classified.

    """
    if determinism_class not in CLASS_NAMES:
        raise ValueError(
            f"{determinism_class!r} is not a determinism class. The declared classes "
            f"are {list(CLASS_NAMES)}; an unrecognised one would fall through to a "
            "branch no rule chose."
        )

    if present:
        return None

    if determinism_class == DETERMINISTIC:
        # The artifact is a cache: the result is a function of the key, so re-running
        # reproduces it. This is the one class where *missing* is recoverable.
        return MissingEvidence(
            determinism_class=determinism_class, recompute=True, reason=None
        )

    return MissingEvidence(
        determinism_class=determinism_class,
        recompute=False,
        reason=Reason(
            code=REASON_EVIDENCE_MISSING,
            message=(
                f"The artifact of stage {stage!r} is missing, and the kernel that "
                f"produced it is {determinism_class!r}: re-running it would produce a "
                "different answer rather than the same one, so the result would change "
                "while the ledger reported success. The stage is failed rather than "
                "re-sampled; a new observation is a different observation."
            ),
        ),
    )


def artifact_is_present(root: Path, sha256: str) -> bool:
    """Report whether an artifact's bytes are on disk and hash to their name.

    The one place a class decision needs to know a fact about the filesystem, kept
    separate so the decision above is a pure function of *(class, present)* and can be
    asserted without a store.

    Args:
        root: The store root.
        sha256: The digest the ledger recorded.

    Returns:
        True when the bytes exist and hash to ``sha256``. A truncated file is **not**
        present: it is the same defect as an absent one - the bytes a claim names are
        not there - and K7's ``verify`` already answers this question that way.

    """
    return store.verify(root, sha256)


def resume_decision(
    record: store.StageRecord,
    *,
    kernel: str,
    store_root: Path,
    stage: str,
) -> MissingEvidence | None:
    """Decide what to do about a recorded stage, given its kernel's class.

    Composes the three steps a caller would otherwise have to remember in order: read
    the class from the **producing kernel**, ask whether the artifact is still there,
    and apply the class's consequence. A caller that skipped the first step would be
    guessing, and one that skipped the second would be trusting a claim about bytes.

    A stage that is not ``done`` has no artifact claim to check, so it answers None -
    this is about *a terminal stage whose bytes are gone*, and ``pending``/``running``
    are neither.

    Args:
        record: The stage's recorded state.
        kernel: The kernel that produced it.
        store_root: The store root, where the artifact should be.
        stage: The stage's name, for the reason's message.

    Returns:
        The decision, or None when the stage is not ``done`` or its artifact is present.

    Raises:
        ValueError: If ``kernel`` has no declared class.

    """
    if record.state != "done" or record.artifact_sha256 is None:
        return None

    return consequence_for(
        class_of(kernel),
        present=artifact_is_present(store_root, record.artifact_sha256),
        stage=stage,
    )
