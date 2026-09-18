"""An authoring source for the generator: the same TestCo Alpha company, but with the *computed*
answers left out. The generator replays the expected entries + adjustments to fill in
``expected_balances`` and each checkpoint figure. Documents carry a ``text_alternative`` so the
renderer can draw them.

Compare against ``testco_alpha.py`` (the finished pack): the numbers the generator computes here
must equal the numbers hand-written there.
"""

from __future__ import annotations

SOURCE: dict = {
    "format_version": 1,
    "company": {
        "slug": "testco-alpha", "name": "TestCo Alpha", "accent_hex": "#1F5F8B",
        "monogram": "TA", "course_tags": ["ACCT1010"], "scope_tags": ["service", "closing"],
    },
    "version": 1,
    "period": {"start": "2026-12-01", "end": "2026-12-31", "fiscal_year_end": "2026-12-31"},
    "statement_sections": [
        "current_assets", "non_current_assets", "equity", "sales_revenue", "operating_expenses",
    ],
    "accounts": [
        {"number": "101", "name": "Cash", "type": "asset", "normal_balance": "debit",
         "statement_section": "current_assets", "sort_order": 1},
        {"number": "112", "name": "Accounts Receivable", "type": "asset",
         "normal_balance": "debit", "statement_section": "current_assets",
         "roles": ["ar_control"], "subsidiary_kind": "customer", "sort_order": 2},
        {"number": "154", "name": "Equipment", "type": "asset", "normal_balance": "debit",
         "statement_section": "non_current_assets", "sort_order": 3},
        {"number": "155", "name": "Accumulated Depreciation", "type": "contra_asset",
         "normal_balance": "credit", "statement_section": "non_current_assets", "sort_order": 4},
        {"number": "301", "name": "Owner Capital", "type": "equity", "normal_balance": "credit",
         "statement_section": "equity", "roles": ["retained_earnings"], "sort_order": 5},
        {"number": "399", "name": "Income Summary", "type": "equity", "normal_balance": "credit",
         "statement_section": "equity", "roles": ["income_summary"], "sort_order": 6},
        {"number": "401", "name": "Sales Revenue", "type": "revenue", "normal_balance": "credit",
         "statement_section": "sales_revenue", "sort_order": 7},
        {"number": "611", "name": "Depreciation Expense", "type": "expense",
         "normal_balance": "debit", "statement_section": "operating_expenses", "sort_order": 8},
    ],
    "parties": [
        {"code": "C-ONE", "kind": "customer", "name": "Firstborn Supply"},
        {"code": "C-TWO", "kind": "customer", "name": "Second Street Traders"},
    ],
    "variants": [{"code": "A", "label": "Variant A", "drivers": {}}],
    "opening_balances": {
        "A": {"accounts": {"101": 500000, "112": 300000, "154": 200000,
                           "155": -50000, "301": -950000},
              "parties": {"C-ONE": 300000}},
    },
    "journals": [
        {"key": "sales", "name": "Sales Journal", "ref_prefix": "S", "kind": "special",
         "columns": [
             {"key": "ar_dr", "label": "Accounts Receivable Dr", "side": "debit",
              "account": "112", "subsidiary_kind": "customer", "posts": "total"},
             {"key": "sales_cr", "label": "Sales Cr", "side": "credit", "account": "401",
              "posts": "total"}]},
        {"key": "general", "name": "General Journal", "ref_prefix": "J", "kind": "general"},
    ],
    "documents": [
        {"ref": "INV-1", "display_ref": "Invoice 1", "type": "sales_invoice",
         "date": "2026-12-02", "received_seq": 1, "guided": True,
         "guidance": "Sales on account are recorded in the journal built for them.",
         "variants": {"A": {"text_alternative": {
             "fields": [["Customer", "Firstborn Supply"], ["Terms", "Net 30"]],
             "lines": [["10", "Kayak rack", "120.00", "1,200.00"]]}}}},
        {"ref": "INV-2", "display_ref": "Invoice 2", "type": "sales_invoice",
         "date": "2026-12-05", "received_seq": 2,
         "variants": {"A": {"text_alternative": {
             "fields": [["Customer", "Second Street Traders"], ["Terms", "Net 30"]],
             "lines": [["8", "Paddle set", "100.00", "800.00"]]}}}},
    ],
    "checkpoints": [
        {"key": "cp1", "ordinal": 1, "stage": "posted",
         "prompt": "Accounts Receivable balance after posting",
         "measure": {"account": "112"}},  # author-only: which figure this checkpoint tests
    ],
    "statements": [
        {"type": "income_statement", "title": "Income Statement", "stage": "adjusted",
         "allowed_sections": ["sales_revenue", "operating_expenses"],
         "subtotal_types": [{"key": "net_sales", "label": "Net sales"},
                            {"key": "net_income", "label": "Net income"}],
         "required_subtotals": ["net_income"]},
    ],
    "rubric": {"components": [{"key": "triage", "points": 10},
                             {"key": "entry_accuracy", "points": 26},
                             {"key": "adjustment_amounts", "points": 6}]},
    # ── author-only answers (the generator computes expected_balances + checkpoint figures) ──
    "answers": {
        "A": {
            "triage": {"INV-1": True, "INV-2": True},
            "designated_journal_documents": {"INV-1": "sales", "INV-2": "sales"},
            "expected_entries": [
                {"document": "INV-1", "journal": "sales", "kind": "regular",
                 "lines": [{"account": "112", "party": "C-ONE", "debit": 120000},
                           {"account": "401", "credit": 120000}]},
                {"document": "INV-2", "journal": "sales", "kind": "regular",
                 "lines": [{"account": "112", "party": "C-TWO", "debit": 80000},
                           {"account": "401", "credit": 80000}]},
            ],
            "adjustments": [
                {"key": "adj_depreciation", "label": "Depreciation of equipment",
                 "amount_basis": "independent", "amount": 25000,
                 "pattern": [{"account": "611", "side": "debit"},
                             {"account": "155", "side": "credit"}]},
            ],
            "error_signatures": [
                {"key": "depr_on_wrong_doc", "label": "Recorded depreciation against a sale",
                 "detect": {"type": "entry_line", "document": "INV-2", "account": "611",
                            "side": "debit"}},
            ],
        }
    },
}
