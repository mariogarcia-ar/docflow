"""docflow — a modular document-processing pipeline.

The library uses a ``src/`` layout whose import name is ``docflow``: the package lives at
``src/docflow/`` and is always imported as ``docflow.…``, never ``src.docflow``.

Five sub-packages exist. Four are processors — ``pdf``, ``image``, ``ocr`` and ``llm`` —
and each exposes exactly one ``Request → Processor → Result`` contract. The fifth,
``workflow``, is the orchestrator and is the only component that composes them.

Conventions fixed here and honoured by every contract module:

* A processor is importable alone; no processor imports another processor.
* Inputs (``*Request``, ``*Options``, ``*Context``, ``*Input``) and leaf value records
  (``*Metrics``, ``*Error``, ``*Ref``) are frozen dataclasses, so a request cannot be
  mutated after it is built.
* Results and durable state (``*Result``, the orchestrator's ``DocumentContext`` and
  ``PageContext``) are mutable dataclasses, because they are assembled across a run.
* Every required field is required: no contract field carries a default, and no empty
  value is ever substituted for a missing answer.

Phase 0 ships the skeleton only: contracts, the stage-state vocabulary, the three
identities and the tooling. Entry points exist as typed signatures whose bodies raise.
"""
