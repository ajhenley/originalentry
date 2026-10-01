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
from datetime import date
from decimal import Decimal
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

    model.py reads PRACTICESET_COMPANY as it is imported, so the variable is set first. Each
    call then builds a fresh module and rebinds sys.modules[name] before executing it, which is
    what keeps two companies in one process apart. The pop is belt and braces: it matters only
    if this ever becomes a plain `import model`.
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


def load_profile(slug: str):
    """The pack's own shape, which lives beside the pack it describes."""
    path = Path(__file__).resolve().parents[1] / "packs" / slug / "profile.py"
    if not path.is_file():
        raise SystemExit(
            f"No profile for {slug!r}.\n"
            f"Expected {path}, which declares the journals, checkpoints and rubric.\n"
            f"Nothing was written."
        )
    spec = importlib.util.spec_from_file_location(f"{slug}_profile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def _ref(txn) -> str:
    """A stable, file-safe reference. The document's own number keeps them in order."""
    return f"D{txn['no']:02d}"


def _face_amount(txn, profile) -> int | None:
    """What the document itself is for, in cents.

    Cash where cash moves, otherwise the receivable or the payable. Summing the debits would
    double-count a sale, which also posts cost of goods sold. Which accounts mean "cash",
    "receivable" and "payable" is the profile's to say.
    """
    cash = int(profile.FACE_ACCOUNTS["cash"])
    receivable = int(profile.FACE_ACCOUNTS["receivable"])
    payable = int(profile.FACE_ACCOUNTS["payable"])
    lines = txn["lines"]
    for account, debit, credit in lines:
        if account == cash:
            return cents(debit or credit)
    for account, debit, _credit in lines:
        if account == receivable and debit:
            return cents(debit)
    for account, _debit, credit in lines:
        if account == payable and credit:
            return cents(credit)
    return cents(sum(d for _a, d, _c in lines))


def _money(value: int) -> str:
    return f"{value / 100:,.2f}"


def _text_alternative(txn, model, cheques: dict, profile) -> dict:
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
        known = {**model.VENDORS, **getattr(model, "LATE_VENDORS", {})}
        if code not in known:
            raise SystemExit(
                f"{profile.COMPANY['slug']}: document {txn['no']} is payable to {code}, which is "
                f"in neither VENDORS nor LATE_VENDORS. Nothing was written."
            )
        name = known[code][0]
        fields.append(["Supplier", name])

    fields += profile.extra_fields(txn, model, _money, cents, stage="furniture")

    stub = cheques.get(txn["no"])
    if stub:
        _number, payee, memo, _amount = stub
        fields.append(["Payee", payee])
        fields.append(["For", memo])

    # What the document is about, in the words on the paper.
    fields.append(["Description", txn["desc"]])

    fields += profile.extra_fields(txn, model, _money, cents, stage="detail")

    amount = _face_amount(txn, profile)
    if amount is not None:
        fields.append(["Amount", _money(amount)])

    lines = []
    for item in txn.get("items") or []:
        sku, qty, unit, total = item
        desc = model.SKUS[sku][0] if sku in model.SKUS else (
            "Freight" if sku == "FRT" else "Office supplies")
        lines.append([str(qty), desc, f"{unit:,.2f}", f"{total:,.2f}"])
    return {"fields": fields, "lines": lines}


def documents(model, profile) -> list[dict]:
    """One document per transaction, in the order they arrive on the desk.

    A label that repeats is no label at all: the three counter sales all say "Cash register
    tape", and in a list of thirty-one they cannot be told apart. The paper tape identifies
    itself by its date, so that is what is added, and it is added to anything that repeats
    rather than to the tapes by name.
    """
    # Descriptions and metadata do not vary by version; which version is "base" does not matter,
    # so the lowest-sorting one stands in rather than a letter this profile might not have.
    base_variant = sorted(model.VARIANTS)[0]
    assert base_variant in model.VARIANTS, f"no such variant: {base_variant!r}"
    base = model.build(base_variant)
    repeated = {doc for doc, count in Counter(t["doc"] for t in base).items() if count > 1}
    docs = []
    for seq, txn in enumerate(base, start=1):
        docs.append({
            "ref": _ref(txn),
            "display_ref": (f'{txn["doc"]}, {txn["date"]}' if txn["doc"] in repeated
                            else txn["doc"]),
            "type": "source_document",
            "date": _iso_date(txn["date"], profile),
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
    for extra in profile.NO_ENTRY_DOCUMENTS:
        docs.append({
            "ref": extra["ref"], "display_ref": extra["display_ref"],
            "type": "source_document", "date": extra["date"],
            "received_seq": len(docs) + 1, "guided": False, "guidance": None,
            "variants": {},
        })
    return docs


def _iso_date(label: str, profile) -> str:
    """"Dec 4" in the model; the pack wants a real date in the period.

    The year and month come from the profile's own period, not a literal: the next company this
    runs for is not necessarily in December 2026.
    """
    day = int(label.split()[1])
    year, month, _day = profile.PERIOD["start"].split("-")
    return f"{year}-{month}-{day:02d}"


def expected_entries(model, variant: str, profile) -> list[dict]:
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
            kind = profile.SUBSIDIARY.get(str(account))
            if kind == "customer" and txn.get("ar"):
                line["party"] = txn["ar"][0]
            if kind == "supplier" and txn.get("ap"):
                line["party"] = txn["ap"][0]
            lines.append(line)
        entries.append({
            "document": _ref(txn),
            "journal": profile.JOURNAL_OF[txn["cycle"]],
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


def build_source(company: str, practicesets: Path, slug: str | None = None) -> dict:
    generators = require_practicesets(practicesets)
    model, errors_mod = load_model(generators, company)
    profile = load_profile(slug or company)
    profile.check(model)

    accounts = []
    for order, (number, name, kind) in enumerate(model.ACCOUNTS, start=1):
        number = str(number)
        atype = TYPE[kind]
        section = SECTION[atype]
        if number in profile.NON_CURRENT:
            section = "non_current_assets"
        if atype == "liability" and number in profile.NON_CURRENT_LIABILITIES:
            section = "non_current_liabilities"
        account = {
            "number": number, "name": name, "type": atype,
            "normal_balance": "debit" if atype in DEBIT_NORMAL else "credit",
            "statement_section": section, "sort_order": order,
        }
        if number in profile.ROLES:
            account["roles"] = profile.ROLES[number]
        if number in profile.SUBSIDIARY:
            account["subsidiary_kind"] = profile.SUBSIDIARY[number]
        accounts.append(account)

    parties = (
        [{"code": c, "kind": "customer", "name": v[0]} for c, v in model.CUSTOMERS.items()]
        + [{"code": c, "kind": "supplier", "name": v[0]} for c, v in model.VENDORS.items()]
        + profile.EXTRA_PARTIES
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
                        | {p["code"]: 0 for p in profile.EXTRA_PARTIES}),
        }

    docs = documents(model, profile)
    cheques = model.DOCS.get("cheques", {})
    # No-entry documents all land on the period's last day; formatted like the model's own
    # dates ("Dec 4"), which _iso_date then turns into a real one.
    period_end = date.fromisoformat(profile.PERIOD["end"])
    no_entry_date = f"{period_end:%b} {period_end.day}"
    answers = {}
    for code in sorted(model.VARIANTS):
        txns = model.build(code)
        # strict: one document per transaction, always. A mismatch is an authoring bug.
        for doc, txn in zip(docs[:len(txns)], txns, strict=True):
            doc["variants"][code] = {
                "text_alternative": _text_alternative(txn, model, cheques, profile)}
        for doc, extra in zip(docs[len(txns):], profile.NO_ENTRY_DOCUMENTS, strict=True):
            doc["variants"][code] = {"text_alternative":
                                     {"fields": [["Date", no_entry_date],
                                                 ["Document", extra["display_ref"]],
                                                 *extra["fields"]],
                                      "lines": extra["lines"]}}
        answers[code] = {
            "triage": ({_ref(t): True for t in txns}
                       | {e["ref"]: False for e in profile.NO_ENTRY_DOCUMENTS}),
            "designated_journal_documents": {_ref(t): profile.JOURNAL_OF[t["cycle"]]
                                              for t in txns},
            "expected_entries": expected_entries(model, code, profile),
            "adjustments": [],
            "error_signatures": error_signatures(model, errors_mod, code),
        }

    return {
        "format_version": 1,
        "company": profile.COMPANY,
        "version": 1,
        "period": profile.PERIOD,
        "statement_sections": profile.STATEMENT_SECTIONS,
        "accounts": accounts,
        "parties": parties,
        "variants": variants,
        "opening_balances": opening,
        "journals": profile.JOURNALS,
        "documents": docs,
        "reference": [page["builder"](model) for page in profile.REFERENCE_PAGES],
        # The paper set's own checkpoint answers table: the two control accounts and cash.
        "checkpoints": profile.CHECKPOINTS,
        "statements": [],
        "rubric": {"components": profile.RUBRIC},
        "answers": answers,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Translate a paper practice set into a pack source.")
    parser.add_argument("company", help="the practicesets company module, e.g. alderfinch")
    parser.add_argument("--practicesets", type=Path, default=DEFAULT_PRACTICESETS,
                        help="path to the practicesets checkout")
    parser.add_argument("--slug", default=None,
                        help="the pack slug, if different from COMPANY (default: COMPANY)")
    args = parser.parse_args()
    json.dump(build_source(args.company, args.practicesets, args.slug), sys.stdout,
              indent=1, ensure_ascii=False)
    print()
