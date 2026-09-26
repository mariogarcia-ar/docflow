# pylint: disable=too-many-lines
# Reason: this module is the engine-independent half of the processor — what a prompt is, what its
# key is, what the provider answered, how two answers compare, and how long a prompt may be. Its
# functions share one vocabulary and one another's inputs (the rendered prompt is what the key
# hashes; the parsed answer is what the comparison reads), so splitting it would separate a rule
# from the value it applies to and let the two drift. The Google-style docstring this project
# requires on every function is a third of the file's length.
"""Engine-independent composition of the LLM processor: prompts, keys, parsing, comparison.

Nothing here reaches a provider. Everything in this module is a pure function of its arguments
except :func:`file_digest` and :func:`input_hashes`, which read the bytes of the inputs to hash
them — reading a file is not reaching an engine.

Four rules shape the module, and each one exists because the opposite behaviour is a silent
stand-in:

* **a placeholder is never resolved to nothing.** ``<doc>``, ``<extra>`` and ``<schema>`` are
  resolved from the request; a template that asks for a document the request does not carry is a
  typed ``DEPENDENCY_ERROR``, never an empty string sent to a model;
* **the rendered prompt is the one that is hashed.** :func:`calculate_request_key` takes the
  rendered text, so two runs that would send different prompts can never share a key;
* **identity is absent from the key.** ``run_id``, ``graph_id``, ``node_id`` and ``attempt_id``
  are deliberately not parameters of :func:`calculate_request_key`, so a restart reproduces the
  key and reuse can fire;
* **no aggregate score.** :func:`compare_outputs` reports agreement per field and never collapses
  it into one number, because a single number cannot say *which* field disagreed.

# TODO: [MVP] richer template features (conditionals, loops, partials) and a real comparison
# policy are deferred; the placeholder set and the per-field comparison are what the happy path
# and the chain need.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from docflow.llm.contracts import (
    ComparisonResult,
    LLMError,
    LLMGraphState,
    LLMInput,
    LLMNodeResult,
    LLMValidationState,
    Timing,
    Usage,
)
from docflow.llm.primitives.errors import is_retryable, typed_failure

#: The inference chain the subplan §3 fixes, in execution order. It is the *documented* chain and
#: not a hardcoded workflow: :func:`build_inference_plan` reads the shape from the request's
#: descriptor and this tuple is what the compiled-in default descriptor is built from.
INFERENCE_CHAIN: Final[tuple[str, ...]] = (
    "classify",
    "extract_a",
    "extract_b",
    "compare",
    "validate",
    "consolidate",
)

#: What each chain node consumes. A descriptor whose nodes do not respect these edges is
#: rejected by :func:`build_inference_plan` rather than executed in an order that cannot work.
CHAIN_DEPENDENCIES: Final[dict[str, tuple[str, ...]]] = {
    "classify": (),
    "extract_a": ("classify",),
    "extract_b": ("classify",),
    "compare": ("extract_a", "extract_b"),
    "validate": ("compare",),
    "consolidate": ("validate",),
}

#: The descriptor keys and node keys this processor models. Anything else is refused by name
#: rather than ignored: a caller asking for a conditional edge would otherwise get a graph that
#: silently ran every node, which is a different graph from the one that was declared.
SUPPORTED_GRAPH_KEYS: Final[frozenset[str]] = frozenset(
    {"graph_id", "graph_version", "nodes"}
)
SUPPORTED_NODE_KEYS: Final[frozenset[str]] = frozenset(
    {"node_id", "depends_on", "task", "template", "schema"}
)

#: The three placeholders a template may carry. Anything else between angle brackets is the
#: template's own text and is left alone.
DOCUMENT_PLACEHOLDER: Final[str] = "<doc>"
EXTRA_PLACEHOLDER: Final[str] = "<extra>"
SCHEMA_PLACEHOLDER: Final[str] = "<schema>"

#: The metadata keys this processor reads. ``LLMInput`` carries no output directory, no asset
#: root and no run identity, and none of the three may be guessed: the caller states them in
#: ``metadata`` or the run reports that the dependency does not resolve. A guess would be exactly
#: the silent stand-in this project forbids.
OUTPUT_DIR_KEY: Final[str] = "output_dir"
ASSETS_DIR_KEY: Final[str] = "assets_dir"
RUN_ID_KEY: Final[str] = "run_id"
MODEL_VERSION_KEY: Final[str] = "model_version"

#: The sub-directories of the asset root, as the subplan §6 names the fixtures: prompts under
#: ``template/`` and schemas under ``schema/``.
TEMPLATE_SUBDIR: Final[str] = "template"
SCHEMA_SUBDIR: Final[str] = "schema"

#: The option keys this processor reads out of the free-form ``options`` mapping.
API_KEY_OPTION: Final[str] = "api_key"
TIMEOUT_OPTION: Final[str] = "timeout"
MAX_ATTEMPTS_OPTION: Final[str] = "max_attempts"
CONTEXT_WINDOW_OPTION: Final[str] = "context_window"
MAX_PROMPT_TOKENS_OPTION: Final[str] = "max_prompt_tokens"

#: One retry by default: the smallest policy that makes the retry path reachable at all. It is a
#: policy, not an answer — it is recorded in ``normalized_options`` and therefore participates in
#: the request key, and a caller that wants a different policy states it in ``options``.
DEFAULT_MAX_ATTEMPTS: Final[int] = 2

#: Documented request timeout, in seconds, for a provider that is not told otherwise. A local
#: daemon and a hosted API both answer far inside it, and the value is recorded in metadata so it
#: is never a hidden decision.
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0

#: Characters per token for the estimate of :func:`count_tokens`. This is an *estimate*, and the
#: processor says so everywhere it reports it.
#:
#: # TODO: [MVP] a provider tokenizer replaces the estimate; no tokenizer is installed in Phase 1,
#: and guessing a real count would be worse than stating an approximate one.
CHARS_PER_TOKEN: Final[int] = 4

#: One answer that is wrapped in a fenced code block, unwrapped before parsing.
_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(?P<body>.*)\n```\s*$", re.DOTALL)


@dataclass(frozen=True)
class RenderedPrompt:
    """The exact text a provider call would send, and what was measured about it.

    Attributes:
        text: The rendered prompt, byte-identical across runs over the same inputs.
        tokens: The estimated token count of :attr:`text`.
        estimated: Whether :attr:`tokens` is an estimate. Phase 1 has no tokenizer, so it is
            ``True`` and every report of the count says so.
        truncated: Whether :attr:`text` was shortened to fit ``options["max_prompt_tokens"]``.
            Truncation is never silent: it is recorded here and in the run's metadata.
    """

    text: str
    tokens: int
    estimated: bool
    truncated: bool


@dataclass(frozen=True)
class InferenceNode:
    """One node of the inference plan, as the descriptor declared it.

    Attributes:
        node_id: The node's identifier, unique inside its graph.
        depends_on: The nodes whose results this one consumes; all of them precede it.
        task: The task this node performs.
        template: The template identifier to render for this node.
        schema: The schema identifier to validate this node's response against, or ``None``.
    """

    node_id: str
    depends_on: tuple[str, ...]
    task: str
    template: str
    schema: str | None


@dataclass(frozen=True)
class InferencePlan:
    """The compiled form of the request's graph descriptor.

    Attributes:
        graph_id: The graph's identity, as the descriptor declares it.
        graph_version: The descriptor's version, recorded in the graph state.
        nodes: The nodes in execution order — the declared order, with every dependency already
            executed when its consumer runs.
    """

    graph_id: str
    graph_version: str
    nodes: tuple[InferenceNode, ...]

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Return the plan's node identifiers, in execution order."""
        return tuple(node.node_id for node in self.nodes)


def assets_dir_for(request: LLMInput) -> Path:
    """Return the asset root the request's template and schema resolve against.

    Args:
        request: The inference request.

    Returns:
        The directory named by ``metadata["assets_dir"]``.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when the request names no asset root. There
            is no default directory: a template identifier that silently resolved against the
            working directory would make the same request mean different things in two places.
    """
    return _required_directory(request, ASSETS_DIR_KEY, "asset root")


def output_dir_for(request: LLMInput) -> Path | None:
    """Return the ``llm/`` namespace this run persists into, or ``None`` when none was asked for.

    Args:
        request: The inference request.

    Returns:
        The directory named by ``metadata["output_dir"]``, or ``None`` when the caller did not ask
        the run to persist anything. A run that persists nothing is a run that writes nothing —
        not a run that writes to a guessed location.
    """
    stated = request.metadata.get(OUTPUT_DIR_KEY)
    return None if stated is None else Path(stated)


def pinned_run_id(request: LLMInput) -> str | None:
    """Return the run identity the caller pinned, or ``None`` when it pinned none.

    A pinned identity is what makes a run resumable: the second call has to name the same run for
    the persisted state to be the state of *this* run.
    """
    stated = request.metadata.get(RUN_ID_KEY)
    return stated if isinstance(stated, str) and stated.strip() else None


def stated_model_version(request: LLMInput) -> str | None:
    """Return the model version the caller stated, or ``None``.

    It is the fallback source of ``model_version`` when the provider cannot be asked (subplan §9
    decision 5).
    """
    stated = request.metadata.get(MODEL_VERSION_KEY)
    return stated if isinstance(stated, str) and stated.strip() else None


def stated_context_window(request: LLMInput) -> int | None:
    """Return the model's context window when the caller states one, else ``None``."""
    stated = request.options.get(CONTEXT_WINDOW_OPTION)
    if isinstance(stated, int) and not isinstance(stated, bool) and stated > 0:
        return stated
    return None


def _required_directory(request: LLMInput, key: str, description: str) -> Path:
    """Return the directory ``metadata[key]`` names, or fail saying which one is missing."""
    stated = request.metadata.get(key)
    if stated is None or not str(stated).strip():
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"the request names no {description}",
            recoverable=False,
            metadata={"metadata_key": key},
        )
    return Path(stated)


def canonical_json(value: Any) -> str:
    """Return ``value`` as canonical JSON: sorted keys, no insignificant whitespace.

    Canonical because a key computed from it must not depend on the order a caller happened to
    build a mapping in, and because two equivalent spellings of one configuration have to hash
    the same.

    Args:
        value: Any JSON-representable value.

    Returns:
        The canonical text.

    Raises:
        LLMPrimitiveError: With ``INTERNAL_ERROR`` when the value cannot be represented — a
            request this processor cannot describe is not one it can key.
    """
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except (TypeError, ValueError) as unrepresentable:
        raise typed_failure(
            "INTERNAL_ERROR",
            "a value of this request cannot be serialized canonically",
            metadata={"json_error": str(unrepresentable)},
        ) from unrepresentable


def sanitize_text(text: str) -> str:
    """Return ``text`` in the one spelling every input is normalized to.

    Two normalizations, both of them lossless in meaning and both needed for a prompt to be
    reproducible across platforms: line endings collapse to ``\\n``, and NUL bytes — which a
    provider would reject and a hash would treat as content — are removed.

    Args:
        text: The raw text.

    Returns:
        The normalized text.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")


def build_messages(prompt: str) -> list[dict[str, str]]:
    """Return the chat messages one call sends.

    One user message carrying the rendered prompt: the template *is* the instruction, and a
    separate system turn would be a second place for the same instruction to live.

    Args:
        prompt: The rendered prompt.

    Returns:
        The messages, in order.
    """
    return [{"role": "user", "content": prompt}]


def resolve_generator(*, structured: bool, multimodal: bool) -> str:
    """Return the name of the provider primitive this call resolves to.

    The resolution is stated rather than inferred at the call site: a schema means the answer has
    to be a structure, images mean the model has to receive them, and a call that is neither is
    plain text. A structured *multimodal* call is not modelled in Phase 1 — the schema wins, and
    ``generate_structured`` receives the images.

    Args:
        structured: Whether the request names a schema.
        multimodal: Whether the request carries images.

    Returns:
        One of ``"generate_structured"``, ``"generate_multimodal"`` or ``"generate_text"``.
    """
    if structured:
        return "generate_structured"
    return "generate_multimodal" if multimodal else "generate_text"


def file_digest(path: Path) -> str:
    """Return the SHA-256 of a file, read in bounded chunks.

    Args:
        path: The file to hash.

    Returns:
        Its digest, in hexadecimal.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when the file cannot be read — an input the
            request names but the run cannot open is a dependency that does not resolve.
    """
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError as unreadable:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"{path} could not be read to be hashed",
            recoverable=False,
            metadata={"input": str(path), "os_error": str(unreadable)},
        ) from unreadable
    return digest.hexdigest()


def input_hashes(document: str | None, images: Sequence[Path]) -> dict[str, Any]:
    """Return the hashes of everything the prompt or the payload carries as input.

    The document is hashed as its sanitized text and each image as its bytes, in order. A
    missing document is ``None`` — *absent* and *empty* are different inputs and must not hash
    the same.

    Args:
        document: The document text, or ``None``.
        images: The image paths, in the order they are sent.

    Returns:
        ``{"document": <digest or None>, "images": [<digest>, …]}``.
    """
    return {
        "document": None if document is None else _sha256_text(sanitize_text(document)),
        "images": [file_digest(path) for path in images],
    }


def _sha256_text(text: str) -> str:
    """Return the SHA-256 of ``text``, encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def process_template(
    template: str,
    *,
    document: str | None,
    extra_context: Mapping[str, Any],
    schema: Mapping[str, Any] | None,
) -> str:
    """Resolve every placeholder a template carries.

    Args:
        template: The template text, verbatim from the asset.
        document: The document text, or ``None`` when the request carries none.
        extra_context: Additional values the template may reference.
        schema: The loaded schema, or ``None`` when the request names none.

    Returns:
        The template with ``<doc>``, ``<extra>`` and ``<schema>`` resolved. A placeholder the
        template does not carry is not an error: a template that needs no document simply has no
        ``<doc>``.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when the template asks for an input the
            request does not carry. Substituting an empty string would send a model a prompt that
            reads as if the document were empty, which is a different question.
    """
    resolved = template
    if DOCUMENT_PLACEHOLDER in resolved:
        if document is None:
            raise typed_failure(
                "DEPENDENCY_ERROR",
                "the template asks for a document and the request carries none",
                recoverable=False,
                metadata={"placeholder": DOCUMENT_PLACEHOLDER},
            )
        resolved = resolved.replace(DOCUMENT_PLACEHOLDER, sanitize_text(document))
    if EXTRA_PLACEHOLDER in resolved:
        resolved = resolved.replace(
            EXTRA_PLACEHOLDER, canonical_json(dict(extra_context))
        )
    if SCHEMA_PLACEHOLDER in resolved:
        if schema is None:
            raise typed_failure(
                "DEPENDENCY_ERROR",
                "the template asks for a schema and the request names none",
                recoverable=False,
                metadata={"placeholder": SCHEMA_PLACEHOLDER},
            )
        resolved = resolved.replace(SCHEMA_PLACEHOLDER, canonical_json(dict(schema)))
    return resolved


def count_tokens(text: str) -> int:
    """Estimate the number of tokens ``text`` costs.

    The estimate is a stated approximation, not a measurement: Phase 1 has no tokenizer, and a
    fabricated exact count would be worse than an approximate one that is labelled as such.

    Args:
        text: The text to measure.

    Returns:
        ``ceil(len(text) / CHARS_PER_TOKEN)``, from the sanitized text.
    """
    return math.ceil(len(sanitize_text(text)) / CHARS_PER_TOKEN)


def truncate_to_token_limit(text: str, limit: int) -> str:
    """Return the longest prefix of ``text`` that fits ``limit`` estimated tokens.

    Only ever applied when a caller asks for a limit: the processor never shortens a prompt on
    its own, because a quietly truncated prompt is a quietly wrong answer.

    Args:
        text: The text to shorten.
        limit: The ceiling, in estimated tokens.

    Returns:
        The prefix, cut at a character boundary derived from :data:`CHARS_PER_TOKEN`. A limit of
        zero or less leaves nothing, which is the honest answer to "fit nothing".
    """
    if limit >= count_tokens(text):
        return text
    return text[: max(limit, 0) * CHARS_PER_TOKEN]


def is_context_limit_exceeded(prompt_tokens: int, context_window: int | None) -> bool:
    """Return whether a prompt is known to exceed the model's context window.

    Args:
        prompt_tokens: The prompt's estimated token count.
        context_window: The model's window, or ``None`` when neither the caller nor the provider
            states one.

    Returns:
        ``True`` only when a known window is exceeded. An unknown window reports ``False``: an
        unmeasured ceiling is not evidence of an overflow, and claiming one would refuse a call
        that would have worked.
    """
    if context_window is None:
        return False
    return prompt_tokens > context_window


def process_prompt(
    request: LLMInput,
    template: str,
    schema: Mapping[str, Any] | None,
) -> RenderedPrompt:
    """Render the request's prompt and measure it.

    Args:
        request: The inference request being prepared.
        template: The template text the request's ``template`` identifier resolved to.
        schema: The loaded schema, or ``None``.

    Returns:
        The rendered prompt. It is truncated only when the caller stated
        ``options["max_prompt_tokens"]``, and the truncation is recorded.
    """
    rendered = process_template(
        template,
        document=request.document,
        extra_context=request.extra_context,
        schema=schema,
    )
    limit = request.options.get(MAX_PROMPT_TOKENS_OPTION)
    if isinstance(limit, int) and not isinstance(limit, bool):
        truncated = truncate_to_token_limit(rendered, limit)
        return RenderedPrompt(
            text=truncated,
            tokens=count_tokens(truncated),
            estimated=True,
            truncated=truncated != rendered,
        )
    return RenderedPrompt(
        text=rendered, tokens=count_tokens(rendered), estimated=True, truncated=False
    )


def normalize_llm_options(options: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical form of the requested options.

    Two equivalent requests have to produce the same options — and therefore the same request key
    — so the mapping is copied into a plain dict and the *credential* is removed. A key is
    persisted in ``state.json`` and ``final_result.json``; an API key must never be in either, and
    two calls that differ only in the credential are the same logical request.

    Args:
        options: The raw options as requested.

    Returns:
        A new mapping with ``api_key`` absent. Key *order* is not fixed here — the key formula
        serializes canonically — and the credential is the only value deliberately dropped.
    """
    return {key: value for key, value in options.items() if key != API_KEY_OPTION}


def max_attempts(options: Mapping[str, Any]) -> int:
    """Return how many attempts a call may make, stated positively.

    Args:
        options: The request's options.

    Returns:
        ``options["max_attempts"]`` when it is a positive integer, and
        :data:`DEFAULT_MAX_ATTEMPTS` otherwise. The value is echoed into the run's metadata, so
        the policy in force is never a hidden one.
    """
    stated = options.get(MAX_ATTEMPTS_OPTION)
    if isinstance(stated, int) and not isinstance(stated, bool) and stated >= 1:
        return stated
    return DEFAULT_MAX_ATTEMPTS


def request_timeout(options: Mapping[str, Any]) -> float:
    """Return the per-call timeout, in seconds.

    Args:
        options: The request's options.

    Returns:
        ``options["timeout"]`` when it is a positive number, and :data:`DEFAULT_TIMEOUT_SECONDS`
        otherwise.
    """
    stated = options.get(TIMEOUT_OPTION)
    if isinstance(stated, (int, float)) and not isinstance(stated, bool) and stated > 0:
        return float(stated)
    return DEFAULT_TIMEOUT_SECONDS


def calculate_request_key(
    *,
    provider: str,
    model: str,
    model_version: str | None,
    rendered_prompt: str,
    hashes: Mapping[str, Any],
    schema_hash: str | None,
    options: Mapping[str, Any],
) -> str:
    """Return the identity of one logical inference request.

    ``hash(provider + model + model_version + rendered_prompt + input_hashes + schema_hash +
    normalized_options)``, exactly as the subplan §3 fixes it. ``run_id``, ``graph_id``,
    ``node_id`` and ``attempt_id`` are **not parameters of this function**, which is how the
    formula excludes them: a restart over the same inputs reproduces the key, and a retry keeps
    it.

    Args:
        provider: Provider name.
        model: Model name.
        model_version: The model's version, or ``None`` when no source states one.
        rendered_prompt: The exact prompt text the call would send.
        hashes: The hashed inputs, from :func:`input_hashes`.
        schema_hash: The digest of the loaded schema, or ``None`` when no schema is used.
        options: The normalized options.

    Returns:
        The request key, hexadecimal.
    """
    material = canonical_json(
        {
            "provider": provider,
            "model": model,
            "model_version": model_version,
            "rendered_prompt": rendered_prompt,
            "input_hashes": hashes,
            "schema_hash": schema_hash,
            "normalized_options": dict(options),
        }
    )
    return _sha256_text(material)


def schema_digest(schema: Mapping[str, Any] | None) -> str | None:
    """Return the digest of a loaded schema, or ``None`` when there is none.

    The digest of the schema's *content*: renaming an identical schema does not change the key,
    and editing it does.
    """
    if schema is None:
        return None
    return _sha256_text(canonical_json(dict(schema)))


def parse_json_response(raw: str) -> Any:
    """Parse a provider's answer as JSON, with one documented tolerance.

    Args:
        raw: The provider's answer text.

    Returns:
        The parsed value.

    Raises:
        LLMPrimitiveError: With ``INVALID_JSON`` when the text is not JSON. Models habitually wrap
            a JSON answer in a fenced code block, so a single fence around the whole answer is
            unwrapped first; anything else is reported as it is rather than guessed at.
    """
    text = raw.strip()
    fenced = _FENCE.match(text)
    if fenced:
        text = fenced.group("body").strip()
    try:
        return json.loads(text)
    except (TypeError, ValueError) as malformed:
        raise typed_failure(
            "INVALID_JSON",
            "the provider answered something that is not JSON",
            metadata={"json_error": str(malformed), "response": raw[:500]},
        ) from malformed


def attempt_validation_state(error: LLMError | None) -> LLMValidationState:
    """Return the verdict one attempt records.

    Args:
        error: The failure that ended the attempt, or ``None`` when it succeeded.

    Returns:
        ``VALID`` for a successful attempt, ``RETRYABLE`` for a failure a further attempt may fix
        and ``INVALID`` for one it may not. The verdict is derived from the typed kind through
        :data:`docflow.llm.primitives.errors.RETRYABLE_KINDS`, so the two can never disagree.
    """
    if error is None:
        return "VALID"
    return "RETRYABLE" if is_retryable(error) else "INVALID"


def should_retry(*, retryable: bool, attempt_index: int, attempt_limit: int) -> bool:
    """Return whether another attempt may be made.

    Args:
        retryable: Whether the failure's kind is retryable.
        attempt_index: The attempt that just finished, 1-based.
        attempt_limit: The most attempts the policy allows.

    Returns:
        ``True`` only when the failure is retryable *and* the policy has attempts left. A
        non-retryable failure never buys another call.
    """
    return retryable and attempt_index < attempt_limit


def increment_attempt(attempt_index: int) -> int:
    """Return the index of the attempt that follows ``attempt_index``."""
    return attempt_index + 1


def mint_attempt_id(node_id: str | None, attempt_index: int) -> str:
    """Return the identifier of one attempt.

    Deterministic on purpose: a retry must be able to name its attempt without the name changing
    the request key, and a resumed run must be able to reproduce it.

    Args:
        node_id: The node the attempt belongs to, or ``None`` for a single call.
        attempt_index: The attempt's 1-based index.

    Returns:
        ``"<node_id|call>-attempt-NNN"``.
    """
    return f"{node_id or 'call'}-attempt-{attempt_index:03d}"


def validate_cached_result(node_result: LLMNodeResult | None) -> bool:
    """Return whether a persisted node result is complete enough to stand in for a new call.

    Three questions, and a *no* to any of them means the node runs: was it a success, does it
    name the request it answered, and does it carry the result it claims? File existence is not
    one of the questions — a file on disk that carries none of this is not evidence.

    Args:
        node_result: The persisted result, or ``None`` when there is none.

    Returns:
        ``True`` only for a node result that is a success, names its request key, carries a
        parsed result and reported ``VALID``.
    """
    if node_result is None:
        return False
    if node_result.status != "SUCCESS":
        return False
    if not node_result.request_key or node_result.result is None:
        return False
    return node_result.validation.get("status") == "VALID"


def is_node_reusable(node_result: LLMNodeResult | None, request_key: str) -> bool:
    """Return whether ``node_result`` may stand in for a call under ``request_key``.

    The whole reuse rule, in the three lines the subplan §3 writes: the key matches, the status
    is ``SUCCESS`` and the persisted result is valid. Nothing else grants a reuse.

    Args:
        node_result: The persisted result, or ``None``.
        request_key: The key this run computed for the node.

    Returns:
        ``True`` when the node must not be called again.
    """
    return (
        validate_cached_result(node_result) and node_result.request_key == request_key
    )


def find_reusable_node_result(
    state: LLMGraphState, node_id: str, request_key: str
) -> LLMNodeResult | None:
    """Return the node's persisted result when it may be reused, else ``None``.

    Args:
        state: The chain state, loaded or freshly built.
        node_id: The node being resolved.
        request_key: The key this run computed for the node.

    Returns:
        The result to reuse, or ``None`` when the node has to run.
    """
    candidate = state.node_results.get(node_id)
    return candidate if is_node_reusable(candidate, request_key) else None


def attempt_validation_record(
    state: LLMValidationState, *, retryable: bool
) -> dict[str, Any]:
    """Return a node's validation record: its verdict, and whether a retry was allowed."""
    return {"status": state, "retryable": retryable}


def merge_usage(records: Iterable[Usage]) -> Usage:
    """Return the sum of several usage records.

    An unmeasured figure stays unmeasured: if no record reports a value, the sum is ``None`` and
    not ``0``, because ``0`` reads as "the provider measured zero tokens".

    Args:
        records: The usage records to add up.

    Returns:
        The accumulated usage, with the providers' own payloads merged.
    """
    records = list(records)
    provider_usage: dict[str, Any] = {}
    for record in records:
        provider_usage.update(record.provider_usage)
    costs = [r.estimated_cost for r in records if r.estimated_cost is not None]
    return Usage(
        input_tokens=_sum_measured(r.input_tokens for r in records),
        output_tokens=_sum_measured(r.output_tokens for r in records),
        total_tokens=_sum_measured(r.total_tokens for r in records),
        cached_tokens=_sum_measured(r.cached_tokens for r in records),
        provider_usage=provider_usage,
        estimated_cost=None if not costs else sum(costs),
    )


def _sum_measured(values: Iterable[int | None]) -> int | None:
    """Return the sum of the measured values, or ``None`` when none was measured."""
    measured = [value for value in values if value is not None]
    return sum(measured) if measured else None


def merge_timing(records: Iterable[Timing]) -> Timing:
    """Return the sum of several timing records.

    ``total_time`` is the sum of the totals, so it is a measurement even when it is zero — the
    three finer figures stay ``None`` when the provider reported none of them.

    Args:
        records: The timing records to add up.

    Returns:
        The accumulated durations.
    """
    ordered = list(records)

    def total_of(attribute: str) -> float | None:
        measured = [
            getattr(record, attribute)
            for record in ordered
            if getattr(record, attribute) is not None
        ]
        return None if not measured else sum(measured)

    return Timing(
        queue_time=total_of("queue_time"),
        load_time=total_of("load_time"),
        inference_time=total_of("inference_time"),
        total_time=sum(record.total_time for record in ordered),
    )


def compare_outputs(
    left: Any,
    right: Any,
    *,
    left_node: str,
    right_node: str,
) -> ComparisonResult:
    """Compare two node outputs field by field.

    Disagreement is reported as data, never resolved: this function says *which* fields differ
    and never picks a winner, and it never collapses the per-field evidence into one score.

    Args:
        left: The left output.
        right: The right output.
        left_node: The node that produced ``left``.
        right_node: The node that produced ``right``.

    Returns:
        The comparison: agreeing fields in ``matches``, disagreeing ones in ``conflicts`` as
        ``{"left": …, "right": …}``, and ``agreement`` as a per-field ``1.0`` / ``0.0``. A
        non-mapping output is compared as the single field ``value``.
    """
    left_fields = _as_fields(left)
    right_fields = _as_fields(right)
    matches: dict[str, Any] = {}
    conflicts: dict[str, Any] = {}
    agreement: dict[str, float] = {}

    for name in sorted(set(left_fields) | set(right_fields)):
        left_value = left_fields.get(name)
        right_value = right_fields.get(name)
        agrees = (
            name in left_fields and name in right_fields and left_value == right_value
        )
        if agrees:
            matches[name] = left_value
            agreement[name] = 1.0
        else:
            conflicts[name] = {"left": left_value, "right": right_value}
            agreement[name] = 0.0
    return ComparisonResult(
        matches=matches,
        conflicts=conflicts,
        agreement=agreement,
        metadata={
            "left_node": left_node,
            "right_node": right_node,
            "fields": len(agreement),
        },
    )


def _as_fields(output: Any) -> dict[str, Any]:
    """Return an output as a field mapping, wrapping a scalar under ``value``."""
    if isinstance(output, Mapping):
        return dict(output)
    return {"value": output}


def build_inference_plan(graph: Mapping[str, Any] | None) -> InferencePlan:
    """Compile the request's graph descriptor into an executable plan.

    The shape is read from the descriptor — no workflow is hardcoded — and the compiled plan is
    the declared node order, with every dependency checked to precede its consumer. The dynamic
    machinery of §9.6 (routing, parallel branches, per-node claims) is not modelled: a descriptor
    that needs it fails here, by name, instead of being executed in an order that cannot work.

    Args:
        graph: The descriptor — ``{"graph_id", "graph_version", "nodes": [...]}`` — or ``None``
            when the request is a single call.

    Returns:
        The plan.

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` when there is no descriptor, it declares no
            nodes, a node is unnamed or unnamed-template, a node identifier repeats, or a node
            depends on something that neither precedes it nor exists.
    """
    if graph is None:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            "a graph run was requested without a graph descriptor",
            recoverable=False,
            metadata={"missing": "graph.nodes"},
        )
    graph_id = _required_name(graph.get("graph_id"), "graph_id")
    graph_version = _required_name(graph.get("graph_version"), "graph_version")
    _refuse_unsupported_keys(
        graph, SUPPORTED_GRAPH_KEYS, what=f"the graph {graph_id!r}"
    )
    declared = graph.get("nodes")
    if not isinstance(declared, list) or not declared:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            "the graph descriptor declares no nodes",
            recoverable=False,
            metadata={"graph_id": graph_id},
        )

    nodes: list[InferenceNode] = []
    seen: set[str] = set()
    for entry in declared:
        node = _compile_node(entry, graph_id=graph_id, already_declared=seen)
        nodes.append(node)
        seen.add(node.node_id)
    return InferencePlan(
        graph_id=graph_id, graph_version=graph_version, nodes=tuple(nodes)
    )


def _required_name(value: Any, field: str) -> str:
    """Return ``value`` as a non-empty name, or fail by the field that is missing."""
    if not isinstance(value, str) or not value.strip():
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"the graph descriptor states no {field}",
            recoverable=False,
            metadata={"field": field},
        )
    return value


def _refuse_unsupported_keys(
    declared: Mapping[str, Any], supported: frozenset[str], *, what: str
) -> None:
    """Fail by name when a descriptor uses a key this processor does not model.

    Ignoring the key would run a graph the caller did not ask for — every node,
    unconditionally — and report it as the declared one. Refusing is the only honest answer
    while routing, parallel branches and per-node ``SKIP`` / ``FORCE`` / ``INVALIDATE`` are
    deferred (subplan §9.6).

    Raises:
        LLMPrimitiveError: With ``DEPENDENCY_ERROR`` naming the unsupported keys.
    """
    unsupported = sorted(set(declared) - supported)
    if unsupported:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"{what} uses keys this processor does not model",
            recoverable=False,
            metadata={"unsupported": unsupported, "supported": sorted(supported)},
        )


def _compile_node(
    entry: Any, *, graph_id: str, already_declared: set[str]
) -> InferenceNode:
    """Compile one declared node, checking its dependencies against what precedes it."""
    if not isinstance(entry, Mapping):
        raise typed_failure(
            "DEPENDENCY_ERROR",
            "a declared node is not a mapping",
            recoverable=False,
            metadata={"graph_id": graph_id, "node": repr(entry)[:200]},
        )
    node_id = _required_name(entry.get("node_id"), "node_id")
    if node_id in already_declared:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"the graph declares {node_id} twice",
            recoverable=False,
            metadata={"graph_id": graph_id, "node_id": node_id},
        )
    _refuse_unsupported_keys(entry, SUPPORTED_NODE_KEYS, what=f"the node {node_id!r}")
    declared_dependencies = entry.get("depends_on", [])
    if not isinstance(declared_dependencies, list):
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"{node_id} declares a depends_on that is not a list",
            recoverable=False,
            metadata={"graph_id": graph_id, "node_id": node_id},
        )
    unresolved = [
        dependency
        for dependency in declared_dependencies
        if dependency not in already_declared
    ]
    if unresolved:
        raise typed_failure(
            "DEPENDENCY_ERROR",
            f"{node_id} depends on nodes that do not precede it",
            recoverable=False,
            metadata={
                "graph_id": graph_id,
                "node_id": node_id,
                "unresolved": unresolved,
            },
        )
    return InferenceNode(
        node_id=node_id,
        depends_on=tuple(declared_dependencies),
        task=_required_name(entry.get("task", node_id), "task"),
        template=_required_name(entry.get("template"), "template"),
        schema=entry.get("schema"),
    )


def default_inference_graph() -> dict[str, Any]:
    """Return the descriptor for the chain the subplan §3 documents.

    It exists so a caller can state the documented chain without spelling out six nodes, and so
    the shape lives in one place. It is *data*: :func:`build_inference_plan` consumes it exactly
    as it consumes a descriptor the caller wrote.
    """
    return {
        "graph_id": "default_inference",
        "graph_version": "1",
        "nodes": [
            {
                "node_id": node_id,
                "task": node_id,
                "template": "simple_extract",
                "schema": "simple",
                "depends_on": list(CHAIN_DEPENDENCIES[node_id]),
            }
            for node_id in INFERENCE_CHAIN
        ],
    }
