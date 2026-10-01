"""What is true of Alder & Finch rather than of packs in general.

A service practice: fees charged on account, no inventory and no cost of sales. Three special
journals instead of four, so a purchase of supplies on account has no special journal to go in
and belongs in the General Journal, which is what the paper books tell the student.
"""

from __future__ import annotations

from decimal import Decimal as D

COMPANY = {
    "slug": "alderfinch",
    "name": "Alder & Finch Veterinary Clinic",
    "accent_hex": "#2F6F4E",
    "monogram": "AF",
    "course_tags": ["ACCT1010"],
    "scope_tags": ["service business", "special journals", "subsidiary ledgers"],
}

PERIOD = {"start": "2026-12-01", "end": "2026-12-07", "fiscal_year_end": "2026-12-31"}

STATEMENT_SECTIONS = ["current_assets", "non_current_assets", "current_liabilities",
                      "non_current_liabilities", "equity", "sales_revenue",
                      "operating_expenses"]

# The clinic has no 155/156; its only fixed asset is clinic equipment and its accumulated
# depreciation.
NON_CURRENT = {"150", "151"}
# Notes Payable, confirmed non-current in the clinic's own chart.
NON_CURRENT_LIABILITIES = {"220"}
ROLES = {"302": ["retained_earnings"], "399": ["income_summary"],
         "105": ["ar_control"], "201": ["ap_control"]}
SUBSIDIARY = {"105": "customer", "201": "supplier"}

# What a document is for, in cents: cash where cash moves, otherwise the receivable or the
# payable. The clinic happens to use the same three numbers as Riverbend, which is exactly why
# leaving them as literals in the translator would go unnoticed until a company that does not.
FACE_ACCOUNTS = {"cash": "101", "receivable": "105", "payable": "201"}

# The clinic's LATE_VENDORS is empty; it trades with nobody extra.
EXTRA_PARTIES = []

# The clinic has nothing to shorten; its one extra item code (MED) takes the model's own words
# as they are.
ITEM_DESCRIPTIONS = {}

# The clinic has no Purchases Journal, so a purchase on account goes where the paper books send
# it: "Use the General Journal only when no special journal fits."
JOURNAL_OF = {"Fees": "fees", "Purchases": "general", "Cash receipts": "cash_receipts",
              "Cash payments": "cash_payments", "General": "general"}


def _journals() -> list[dict]:
    """Three special journals plus the general journal, with the columns the transactions
    actually use.

    Each special journal carries an "Other accounts" column (``account: null``), which is how a
    real special journal handles the entries that do not fit its named columns; without it V8
    would refuse the rent cheque and the payroll.
    """
    def col(key, label, side, account, posts="total", subsidiary=None):
        c = {"key": key, "label": label, "side": side, "posts": posts}
        if account is not None:
            c["account"] = account
        if subsidiary:
            c["subsidiary_kind"] = subsidiary
        return c

    return [
        {"key": "fees", "name": "Fees Journal", "ref_prefix": "F", "kind": "special",
         "columns": [
             col("ar_dr", "Accounts Receivable Dr", "debit", "105", subsidiary="customer"),
             col("fees_cr", "Fees Earned Cr", "credit", "401")]},
        {"key": "cash_receipts", "name": "Cash Receipts Journal", "ref_prefix": "CR",
         "kind": "special", "columns": [
             col("cash_dr", "Cash Dr", "debit", "101"),
             col("disc_dr", "Fee Discounts Dr", "debit", "403"),
             col("ar_cr", "Accounts Receivable Cr", "credit", "105", subsidiary="customer"),
             col("fees_cr", "Fees Earned Cr", "credit", "401"),
             col("other_cr", "Other accounts Cr", "credit", None, posts="individual")]},
        {"key": "cash_payments", "name": "Cash Payments Journal", "ref_prefix": "CP",
         "kind": "special", "columns": [
             col("ap_dr", "Accounts Payable Dr", "debit", "201", subsidiary="supplier"),
             col("other_dr", "Other accounts Dr", "debit", None, posts="individual"),
             col("cash_cr", "Cash Cr", "credit", "101"),
             col("other_cr", "Other accounts Cr", "credit", None, posts="individual")]},
        # No "columns" key at all, exactly as Riverbend's general journal is written.
        {"key": "general", "name": "General Journal", "ref_prefix": "J", "kind": "general"},
    ]


JOURNALS = _journals()

# Documents that arrive and need nothing done with them. Dated inside 1-7 December, the clinic's
# own period, not Riverbend's 15 December. The second is deliberately close to transaction 9,
# where Harborview Kennels *does* pay in advance for boarding and that deposit is a real entry: a
# student who records the enquiry has not distinguished a booking from an enquiry, which is the
# judgement the triage marks are for.
NO_ENTRY_DOCUMENTS = [
    {
        "ref": "N01", "display_ref": "Quotation CV-Q-0118", "date": "2026-12-07",
        "fields": [["From", "Cedarline Veterinary Supply"], ["Quotation", "CV-Q-0118"],
                   ["Valid until", "31 January"], ["Terms", "n/30"],
                   ["Description", "Price held for a digital dental radiography unit, "
                                   "no order placed"],
                   ["Amount", "6,400.00"]],
        "lines": [["1", "Digital dental radiography unit", "6,400.00", "6,400.00"]],
    },
    {
        "ref": "N02", "display_ref": "Boarding enquiry BK-2209", "date": "2026-12-07",
        "fields": [["From", "Harborview Kennels"], ["Reference", "BK-2209"],
                   ["Dates enquired", "12 to 19 February"],
                   ["Description", "Asks whether twelve runs can be held for the dates below"],
                   ["Amount", "—"]],
        "lines": [],
    },
]

# The paper set's own checkpoint answers table. Checkpoint 3 is deliberately not the Accounts
# Payable control: the clinic's A/P closes at 6,040.00 in all three versions, so it could be
# copied between students without being worked. Unearned Boarding Revenue differs in every
# version and is the distinction the set is built to teach: money taken for work not yet done is
# not a fee.
# What the first two guided documents tell the student: which journal, and why, never which
# accounts. The clinic has no sales; the paper books' own words are "Every line here is a fee
# charged on account."
GUIDANCE = {
    1: "A payment by cheque belongs in the journal built for cash going out.",
    2: "Fees charged on account are recorded in the journal built for them.",
}

CHECKPOINTS = [
    {"key": "cp1", "ordinal": 1, "stage": "posted",
     "prompt": "Accounts Receivable control balance at 7 December",
     "measure": {"account": "105"}},
    {"key": "cp2", "ordinal": 2, "stage": "posted",
     "prompt": "Cash balance at 7 December", "measure": {"account": "101"}},
    {"key": "cp3", "ordinal": 3, "stage": "posted",
     "prompt": "Unearned Boarding Revenue balance at 7 December",
     "measure": {"account": "215"}},
]

RUBRIC = [
    {"key": "triage", "points": 10},
    {"key": "journal_selection", "points": 20},
    {"key": "entry_accuracy", "points": 40},
    {"key": "posting_completeness", "points": 20},
    {"key": "subsidiary_agreement", "points": 10},
]


def _payroll_page(model) -> dict:
    """The clinic's only reference page. It holds no inventory, so Riverbend's 'Inventory and
    costs' page has no counterpart here — printing one would describe a business this is not."""
    pr = model.PR
    return {
        "key": "payroll",
        "title": "Payroll",
        "blocks": [
            {"type": "p", "text": "Staff are paid weekly. The employer owes the same FICA as the "
                                  "employee, which is a separate entry from the wages."},
            {"type": "table",
             "rows": [[PAYROLL_LABELS[511], f"{pr['sales_sal']:,.2f}"],
                      [PAYROLL_LABELS[512], f"{pr['office_sal']:,.2f}"],
                      ["FICA rate", f"{pr['fica_rate'] * 100:.2f}%"],
                      ["Federal withholding", f"{pr['fed_wh']:,.2f}"],
                      ["State withholding", f"{pr['st_wh']:,.2f}"]]},
        ],
    }


REFERENCE_PAGES = [{"key": "payroll", "title": "Payroll", "builder": _payroll_page}]

# One statement of what the documents call each payroll salary account, read by both the stub
# (extra_fields) and the reference page, so there is one name rather than three. The chart calls
# 511 "Veterinary Salaries Expense"; this packet once called it "Clinical salaries" on the
# reference page and "Sales salaries" on the document a student actually reads, in a practice
# with no sales staff. check() below refuses a label the chart does not contain.
PAYROLL_LABELS = {511: "Veterinary salaries", 512: "Office salaries"}

# Transaction numbers extra_fields special-cases, kept apart from the literal ifs so check() can
# confirm they still exist: 7 for the reception tape's till furniture, 13 and 15 for the weekly
# payroll and the employer's own FICA.
_SPECIAL_TRANSACTIONS = {7, 13, 15}


def extra_fields(txn, model, money, cents, *, stage):
    """Document detail only this company's documents carry.

    These are the clinic's own figures and its own document furniture, read from the practice
    set's model rather than typed in. Called twice per document, because the two kinds of detail
    sit on opposite sides of the free-text description in the paper document itself: the
    reception tape's till number is part of what identifies the document (``stage="furniture"``),
    read before the description; the payroll breakdown explains the description's figure
    (``stage="detail"``), read after it.
    """
    if stage == "furniture":
        if txn["doc"] == "Reception tape":
            register, _sep, clerk = model.COMPANY["register"].partition(" &nbsp; CLERK ")
            return [["Register", register], ["Clerk", clerk]]
        return []

    # stage == "detail": the breakdowns a stub carries because the face amount alone cannot be
    # journalised.
    fields = []
    pay = model.PR
    gross = pay["sales_sal"] + pay["office_sal"]
    fica = float(model.money(D(str(gross)) * pay["fica_rate"]))
    if txn["no"] == 13:
        fields += [["Gross pay", money(cents(gross))],
                   [PAYROLL_LABELS[511], money(cents(pay["sales_sal"]))],
                   [PAYROLL_LABELS[512], money(cents(pay["office_sal"]))],
                   ["FICA withheld", money(cents(fica))],
                   ["Federal income tax withheld", money(cents(pay["fed_wh"]))],
                   ["State income tax withheld", money(cents(pay["st_wh"]))]]
    if txn["no"] == 15:
        fields.append(["Employer FICA", money(cents(fica))])
    return fields


_LABEL_SUFFIXES = (" Expense", " Dr", " Cr")


def _bare(text: str) -> str:
    """A column or payroll label with its trailing Dr/Cr/Expense qualifier removed, lower-cased.

    The chart never carries that qualifier, so comparing the bare words is what tells a label
    that genuinely names its account from a vague one ("Salaries") that would satisfy more than
    one account by pure substring containment.
    """
    for suffix in _LABEL_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip().lower()
    return text.strip().lower()


# The translator guides these two sequence numbers (``documents()`` in build_pack.py) and no
# others; defined once here so the two checks below do not each repeat the literal.
GUIDED_SEQUENCES = {1, 2}


def check(model):
    """Special-cased transaction numbers, journal column accounts, checkpoint accounts, payroll
    labels and guidance coverage — everything this profile asserts about itself before it is
    trusted."""
    numbers = {t["no"] for t in model.build(sorted(model.VARIANTS)[0])}
    missing = _SPECIAL_TRANSACTIONS - numbers
    if missing:
        raise SystemExit(f"{COMPANY['slug']}: no transaction numbered {sorted(missing)}.")

    # Every journal column that names an account must point at an account the chart actually
    # has, and its label must not contradict the chart's own name for it.
    for journal in JOURNALS:
        for column in journal.get("columns", []):
            account = column.get("account")
            if account is None:
                continue
            number = int(account)
            if number not in model.ACCT_NAME:
                raise SystemExit(
                    f"{COMPANY['slug']}: {journal['key']} column {column['key']!r} names "
                    f"account {account}, which is not in the chart. Nothing was written."
                )
            chart = model.ACCT_NAME[number]
            if _bare(column["label"]) != _bare(chart):
                raise SystemExit(
                    f"{COMPANY['slug']}: {journal['key']} column {column['key']!r} is labelled "
                    f"{column['label']!r}, which does not match the chart's {chart!r} for "
                    f"account {account}. Nothing was written."
                )

    # Every checkpoint must measure an account the chart actually has.
    for cp in CHECKPOINTS:
        account = cp["measure"]["account"]
        if int(account) not in model.ACCT_NAME:
            raise SystemExit(
                f"{COMPANY['slug']}: checkpoint {cp['key']} measures account {account}, which "
                f"is not in the chart. Nothing was written."
            )

    # One account, one name. The packet once called 511 "Veterinary Salaries Expense" in the
    # chart, "Clinical salaries" on the reference page and "Sales salaries" on the document a
    # student reads. Nothing could see it: every figure was right.
    for number, label in PAYROLL_LABELS.items():
        chart = model.ACCT_NAME[number]
        if _bare(label) != _bare(chart):
            raise SystemExit(
                f"{COMPANY['slug']}: the payroll document calls account {number} {label!r}, "
                f"but the chart calls it {chart!r}. Nothing was written."
            )

    # Every sequence number the translator guides must have words in GUIDANCE (an empty string
    # counts as missing, which is why this tests truthiness rather than key presence), and
    # GUIDANCE must hold nothing for a sequence that is never guided. A guided document with no
    # guidance passed silently until this, the hole this round's own guidance fix opened.
    missing = {seq for seq in GUIDED_SEQUENCES if not GUIDANCE.get(seq)}
    if missing:
        raise SystemExit(
            f"{COMPANY['slug']}: document {sorted(missing)} is guided but GUIDANCE says nothing "
            f"for it. A guided document with no guidance is worse than an unguided one. "
            f"Nothing was written."
        )
    stray = set(GUIDANCE) - GUIDED_SEQUENCES
    if stray:
        raise SystemExit(
            f"{COMPANY['slug']}: GUIDANCE has text for document {sorted(stray)}, which is never "
            f"guided, so nobody would read it. Nothing was written."
        )
