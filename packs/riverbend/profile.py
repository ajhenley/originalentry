"""What is true of Riverbend rather than of packs in general.

The translator is machinery and knows no company. Everything here is one company's shape: which
accounts are non-current, which cycle goes in which journal, what the checkpoints ask for, and
the documents that start no entry at all.

Moved out of the translator unchanged. tests/unit/test_pack_reproducible.py is what proves the
move altered nothing.
"""

from __future__ import annotations

from decimal import Decimal as D

NON_CURRENT = {"150", "151", "155", "156"}
NON_CURRENT_LIABILITIES = {"220"}
ROLES = {"302": ["retained_earnings"], "399": ["income_summary"],
         "105": ["ar_control"], "201": ["ap_control"]}
SUBSIDIARY = {"105": "customer", "201": "supplier"}

# What a document is for, in cents: cash where cash moves, otherwise the receivable or the
# payable. The clinic happens to use the same three numbers, which is exactly why leaving them
# as literals in the translator would go unnoticed until a company that does not.
FACE_ACCOUNTS = {"cash": "101", "receivable": "105", "payable": "201"}

# A vendor who first appears during the month, so Riverbend never meant it to live in
# generators/companies/riverbend.py's VENDORS. The clinic never traded with this supplier at
# all; left as a translator literal, it would show up in the clinic's subsidiary ledger with no
# history behind it. Defaults to [] for any company that has no such party.
EXTRA_PARTIES = [{"code": "V-206", "kind": "supplier", "name": "Kestrel Office Supply"}]

# These two disagree with the model, which calls them "Freight — prepaid and added (FOB
# shipping point)" and "Assorted office supplies — see packing list". The translator invented
# the short forms before it could read ITEM_DESC_EXTRA, and the pack built from them is in
# front of students. Kept so their documents do not change mid-set; remove when the pack is
# next revised and let the model's own words through.
ITEM_DESCRIPTIONS = {"FRT": "Freight", "OFF": "Office supplies"}

# The paper set's five cycles, and the journal each becomes here.
JOURNAL_OF = {"Sales": "sales", "Purchases": "purchases", "Cash receipts": "cash_receipts",
              "Cash payments": "cash_payments", "General": "general"}


def _journals() -> list[dict]:
    """Five journals with the columns the transactions actually use.

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
        {"key": "sales", "name": "Sales Journal", "ref_prefix": "S", "kind": "special",
         "columns": [
             col("ar_dr", "Accounts Receivable Dr", "debit", "105", subsidiary="customer"),
             col("sales_cr", "Sales Cr", "credit", "401"),
             col("cogs_dr", "Cost of Goods Sold Dr", "debit", "501"),
             col("inv_cr", "Merchandise Inventory Cr", "credit", "110")]},
        {"key": "purchases", "name": "Purchases Journal", "ref_prefix": "P", "kind": "special",
         "columns": [
             col("inv_dr", "Merchandise Inventory Dr", "debit", "110"),
             col("other_dr", "Other accounts Dr", "debit", None, posts="individual"),
             col("ap_cr", "Accounts Payable Cr", "credit", "201", subsidiary="supplier")]},
        {"key": "cash_receipts", "name": "Cash Receipts Journal", "ref_prefix": "CR",
         "kind": "special", "columns": [
             col("cash_dr", "Cash Dr", "debit", "101"),
             col("disc_dr", "Sales Discounts Dr", "debit", "403"),
             col("cogs_dr", "Cost of Goods Sold Dr", "debit", "501"),
             col("ar_cr", "Accounts Receivable Cr", "credit", "105", subsidiary="customer"),
             col("sales_cr", "Sales Cr", "credit", "401"),
             col("inv_cr", "Merchandise Inventory Cr", "credit", "110"),
             col("other_cr", "Other accounts Cr", "credit", None, posts="individual")]},
        {"key": "cash_payments", "name": "Cash Payments Journal", "ref_prefix": "CP",
         "kind": "special", "columns": [
             col("ap_dr", "Accounts Payable Dr", "debit", "201", subsidiary="supplier"),
             col("other_dr", "Other accounts Dr", "debit", None, posts="individual"),
             col("cash_cr", "Cash Cr", "credit", "101"),
             col("inv_cr", "Merchandise Inventory Cr", "credit", "110"),
             col("other_cr", "Other accounts Cr", "credit", None, posts="individual")]},
        {"key": "general", "name": "General Journal", "ref_prefix": "J", "kind": "general"},
    ]


JOURNALS = _journals()


# Documents that arrive and need nothing done with them. Triage is the first thing marked, and
# without these every document in the set would need an entry, which would make it no exercise
# at all. Taken from the paper set's own "documents requiring no entry".
NO_ENTRY_DOCUMENTS = [
    {
        "ref": "N01", "display_ref": "Purchase order RV-2210", "date": "2026-12-15",
        "fields": [["From", "Ridgeview Cycles"], ["Purchase order", "RV-2210"],
                   ["Required delivery", "18 January"], ["Terms", "2/10, n/30"],
                   ["Description", "Order for 6 mountain bikes, not to ship before 15 January"],
                   ["Amount", "3,840.00"]],
        "lines": [["6", "Cascade 29er mountain bike", "640.00", "3,840.00"]],
    },
    {
        "ref": "N02", "display_ref": "Request for quotation RFQ-0041", "date": "2026-12-15",
        "fields": [["From", "Halden & Coe Outfitters"], ["Reference", "RFQ-0041"],
                   ["Description",
                    "An enquiry about wholesale terms for 25 and 50 units. No order is placed "
                    "and no goods are requested."],
                   ["Amount", "None stated"]],
        "lines": [],
    },
    {
        "ref": "N03", "display_ref": "Price list from Ridgeline Tires", "date": "2026-12-15",
        "fields": [["From", "Ridgeline Tires"], ["Effective", "1 January"],
                   ["Description",
                    "Notice of wholesale prices changing from 1 January. No goods have been "
                    "ordered or shipped against this notice."],
                   ["Amount", "None stated"]],
        "lines": [["", "Commuter tire, pair", "32.00", "34.00 from 1 Jan"]],
    },
]

COMPANY = {
    "slug": "riverbend", "name": "Riverbend Bicycle Supply",
    "accent_hex": "#1F7A6E", "monogram": "RB",
    "course_tags": ["ACCT1010"],
    "scope_tags": ["merchandising", "special journals", "subsidiary ledgers"],
}

PERIOD = {"start": "2026-12-01", "end": "2026-12-15",
          "fiscal_year_end": "2026-12-31"}

STATEMENT_SECTIONS = ["current_assets", "non_current_assets", "current_liabilities",
                      "non_current_liabilities", "equity", "sales_revenue",
                      "operating_expenses"]

# The paper set's own checkpoint answers table: the two control accounts and cash.
# What the first two guided documents tell the student: which journal, and why, never which
# accounts. Kept word for word from the translator's own former literals, so the pack's text does
# not move.
GUIDANCE = {
    1: "A payment by cheque belongs in the journal built for cash going out.",
    2: "Sales on account are recorded in the journal built for them.",
}

CHECKPOINTS = [
    {"key": "cp1", "ordinal": 1, "stage": "posted",
     "prompt": "Accounts Receivable control balance at 15 December",
     "measure": {"account": "105"}},
    {"key": "cp2", "ordinal": 2, "stage": "posted",
     "prompt": "Cash balance at 15 December", "measure": {"account": "101"}},
    {"key": "cp3", "ordinal": 3, "stage": "posted",
     "prompt": "Accounts Payable control balance at 15 December",
     "measure": {"account": "201"}},
]

RUBRIC = [
    {"key": "triage", "points": 10},
    {"key": "journal_selection", "points": 20},
    {"key": "entry_accuracy", "points": 40},
    {"key": "posting_completeness", "points": 20},
    {"key": "subsidiary_agreement", "points": 10},
]


def _inventory_page(model) -> dict:
    """What the instruction booklet puts in front of the student and the documents cannot.

    Chiefly the cost of each item. A sales invoice shows what the customer pays; the cost of
    goods sold comes from the company's own records, and without it half the sales entries
    cannot be made at all. Costs do not vary by version, so this is pack-level: only S-01's
    selling price changes, and that is printed on the invoice.

    Riverbend keeps a perpetual inventory and sells stock. A company with no inventory — a
    service business — has nothing to put on this page, which is why it is Riverbend's own page
    rather than the translator's.
    """
    rows = [[sku, spec[0], f"{spec[1]:,.2f}", "Yes" if spec[4] else "—"]
            for sku, spec in model.SKUS.items()]
    return {
        "key": "inventory",
        "title": "Inventory and costs",
        "blocks": [
            {"type": "p", "text":
             "Riverbend keeps a perpetual inventory. Every sale records the revenue and, in the "
             "same entry, the cost of the goods that left. The selling price is on the invoice; "
             "the cost is here."},
            {"type": "table", "caption": "Cost and stock records",
             "headers": ["Item", "Description", "Our cost", "Stock card kept?"],
             "rows": rows},
            {"type": "p", "text":
             "A stock card is kept for the items marked above. Freight paid on goods bought FOB "
             "shipping point is part of what the inventory cost, not a separate expense."},
        ],
    }


def _payroll_page(model) -> dict:
    """The payroll rules a student needs and no document states on its own."""
    return {
        "key": "payroll",
        "title": "Payroll",
        "blocks": [
            {"type": "ul", "items": [
                f"FICA is withheld at {float(model.PR['fica_rate']) * 100:.2f} per cent of gross "
                "pay, and the company owes the same amount again as its own expense.",
                "Amounts withheld from employees are liabilities until they are remitted; the "
                "company's own share is Payroll Tax Expense. Keeping those apart is the single "
                "most common payroll error.",
                "No federal or state unemployment tax is due in December: every employee passed "
                "the wage base earlier in the year.",
            ]},
        ],
    }


REFERENCE_PAGES = [
    {"key": "inventory", "title": "Inventory and costs", "builder": _inventory_page},
    {"key": "payroll", "title": "Payroll", "builder": _payroll_page},
]

# Transaction numbers extra_fields special-cases, kept apart from the literal ifs so check() can
# confirm they still exist. Riverbend has 28 transactions; a company with fewer (the clinic has
# 15) would make every one of these branches dead, silently, with nothing reporting it.
_SPECIAL_TRANSACTIONS = {18, 24, 25, 26, 27}


def extra_fields(txn, model, money, cents, *, stage):
    """Document detail only this company's documents carry.

    These are Riverbend's figures and Riverbend's document furniture. They were literals in the
    translator, which is machinery shared with every other company; an invoice number belongs to
    the company that issued it.

    Called twice per document, because the two kinds of detail sit on opposite sides of the
    free-text description in the paper document itself: a register tape's till number is part of
    what identifies the document (``stage="furniture"``), read before the description; a payroll
    or discount breakdown explains the description's figure (``stage="detail"``), read after it.
    Splitting the call is what keeps the pack byte-identical to the one this replaced.
    """
    if stage == "furniture":
        if txn["doc"] == "Cash register tape":
            return [["Register", "1"], ["Clerk", "04"]]
        return []

    # stage == "detail": the breakdowns a stub carries because the face amount alone cannot be
    # journalised.
    fields = []
    pay = model.PR
    gross = pay["sales_sal"] + pay["office_sal"]
    fica = float(model.money(D(str(gross)) * pay["fica_rate"]))
    if txn["no"] == 24:
        fields += [["Gross pay", money(cents(gross))],
                   ["Sales salaries", money(cents(pay["sales_sal"]))],
                   ["Office salaries", money(cents(pay["office_sal"]))],
                   ["FICA withheld", money(cents(fica))],
                   ["Federal income tax withheld", money(cents(pay["fed_wh"]))],
                   ["State income tax withheld", money(cents(pay["st_wh"]))]]
    if txn["no"] == 25:
        fields.append(["Employer FICA", money(cents(fica))])
    if txn["no"] == 26:
        fields += [["FICA payable", money(cents(1430))],
                   ["Federal income tax payable", money(cents(2180))],
                   ["State income tax payable", money(cents(640))]]
    if txn["no"] == 18:
        fields += [["Invoice", "N-8841, 7,860.00"], ["Discount taken", "1%, 78.60"]]
    if txn["no"] == 27:
        fields += [["Delivery", money(cents(190))], ["Office supplies", money(cents(275))],
                   ["Advertising", money(cents(155))]]
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


def check(model):
    """A special-cased number that no longer exists must fail, not quietly do nothing."""
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
