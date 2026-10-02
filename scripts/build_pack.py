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
import re
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser
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


# ---------------------------------------------------------------------------
# What the artefact itself says
#
# A document's text alternative is read off the printed artefact's own html, not built from the
# transaction behind it. Two defects made that necessary rather than merely tidy. A purchase order
# and its vendor invoice share a transaction, so the order carried the invoice's text
# byte-identically — the document a student is told to file read as the one they are told to enter,
# and contradicted its own photograph. And the nine artefacts that belong to no transaction had no
# text at all: a void cheque, four time cards, two petty cash vouchers, an appointment request and
# a price list were blank pages for every paper-mode student and every screen-reader user, while
# all nine still carried a triage mark.
#
# The html is also exactly what the photograph shows, so deriving the text from it is the only way
# the picture and the text cannot disagree — which is the accessibility property this codebase
# states as a commitment rather than an aspiration.
#
# html.parser is the standard library's. A pack has to build on a machine carrying nothing but
# this repository's own dependencies, so this adds none.
# ---------------------------------------------------------------------------

_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                        "meta", "param", "source", "track", "wbr"})

# Tags whose words join the words around them. Everything else begins and ends a line of reading.
_INLINE_TAGS = frozenset({"a", "abbr", "b", "big", "cite", "code", "em", "i", "s", "small",
                          "span", "strong", "sub", "sup", "u"})

_CELL_TAGS = frozenset({"td", "th"})


class _Node:
    """One element of an artefact's markup: what it is, what it is called, what is inside it."""

    __slots__ = ("tag", "classes", "children")

    def __init__(self, tag: str, classes: frozenset[str]):
        self.tag = tag
        self.classes = classes
        self.children: list = []


class _Markup(HTMLParser):
    """The smallest tree the reading below needs.

    ``convert_charrefs`` is the default and is wanted: ``&middot;`` and ``&mdash;`` are characters
    a student reads, and ``&nbsp;`` is a space, which :func:`_collapse` then treats as one.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("", frozenset())
        self._open = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, frozenset(dict(attrs).get("class", "").split()))
        self._open[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._open.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS:
            self._open.pop()

    def handle_endtag(self, tag):
        # An end tag nothing opened is ignored, and an element left open is closed by its parent's
        # end tag, which is what a browser does with the same markup. The paper set writes
        # unclosed <td> and <tr> in places, so this is not hypothetical.
        for depth in range(len(self._open) - 1, 0, -1):
            if self._open[depth].tag == tag:
                del self._open[depth:]
                return

    def handle_data(self, data):
        self._open[-1].children.append(data)


def _collapse(text: str) -> str:
    """One space between words and none at the ends. A non-breaking space is a space to a reader."""
    return " ".join(text.replace("\xa0", " ").split())


class _Reading:
    """What one artefact says, in the order it is printed.

    ``fields`` are label/value pairs; ``lines`` are the rows of the line-item table. Text carrying
    no label of its own is still a field, with an empty label, because dropping it would lose the
    company's name, a cheque's "Pay to the order of", and a register tape's total.
    """

    def __init__(self):
        self.fields: list[list[str]] = []
        self.lines: list[list[str]] = []
        self._words: list[str] = []
        self._label: str | None = None

    def text(self, data: str) -> None:
        self._words.append(data)

    def label(self, data: str) -> None:
        """A ``span.lbl``: the words after it are its value."""
        self.close()
        if self._label is not None:
            self.fields.append(["", self._label])
        self._label = _collapse(data).rstrip(":")

    def line_break(self) -> None:
        """A ``<br>`` ends a line — unless a label is still waiting for its value. A label and its
        value are routinely on two lines ("Received from" above the customer's address)."""
        if self._label is None:
            self.close()
        else:
            self._words.append(" ")

    def close(self) -> None:
        """Emit whatever has been read. A label whose value has not arrived keeps waiting."""
        value = _collapse("".join(self._words))
        self._words = []
        if self._label is not None:
            if value:
                self.fields.append([self._label, value])
                self._label = None
            return
        if value:
            self.fields.append(["", value])

    def end_block(self) -> None:
        """The end of a block element, which is the end of whatever was being read."""
        self.close()
        if self._label is not None:
            # A label with nothing after it is not a label; it is a line of its own, like the
            # "CUSTOMER COPY" stamped on an invoice.
            self.fields.append(["", self._label])
            self._label = None


def _flat(node: _Node) -> str:
    """Everything inside one element as a single line, for a table cell."""
    parts: list[str] = []

    def walk(current: _Node) -> None:
        for child in current.children:
            if isinstance(child, str):
                parts.append(child)
            elif child.tag == "br":
                parts.append(" ")
            elif "foot" not in child.classes:
                walk(child)

    walk(node)
    return _collapse("".join(parts))


def _rows(table: _Node) -> list[list[str]]:
    """Every row of the line-item table, the heading row included: a column of figures with no
    heading is not something a screen reader can make sense of."""
    rows = []
    for row in _tagged(table, "tr"):
        cells = [_flat(cell) for cell in row.children
                 if isinstance(cell, _Node) and cell.tag in _CELL_TAGS]
        if any(cells):
            rows.append(cells)
    return rows


def _tagged(node: _Node, tag: str) -> list[_Node]:
    found = []
    for child in node.children:
        if isinstance(child, _Node):
            if child.tag == tag:
                found.append(child)
            else:
                found.extend(_tagged(child, tag))
    return found


def _read(node: _Node, out: _Reading) -> None:
    for child in node.children:
        if isinstance(child, str):
            out.text(child)
        elif "foot" in child.classes:
            # The printed footer names the version ("… · version B"). A student must not be able
            # to read which version they hold off their own document, and the photograph carries
            # the same marker, so neither may show it.
            continue
        elif child.tag == "br":
            out.line_break()
        elif child.tag in _VOID_TAGS:
            continue
        elif child.tag == "table" and "items" in child.classes:
            out.end_block()
            out.lines.extend(_rows(child))
        elif child.tag == "span" and "lbl" in child.classes:
            out.label(_flat(child))
        elif child.tag in _INLINE_TAGS:
            _read(child, out)
        else:
            # Every other element — a div, a paragraph, a cell of a layout or meta table — is a
            # block, and a block is a line of reading.
            out.end_block()
            _read(child, out)
            out.end_block()


def _text_from_html(markup: str) -> dict:
    """One printed artefact's own words, as the pack's ``text_alternative``."""
    parser = _Markup()
    parser.feed(markup)
    parser.close()
    reading = _Reading()
    _read(parser.root, reading)
    reading.end_block()
    return {"fields": reading.fields, "lines": reading.lines}


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_A_DATE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})\b")


def _stated_date(text: dict, profile) -> str | None:
    """The date an artefact prints, if it prints one.

    Nine artefacts belong to no transaction, so the manifest holds no date for them and the
    period's last day stood in — which listed the void cheque as Dec 7 while its own stub says
    Dec 6. Four of the nine state a date and are now read; a time card states a period rather than
    a date and a price list takes effect in January, and neither is guessed at.

    Only a day inside the pack's own period counts. A document may well mention another date — a
    remittance explains that the invoice it pays was "Dated 28 November" — and that is not its own.
    """
    start = date.fromisoformat(profile.PERIOD["start"])
    end = date.fromisoformat(profile.PERIOD["end"])
    for label, value in text["fields"]:
        for month, day in _A_DATE.findall(f"{label} {value}"):
            try:
                stated = date(start.year, _MONTHS.index(month) + 1, int(day))
            except ValueError:          # "Feb 30" on a document is not a date
                continue
            if start <= stated <= end:
                return stated.isoformat()
    return None


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
        desc = _item_description(sku, model, profile, txn)
        lines.append([str(qty), desc, f"{unit:,.2f}", f"{total:,.2f}"])
    return {"fields": fields, "lines": lines}


def _item_description(sku: str, model, profile, txn) -> str:
    """What a document line says for a code that is not in the stock list.

    The profile's own override comes first, because Riverbend's committed pack already shortened
    two of the model's descriptions and that pack is in front of students; the model's own text
    comes next, for a company (the clinic) with nothing to override. A code neither names is not
    guessed at.
    """
    if sku in model.SKUS:
        return model.SKUS[sku][0]
    if sku in profile.ITEM_DESCRIPTIONS:
        return profile.ITEM_DESCRIPTIONS[sku]
    if sku in model.ITEM_DESC_EXTRA:
        return model.ITEM_DESC_EXTRA[sku]
    raise SystemExit(
        f"{profile.COMPANY['slug']}: document {txn['no']} has an item coded {sku!r}, which is "
        f"in none of SKUS, the profile's ITEM_DESCRIPTIONS or the model's ITEM_DESC_EXTRA. "
        f"Nothing was written."
    )


def _documents_by_transaction(model, profile) -> list[dict]:
    """One document per transaction, in the order they arrive on the desk, plus the profile's
    own invented distractors.

    A label that repeats is no label at all: the three counter sales all say "Cash register
    tape", and in a list of thirty-one they cannot be told apart. The paper tape identifies
    itself by its date, so that is what is added, and it is added to anything that repeats
    rather than to the tapes by name.

    This is Riverbend's own path, kept exactly as it was: one document per transaction, found by
    replaying the model, with no printed envelope to take an inventory from. The clinic has moved
    to ``documents()`` below, which takes its list from the envelope's own manifest instead.
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
            # Which documents are guided, and what to say, are the company's own: which journal
            # and why, never which accounts, and "sales on account" is not true of a service
            # practice with no sales. check() has already proven GUIDANCE covers exactly
            # GUIDED_SEQUENCES and nothing past it, so .get is safe here rather than a guess.
            "guided": seq in profile.GUIDED_SEQUENCES,
            "guidance": profile.GUIDANCE.get(seq),
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


# What each printed artefact is called in a list of them, in the vocabulary the old labels used
# ("Check 4101", "Invoice 7101"). Without it the list showed the bare printed reference — "4104",
# "18", "J. Finch" — and a void cheque could not be told from the three real ones.
KIND_LABEL = {
    "sales_invoice": "Invoice",
    "vendor_invoice": "Vendor invoice",
    "credit_memo": "Credit memo",
    "remittance": "Remittance",
    "receipt": "Receipt",
    "register_tape": "Cash register tape",
    "purchase_order": "Purchase order",
    "cheque": "Check",
    "void_cheque": "Void cheque",
    "time_card": "Time card",
    "petty_cash_voucher": "Petty cash voucher",
    "payroll_register": "Payroll register",
    "appointment_request": "Appointment request",
    "price_list": "Price list",
}


def _display_ref(entry: dict, profile) -> str:
    """What the artefact is, and then which one it is."""
    if entry["kind"] not in KIND_LABEL:
        raise SystemExit(
            f"{profile.COMPANY['slug']}: the envelope holds a {entry['kind']!r}, which KIND_LABEL "
            f"has no name for, so it would be listed by its bare reference and a student could "
            f"not tell it from anything else. Nothing was written."
        )
    label = KIND_LABEL[entry["kind"]]
    printed = entry["printed_ref"]
    if not printed:
        return label
    # A number reads as part of the name ("Void cheque 4104"); a person's does not, so the two are
    # separated ("Time card, J. Finch").
    return f"{label} {printed}" if any(c.isdigit() for c in printed) else f"{label}, {printed}"


def documents(model, profile, manifest, stated: dict[str, str | None]) -> list[dict]:
    """One document per printed artefact, in the order the envelope holds them.

    It was one per transaction plus distractors the profile invented, which is how the paper
    student came to triage a void cheque and four time cards while the screen student triaged a
    quotation that exists nowhere in the envelope. ``model`` is unused here — the manifest alone
    says what was printed — but kept in the signature so the two document-list builders share a
    shape.

    ``stated`` is the date each artefact prints, per :func:`_stated_date`, used where the manifest
    has none: nine artefacts belong to no transaction, and the period's last day stood in for all
    of them, which listed the void cheque as Dec 7 while its own stub says Dec 6.
    """
    labels = [_display_ref(entry, profile) for entry in manifest]
    # A label that repeats is no label at all, so anything that repeats says its date too.
    repeated = {label for label, count in Counter(labels).items() if count > 1}
    docs = []
    for seq, (entry, label) in enumerate(zip(manifest, labels, strict=True), start=1):
        when = (_iso_date(entry["date"], profile) if entry["date"]
                else stated.get(entry["ref"]) or profile.PERIOD["end"])
        docs.append({
            "ref": entry["ref"],
            "display_ref": f"{label}, {_day_label(when)}" if label in repeated else label,
            "type": "source_document",
            "kind": entry["kind"],
            "date": when,
            "received_seq": seq,
            # Guidance is keyed by ref rather than received_seq, so adding a document to the
            # envelope cannot silently move the guidance onto a different one. check() has
            # already proven every guided ref is a real manifest entry.
            "guided": entry["ref"] in profile.GUIDANCE,
            "guidance": profile.GUIDANCE.get(entry["ref"]),
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


def _day_label(iso: str) -> str:
    """The reverse of :func:`_iso_date`: the date as the documents themselves print it."""
    when = date.fromisoformat(iso)
    return f"{when:%b} {when.day}"


def expected_entries(model, variant: str, profile, manifest=None) -> list[dict]:
    """Each transaction as the entry the key says it is, in cents.

    ``document`` names the artefact that is the *evidence* for the entry. Without a manifest
    that is simply the transaction's own ref (Riverbend's path: one document per transaction,
    so the two can never disagree). With one, a transaction can print two artefacts — a purchase
    prints both a purchase order and a vendor invoice, and both carry the transaction — so the
    document is found by the manifest entry whose ``entry_for`` matches, never by ``txn``, which
    would also match the purchase order and tell a student to journalise it a second time.
    """
    doc_for_txn = None
    if manifest is not None:
        doc_for_txn = {entry["entry_for"]: entry["ref"]
                       for entry in manifest if entry["entry_for"] is not None}
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
        document = doc_for_txn[txn["no"]] if doc_for_txn is not None else _ref(txn)
        entries.append({
            "document": document,
            "journal": profile.JOURNAL_OF[txn["cycle"]],
            "kind": "regular",
            "lines": lines,
        })
    return entries


def _amount_lines(lines):
    """Every posting as (account, side, cents), so a changed figure can be found on either side."""
    out = []
    for account, debit, credit in lines:
        if debit:
            out.append((str(account), "debit", cents(debit)))
        if credit:
            out.append((str(account), "credit", cents(credit)))
    return out


def error_signatures(model, errors_mod, variant: str, manifest=None) -> list[dict]:
    """The five designed errors, each detected on the one document that produces it.

    Detection is document-first (T8.5): the trap changes a named line on a named document, so the
    signature names that line rather than hunting a balance difference. With a manifest, that
    document is the one whose ``entry_for`` names the transaction — the same reasoning as
    ``expected_entries``, and for the same reason: a purchase's vendor invoice is where the trap
    is detected, never its purchase order.
    """
    txn_of = {t["no"]: t for t in model.build(variant)}
    doc_for_txn = None
    if manifest is not None:
        doc_for_txn = {entry["entry_for"]: entry["ref"]
                       for entry in manifest if entry["entry_for"] is not None}
    signatures = []
    for kind, _date, label in errors_mod.TRAPS:
        mutated = {t["no"]: t for t in errors_mod.mutate(variant, kind)}
        for no, txn in txn_of.items():
            if mutated[no]["lines"] == txn["lines"]:
                continue
            document = doc_for_txn[no] if doc_for_txn is not None else _ref(txn)
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
                    "detect": {"type": "entry_line", "document": document,
                               "account": account, "side": side},
                })
            else:
                # Same accounts and sides, different figures: name the posting whose figure
                # actually moved. The filter this replaces tested membership in `wrong`, which
                # holds every line of the mutated entry, so it excluded nothing and the first
                # debit was named however the trap had been drawn. A multi-debit entry, or any
                # trap on a credit, would therefore name a figure the student got right and
                # report the designed error present for everyone who did the work properly.
                # Sorting makes the choice deterministic when a trap moves more than one figure.
                changed = sorted(set(_amount_lines(mutated[no]["lines"]))
                                 - set(_amount_lines(txn["lines"])))
                if changed:
                    account, side, amount = changed[0]
                    signatures.append({
                        "key": kind, "label": label,
                        "detect": {"type": "entry_amount", "document": document,
                                   "account": account, "side": side, "amount": amount},
                    })
            break
    return signatures


def _render_manifest_images(set_dir: Path) -> dict[str, bytes]:
    """``scripts/render_documents.py``'s ``render_manifest``, loaded by path.

    ``scripts`` is not a package, so this cannot be a plain ``import``: ``build_pack.py`` is
    itself loaded by path in several tests (``load_profile`` and ``load_model`` do the same
    thing, for the same reason). Loaded lazily, and only when a documents directory is given, so
    a company with no envelope to photograph (Riverbend) never needs WeasyPrint or poppler
    installed at all.
    """
    path = Path(__file__).resolve().parent / "render_documents.py"
    spec = importlib.util.spec_from_file_location("render_documents", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_manifest(set_dir)


def _variant_sets(documents_dir: Path, codes: list[str]) -> dict[str, Path]:
    """One printed envelope per version, each the output of ``gendocs.py <CODE>``.

    One set used to stand in for all three, because the printed artefact was said not to differ by
    version "except in the figures it already carries". The figures are exactly what differs by
    version, and that is the only reason three versions exist: D09's receipt reads 810.00 in A,
    900.00 in B and 990.00 in C. Every student was shown version B's picture.
    """
    sets = {}
    for code in codes:
        set_dir = documents_dir / code
        if not (set_dir / "manifest.json").is_file():
            raise SystemExit(
                f"--documents {documents_dir} must hold one directory per version "
                f"({', '.join(codes)}), each the output of gendocs.py for that version.\n"
                f"Expected {set_dir / 'manifest.json'}.\n"
                f"A student is shown their own version's document, and the figures on it are the "
                f"whole difference between the versions, so one set cannot stand in for three.\n"
                f"Nothing was written."
            )
        sets[code] = set_dir
    return sets


# What the versions must agree about: which artefacts were printed, in what order, what each one is,
# which transaction it belongs to and which one it is the evidence for. The figures on them differ;
# the envelope does not.
_INVENTORY = ("ref", "kind", "txn", "entry_for")


def _one_inventory(manifests: dict[str, list[dict]]) -> list[dict]:
    """The envelope's inventory, which must be the same envelope in every version.

    The pack carries one document list for every version, so one version's manifest is taken — but
    only because the others are checked against it rather than assumed to match. Inventories that
    have diverged are two different practice sets, and reconciling them here would hand some
    students a document their own version never printed.
    """
    codes = sorted(manifests)
    base_code, base = codes[0], manifests[codes[0]]

    def shape(entries):
        return [{key: entry[key] for key in _INVENTORY} for entry in entries]

    for code in codes[1:]:
        if shape(manifests[code]) != shape(base):
            theirs = {entry["ref"] for entry in manifests[code]}
            mine = {entry["ref"] for entry in base}
            raise SystemExit(
                f"Version {code}'s document inventory is not version {base_code}'s.\n"
                f"Only in {base_code}: {sorted(mine - theirs) or 'none'}\n"
                f"Only in {code}: {sorted(theirs - mine) or 'none'}\n"
                f"Compared on {', '.join(_INVENTORY)}, in order. The pack carries one document "
                f"list for every version, so a difference here means the versions printed "
                f"different envelopes and neither can speak for the other.\n"
                f"Nothing was written."
            )
    return base


def _agreed_dates(readings: dict[str, dict[str, dict]], profile) -> dict[str, str | None]:
    """The date each artefact prints, which must be the same date in every version."""
    codes = sorted(readings)
    base_code = codes[0]
    dates = {ref: _stated_date(text, profile) for ref, text in readings[base_code].items()}
    for code in codes[1:]:
        for ref, text in readings[code].items():
            theirs = _stated_date(text, profile)
            if theirs != dates[ref]:
                raise SystemExit(
                    f"{ref} prints {dates[ref]} in version {base_code} and {theirs} in version "
                    f"{code}, and the pack lists one date per document.\n"
                    f"Nothing was written."
                )
    return dates


def build_source(company: str, practicesets: Path, slug: str | None = None,
                  documents_dir: Path | None = None, images_dir: Path | None = None) -> dict:
    """``documents_dir``, when given, holds one directory per version (``A/``, ``B/``, ``C/``),
    each the output of ``gendocs.py`` for that version. ``images_dir``, when given, is where the
    photographs are written, one subdirectory per version; without it none are rendered, which is
    what lets a test build the pack without WeasyPrint and poppler doing 78 renders.
    """
    generators = require_practicesets(practicesets)
    model, errors_mod = load_model(generators, company)
    profile = load_profile(slug or company)

    set_dirs: dict[str, Path] = {}
    manifest = None
    if documents_dir is not None:
        set_dirs = _variant_sets(documents_dir, sorted(model.VARIANTS))
        manifest = _one_inventory({code: json.loads((set_dir / "manifest.json").read_text())
                                   for code, set_dir in set_dirs.items()})
    # Riverbend's own check(model) takes no manifest; only a company that has moved to the
    # manifest path passes one, and only its profile's check() accepts the extra argument.
    if manifest is not None:
        profile.check(model, manifest)
    else:
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

    cheques = model.DOCS.get("cheques", {})
    answers = {}

    if manifest is not None:
        # The clinic's path: the document list, the pictures and the triage all come from what
        # was actually printed, not from replaying the model a second time.
        # The text a student reads is the artefact's own html, per version. Built from the
        # transaction instead, a purchase order carried its vendor invoice's text word for word
        # (they share a transaction) and the nine artefacts belonging to no transaction carried
        # none at all.
        readings = {code: {entry["ref"]: _text_from_html((set_dir / entry["file"]).read_text())
                           for entry in manifest}
                    for code, set_dir in set_dirs.items()}
        docs = documents(model, profile, manifest, _agreed_dates(readings, profile))
        if images_dir is not None:
            # One file per ref **per version**, because the figures on the artefact are what
            # differs between versions. generate_pack.py loads these by (ref, code). Images are
            # not embedded in source.json — that is not where this pack format keeps them
            # (PackAsset and V12 expect them in the zip), and embedding 78 renders as base64 once
            # took this file from 64 KB to 7.5 MB.
            for code, set_dir in sorted(set_dirs.items()):
                pictures = _render_manifest_images(set_dir)
                into = images_dir / code
                into.mkdir(parents=True, exist_ok=True)
                for ref, picture in pictures.items():
                    (into / f"{ref}.png").write_bytes(picture)
                print(f"Wrote {len(pictures)} photograph(s) of version {code} to {into}",
                      file=sys.stderr)
        for code in sorted(model.VARIANTS):
            txns_by_no = {t["no"]: t for t in model.build(code)}
            for doc, entry in zip(docs, manifest, strict=True):
                # image/alt are left unset: generator.build()'s _attach_images fills them in,
                # using the photograph of this version supplied from images_dir.
                doc["variants"][code] = {"text_alternative": readings[code][entry["ref"]]}
            answers[code] = {
                # entry_for, not txn: a purchase order and its vendor invoice share a txn, and
                # only the invoice is the evidence a student journalises from.
                "triage": {entry["ref"]: entry["entry_for"] is not None for entry in manifest},
                "designated_journal_documents": {
                    entry["ref"]: profile.JOURNAL_OF[txns_by_no[entry["entry_for"]]["cycle"]]
                    for entry in manifest if entry["entry_for"] is not None
                },
                "expected_entries": expected_entries(model, code, profile, manifest),
                "adjustments": [],
                "error_signatures": error_signatures(model, errors_mod, code, manifest),
            }
    else:
        # Riverbend's path, untouched: one document per transaction plus the profile's own
        # invented distractors.
        docs = _documents_by_transaction(model, profile)
        # No-entry documents all land on the period's last day; formatted like the model's own
        # dates ("Dec 4"), which _iso_date then turns into a real one.
        period_end = date.fromisoformat(profile.PERIOD["end"])
        no_entry_date = f"{period_end:%b} {period_end.day}"
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
    parser.add_argument("--documents", type=Path, default=None, dest="documents_dir",
                        help="a directory holding one subdirectory per version (A/, B/, C/), each "
                             "the output of gendocs.py for that version; when given, the document "
                             "list and pictures come from what was printed rather than from one "
                             "document per transaction")
    parser.add_argument("--images", type=Path, default=None, dest="images_dir",
                        help="directory to write the photographed PNGs into, one subdirectory per "
                             "version and one file per document ref "
                             "(default packs/<slug>/documents); used only alongside --documents")
    args = parser.parse_args()
    images_dir = args.images_dir
    if images_dir is None and args.documents_dir is not None:
        images_dir = (Path(__file__).resolve().parents[1] / "packs"
                     / (args.slug or args.company) / "documents")
    json.dump(build_source(args.company, args.practicesets, args.slug, args.documents_dir,
                           images_dir),
              sys.stdout, indent=1, ensure_ascii=False)
    print()
