"""Shared fixtures of the LLM processor's tests.

The only double this processor has is the in-memory provider fake, installed at the provider
primitives inside ``docflow.llm.primitives`` and nowhere higher (`README.md` §9.7). There is one
tier and one gate: ``pytest`` runs whole, with no provider reached and no client library imported
by production code.

**Seven names are patched, and all of them are inside the seam.** The three generators are what
:func:`docflow.llm.process_llm_request` resolves through the module at call time — the frozen
injection point — and the four model primitives are patched for the same reason the OCR suite
patches its engine namespace: a suite that needed a live endpoint to answer "what is this model"
would not be a suite that runs with no provider.

Importing the seam never needs a client, which is what makes the patch below possible: the module
imports ``httpx`` inside the call that needs it and no test ever imports it.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from docflow.llm import primitives
from tests.fakes.engines.fake_provider import FakeProvider

#: Every name the double replaces, taken from the seam so the two cannot drift apart.
PATCH_TARGETS = tuple(
    f"docflow.llm.primitives.{name}" for name in primitives.PRIMITIVE_NAMES
)


@pytest.fixture(autouse=True)
def provider(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeProvider]:
    """Return a factory that installs a provider double, for every test in this package.

    The fixture is autouse on purpose: a test that forgot it would reach a real endpoint on a
    developer's machine, which is exactly the accident the double exists to prevent. A test that
    needs the double scripted calls the returned factory; a test that needs the client library
    *absent* patches ``httpx`` out of ``sys.modules`` itself, after this fixture has run.

    Args:
        monkeypatch: pytest's patcher, which restores the seam afterwards.

    Returns:
        A factory taking the double's own knobs, or a pre-built double, and installing it.
    """

    def install(
        *, double: FakeProvider | None = None, **settings: object
    ) -> FakeProvider:
        """Install a double at every provider primitive and return it.

        Args:
            double: A pre-built double, for a test that scripts a sequence before installing it.
            settings: The double's own knobs.
        """
        fake = double if double is not None else FakeProvider(**settings)
        for name, target in zip(primitives.PRIMITIVE_NAMES, PATCH_TARGETS, strict=True):
            monkeypatch.setattr(target, getattr(fake, name))
        return fake

    install()
    return install
