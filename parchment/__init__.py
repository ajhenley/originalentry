"""Parchment — a browser-based accounting system simulation (Riverbend Ledger build).

Kept deliberately import-light: ``parchment.money``, ``parchment.messages`` and the pure
``parchment.ledger`` engine must import cleanly with no Flask and no database, so the engine
and its A2 tests run in milliseconds. ``create_app()`` is defined in ``parchment.app`` and
imported lazily by the web/CLI entry points, never at package import time.
"""

__version__ = "0.1.0"
