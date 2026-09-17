"""Pack schema parsing (T5.2/T5.3) and the pure validation rules (T5.4)."""

import copy

import pytest
from parchment.packs import schema, validate
from pydantic import ValidationError


def _pack_dict() -> dict:
    return {
        "format_version": 1,
        "company": {
            "slug": "testco-alpha",
            "name": "TestCo Alpha",
            "accent_hex": "#1F5F8B",
            "monogram": "TA",
            "course_tags": ["ACCT1010"],
            "scope_tags": ["merchandising"],
        },
        "version": 1,
        "period": {"start": "2026-12-01", "end": "2026-12-31", "fiscal_year_end": "2026-12-31"},
        "statement_sections": ["current_assets", "sales_revenue"],
        "accounts": [
            {"number": "101", "name": "Cash", "type": "asset", "normal_balance": "debit",
             "statement_section": "current_assets"},
            {"number": "112", "name": "Accounts Receivable", "type": "asset",
             "normal_balance": "debit", "statement_section": "current_assets",
             "roles": ["ar_control"], "subsidiary_kind": "customer"},
            {"number": "300", "name": "Owner Capital", "type": "equity",
             "normal_balance": "credit"},
            {"number": "401", "name": "Sales Revenue", "type": "revenue",
             "normal_balance": "credit", "statement_section": "sales_revenue"},
        ],
        "parties": [{"code": "C-HALV", "kind": "customer", "name": "Halvorsen Outfitters"}],
        "variants": [{"code": "A", "label": "Variant A", "drivers": {}}],
        "opening_balances": {
            "A": {"accounts": {"101": 1845000, "112": 420000, "300": -2265000},
                  "parties": {"C-HALV": 420000}},
        },
        "journals": [
            {"key": "sales", "name": "Sales Journal", "ref_prefix": "S", "kind": "special",
             "columns": [
                 {"key": "ar_dr", "label": "AR Dr", "side": "debit", "account": "112",
                  "subsidiary_kind": "customer", "posts": "total"},
                 {"key": "sales_cr", "label": "Sales Cr", "side": "credit", "account": "401",
                  "posts": "total"}]},
            {"key": "general", "name": "General Journal", "ref_prefix": "J", "kind": "general"},
        ],
        "documents": [
            {"ref": "INV-1", "display_ref": "Invoice 1", "type": "sales_invoice",
             "date": "2026-12-02", "received_seq": 1, "guided": True, "guidance": "…",
             "variants": {"A": {"alt": "Invoice 1",
                                 "text_alternative": {"fields": [], "lines": []}}}},
        ],
        "checkpoints": [{"key": "cp1", "ordinal": 1, "stage": "posted", "prompt": "AR balance"}],
        "statements": [
            {"type": "income_statement", "title": "Income Statement",
             "allowed_sections": ["sales_revenue"],
             "subtotal_types": [{"key": "net_sales", "label": "Net sales"}],
             "required_subtotals": ["net_sales"]},
        ],
        "rubric": {"components": [{"key": "triage", "points": 10}]},
    }


def _key_dict() -> dict:
    return {
        "variant": "A",
        "triage": {"INV-1": True},
        "designated_journal_documents": {"INV-1": "sales"},
        "expected_entries": [
            {"document": "INV-1", "journal": "sales", "kind": "regular",
             "lines": [{"account": "112", "party": "C-HALV", "debit": 168000},
                       {"account": "401", "credit": 168000}]},
        ],
        "checkpoints": {"cp1": 688000},
    }


def test_valid_pack_parses_and_validates_clean():
    pack = schema.load_pack(_pack_dict())
    key = schema.load_answer_key(_key_dict())
    assert validate.validate_pack(pack, {"A": key}) == []


def test_extra_key_is_rejected_by_schema():
    data = _pack_dict()
    data["company"]["surprise"] = "nope"
    with pytest.raises(ValidationError):
        schema.load_pack(data)


def _rules(problems):
    return {p.rule for p in problems}


def test_v2_duplicate_account_number():
    data = _pack_dict()
    data["accounts"].append(
        {"number": "101", "name": "Cash 2", "type": "asset", "normal_balance": "debit"}
    )
    problems = validate.validate_pack(schema.load_pack(data))
    assert "V2" in _rules(problems)


def test_v6_openings_must_sum_to_zero():
    data = _pack_dict()
    data["opening_balances"]["A"]["accounts"]["101"] = 1845001
    problems = validate.validate_pack(schema.load_pack(data))
    assert "V6" in _rules(problems)


def test_v7_party_openings_tie_to_control():
    data = _pack_dict()
    data["opening_balances"]["A"]["parties"]["C-HALV"] = 419000  # no longer equals 112 opening
    problems = validate.validate_pack(schema.load_pack(data))
    assert "V7" in _rules(problems)


def test_v13_low_contrast_accent_flagged():
    data = _pack_dict()
    data["company"]["accent_hex"] = "#EEEEEE"
    problems = validate.validate_pack(schema.load_pack(data))
    assert "V13" in _rules(problems)


def test_v15_unknown_rubric_component():
    data = _pack_dict()
    data["rubric"]["components"] = [{"key": "made_up", "points": 5}]
    problems = validate.validate_pack(schema.load_pack(data))
    assert "V15" in _rules(problems)


def test_v10_missing_checkpoint_answer():
    pack = schema.load_pack(_pack_dict())
    key = copy.deepcopy(_key_dict())
    key["checkpoints"] = {}  # no answer for cp1
    problems = validate.validate_pack(pack, {"A": schema.load_answer_key(key)})
    assert "V10" in _rules(problems)


def test_v3_bad_reference_in_key():
    pack = schema.load_pack(_pack_dict())
    key = _key_dict()
    key["expected_entries"][0]["lines"][0]["account"] = "999"
    problems = validate.validate_pack(pack, {"A": schema.load_answer_key(key)})
    assert "V3" in _rules(problems)
