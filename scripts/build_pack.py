"""Turn a paper practice set into an Original Entry pack source.

The master model in the paper set is the source of truth (PRD §7): transactions are authored
there, once, and this script only translates. It never invents a figure. Run it again after the
practice set changes and the pack follows.

    python scripts/build_pack.py COMPANY [--practicesets PATH] > packs/COMPANY/source.json

COMPANY is a practicesets company module, e.g. riverbend, alderfinch, or thornemeadow. What it
reads: `generators/model.py` (chart, opening balances, parties, the transactions for each
version) and `generators/errors.py` (the designed errors and the exact mis-entry each produces).

Scope note: the Riverbend set runs 1–15 December and ends at the unadjusted trial balance. The
adjusting and closing practice in the same packet belongs to a different company (Sundial Press),
so this pack carries no adjustments, no statements and no closing entries.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import sys
from collections import Counter
from decimal import Decimal
from decimal import Decimal as D
from pathlib import Path

DEFAULT_PRACTICESETS = Path(__file__).resolve().parents[2] / "practicesets"


def require_practicesets(path: Path) -> Path:
    """The figures live in a sibling checkout. Say plainly when they are not there.

    The script this replaces resolved a path that had been refactored away and raised
    FileNotFoundError from deep inside an import. It failed that way for long enough that the
    pack it maintains had to be corrected by hand instead of regenerated.
    """
    generators = path / "generators"
    if not (generators / "model.py").is_file():
        raise SystemExit(
            f"The practice sets are not at {path}.\n"
            f"Expected {generators / 'model.py'}, which is where every figure comes from.\n"
            f"Pass --practicesets PATH, or check practicesets out beside this repository.\n"
            f"Nothing was written."
        )
    return generators


def load_model(generators: Path, company: str):
    """Import the practice set's model and errors for one company.

    model.py reads PRACTICESET_COMPANY as it is imported, so the variable is set first and the
    module cache is cleared. Without the clearing, a second company in the same process returns
    the first one's figures and nothing complains.
    """
    os.environ["PRACTICESET_COMPANY"] = company
    if str(generators) not in sys.path:
        sys.path.insert(0, str(generators))

    out = {}
    # The practice set prints a self-check banner when imported; it must not land in the JSON.
    with contextlib.redirect_stdout(io.StringIO()):
        for name in ("model", "errors"):
            sys.modules.pop(name, None)
            spec = importlib.util.spec_from_file_location(name, generators / f"{name}.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            out[name] = mod
    return out["model"], out["errors"]


def cents(amount) -> int:
    """Money is integer cents everywhere in this app (D1). The model works in dollars."""
    return int((Decimal(str(amount)) * 100).quantize(Decimal("1")))


# The paper set's one-letter account types, in this app's vocabulary.
TYPE = {"A": "asset", "XA": "contra_asset", "L": "liability", "E": "equity",
        "R": "revenue", "XR": "contra_revenue", "X": "expense"}
DEBIT_NORMAL = {"asset", "expense", "contra_revenue"}

SECTION = {
    "asset": "current_assets", "contra_asset": "non_current_assets",
    "liability": "current_liabilities", "equity": "equity",
    "revenue": "sales_revenue", "contra_revenue": "sales_revenue",
    "expense": "operating_expenses",
}
NON_CURRENT = {"150", "151", "155", "156"}
ROLES = {"302": ["retained_earnings"], "399": ["income_summary"],
         "105": ["ar_control"], "201": ["ap_control"]}
SUBSIDIARY = {"105": "customer", "201": "supplier"}

# The paper set's five cycles, and the journal each becomes here.
JOURNAL_OF = {"Sales": "sales", "Purchases": "purchases", "Cash receipts": "cash_receipts",
              "Cash payments": "cash_payments", "General": "general"}


def journals() -> list[dict]:
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


def reference(model) -> list[dict]:
    """What the instruction booklet puts in front of the student and the documents cannot.

    Chiefly the cost of each item. A sales invoice shows what the customer pays; the cost of
    goods sold comes from the company's own records, and without it half the sales entries
    cannot be made at all. Costs do not vary by version, so this is pack-level: only S-01's
    selling price changes, and that is printed on the invoice.
    """
    rows = [[sku, spec[0], f"{spec[1]:,.2f}", "Yes" if spec[4] else "\u2014"]
            for sku, spec in model.SKUS.items()]
    return [{
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
    }, {
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
    }]


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


def _ref(txn) -> str:
    """A stable, file-safe reference. The document's own number keeps them in order."""
    return f"D{txn['no']:02d}"


def _face_amount(txn) -> int | None:
    """What the document itself is for, in cents.

    Cash where cash moves, otherwise the receivable or the payable. Summing the debits would
    double-count a sale, which also posts cost of goods sold.
    """
    lines = txn["lines"]
    for account, debit, credit in lines:
        if account == 101:
            return cents(debit or credit)
    for account, debit, _credit in lines:
        if account == 105 and debit:
            return cents(debit)
    for account, _debit, credit in lines:
        if account == 201 and credit:
            return cents(credit)
    return cents(sum(d for _a, d, _c in lines))


def _money(value: int) -> str:
    return f"{value / 100:,.2f}"


def _text_alternative(txn, model, cheques: dict) -> dict:
    """What the paper document says, as text.

    This is the whole document in paper mode, so it has to carry everything a student needs to
    journalise it and nothing that tells them how. The first version of this carried only the
    item lines, which left a rent cheque showing a date and a number and no amount at all.
    """
    fields = [["Date", txn["date"]], ["Document", txn["doc"]]]
    meta = txn.get("meta") or {}
    for label, key in (("Vendor invoice", "vinv"), ("Purchase order", "po"),
                       ("Receiving report", "rr"), ("Terms", "terms"), ("FOB", "fob"),
                       ("Quantity billed", "billed"), ("Quantity received", "received")):
        if key in meta:
            fields.append([label, str(meta[key])])
    if txn.get("ar"):
        fields.append(["Customer", model.CUSTOMERS[txn["ar"][0]][0]])
    if txn.get("ap"):
        code = txn["ap"][0]
        name = model.VENDORS.get(code, ("Kestrel Office Supply",))[0]
        fields.append(["Supplier", name])

    if txn["doc"] == "Cash register tape":
        fields += [["Register", "1"], ["Clerk", "04"]]

    stub = cheques.get(txn["no"])
    if stub:
        _number, payee, memo, _amount = stub
        fields.append(["Payee", payee])
        fields.append(["For", memo])

    # What the document is about, in the words on the paper.
    fields.append(["Description", txn["desc"]])

    # The breakdowns a stub carries because the face amount alone cannot be journalised.
    pay = model.PR
    gross = pay["sales_sal"] + pay["office_sal"]
    fica = float(model.money(D(str(gross)) * pay["fica_rate"]))
    if txn["no"] == 24:
        fields += [["Gross pay", _money(cents(gross))],
                   ["Sales salaries", _money(cents(pay["sales_sal"]))],
                   ["Office salaries", _money(cents(pay["office_sal"]))],
                   ["FICA withheld", _money(cents(fica))],
                   ["Federal income tax withheld", _money(cents(pay["fed_wh"]))],
                   ["State income tax withheld", _money(cents(pay["st_wh"]))]]
    if txn["no"] == 25:
        fields.append(["Employer FICA", _money(cents(fica))])
    if txn["no"] == 26:
        fields += [["FICA payable", _money(cents(1430))],
                   ["Federal income tax payable", _money(cents(2180))],
                   ["State income tax payable", _money(cents(640))]]
    if txn["no"] == 18:
        fields += [["Invoice", "N-8841, 7,860.00"], ["Discount taken", "1%, 78.60"]]
    if txn["no"] == 27:
        fields += [["Delivery", _money(cents(190))], ["Office supplies", _money(cents(275))],
                   ["Advertising", _money(cents(155))]]

    amount = _face_amount(txn)
    if amount is not None:
        fields.append(["Amount", _money(amount)])

    lines = []
    for item in txn.get("items") or []:
        sku, qty, unit, total = item
        desc = model.SKUS[sku][0] if sku in model.SKUS else (
            "Freight" if sku == "FRT" else "Office supplies")
        lines.append([str(qty), desc, f"{unit:,.2f}", f"{total:,.2f}"])
    return {"fields": fields, "lines": lines}


def documents(model) -> list[dict]:
    """One document per transaction, in the order they arrive on the desk.

    A label that repeats is no label at all: the three counter sales all say "Cash register
    tape", and in a list of thirty-one they cannot be told apart. The paper tape identifies
    itself by its date, so that is what is added, and it is added to anything that repeats
    rather than to the tapes by name.
    """
    base = model.build("B")            # descriptions and metadata do not vary by version
    repeated = {doc for doc, count in Counter(t["doc"] for t in base).items() if count > 1}
    docs = []
    for seq, txn in enumerate(base, start=1):
        docs.append({
            "ref": _ref(txn),
            "display_ref": (f'{txn["doc"]}, {txn["date"]}' if txn["doc"] in repeated
                            else txn["doc"]),
            "type": "source_document",
            "date": _iso_date(txn["date"]),
            "received_seq": seq,
            # The first two documents are guided: which journal, and why. Never which accounts.
            "guided": seq <= 2,
            "guidance": (
                "Sales on account are recorded in the journal built for them."
                if seq == 2 else
                "A payment by cheque belongs in the journal built for cash going out."
            ) if seq <= 2 else None,
            "variants": {},
        })
    for extra in NO_ENTRY_DOCUMENTS:
        docs.append({
            "ref": extra["ref"], "display_ref": extra["display_ref"],
            "type": "source_document", "date": extra["date"],
            "received_seq": len(docs) + 1, "guided": False, "guidance": None,
            "variants": {},
        })
    return docs


def _iso_date(label: str) -> str:
    """"Dec 4" in the model; the pack wants a real date in the period."""
    day = int(label.split()[1])
    return f"2026-12-{day:02d}"


def expected_entries(model, variant: str) -> list[dict]:
    """Each transaction as the entry the key says it is, in cents."""
    entries = []
    for txn in model.build(variant):
        lines = []
        for account, debit, credit in txn["lines"]:
            line = {"account": str(account)}
            if debit:
                line["debit"] = cents(debit)
            if credit:
                line["credit"] = cents(credit)
            # The subsidiary account the line belongs to, where there is one.
            if str(account) == "105" and txn.get("ar"):
                line["party"] = txn["ar"][0]
            if str(account) == "201" and txn.get("ap"):
                line["party"] = txn["ap"][0]
            lines.append(line)
        entries.append({
            "document": _ref(txn),
            "journal": JOURNAL_OF[txn["cycle"]],
            "kind": "regular",
            "lines": lines,
        })
    return entries


def error_signatures(model, errors_mod, variant: str) -> list[dict]:
    """The five designed errors, each detected on the one document that produces it.

    Detection is document-first (T8.5): the trap changes a named line on a named document, so the
    signature names that line rather than hunting a balance difference.
    """
    txn_of = {t["no"]: t for t in model.build(variant)}
    signatures = []
    for kind, _date, label in errors_mod.TRAPS:
        mutated = {t["no"]: t for t in errors_mod.mutate(variant, kind)}
        for no, txn in txn_of.items():
            if mutated[no]["lines"] == txn["lines"]:
                continue
            # The account and side that appear only in the mistaken version.
            right = {(str(a), "debit" if d else "credit") for a, d, _c in txn["lines"] if d} | \
                    {(str(a), "credit") for a, _d, c in txn["lines"] if c}
            wrong = {(str(a), "debit") for a, d, _c in mutated[no]["lines"] if d} | \
                    {(str(a), "credit") for a, _d, c in mutated[no]["lines"] if c}
            tell = sorted(wrong - right)
            if tell:
                account, side = tell[0]
                signatures.append({
                    "key": kind, "label": label,
                    "detect": {"type": "entry_line", "document": _ref(txn),
                               "account": account, "side": side},
                })
            else:
                # Same accounts, different figures: name the amount instead.
                amount = next((cents(d) for a, d, _c in mutated[no]["lines"]
                               if d and (str(a), "debit") in wrong), None)
                account = next((str(a) for a, d, _c in mutated[no]["lines"] if d), None)
                if amount and account:
                    signatures.append({
                        "key": kind, "label": label,
                        "detect": {"type": "entry_amount", "document": _ref(txn),
                                   "account": account, "side": "debit", "amount": amount},
                    })
            break
    return signatures


def build_source(company: str, practicesets: Path) -> dict:
    generators = require_practicesets(practicesets)
    model, errors_mod = load_model(generators, company)

    accounts = []
    for order, (number, name, kind) in enumerate(model.ACCOUNTS, start=1):
        number = str(number)
        atype = TYPE[kind]
        section = SECTION[atype]
        if number in NON_CURRENT:
            section = "non_current_assets"
        if atype == "liability" and number == "220":
            section = "non_current_liabilities"
        account = {
            "number": number, "name": name, "type": atype,
            "normal_balance": "debit" if atype in DEBIT_NORMAL else "credit",
            "statement_section": section, "sort_order": order,
        }
        if number in ROLES:
            account["roles"] = ROLES[number]
        if number in SUBSIDIARY:
            account["subsidiary_kind"] = SUBSIDIARY[number]
        accounts.append(account)

    parties = (
        [{"code": c, "kind": "customer", "name": v[0]} for c, v in model.CUSTOMERS.items()]
        + [{"code": c, "kind": "supplier", "name": v[0]} for c, v in model.VENDORS.items()]
        + [{"code": "V-206", "kind": "supplier", "name": "Kestrel Office Supply"}]
    )

    variants = [{"code": c, "label": f"Version {c}", "drivers": model.VARIANTS[c]}
                for c in sorted(model.VARIANTS)]

    opening = {}
    for code in sorted(model.VARIANTS):
        opening[code] = {
            "accounts": {str(a): cents(v) for a, v in model.OPENING.items()},
            # Debit-positive throughout, so a supplier's credit balance is negative.
            "parties": ({c: cents(v[1]) for c, v in model.CUSTOMERS.items()}
                        | {c: -cents(v[1]) for c, v in model.VENDORS.items()}
                        | {"V-206": 0}),
        }

    docs = documents(model)
    cheques = model.DOCS.get("cheques", {})
    answers = {}
    for code in sorted(model.VARIANTS):
        txns = model.build(code)
        # strict: one document per transaction, always. A mismatch is an authoring bug.
        for doc, txn in zip(docs[:len(txns)], txns, strict=True):
            doc["variants"][code] = {"text_alternative": _text_alternative(txn, model, cheques)}
        for doc, extra in zip(docs[len(txns):], NO_ENTRY_DOCUMENTS, strict=True):
            doc["variants"][code] = {"text_alternative":
                                     {"fields": [["Date", "Dec 15"],
                                                 ["Document", extra["display_ref"]],
                                                 *extra["fields"]],
                                      "lines": extra["lines"]}}
        answers[code] = {
            "triage": ({_ref(t): True for t in txns}
                       | {e["ref"]: False for e in NO_ENTRY_DOCUMENTS}),
            "designated_journal_documents": {_ref(t): JOURNAL_OF[t["cycle"]] for t in txns},
            "expected_entries": expected_entries(model, code),
            "adjustments": [],
            "error_signatures": error_signatures(model, errors_mod, code),
        }

    return {
        "format_version": 1,
        "company": {
            "slug": "riverbend", "name": "Riverbend Bicycle Supply",
            "accent_hex": "#1F7A6E", "monogram": "RB",
            "course_tags": ["ACCT1010"],
            "scope_tags": ["merchandising", "special journals", "subsidiary ledgers"],
        },
        "version": 1,
        "period": {"start": "2026-12-01", "end": "2026-12-15",
                   "fiscal_year_end": "2026-12-31"},
        "statement_sections": ["current_assets", "non_current_assets", "current_liabilities",
                               "non_current_liabilities", "equity", "sales_revenue",
                               "operating_expenses"],
        "accounts": accounts,
        "parties": parties,
        "variants": variants,
        "opening_balances": opening,
        "journals": journals(),
        "documents": docs,
        "reference": reference(model),
        # The paper set's own checkpoint answers table: the two control accounts and cash.
        "checkpoints": [
            {"key": "cp1", "ordinal": 1, "stage": "posted",
             "prompt": "Accounts Receivable control balance at 15 December",
             "measure": {"account": "105"}},
            {"key": "cp2", "ordinal": 2, "stage": "posted",
             "prompt": "Cash balance at 15 December", "measure": {"account": "101"}},
            {"key": "cp3", "ordinal": 3, "stage": "posted",
             "prompt": "Accounts Payable control balance at 15 December",
             "measure": {"account": "201"}},
        ],
        "statements": [],
        "rubric": {"components": [
            {"key": "triage", "points": 10},
            {"key": "journal_selection", "points": 20},
            {"key": "entry_accuracy", "points": 40},
            {"key": "posting_completeness", "points": 20},
            {"key": "subsidiary_agreement", "points": 10},
        ]},
        "answers": answers,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Translate a paper practice set into a pack source.")
    parser.add_argument("company", help="the practicesets company module, e.g. alderfinch")
    parser.add_argument("--practicesets", type=Path, default=DEFAULT_PRACTICESETS,
                        help="path to the practicesets checkout")
    args = parser.parse_args()
    json.dump(build_source(args.company, args.practicesets), sys.stdout,
              indent=1, ensure_ascii=False)
    print()
