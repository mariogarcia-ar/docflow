# Python Architecture & Coding Standards

## 1. Language & Vocabulary
- **All code identifiers** (variables, functions, classes, methods, constants, modules) MUST be written in English.
- **All documentation** (docstrings, inline comments, logging messages, exception text) MUST be written in English.
- If the user prompts or provides context in Spanish, translate the logic and intent, but output Python code exclusively in English.

## 2. Naming Conventions (PEP 8)
Follow strict PEP 8 naming conventions using English terminology:
- **Functions, methods, and variables:** Use `snake_case` (e.g., `calculate_total_price`, `is_active`).
- **Classes:** Use `PascalCase` (e.g., `UserManager`, `DatabaseConnection`).
- **Constants:** Use `UPPER_CASE` with underscores (e.g., `MAX_RETRY_ATTEMPTS`, `API_VERSION`).
- **Modules and packages:** Use short, lowercase names (e.g., `auth`, `payment_gateway`).

## 3. Pythonic Best Practices
- **Type Hinting:** Always include explicit type hints for function arguments and return values (e.g., `def get_user(user_id: int) -> User:`).
- **Docstrings:** Write comprehensive docstrings in English for all public modules, classes, and functions using **Google Style** format.
- **Clean Code:** Prioritize readability, use descriptive English verbs for function names (e.g., `fetch_data`, `validate_email` instead of `data`, `email`).
