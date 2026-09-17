"""Pure dataclasses for the ledger engine (T6).

These are the engine's only view of the world. They carry no database identity semantics and
no Flask. ``ledger/snapshot.py`` (added with the ORM in phase 1) is the *only* place that turns
rows into these dataclasses; everything else in ``ledger/`` operates on them.

Sign convention: every ``*_cents`` amount is a non-negative integer. Balances derived by the
engine are **debit-positive** (D1): a positive balance means net debits, negative means net
credits. The display layer converts to Dr/Cr using ``Account.normal_balance``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Entry kinds.
REGULAR = "regular"
ADJUSTING = "adjusting"
CLOSING = "closing"

# Posting targets.
GENERAL = "general"
SUBSIDIARY = "subsidiary"

# Column posting modes.
TOTAL = "total"
INDIVIDUAL = "individual"


@dataclass(frozen=True)
class Account:
    number: str
    name: str
    account_type: str  # asset, liability, equity, revenue, contra_revenue, expense, ...
    normal_balance: str  # "debit" or "credit"
    statement_section: str | None = None
    roles: tuple[str, ...] = ()
    subsidiary_kind: str | None = None  # e.g. "customer"/"supplier" for a control account
    sort_order: int = 0


@dataclass(frozen=True)
class Party:
    code: str
    kind: str  # "customer", "supplier", ...
    name: str


@dataclass(frozen=True)
class JournalColumn:
    key: str
    label: str
    side: str  # "debit" or "credit"
    account_number: str | None  # fixed account, or None for an "Other accounts" column
    posts: str  # TOTAL or INDIVIDUAL
    subsidiary_kind: str | None = None


@dataclass(frozen=True)
class Journal:
    key: str
    name: str
    ref_prefix: str  # "S", "P", "J", ...
    kind: str  # "special" or "general"
    columns: tuple[JournalColumn, ...] = ()

    def column(self, key: str) -> JournalColumn | None:
        for c in self.columns:
            if c.key == key:
                return c
        return None


@dataclass(frozen=True)
class Line:
    line_no: int
    account_number: str
    debit_cents: int = 0
    credit_cents: int = 0
    column_key: str | None = None  # set for special-journal rows
    party_code: str | None = None
    memo: str | None = None

    @property
    def side(self) -> str:
        return "debit" if self.debit_cents else "credit"

    @property
    def amount_cents(self) -> int:
        return self.debit_cents or self.credit_cents


@dataclass(frozen=True)
class Entry:
    id: int
    journal_key: str
    entry_date: date
    kind: str  # REGULAR, ADJUSTING, CLOSING
    lines: tuple[Line, ...]
    document_ref: str | None = None
    description: str | None = None
    voided: bool = False
    seq: int = 0


@dataclass(frozen=True)
class Posting:
    """An *active* posting run: the entries that are currently posted to one target.

    The service layer resolves reversals and per-entry ``active`` flags before building this;
    the engine only ever sees live postings.
    """

    journal_key: str
    target: str  # GENERAL or SUBSIDIARY
    ordinal: int
    entry_ids: tuple[int, ...]


@dataclass
class Snapshot:
    """Everything the engine needs for one workspace, already scoped to its pack version."""

    accounts: dict[str, Account] = field(default_factory=dict)
    parties: dict[str, Party] = field(default_factory=dict)
    journals: dict[str, Journal] = field(default_factory=dict)
    opening_account_cents: dict[str, int] = field(default_factory=dict)  # debit-positive
    opening_party_cents: dict[str, int] = field(default_factory=dict)  # debit-positive
    entries: dict[int, Entry] = field(default_factory=dict)
    general_postings: tuple[Posting, ...] = ()
    subsidiary_postings: tuple[Posting, ...] = ()

    def account_by_role(self, role: str) -> Account | None:
        """Engine code finds accounts by role, never by number literal (A21)."""
        for acct in self.accounts.values():
            if role in acct.roles:
                return acct
        return None


@dataclass(frozen=True)
class LedgerLine:
    """One derived posting into a ledger account. Never stored (D6 rule 3)."""

    account_number: str
    date: date
    reference: str  # e.g. "S1", "J1"
    journal_key: str
    kind: str
    debit_cents: int = 0
    credit_cents: int = 0
    party_code: str | None = None
    source_entry_id: int | None = None  # None for a special-journal column total
