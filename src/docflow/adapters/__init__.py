"""Adapters — the thin implementations behind the five ports.

Each adapter imports a port and never the reverse, so the dependency arrow only
ever points down (`ADR-004`). Nothing here is imported except by the composition
root.
"""
