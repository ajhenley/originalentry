"""One function per rubric component (T8.2). Each takes the student's work, the pack, the key and
the points the pack gives it, and returns a :class:`ComponentResult` with its evidence.

A pack's rubric decides which components run and what each is worth; the engine decides nothing
about weights (Part I §1, no rubric editing in the app).
"""

from .books import posting_completeness, subsidiary_agreement
from .cycle import adjustment_amounts, adjustment_form, closing
from .documents import entry_accuracy, journal_selection, triage
from .statements import statements_figures, statements_structure

COMPONENTS = {
    "triage": triage,
    "journal_selection": journal_selection,
    "entry_accuracy": entry_accuracy,
    "posting_completeness": posting_completeness,
    "subsidiary_agreement": subsidiary_agreement,
    "adjustment_form": adjustment_form,
    "adjustment_amounts": adjustment_amounts,
    "statements_structure": statements_structure,
    "statements_figures": statements_figures,
    "closing": closing,
}

__all__ = ["COMPONENTS"]
