"""Building a student's work for the grading tests.

``perfect_work`` is the student who did everything the way the key does: every document handled
as the key has it, every entry journalised and posted, the adjustment recorded, the books closed,
and the income statement laid out from their own adjusted balances. Each test starts from that
and introduces exactly one mistake, so what a mistake costs is visible on its own.
"""

from originalentry.grading.models import StatementRow, StudentWork
from originalentry.packs import replay

# TestCo Alpha's income statement, built from the adjusted balances the replay produces.
MODEL_INCOME_STATEMENT = (
    StatementRow(kind="heading", label="Revenue"),
    StatementRow(kind="account", account_number="401", amount_cents=200000, indent=1),
    StatementRow(kind="heading", label="Expenses"),
    StatementRow(kind="account", account_number="611", amount_cents=25000, indent=1),
    StatementRow(kind="subtotal", subtotal_type="net_income", amount_cents=175000),
)


def perfect_work(pack, key, snapshot=None, dispositions=None, statements=None):
    snapshot = snapshot if snapshot is not None else replay.build_replay_snapshot(pack, key)
    if dispositions is None:
        dispositions = {
            ref: ("record" if requires_entry else "no_entry")
            for ref, requires_entry in key.triage.items()
        }
    if statements is None:
        statements = {"income_statement": MODEL_INCOME_STATEMENT}
    return StudentWork(snapshot=snapshot, dispositions=dispositions, statements=statements)


def statement_rows_from_own_balances(snapshot, pack, statement_type="income_statement"):
    """Lay a statement out from the student's **own** adjusted balances.

    This is what "handled properly on their own figures" looks like on a statement: every line
    carries the balance their ledger actually holds, whatever happened earlier.
    """
    from originalentry.ledger import balances

    definition = next(s for s in pack.statements if s.type == statement_type)
    own = balances(snapshot, "adjusted")
    rows = []
    net = 0
    for number in sorted(own, key=lambda n: snapshot.accounts[n].sort_order
                         if n in snapshot.accounts else 0):
        account = snapshot.accounts.get(number)
        if account is None or account.statement_section not in definition.allowed_sections:
            continue
        amount = own[number]
        if amount == 0:
            continue
        rows.append(StatementRow(kind="account", account_number=number,
                                 amount_cents=abs(amount), indent=1))
        net -= amount  # debit-positive in, profit out
    rows.append(StatementRow(kind="subtotal", subtotal_type="net_income", amount_cents=net))
    return tuple(rows)
