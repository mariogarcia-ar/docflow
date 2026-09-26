"""The scripted in-memory provider double (``LLM-03``).

A model's answer is not a deterministic function of its input, and ``LLM-08`` needs a *sequence*
— invalid JSON on the first attempt, valid JSON on the second — which a single canned response
cannot express. So this double is **scripted**, deliberately, unlike the content-shaped doubles
of ``pdf``, ``image`` and ``ocr`` (``README.md`` §9.7 explains why the difference is not an
oversight).

It stands where the seam is: the module attributes ``docflow.llm.primitives.<primitive>``, which
the entry point resolves through the module at call time. Two properties are load-bearing:

* **the answers are the provider's own shape.** A generation returns a parsed HTTP response body
  — Ollama's ``{"message": {"content": …}, "prompt_eval_count": …}`` or the OpenAI dialect's
  ``{"choices": [{"message": {"content": …}}], "usage": {…}}`` — never one of our types. A fake
  that returned an ``LLMResult`` would delete the translation this package exists to test;
* **every call is recorded.** :attr:`FakeProvider.calls` is what proves a node was *not* called
  again on resume, which is the whole of invariant 1.

What it does **not** model is HTTP: no socket is opened, no client library is imported, and the
seam's own error mapping is exercised separately, against a stub client. Nothing here reaches a
provider — not Ollama, not vLLM, not a hosted API.

# TODO: [RELEASE] re-read this double against each provider's documented response shape on every
# pin bump (``GEN-17``): a hand-written double is the one place a provider shape change can pass
# unnoticed, and no test can detect it by itself.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from docflow.llm.primitives import typed_failure

#: The version the double reports for the model. Deliberately synthetic: a test asserting a real
#: one would be asserting what the provider says, not what our seam does.
FAKE_MODEL_VERSION = "fake-model-9.9.9"

#: The context window the double reports. Deliberately small enough to be exceeded on purpose.
FAKE_CONTEXT_WINDOW = 4096

#: The models the double says the endpoint offers.
FAKE_MODELS = ("test-model",)

#: The answer the double returns when no answer was scripted for the call: one JSON object that
#: satisfies the committed ``simple`` schema exactly.
DEFAULT_CONTENT = json.dumps(
    {
        "summary": "The document describes one region and its revenue.",
        "topics": ["region", "revenue"],
        "page_count": 3,
    }
)

#: A scripted entry: a provider body, answer text, an exception, or a callable that returns one.
ScriptedAnswer = Mapping[str, Any] | str | Exception | Callable[[Any], Any]


class FakeProvider:
    """A scripted, in-memory provider: seven primitives, no network, every call recorded.

    Attributes:
        calls: The generation calls it was asked for, in order. This is the counter invariant 1
            reads: a reused node must not appear here again.
        model_calls: The inventory questions it was asked (``list_models`` and friends).
    """

    __version__ = FAKE_MODEL_VERSION

    def __init__(
        self,
        *,
        answers: Sequence[ScriptedAnswer] | None = None,
        context_window: int | None = FAKE_CONTEXT_WINDOW,
        model_version: str | None = FAKE_MODEL_VERSION,
        models: Sequence[str] = FAKE_MODELS,
        raises: Exception | None = None,
    ) -> None:
        """Build the double.

        Args:
            answers: The scripted answers, consumed one per generation call. An entry that is an
                exception is raised — and it should be the *typed* failure the seam would have
                produced, because an unclassified exception is reported as an ``INTERNAL_ERROR``
                defect of the processor rather than as a provider signal. A string becomes the
                answer text; a mapping is returned as the provider's body; a callable is called
                with the call and its result is used the same way, while ``None`` means "the default
                answer". Once the script is exhausted the double answers :data:`DEFAULT_CONTENT`.
            context_window: The window ``get_context_window`` reports, or ``None`` for unknown.
            model_version: The version ``get_model_info`` reports, or ``None``.
            models: The model names the endpoint is said to offer.
            raises: An exception every generation call raises, for the timeout path.
        """
        self.answers = list(answers or [])
        self.context_window = context_window
        self.model_version = model_version
        self.models = list(models)
        self.raises = raises
        self.calls: list[Any] = []
        self.model_calls: list[Any] = []

    # -- the seven primitives ------------------------------------------------------------------

    def generate_text(self, call: Any) -> Mapping[str, Any]:
        """Answer a text-only call."""
        return self._answer(call)

    def generate_multimodal(self, call: Any) -> Mapping[str, Any]:
        """Answer a call carrying images."""
        return self._answer(call)

    def generate_structured(self, call: Any) -> Mapping[str, Any]:
        """Answer a call constrained to a response format."""
        return self._answer(call)

    def list_models(self, query: Any) -> list[str]:
        """Answer which models the endpoint offers."""
        self.model_calls.append(query)
        return list(self.models)

    def check_model_available(self, query: Any) -> bool:
        """Answer whether the model is one of them, and refuse by name when it is not."""
        self.model_calls.append(query)
        if query.model not in self.models:
            raise typed_failure(
                "MODEL_UNAVAILABLE",
                f"{query.provider} does not offer the model {query.model!r}",
                recoverable=False,
                metadata={"provider": query.provider, "model": query.model},
            )
        return True

    def get_context_window(self, query: Any) -> int | None:
        """Answer the model's context window, or ``None`` when it states none."""
        self.model_calls.append(query)
        return self.context_window

    def get_model_info(self, query: Any) -> dict[str, Any]:
        """Answer what the endpoint knows about the model."""
        self.model_calls.append(query)
        return {
            "provider": query.provider,
            "model": query.model,
            "version": self.model_version,
        }

    # -- scripting -----------------------------------------------------------------------------

    def _answer(self, call: Any) -> Mapping[str, Any]:
        """Return the next scripted answer, in the provider's own shape."""
        self.calls.append(call)
        if self.raises is not None:
            raise self.raises
        if self.answers:
            scripted = self.answers.pop(0)
            if isinstance(scripted, Exception):
                raise scripted
            if callable(scripted):
                scripted = scripted(call)
            if isinstance(scripted, Mapping):
                return dict(scripted)
            if isinstance(scripted, str):
                return self.body_for(call, scripted)
        return self.body_for(call, DEFAULT_CONTENT)

    def body_for(self, call: Any, content: str) -> dict[str, Any]:
        """Return ``content`` in the response shape of the provider ``call`` names.

        Args:
            call: The call the provider was asked for.
            content: The answer text.

        Returns:
            Ollama's chat body or the OpenAI-compatible one, whichever the provider speaks. The
            two carry their usage figures under different names, which is exactly the difference
            the seam's translators exist to absorb.
        """
        if getattr(call, "provider", "ollama") == "ollama":
            return {
                "model": call.model,
                "message": {"role": "assistant", "content": content},
                "done_reason": "stop",
                "prompt_eval_count": 12,
                "eval_count": 4,
                "load_duration": 100_000_000,
                "eval_duration": 400_000_000,
                "total_duration": 500_000_000,
            }
        return {
            "model": call.model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 4,
                "total_tokens": 16,
            },
        }


def invalid_json(answer: str = "not json at all") -> str:
    """Return a scripted answer that is not JSON, for the retry path."""
    return answer
