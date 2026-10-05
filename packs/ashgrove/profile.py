"""What is true of Ashgrove Millwork rather than of packs in general.

The catalogue's first manufacturer, and a sole proprietorship. Cost moves through three inventory
accounts where a merchandiser has one -- raw materials, work in process, finished goods -- and two
clearing accounts, factory overhead and factory wages, so the direct/indirect/period decision is a
journal entry the student makes rather than something the chart decides for them. Equity is a
capital account and a drawing account where the other sets have common stock and dividends.

The translator is machinery and knows no company; everything here is this one's shape. The paper
set it reads is authored in ``../practicesets/companies/ashgrove.py`` and nowhere else.

Scope. This pack covers the recording cycle to the unadjusted trial balance, as the paper set does.
It keeps three subsidiary ledgers where the merchandisers keep two: customers, suppliers, and a
cost sheet for every job on the floor, subsidiary to Work in Process. Each requisition, time ticket
and overhead charge names its job, so the student posts it to that sheet exactly as a sale is posted
to a customer, and the Work in Process control is proved against the open sheets -- the fourth
checkpoint, and the one trap (a job transferred at its selling price) that nothing in the general
ledger reveals. The cost of goods manufactured schedule the sheets feed is the next piece of work,
not this one; this pack stops at the trial balance.
"""

from __future__ import annotations

# Shop equipment and the delivery truck, each with its accumulated depreciation.
NON_CURRENT = {"150", "151", "155", "156"}
# Notes Payable, confirmed non-current in the shop's own chart.
NON_CURRENT_LIABILITIES = {"220"}

# A proprietorship has no retained earnings; the owner's capital is the permanent equity account
# the engine closes the nominal accounts into, so it carries the role a corporation gives to
# retained earnings (A21: the engine finds accounts by role, never by number). 302 is the drawing
# account, the proprietorship's answer to dividends, and holds no role of its own.
ROLES = {"301": ["retained_earnings"], "399": ["income_summary"],
         "105": ["ar_control"], "201": ["ap_control"]}
# Three subsidiary ledgers. Work in Process is the manufacturer's own: its control equals the sum
# of the open job cost sheets, and every line that moves it names the job it belongs to.
SUBSIDIARY = {"105": "customer", "201": "supplier", "112": "job"}

# What a document is for, in cents: cash where cash moves, otherwise the receivable or the payable.
# "returns" (Sales Returns and Allowances, 402) is for the credit memo CM-204, whose own lines move
# no cash, no receivable debit and no payable credit. Read only on the per-transaction path, which
# this pack does not take -- its text comes from the printed artefact's own html -- but declared and
# checked so the three numbers are this company's rather than a translator literal.
FACE_ACCOUNTS = {"cash": "101", "receivable": "105", "payable": "201", "returns": "402"}

# Draycott Office Supply first appears during the month (the showroom's office supplies, invoice
# DO-1180), so the paper set keeps it in LATE_VENDORS rather than VENDORS and it has no opening
# balance. Declared here so its one invoice has a party in the suppliers ledger to post to.
EXTRA_PARTIES = [{"code": "V-206", "kind": "supplier", "name": "Draycott Office Supply"}]

# Nothing to shorten: the printed envelope is this pack's source of document text, so the model's
# own item words are never re-typed here. Kept for the translator's signature.
ITEM_DESCRIPTIONS = {}

# The paper set's five cycles, and the journal each becomes here. A manufacturer's distinguishing
# entries -- requisitions, the wage distribution, the overhead charge, a job transferred into
# finished goods -- are occasional, so they go to the General Journal rather than a sixth special
# journal that would imply a volume this shop does not have.
JOURNAL_OF = {"Sales": "sales", "Purchases": "purchases", "Cash receipts": "cash_receipts",
              "Cash payments": "cash_payments", "General": "general"}


def _journals() -> list[dict]:
    """Five journals with the columns the transactions actually use.

    Each special journal carries an "Other accounts" column (``account: null``), which is how a real
    special journal handles the entries that do not fit its named columns; without it V8 would refuse
    the rent cheque, the payroll, the showroom's office supplies and the purchase-discount cheque.
    """
    def col(key, label, side, account, posts="total", subsidiary=None):
        c = {"key": key, "label": label, "side": side, "posts": posts}
        if account is not None:
            c["account"] = account
        if subsidiary:
            c["subsidiary_kind"] = subsidiary
        return c

    return [
        # A sale is invoiced at its contract price and, in the same entry, the finished job's own
        # accumulated cost leaves finished goods for cost of goods sold.
        {"key": "sales", "name": "Sales Journal", "ref_prefix": "S", "kind": "special",
         "columns": [
             col("ar_dr", "Accounts Receivable Dr", "debit", "105", subsidiary="customer"),
             col("sales_cr", "Cabinetry Sales Cr", "credit", "401"),
             col("cogs_dr", "Cost of Goods Sold Dr", "debit", "501"),
             col("fg_cr", "Finished Goods Inventory Cr", "credit", "113")]},
        # Lumber, panel, hardware and finish are raw materials; the showroom's office supplies are
        # not, and fall to the Other column.
        {"key": "purchases", "name": "Purchases Journal", "ref_prefix": "P", "kind": "special",
         "columns": [
             col("raw_dr", "Raw Materials Inventory Dr", "debit", "111"),
             col("other_dr", "Other accounts Dr", "debit", None, posts="individual"),
             col("ap_cr", "Accounts Payable Cr", "credit", "201", subsidiary="supplier")]},
        {"key": "cash_receipts", "name": "Cash Receipts Journal", "ref_prefix": "CR",
         "kind": "special", "columns": [
             col("cash_dr", "Cash Dr", "debit", "101"),
             col("disc_dr", "Sales Discounts Dr", "debit", "403"),
             col("ar_cr", "Accounts Receivable Cr", "credit", "105", subsidiary="customer"),
             col("sales_cr", "Cabinetry Sales Cr", "credit", "401"),
             col("other_cr", "Other accounts Cr", "credit", None, posts="individual")]},
        # A purchase discount taken reduces the cost of the materials (a credit to Raw Materials),
        # so that credit needs the Other column; it is not income.
        {"key": "cash_payments", "name": "Cash Payments Journal", "ref_prefix": "CP",
         "kind": "special", "columns": [
             col("ap_dr", "Accounts Payable Dr", "debit", "201", subsidiary="supplier"),
             col("other_dr", "Other accounts Dr", "debit", None, posts="individual"),
             col("cash_cr", "Cash Cr", "credit", "101"),
             col("other_cr", "Other accounts Cr", "credit", None, posts="individual")]},
        {"key": "general", "name": "General Journal", "ref_prefix": "J", "kind": "general"},
    ]


JOURNALS = _journals()


# Why each filed document needs no entry, authored by kind: the envelope files many documents of a
# handful of kinds, so one sentence per kind and a mechanism (build_pack expands kind to ref) beat a
# string per document. V17 still requires one reason per filed document. None of these says "no
# accounting entry": that phrase is the triage answer on the face of the question, and deciding it is
# the first thing the set marks.
FILED_REASONS = {
    "purchase_order": "Our own order to a supplier. It commits to a purchase but records nothing of "
                      "its own; the vendor's invoice is what is recorded when the goods arrive, and "
                      "the receiving report is checked against it.",
    "receiving_report": "What the shop counted on arrival. It is the check against the vendor's "
                        "invoice, not an entry of its own.",
    "void_cheque": "Spoiled and voided before use. No money moved; it is kept so the cheque "
                   "sequence can be accounted for.",
    "time_card": "A record of a family member's hours for the fortnight. The hours reach the books "
                 "through the payroll entry and the distribution, not card by card.",
    "estimate": "A quotation for work the customer has not authorised. Nothing has been ordered "
                "against it and no production order has been raised.",
    "lease_schedule": "The landlord's apportionment of one monthly rent between the workshop and the "
                      "showroom. It is read so the single cheque can be split, and records nothing "
                      "of its own.",
    "production_order": "An internal release of a job to the shop. It opens a cost sheet; the costs "
                        "reach the books through the requisitions, time tickets and overhead charged "
                        "against that job.",
    "delivery_note": "A supplier's note of quantities delivered. It carries no prices: the goods are "
                     "invoiced on their own document, which is where the purchase is recorded.",
    "statement_of_account": "A supplier's monthly summary, sent for information. Each line repeats a "
                            "document already received and entered under its own cover.",
}

COMPANY = {
    "slug": "ashgrove",
    "name": "Ashgrove Millwork",
    "accent_hex": "#6F4A24",
    "monogram": "AM",
    "course_tags": ["ACCT1010"],
    "scope_tags": ["manufacturing", "job costing", "special journals", "subsidiary ledgers"],
}

PERIOD = {"start": "2026-12-01", "end": "2026-12-18", "fiscal_year_end": "2026-12-31"}

STATEMENT_SECTIONS = ["current_assets", "non_current_assets", "current_liabilities",
                      "non_current_liabilities", "equity", "sales_revenue",
                      "operating_expenses"]

# What the first two guided documents tell the student: which journal, and why, never which
# accounts. Keyed by the manifest's own refs. D01 is the rent cheque; D02-2 is the first vendor
# invoice (transaction 2 prints an order, an invoice and a receiving report, and the invoice is the
# one that takes the entry).
GUIDANCE = {
    "D01": "A payment by cheque belongs in the journal built for cash going out.",
    "D02-2": "A purchase of materials on account belongs in the journal built for purchases.",
}

# The translator guides these two refs and no others. An independent literal, deliberately, so the
# check below can catch GUIDANCE and it disagreeing rather than deriving one from the other.
GUIDED_SEQUENCES = {"D01", "D02-2"}

# The paper set's own four checkpoints: cash, the two controls, and the Work in Process balance.
# The fourth is this case's own. On paper it is proved against the open job cost sheets; here it is
# the account balance, which is as far as a pack with two subsidiary ledgers can take it.
CHECKPOINTS = [
    {"key": "cp1", "ordinal": 1, "stage": "posted",
     "prompt": "Accounts Receivable control balance at 18 December",
     "measure": {"account": "105"}},
    {"key": "cp2", "ordinal": 2, "stage": "posted",
     "prompt": "Cash balance at 18 December", "measure": {"account": "101"}},
    {"key": "cp3", "ordinal": 3, "stage": "posted",
     "prompt": "Accounts Payable control balance at 18 December",
     "measure": {"account": "201"}},
    {"key": "cp4", "ordinal": 4, "stage": "posted",
     "prompt": "Work in Process balance at 18 December",
     "measure": {"account": "112"}},
]

RUBRIC = [
    {"key": "triage", "points": 10},
    {"key": "journal_selection", "points": 20},
    {"key": "entry_accuracy", "points": 40},
    {"key": "posting_completeness", "points": 20},
    {"key": "subsidiary_agreement", "points": 10},
]


def _payroll_page(model) -> dict:
    """The payroll rules a student needs and no document states on its own."""
    return {
        "key": "payroll",
        "title": "Payroll",
        "blocks": [
            {"type": "ul", "items": [
                f"FICA is withheld at {float(model.PR['fica_rate']) * 100:.2f} per cent of gross "
                "pay, and the shop owes the same amount again as its own expense.",
                "Amounts withheld from the two employees are liabilities until they are remitted; "
                "the shop's own share is Payroll Tax Expense. Keeping those apart is the single most "
                "common payroll error.",
                "Shop time booked to a numbered job is direct labour and goes to that job. Shop time "
                "spent sweeping, moving stock, sharpening and setting machines is indirect and "
                "belongs to factory overhead. The showroom and office wage is neither: it is an "
                "expense of the period.",
                "The proprietor is not on the payroll. A sole proprietor is not an employee of their "
                "own business, so the owner keeps no time card, the owner's labour never reaches a "
                "job, and money the owner takes out is a withdrawal of capital, not a wage.",
                "The payroll covers 1 to 15 December. The shop works on to the eighteenth, and those "
                "three days are not paid until the end of the month, so no wages for 16, 17 and 18 "
                "December appear in these books, which is as it should be for a trial balance taken "
                "before the adjusting entries.",
            ]},
        ],
    }


def _costs_page(model) -> dict:
    """How cost moves, which the documents show one leg at a time but never state as a whole."""
    return {
        "key": "costs",
        "title": "How cost moves",
        "blocks": [
            {"type": "p", "text":
             "Ashgrove makes what it sells, so cost is built up job by job before any of it becomes "
             "an expense. Lumber, panel, hardware and finish are bought into Raw Materials. As a job "
             "needs them they are requisitioned out of Raw Materials and into Work in Process; the "
             "hours booked to the job and its share of factory overhead go into Work in Process too. "
             "When the job is finished it moves, at what it accumulated, into Finished Goods. Only "
             "when it is delivered and invoiced does that cost leave Finished Goods for Cost of "
             "Goods Sold."},
            {"type": "p", "text":
             "Every kitchen and every stair rail has a number, a production order and a cost sheet. "
             "The requisitions and time tickets in the envelope say which job each one belongs to, "
             "and the cost sheets together must always equal the Work in Process account. The shop "
             "closed for the last week of November and finished everything on the bench first, so "
             "Work in Process opens at nil: nothing on 18 December was carried in from last month."},
            {"type": "p", "text":
             "Overhead is actual, not a rate set in advance. The fortnight's factory overhead is "
             "charged to the jobs in proportion to the direct labour on each one's cost sheet, so "
             "that the Factory Overhead account empties. Factory Wages is a clearing account for the "
             "same reason: the week's shop wages go in, and the entry that splits them between the "
             "jobs, the shop and the showroom takes them out again."},
        ],
    }


REFERENCE_PAGES = [
    {"key": "payroll", "title": "Payroll", "builder": _payroll_page},
    {"key": "costs", "title": "How cost moves", "builder": _costs_page},
]


_LABEL_SUFFIXES = (" Expense", " Dr", " Cr")


def _bare(text: str) -> str:
    """A column label with its trailing Dr/Cr/Expense qualifier removed, lower-cased.

    The chart never carries that qualifier, so comparing the bare words is what tells a label that
    genuinely names its account from a vague one that would satisfy more than one account by pure
    substring containment.
    """
    for suffix in _LABEL_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)].strip().lower()
    return text.strip().lower()


def check(model, manifest=None):
    """Journal column accounts, checkpoint accounts, FACE_ACCOUNTS and guidance coverage --
    everything this profile asserts about itself before it is trusted.

    ``manifest`` is the envelope's own inventory, which build_pack.py passes because this pack takes
    its document list from what was printed. GUIDANCE is keyed by the manifest's own refs, so the two
    guidance constants agreeing with each other proves only that they agree; only the manifest can
    say a guided ref is a ref the envelope actually contains.
    """
    # FACE_ACCOUNTS entries must name an account the chart actually has -- "returns" included, since
    # a typo there would make the per-transaction path's returns check silently never fire.
    for role, account in FACE_ACCOUNTS.items():
        if int(account) not in model.ACCT_NAME:
            raise SystemExit(
                f"{COMPANY['slug']}: FACE_ACCOUNTS[{role!r}] names account {account}, which is not "
                f"in the chart. Nothing was written."
            )

    # Every journal column that names an account must point at an account the chart actually has,
    # and its label must not contradict the chart's own name for it.
    for journal in JOURNALS:
        for column in journal.get("columns", []):
            account = column.get("account")
            if account is None:
                continue
            number = int(account)
            if number not in model.ACCT_NAME:
                raise SystemExit(
                    f"{COMPANY['slug']}: {journal['key']} column {column['key']!r} names account "
                    f"{account}, which is not in the chart. Nothing was written."
                )
            chart = model.ACCT_NAME[number]
            if _bare(column["label"]) != _bare(chart):
                raise SystemExit(
                    f"{COMPANY['slug']}: {journal['key']} column {column['key']!r} is labelled "
                    f"{column['label']!r}, which does not match the chart's {chart!r} for account "
                    f"{account}. Nothing was written."
                )

    # Every checkpoint must measure an account the chart actually has.
    for cp in CHECKPOINTS:
        account = cp["measure"]["account"]
        if int(account) not in model.ACCT_NAME:
            raise SystemExit(
                f"{COMPANY['slug']}: checkpoint {cp['key']} measures account {account}, which is not "
                f"in the chart. Nothing was written."
            )

    # Every guided ref must have words in GUIDANCE (an empty string counts as missing), and GUIDANCE
    # must hold nothing for a ref that is never guided.
    missing = {ref for ref in GUIDED_SEQUENCES if not GUIDANCE.get(ref)}
    if missing:
        raise SystemExit(
            f"{COMPANY['slug']}: document {sorted(missing)} is guided but GUIDANCE says nothing for "
            f"it. A guided document with no guidance is worse than an unguided one. Nothing was "
            f"written."
        )
    stray = set(GUIDANCE) - GUIDED_SEQUENCES
    if stray:
        raise SystemExit(
            f"{COMPANY['slug']}: GUIDANCE has text for document {sorted(stray)}, which is never "
            f"guided, so nobody would read it. Nothing was written."
        )

    # Every guided ref must be a document the envelope actually contains.
    if manifest is not None:
        manifest_refs = {entry["ref"] for entry in manifest}
        unprinted = set(GUIDED_SEQUENCES) - manifest_refs
        if unprinted:
            raise SystemExit(
                f"{COMPANY['slug']}: GUIDANCE guides {sorted(unprinted)}, which the envelope's "
                f"manifest does not contain. Nothing was written."
            )
