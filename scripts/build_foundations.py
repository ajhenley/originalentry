"""The accounting a student should already hold before opening this set.

    python scripts/build_foundations.py                 # the student booklet
    python scripts/build_foundations.py packs/alderfinch/source.json

The walkthrough (build_walkthrough.py) covers the software and says, in as many words, that the
instruction booklet covers the accounting. A paper practice set — SUA, Granite Bay Jet Ski — ships
that booklet in the box. A generated company has no box, so this is the booklet: the principles a
merchandising set with special journals and subsidiary ledgers assumes you already understand.

It teaches nothing company-specific as if it were general, and it gives away no entry. The chart
of accounts, the five journals, the credit terms and the inventory rule are read from the pack
source, so the booklet names the same accounts and journals the student will actually open; the
worked figures are invented and are not in the set. A booklet that drifts from the company is
worse than none, which is why it is generated from the same source the app imports.

WeasyPrint is a laptop-only dependency, like Pillow for the pack generator and the walkthrough. It
is not in requirements.txt and Heroku never sees it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# Reuse the walkthrough's house tokens and helpers verbatim, so the two printed pieces that land
# in a student's hands cannot drift in type, colour or font.
import build_walkthrough as wk  # noqa: E402

DEFAULT_SOURCE = ROOT / "packs" / "riverbend" / "source.json"
DEFAULT_OUT = ROOT / "packs" / "riverbend" / "foundations.pdf"

esc = wk.esc

# A little more than the walkthrough needs: definition lists, a two-column glossary, plain
# T-accounts drawn in CSS, and a "type key" chip. Everything else is inherited from wk.CSS.
EXTRA_CSS = """
dl.defs { margin: 6pt 0 10pt; }
dl.defs dt { font-weight: 600; color: #1b3a5c; margin: 8pt 0 1pt; break-after: avoid; }
dl.defs dd { margin: 0 0 0 0; max-width: 34em; }
.cols2 { column-count: 2; column-gap: 18pt; }
.cols2 > * { break-inside: avoid; }
.eq { font-family: oe-mono; font-size: 11pt; text-align: center; color: #1b3a5c;
      background: #f4f6f9; border: 1px solid #e2e6ee; border-radius: 6pt; padding: 9pt;
      margin: 8pt 0 10pt; }
.taccts { display: flex; gap: 14pt; margin: 6pt 0 10pt; break-inside: avoid; }
.tacct { flex: 1; }
.tacct .name { font-weight: 600; text-align: center; font-size: 9.5pt; border-bottom: 2px solid
               #1b3a5c; padding-bottom: 2pt; }
.tacct .tc { display: flex; font-family: oe-mono; font-size: 9pt; }
.tacct .tc > div { flex: 1; padding: 3pt 6pt; min-height: 34pt; }
.tacct .tc .dr { border-right: 1px solid #c9d0dd; }
.tacct .side { display: flex; font-family: oe-mono; font-size: 7.5pt; letter-spacing: .1em;
               text-transform: uppercase; color: #6b7688; }
.tacct .side > div { flex: 1; padding: 1pt 6pt; }
.chip { font-family: oe-mono; font-size: 7.5pt; letter-spacing: .08em; text-transform: uppercase;
        border: 1px solid #c9d0dd; border-radius: 10pt; padding: 1pt 7pt; color: #4a5568;
        white-space: nowrap; }
.chips { margin: 4pt 0 8pt; line-height: 2.1; }
td.nb { font-family: oe-mono; font-size: 8pt; color: #6b7688; }
.grp { font-family: oe-mono; font-size: 7.5pt; letter-spacing: .12em; text-transform: uppercase;
       color: #1f7a6e; padding-top: 8pt; }
h2 { break-before: auto; }
.section-lead { break-before: page; }
"""

TYPE_LABEL = {
    "asset": "Asset",
    "contra_asset": "Contra-asset",
    "liability": "Liability",
    "equity": "Equity",
    "revenue": "Revenue",
    "contra_revenue": "Contra-revenue",
    "expense": "Expense",
}
# The order the statements read in, not the order accounts happen to be numbered.
TYPE_ORDER = ["asset", "contra_asset", "liability", "equity",
              "revenue", "contra_revenue", "expense"]


def taccount(name: str, dr: str = "", cr: str = "", *, dr_up=True) -> str:
    up = "increase" if dr_up else "decrease"
    down = "decrease" if dr_up else "increase"
    return (
        f'<div class="tacct"><div class="name">{esc(name)}</div>'
        f'<div class="side"><div>Debit</div><div>Credit</div></div>'
        f'<div class="tc"><div class="dr">{esc(dr)}</div><div>{esc(cr)}</div></div>'
        f'<div class="side"><div>{up}</div><div>{down}</div></div></div>'
    )


def chart_rows(accounts: list[dict]) -> str:
    by_type: dict[str, list[dict]] = {}
    for a in accounts:
        by_type.setdefault(a["type"], []).append(a)
    out = []
    for t in TYPE_ORDER:
        rows = by_type.get(t)
        if not rows:
            continue
        out.append(
            f'<tr><td class="grp" colspan="3">{esc(TYPE_LABEL[t])} '
            f'&middot; normal balance {rows[0]["normal_balance"]}</td></tr>'
        )
        for a in sorted(rows, key=lambda a: a["sort_order"]):
            role = ""
            if "ar_control" in a.get("roles", []) or "ap_control" in a.get("roles", []):
                role = " &nbsp;<span class='chip'>control account</span>"
            out.append(
                f'<tr><td class="nb">{a["number"]}</td>'
                f'<td>{esc(a["name"])}{role}</td>'
                f'<td class="nb">{a["normal_balance"]}</td></tr>'
            )
    return "".join(out)


def build_html(src: dict) -> str:
    company = src["company"]["name"]
    period = src["period"]
    accounts = src["accounts"]
    journals = src["journals"]
    n_docs = len(src["documents"])
    versions = ", ".join(v["code"] for v in src["variants"])

    control = [a for a in accounts
               if {"ar_control", "ap_control"} & set(a.get("roles", []))]
    control_names = " and ".join(f'{a["number"]} {a["name"]}' for a in control) or "its controls"

    journal_rows = "".join(
        f"<tr><td><b>{esc(j['name'])}</b></td>"
        f"<td>{esc(wk.WHAT_FOR.get(j['key'], 'The company-specific journal.'))}</td></tr>"
        for j in journals
    )
    chart = chart_rows(accounts)

    css = wk.CSS.replace("FONTS", wk.FONTS.as_uri()) + EXTRA_CSS

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Foundations — {esc(company)}</title>
<style>{css}</style></head>
<body>

<div class="cover">
  <p class="label">Original Entry · foundations</p>
  <h1>Before you begin</h1>
  <p class="lede">The accounting you are assumed to hold already, for the books of
     {esc(company)}, {period['start']} to {period['end']}.</p>
  <p class="meta">{len(accounts)} accounts · {len(journals)} journals · {n_docs} documents ·
     versions {versions}</p>
</div>

<p class="lede">This set does not teach these principles; it tests whether you can apply them to a
real month of documents. Read this once before you open the first document, and keep it beside
the chart of accounts while you work. Every figure in the worked examples is invented — none of
them is one of your {n_docs}.</p>

<div class="note"><b>What is marked.</b> Deciding whether a document is a transaction at all;
choosing the journal built for it; the accounts and amounts in the entry; posting it in full; and
whether your subsidiary ledgers agree with their control accounts. The six sections that follow
are those five things and the ground they stand on.</div>

<h2>1 · The equation, and why every entry has two sides</h2>
<p>Every account a business keeps answers to one equation. It never stops being true, not for a
moment, not between two halves of an entry:</p>
<div class="eq">Assets = Liabilities + Equity</div>
<p>Revenue raises equity and expenses lower it, so the working form is
<b>Assets = Liabilities + Equity + Revenue &minus; Expenses</b>. An entry that left the equation
unbalanced would be describing a business that cannot exist, so the system forbids it: in every
entry the debits equal the credits. That is not a convention you could choose differently. It is
the equation, written one transaction at a time.</p>

<div class="taccts">
  {taccount("Any asset", dr="recorded here", cr="", dr_up=True)}
  {taccount("Any liability / equity", dr="", cr="recorded here", dr_up=False)}
</div>
<p>Debit means the left side of an account and credit means the right; neither means good or bad,
and neither means add or subtract on its own. Which side <i>increases</i> an account is fixed by
what kind of account it is — its <b>normal balance</b>, the side it is expected to sit on:</p>

<table>
  <tr><th>Account type</th><th>Increased by a</th><th>Normal balance</th><th>Examples here</th></tr>
  <tr><td>Asset</td><td>debit</td><td class="nb">debit</td><td>Cash, Merchandise Inventory</td></tr>
  <tr><td>Liability</td><td>credit</td><td class="nb">credit</td><td>Accounts Payable, Notes Payable</td></tr>
  <tr><td>Equity</td><td>credit</td><td class="nb">credit</td><td>Common Stock, Retained Earnings</td></tr>
  <tr><td>Revenue</td><td>credit</td><td class="nb">credit</td><td>Sales</td></tr>
  <tr><td>Expense</td><td>debit</td><td class="nb">debit</td><td>Rent Expense, Cost of Goods Sold</td></tr>
</table>
<div class="note"><b>Contra accounts sit on the wrong side on purpose.</b> A contra-asset such as
<i>Accumulated Depreciation</i> or <i>Allowance for Doubtful Accounts</i> carries a credit
balance and is subtracted from the asset it follows; a contra-revenue such as <i>Sales Returns
and Allowances</i> or <i>Sales Discounts</i> carries a debit balance and is subtracted from Sales.
They are not errors. They let the books show both the gross figure and what reduced it.</div>

<h2 class="section-lead">2 · The chart of accounts for this company</h2>
<p>These are the only accounts you may use, named and numbered exactly as the set expects them.
An entry to an account that is not on this list, or a plausible synonym for one that is, will not
be what the set is marking against. Learn the shape of it: where the assets end and the
liabilities begin, which accounts are contra, and which two are <b>control accounts</b> that a
subsidiary ledger stands behind (section 5).</p>
<table><tr><th>No.</th><th>Account</th><th>Normal</th></tr>{chart}</table>

<h2 class="section-lead">3 · Reading a document, and the first decision</h2>
<p>Work in this set begins at a document — an invoice, a cheque, a bank memo — not at a journal.
The first decision is the one most easily skipped: <b>is this a transaction to record at all?</b>
A purchase order or a price quote changes nothing until goods or money move; a document can arrive
that needs no entry, and saying so, with a reason, is itself marked. Only once you have decided an
entry is owed do you analyse it:</p>
<ol class="steps">
  <li><h3>What happened, in the company's terms</h3><p>Did it receive or pay cash? Sell or buy on
  account? Settle an earlier debt? The document's own words — payee, terms, "on account" — tell
  you.</p></li>
  <li><h3>Which accounts it touches</h3><p>Name every account that changed. A single transaction
  often moves more than two: a sale on account moves a receivable and revenue, and, under
  perpetual inventory, cost and inventory as well (section 6).</p></li>
  <li><h3>Debit or credit, and how much</h3><p>For each account, decide the side from its type in
  section 1, and read the amount from the document. Then check the entry balances before you
  commit it.</p></li>
</ol>
<div class="note"><b>The amount is not always the number printed largest.</b> A cheque paying an
invoice within its discount period settles the full invoice while less cash leaves the bank; the
difference is a discount, not a rounding. Read the terms before you read the total (section 4).</div>

<h2 class="section-lead">4 · Credit terms, and the cash discount</h2>
<p>Goods bought or sold on account carry terms that say when payment is due and whether paying
early earns a discount. They are written as a shorthand you must be able to read on sight. This
set uses these:</p>
<dl class="defs">
  <dt>2/10, n/30</dt><dd>2% off if paid within 10 days; otherwise the net amount is due in 30. On
  a $4,000 invoice, paying by day 10 settles the debt with $3,920 — the $80 is a discount, not a
  part-payment.</dd>
  <dt>1/15, n/30</dt><dd>1% off within 15 days; net in 30.</dd>
  <dt>n/30</dt><dd>No discount. The whole amount is due in 30 days.</dd>
</dl>
<p>Whose discount it is depends on which side you are on. A discount you take for paying a supplier
early reduces the cost of what you bought. A discount a customer takes for paying you early is a
<b>Sales Discount</b> — a contra-revenue, recorded when the customer pays, not when the sale is
made. The days count from the invoice date, so the invoice date is a figure, not decoration.</p>

<h2 class="section-lead">5 · Special journals, subsidiary ledgers, and control accounts</h2>
<p>A general journal can record anything, but a month of a merchandiser's trade is mostly the same
few transactions repeated. A <b>special journal</b> is a page built for one of them, with a named
column for each account that kind of transaction always touches, so a row is a few figures rather
than a full entry. This company keeps these:</p>
<table><tr><th>Journal</th><th>Use it for</th></tr>{journal_rows}</table>
<p>Choosing the journal built for a transaction is part of the work and is marked. A special
journal has a column only for the accounts its transaction type expects; anything else goes in its
<b>Other accounts</b> column or, if it fits no special journal at all, in the general journal. The
general journal is the catch-all — returns, adjustments, the payment that fits nowhere else.</p>

<h3>Control accounts and the ledgers behind them</h3>
<p>You do not need to know the balance owed by every customer to read the balance sheet — you need
the total. So the general ledger keeps one <b>control account</b> for the total
({control_names}), and a separate <b>subsidiary ledger</b> keeps a page per customer or supplier
behind it. Every entry that touches a receivable or a payable is posted twice: once to the control
account in the general ledger, and once to that party's page in the subsidiary ledger.</p>
<div class="eq">sum of the subsidiary ledger pages = the control account balance</div>
<p>That equality is the point of the structure, and the set checks it: if the customers' pages do
not add up to Accounts Receivable, a posting is missing or doubled. Keeping the two in agreement
is marked in its own right. When you post, post both sides — the general ledger and, where a line
names a party, the subsidiary page — or they will not agree.</p>

<h2 class="section-lead">6 · Merchandising: inventory, cost, freight, and returns</h2>
<p>This company buys goods and sells them, and that adds entries a service business never makes.</p>
<dl class="defs">
  <dt>Perpetual inventory and cost of goods sold</dt><dd>The inventory account is kept current as
  goods move, not counted once at period end. So a sale on account is two things in one entry: the
  revenue at selling price, and, in the same breath, the <b>cost</b> of the goods that left —
  debit Cost of Goods Sold, credit Merchandise Inventory. The selling price is on the invoice; the
  cost is given in the set's reference. The sales journal here has columns for both, which is the
  set telling you both belong in the one entry.</dd>
  <dt>Freight on goods you buy (FOB shipping point)</dt><dd>When the terms are FOB shipping point,
  the goods are yours the moment they ship and the freight to bring them in is part of what they
  cost you — it is added to Merchandise Inventory, not expensed. Freight to deliver goods to a
  customer is a different thing and is a selling expense.</dd>
  <dt>Returns and allowances</dt><dd>Goods sent back, or a price reduced after the sale, are not
  erased from Sales. They are recorded in <i>Sales Returns and Allowances</i> (contra-revenue) so
  the books keep both the original sale and the reversal. A purchase returned reduces what you owe
  and the inventory you hold.</dd>
  <dt>Cash sales versus sales on account</dt><dd>A sale for cash is a receipt and lives in the cash
  receipts journal; a sale on account creates a receivable and lives in the sales journal. The
  document tells you which — look for "on account", a customer name, or terms.</dd>
</dl>

<h2 class="section-lead">7 · Posting, the trial balance, and what comes after</h2>
<p>Writing an entry in a journal records it; it does not move it to the accounts. <b>Posting</b>
is that second step, and nothing posts itself. From a special journal you post each column's total
to its account, and each line in an <b>Other accounts</b> column individually; from the general
journal you post line by line. Where a line names a customer or supplier, post it to the
subsidiary ledger as well (section 5). An entry left unposted reaches no ledger and no trial
balance, and is the most common reason a balance looks wrong.</p>
<p>The <b>trial balance</b> lists every account's balance in a debit column or a credit column and
adds them. Because every entry was balanced, the two totals must match. A trial balance that
balances proves the arithmetic, not the judgement: it cannot catch an amount posted to the wrong
account, or a transaction never recorded. It catches only entries that do not balance and totals
that were mis-added.</p>
<div class="panel"><p class="label">The rest of the cycle, for orientation</p>
<p style="margin:0">This set stops at a posted trial balance, but the accounts you see — prepaid
insurance, accumulated depreciation, the allowance for doubtful accounts, salaries payable — exist
because the full cycle continues past it. <b>Adjusting entries</b> at period end record what time
and use consumed (insurance expiring, equipment depreciating, salaries earned but unpaid, a slice
of receivables not expected to pay). <b>Closing entries</b> then empty the revenue and expense
accounts into Retained Earnings so the next period starts at zero. You are not asked to do them
here; you are asked to build books clean enough that someone could.</p></div>

<h2 class="section-lead">A quick glossary</h2>
<div class="cols2">
<dl class="defs">
  <dt>Account</dt><dd>A record of every increase and decrease in one thing the business tracks.</dd>
  <dt>Debit / credit</dt><dd>The left and right side of an account. Which one increases it depends
  on the account's type.</dd>
  <dt>Normal balance</dt><dd>The side an account is expected to sit on — the side that increases
  it.</dd>
  <dt>Contra account</dt><dd>An account deliberately on the opposite side, subtracted from the one
  it follows.</dd>
  <dt>On account</dt><dd>Bought or sold now, paid or collected later; it creates a payable or a
  receivable.</dd>
  <dt>Control account</dt><dd>A general-ledger account holding the total that a subsidiary ledger
  details.</dd>
  <dt>Subsidiary ledger</dt><dd>The per-customer or per-supplier pages that add up to a control
  account.</dd>
  <dt>Special journal</dt><dd>A journal with named columns for one recurring kind of
  transaction.</dd>
  <dt>Perpetual inventory</dt><dd>Inventory kept current as goods move, with cost recorded on each
  sale.</dd>
  <dt>FOB shipping point</dt><dd>Title passes when goods ship; the buyer owns them in transit and
  bears the inbound freight.</dd>
  <dt>Cash discount</dt><dd>A reduction for paying within the discount period, written like
  2/10, n/30.</dd>
  <dt>Posting</dt><dd>Moving a journalised entry into the ledger accounts. A separate, manual
  step.</dd>
  <dt>Trial balance</dt><dd>A list proving total debits equal total credits. Proves arithmetic,
  not judgement.</dd>
</dl>
</div>
<p class="meta">Original Entry · foundations for {esc(company)} · the accounting is yours to apply;
the software is covered in the walkthrough.</p>

</body></html>"""


def main() -> None:
    args = sys.argv[1:]
    source = Path(args[0]) if args else DEFAULT_SOURCE
    src = json.loads(source.read_text())

    out = (source.parent / "foundations.pdf") if args else DEFAULT_OUT

    from weasyprint import HTML  # laptop-only; never imported by the app

    out.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=build_html(src), base_url=str(ROOT)).write_pdf(out)
    print(f"Wrote {out.name} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
