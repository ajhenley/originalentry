"""Original Entry — a browser-based accounting system simulation (Riverbend Ledger build).

Kept deliberately import-light: ``originalentry.money``, ``originalentry.messages`` and the pure
``originalentry.ledger`` engine must import cleanly with no Flask and no database, so the engine
and its A2 tests run in milliseconds. ``create_app()`` is defined in ``originalentry.app`` and
imported lazily by the web/CLI entry points, never at package import time.
"""

__version__ = "0.1.0"
