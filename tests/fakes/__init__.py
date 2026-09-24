"""Test infrastructure: in-memory doubles and the rules that keep them honest.

Nothing under ``src/docflow/`` may import anything from here (`README.md` §9.7): a double
that production code can reach has stopped being a double and become a fallback.
"""
