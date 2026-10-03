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
#
# "returns" (Sales Returns and Allowances, 402) is Riverbend's alone: the one document that needs
# it is the credit memo, CM-118, whose own lines move no cash, no receivable debit and no payable
# credit. Left unset, the clinic is unaffected — _face_amount treats a missing key as "this
# company has no such figure", not as an error.
FACE_ACCOUNTS = {"cash": "101", "receivable": "105", "payable": "201", "returns": "402"}

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


# Why each filed document needs no entry, authored by kind: the envelope files 34 documents and
# they are nine kinds, so nine sentences and a mechanism beat thirty-four strings. V17 still
# requires one reason per document; scripts/build_pack.py expands kind to ref.
FILED_REASONS = {
    # These two used to say nothing had happened *yet* -- shipped, invoiced, arrived, owed -- as
    # though the reason were timing. It is not: ten of the sixteen customer_po/purchase_order
    # documents have an entered invoice sibling already in the envelope, so that clause was false
    # on most of its own members. What is actually true of every member of each kind, invoiced
    # sibling or not, is that the order itself is never what gets journalised (I-2).
    "customer_po": "The customer's own order. It is the request, not the sale, and records "
                   "nothing of its own; the invoice issued against it is what is recorded.",
    "purchase_order": "Our own order to a supplier. It commits to a purchase but records "
                      "nothing of its own; the vendor's invoice is what is recorded when the "
                      "goods arrive.",
    "bill_of_lading": "The carrier's receipt for goods leaving the warehouse. It evidences the "
                      "shipment behind an invoice, and the invoice is what is recorded.",
    "receiving_report": "What the warehouse counted on arrival. It is the check against the "
                        "vendor's invoice, not an entry of its own.",
    "time_card": "Supporting record for the payroll cheque. The hours reach the books once, "
                 "through the payroll entry, not card by card.",
    "petty_cash_voucher": "A disbursement from the petty cash fund. Nothing is journalised until "
                          "the fund is replenished.",
    "void_cheque": "Spoiled and voided before use. No money moved; it is kept so the cheque "
                   "sequence can be accounted for.",
    "request_for_quote": "An enquiry about terms. No order is placed and no goods are requested.",
    "price_list": "A supplier's price notice. Nothing has been ordered against it.",
}

# NO_ENTRY_DOCUMENTS is gone. It held three distractors this profile invented — an incoming
# purchase order, a request for quotation and a price list — because the per-transaction document
# list had no envelope to take an inventory from, so without them every document in the set would
# have needed an entry and there would have been nothing to triage. The printed envelope files
# thirty-four of its own, the invented three among them (N13, N14, N15), and a document that is
# photographed cannot contradict its own photograph the way an authored summary could.

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
    "D01": "A payment by cheque belongs in the journal built for cash going out.",
    "D02-2": "Sales on account are recorded in the journal built for them.",
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
#
# 14, 16 and 23 are gone from this set with their branches. They were the two customer
# remittances and the credit memo, and each carried arithmetic the *summary* could not be
# journalised without: a remitted figure whose invoice, discount and deduction were nowhere on
# it, and a credit memo whose returned item was nowhere on it. The printed remittance advice and
# the printed memo state all of it themselves -- invoice 4871 4,080.00 less 2% (81.60) remitted
# 3,998.40; invoice 4872 5,120.00 less credit memo CM-118 (640.00) less 2% (89.60) remitted
# 4,390.40; "Against invoice 4872" over an item row reading 1 Cascade 29er mountain bike 640.00
# -- so restating them here could only be a second copy of a figure the artefact already prints,
# and a copy is a thing that can disagree.
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
        # A Terms row stood here for the five sales invoices, saying "2/10, n/30". It was added
        # because the invoice's *summary* carried no terms at all -- the model's meta dict sets
        # "terms" only for a vendor's own invoice, so the generic furniture loop in
        # build_pack.py, which reads meta["terms"], never saw a customer's. The printed invoice
        # has always had them on its face ("Terms 2/10, n/30", in gendocs.py's own invoice body),
        # and D02-2, D05-2, D09-2, D11-2 and D19-2 each read a Terms field off it in all three
        # versions, so this row would now be a second statement of a figure the paper already
        # makes.
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


# Keyed by ref, as the manifest arm requires. Transaction 2 is three artefacts in the envelope --
# D02 the customer's purchase order, D02-2 the invoice, D02-3 the bill of lading -- and the
# scaffolding belongs on the invoice, which is the one that takes an entry. V10 caps guided
# documents at two.
GUIDED_SEQUENCES = {"D01", "D02-2"}


def check(model, manifest=None):
    """Special-cased transaction numbers, journal column accounts, checkpoint accounts and
    guidance coverage — everything this profile asserts about itself before it is trusted.

    ``manifest`` is the envelope's own inventory, which scripts/build_pack.py passes once a
    company takes its document list from what was printed. GUIDANCE is keyed by the manifest's
    own refs, so the two constants agreeing with each other proves only that they agree: renaming
    or dropping a printed artefact leaves GUIDANCE pointing at a ref nothing prints, and only the
    manifest can see that. Defaulted to None because build_source still calls check(model) for a
    build with no envelope.
    """
    numbers = {t["no"] for t in model.build(sorted(model.VARIANTS)[0])}
    missing = _SPECIAL_TRANSACTIONS - numbers
    if missing:
        raise SystemExit(f"{COMPANY['slug']}: no transaction numbered {sorted(missing)}.")

    # FACE_ACCOUNTS entries must name an account the chart actually has -- "returns" included,
    # since a typo there would make _face_amount's returns check silently never fire rather than
    # raise, and the credit memo would go back to summing debits.
    for role, account in FACE_ACCOUNTS.items():
        if int(account) not in model.ACCT_NAME:
            raise SystemExit(
                f"{COMPANY['slug']}: FACE_ACCOUNTS[{role!r}] names account {account}, which is "
                f"not in the chart. Nothing was written."
            )

    # Two cross-checks stood here and went with the branches they guarded. One compared D16's
    # hardcoded 640.00 "Item returned" total against the credit memo's own returns-account debit;
    # the other compared D23's hardcoded 5,120.00 less 640.00 less 2% against the cash the model
    # books. Both existed because extra_fields printed a literal beside a figure derived from the
    # model, so the two could drift apart in front of a student. Neither figure is printed from
    # here any more -- both documents state their own arithmetic on their face, and the paper's
    # own gendocs.py already asserts D16's 640.00 against the books -- so there is no longer a
    # second copy to keep in step with the first. A third checked that model.DOCS carried the
    # purchase_orders the Terms branch was keyed off; that branch is gone too.

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

    # Every ref the translator guides must have words in GUIDANCE (an empty string counts as
    # missing, which is why this tests truthiness rather than key presence), and GUIDANCE must
    # hold nothing for a ref that is never guided. A guided document with no guidance passed
    # silently until this, the hole this round's own guidance fix opened.
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

    # Every guided ref must be a document the envelope actually contains. Without this, renaming
    # or dropping a printed artefact leaves GUIDANCE pointing at a ref nothing prints, and
    # GUIDANCE/GUIDED_SEQUENCES agreeing with each other would not catch it — they would just
    # agree on the wrong thing. D02-2 is exactly the ref at risk: the invoice is the second
    # artefact of transaction 2, so its ref is assigned by the envelope's own numbering.
    if manifest is not None:
        manifest_refs = {entry["ref"] for entry in manifest}
        unprinted = set(GUIDED_SEQUENCES) - manifest_refs
        if unprinted:
            raise SystemExit(
                f"{COMPANY['slug']}: GUIDANCE guides {sorted(unprinted)}, which the envelope's "
                f"manifest does not contain. Nothing was written."
            )
