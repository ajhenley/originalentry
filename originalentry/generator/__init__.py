"""The pack generator (T5).

Runs on the instructor's laptop, not on Heroku. It turns an authoring *source* — the chart, the
documents, and the answer (the expected entries and adjustments) — into the pack zip the app
imports: ``pack.json``, ``answer_keys/<variant>.json`` and ``documents/<variant>/<ref>.png``.

Its point is that the answers cannot disagree with the app. The author writes the transactions;
the generator **replays them through the same ledger engine the app uses** to compute the
expected balances and the checkpoint figures, then validates the whole pack against the same
schema and rules the upload screen runs (so V9 passes by construction). A pack that would be
refused on upload is refused here first, with every problem listed.

Image rendering needs Pillow (a laptop-only dependency, T16); the core — pack.json and the
answer keys — needs nothing beyond the app itself, and produces a valid *paper* pack on its own.
"""

from .build import GeneratedPack, GeneratorError, build
from .pack_zip import write_zip

__all__ = ["build", "GeneratedPack", "GeneratorError", "write_zip"]
