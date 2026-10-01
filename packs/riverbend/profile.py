"""What is true of Riverbend rather than of packs in general.

The translator is machinery and knows no company. Everything here is one company's shape: which
accounts are non-current, which cycle goes in which journal, what the checkpoints ask for, and
the documents that start no entry at all.

Moved out of the translator unchanged. tests/unit/test_pack_reproducible.py is what proves the
move altered nothing.
"""

from __future__ import annotations

NON_CURRENT = {"150", "151", "155", "156"}
ROLES = {"302": ["retained_earnings"], "399": ["income_summary"],
         "105": ["ar_control"], "201": ["ap_control"]}
SUBSIDIARY = {"105": "customer", "201": "supplier"}

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
