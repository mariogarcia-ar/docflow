# Python Architecture & Coding Standards

## 1. Absolute English Policy (Strict Rule)
- **CRITICAL:** ALL outputs, responses, code, explanations, and text MUST be strictly in English. 
- Even if the user communicates, asks questions, or provides context in Spanish (or any other language), you MUST understand the input but reply and generate content **100% in English**.

## 2. Language & Vocabulary in Code
- **All code identifiers** (variables, functions, classes, methods, constants, modules) MUST be written in English.
- **All documentation** (docstrings, inline comments, logging messages, exception text) MUST be written in English.

## 3. Naming Conventions (PEP 8)
Follow strict PEP 8 naming conventions using English terminology:
- **Functions, methods, and variables:** Use `snake_case` (e.g., `calculate_total_price`, `is_active`).
- **Classes:** Use `PascalCase` (e.g., `UserManager`, `DatabaseConnection`).
- **Constants:** Use `UPPER_CASE` with underscores (e.g., `MAX_RETRY_ATTEMPTS`, `API_VERSION`).

## 4. Pythonic Best Practices
- **Type Hinting:** Always include explicit type hints for function arguments and return values (e.g., `def get_user(user_id: int) -> User:`).
- **Docstrings:** Write comprehensive docstrings in English using **Google Style** format.

## 5. Software Lifecycle Rules (PoC -> MVP -> Release)
The project evolves through three clear stages, prioritizing flow completion in the current phase:

- **PoC (Proof of Concept) [CURRENT MODE - KEY: CLOSE THE FLOWS]:**
  - **Primary Objective:** Validate technical feasibility by closing end-to-end user journeys and data flows as fast as possible (*Happy Path* focus).
  - **Execution over Perfection:** Prioritize a working end-to-end integration over exhaustive edge-case handling.
  - **Pragmatic Shortcuts:** Use hardcoded configurations, in-memory storage, or mocked external services if it accelerates closing the functional loop. Do not over-engineer architecture.

- **MVP (Minimum Viable Product) [NEXT STAGE]:**
  - Transition from simulated loops to basic production reality.
  - Leave explicit `# TODO: [MVP]` comments where proper validation, real databases, actual API endpoints, and robust error handling must replace PoC shortcuts.

- **Release (Production Ready) [FINAL STAGE]:**
  - Scalability and bulletproof reliability.
  - Leave explicit `# TODO: [RELEASE]` comments for telemetry, caching layers, high-availability setups, and strict security compliance.

## 6. PoC Development Workflow
When the user requests a new feature or flow in PoC mode, you MUST structure and present your solution following this strict order:
1. **Skeleton & Flow Declaration:** Provide the high-level architecture first. Define empty functions, methods, or classes with proper type hints, using `pass` or mock return types to sketch out the entire data pipeline.
2. **Technical Debt Marking:** Insert clear `# TODO: [MVP]` or `# TODO: [RELEASE]` tags inside the skeleton to explicitly document missing features, infrastructure debt, or shortcuts.
3. **Happy Path Testing:** Provide a minimal, high-level `pytest` implementation immediately after the skeleton. This test should only validate that data successfully moves end-to-end through the proposed pipeline. Do not test edge cases yet.
4. **Flow Resolution:** Implement the minimum required Python logic to connect the pipeline, ensure the code runs, and make the happy path test pass successfully.
