# Python Standards (PoC mode)

## Language
- Output, code, and docs: 100% English, regardless of input language (understand Spanish, respond in English).
- Identifiers, docstrings, comments, logs, exceptions: English, PEP8 naming.

## Code Quality
- Ruff + Pylint clean. Sorted imports (stdlib → third-party → local). No unused imports.
- Type hints on all function signatures. Google-style docstrings. No redundant comments.
- DRY: no copy-paste logic blocks.

## Current Stage: PoC — close flows fast
- Happy path only. Hardcode/mock/in-memory OK if it closes the loop faster.
- No abstractions, no generic wrappers, no deep nesting (low McCabe complexity).
- If a stdlib/SDK call closes it in 5 lines, don't wrap it in a class.
- Mark all shortcuts inline: `# TODO: [MVP]` (real DB/API/validation) or `# TODO: [RELEASE]` (telemetry/caching/HA/security). These tags are the *expected* way to defer complexity — not a violation of the no-abstraction rule above.

## Workflow for new features (in order)
1. Skeleton: typed function/class signatures, `pass`/mock returns — full pipeline shape first.
2. Tag debt: `# TODO: [MVP|RELEASE]` on every shortcut in the skeleton.
3. One `pytest` happy-path test proving data flows end-to-end (no edge cases).
4. Implement minimum logic to pass that test, Ruff/Pylint clean.