"""Marker that makes ``tests/fixtures`` a package, not a data folder.

The folder holds the committed fixtures; this marker exists so
``test_manifest.py`` can import the generator next to it by relative import
instead of by patching ``sys.path``. Both Python sources here are excluded from
the inventory by the generator's suffix rule, so a marker in this file does not
make the folder's contents ambiguous.
"""
