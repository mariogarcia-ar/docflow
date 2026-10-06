"""Test suite of ``docflow``.

The tree mirrors ``src/docflow/``: one package per sub-package, one test module per source
module. The packages are real Python packages so that two modules may share a file name —
``tests/pdf/test_contracts.py`` and ``tests/llm/test_contracts.py`` are distinct modules
testing distinct seams.
"""
