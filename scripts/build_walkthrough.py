"""A printable walkthrough for working one company in Original Entry.

    python scripts/build_walkthrough.py [packs/riverbend/source.json] [out.pdf]

The paper practice set already has an instruction booklet, and it covers the accounting: terms,
freight, the discount periods. What it cannot cover is the software, because the software did not
exist when it was written. This is that missing half, and only that half.

Everything company-specific is read from the pack source, so the walkthrough cannot drift from
the company a student actually opens: the journals are named from the pack's journals, the
document count is counted, the checkpoints are quoted from their own prompts.

**It gives away no answers.** The worked example uses a transaction that is deliberately not in
the set, so every mechanical step can be shown in full without leaking one of the twenty-eight
the student has to judge for themselves.

WeasyPrint is a laptop-only dependency, like Pillow for the pack generator (T16). It is not in
requirements.txt and Heroku never sees it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "packs" / "riverbend" / "source.json"
DEFAULT_OUT = ROOT / "packs" / "riverbend" / "walkthrough.pdf"
FONTS = ROOT / "originalentry" / "static" / "fonts"

# The app's own tokens, so the paper matches the screen.
CSS = """
@page { size: Letter; margin: 18mm 16mm 16mm 16mm;
        @bottom-center { content: counter(page) " of " counter(pages);
                         font-family: oe-mono; font-size: 8pt; color: #6b7688; } }
@page :first { @bottom-center { content: ""; } }
@font-face { font-family: oe-display; src: url("FONTS/dm-serif-display-400.woff2"); }
@font-face { font-family: oe-sans; src: url("FONTS/outfit-400.woff2"); }
@font-face { font-family: oe-sans; font-weight: 600; src: url("FONTS/outfit-600.woff2"); }
@font-face { font-family: oe-mono; src: url("FONTS/jetbrains-mono-400.woff2"); }
body { font-family: oe-sans, "Helvetica Neue", sans-serif; font-size: 10.5pt; line-height: 1.55;
       color: #1e2532; }
h1, h2, h3 { font-family: oe-display, Georgia, serif; color: #1b3a5c; font-weight: 400; }
h1 { font-size: 30pt; line-height: 1.1; margin: 0 0 6pt; }
h2 { font-size: 16pt; margin: 22pt 0 6pt; break-after: avoid; }
h3 { font-size: 12pt; margin: 14pt 0 3pt; break-after: avoid; }
p { margin: 0 0 8pt; max-width: 34em; }
.lede { font-size: 12pt; color: #4a5568; }
.label { font-family: oe-mono; font-size: 7.5pt; letter-spacing: .14em; text-transform: uppercase;
         color: #1f7a6e; margin: 0 0 4pt; }
.meta { font-family: oe-mono; font-size: 8pt; color: #6b7688; }
.cover { border-bottom: 3px solid #1b3a5c; padding-bottom: 14pt; margin-bottom: 14pt; }
ol.steps { padding-left: 0; list-style: none; counter-reset: s; }
ol.steps > li { counter-increment: s; border-left: 2px solid #e2e6ee; padding: 0 0 0 10pt;
                margin: 0 0 11pt; break-inside: avoid; }
ol.steps > li::before { content: "Step " counter(s); font-family: oe-mono; font-size: 7.5pt;
                        letter-spacing: .12em; text-transform: uppercase; color: #6b7688;
                        display: block; }
ol.steps h3 { margin: 1pt 0 2pt; }
table { width: 100%; border-collapse: collapse; font-size: 9.5pt; margin: 6pt 0 10pt;
        break-inside: avoid; }
th { text-align: left; font-weight: 600; border-bottom: 1px solid #1b3a5c; padding: 3pt 6pt 3pt 0;
     font-size: 8.5pt; }
td { border-bottom: 1px solid #e2e6ee; padding: 3pt 6pt 3pt 0; vertical-align: top; }
td.fig, th.fig { font-family: oe-mono; text-align: right; padding-right: 0; }
.panel { border: 1px solid #e2e6ee; border-radius: 6pt; padding: 9pt 11pt; margin: 8pt 0 10pt;
         background: #fcfcfd; break-inside: avoid; }
.panel h3 { margin-top: 0; }
.note { border-left: 3px solid #e9c46a; padding: 2pt 0 2pt 9pt; margin: 8pt 0;
        background: #fffdf7; break-inside: avoid; }
.note b { color: #8a5a00; }
.screen { font-family: oe-mono; font-size: 9pt; background: #f4f6f9; border: 1px solid #e2e6ee;
          border-radius: 4pt; padding: 7pt 9pt; margin: 5pt 0 9pt; break-inside: avoid; }
.you { font-weight: 600; }
section { break-inside: auto; }
.newpage { break-before: page; }
"""


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_html(src: dict) -> str:
    company = src["company"]["name"]
    period = src["period"]
    documents = src["documents"]
    journals = src["journals"]
    checkpoints = src["checkpoints"]
    versions = ", ".join(v["code"] for v in src["variants"])
    accounts = len(src["accounts"])

    journal_rows = "".join(
        f"<tr><td><b>{esc(j['name'])}</b></td><td>{esc(WHAT_FOR.get(j['key'], ''))}</td></tr>"
        for j in journals
    )
    checkpoint_rows = "".join(
        f"<tr><td class='fig' style='text-align:left'>{c['ordinal']}</td>"
        f"<td>{esc(c['prompt'])}</td></tr>"
        for c in sorted(checkpoints, key=lambda c: c["ordinal"])
    )
    steps = "".join(
        f"<li><h3>{esc(title)}</h3><p>{body}</p></li>" for title, body in STEPS
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Walkthrough — {esc(company)}</title>
<style>{CSS.replace('FONTS', FONTS.as_uri())}</style></head>
<body>

<div class="cover">
  <p class="label">Original Entry · walkthrough</p>
  <h1>{esc(company)}</h1>
  <p class="lede">Keeping the books for {period['start']} to {period['end']}, on screen.</p>
  <p class="meta">{len(documents)} documents · {len(journals)} journals · {accounts} accounts ·
     versions {versions}</p>
</div>

<p class="lede">Your instruction booklet covers the accounting. This covers the software: what
each screen is for, which steps are yours, and the two things the app works out for itself.</p>

<div class="note"><b>Nothing here happens on its own.</b> Entries are written, postings are
posted, checkpoints are asked. The ledgers and the trial balance are the only things the app
derives, and it derives them from what you posted.</div>

<h2>The order of work</h2>
<ol class="steps">{steps}</ol>

<section class="newpage">
<h2>A worked example</h2>
<p>This transaction is <b>not</b> one of your {len(documents)}. It is here so every step can be
shown in full without answering anything you are meant to judge yourself.</p>

<div class="panel">
  <p class="label">The document</p>
  <p style="margin:0"><b>Cheque 9001</b>, 3 December. Paid Marlow Window Cleaning $60.00 for
  cleaning the shop front.</p>
</div>

<h3>1. On the document, say what it needs</h3>
<p>It is a transaction, so choose <span class="you">Record an entry</span>. That marks the
decision and nothing more: no entry exists yet.</p>
<div class="screen">Documents › Cheque 9001<br>
[ Record an entry ]&nbsp;&nbsp;[ No entry required ]</div>

<h3>2. Choose the journal</h3>
<p>Money left the business by cheque, so it belongs in the <b>Cash Payments Journal</b>. Choosing
the journal built for a transaction is part of what is marked.</p>

<h3>3. Write the lines</h3>
<p>Enter the accounts and the amounts. The app checks two mechanical things: that the entry
balances, and that the journal has a column for each account you used. It says which of those
failed and nothing else, because the accounts you chose are your judgement.</p>
<table>
  <tr><th>Account</th><th class="fig">Debit</th><th class="fig">Credit</th></tr>
  <tr><td>Some expense account, as you judge it</td>
      <td class="fig">60.00</td><td class="fig"></td></tr>
  <tr><td>101 Cash</td><td class="fig"></td><td class="fig">60.00</td></tr>
</table>
<div class="note"><b>The app never names the account for you.</b> It is shown here as a blank on
purpose; deciding it is the work.</div>

<h3>4. Post it</h3>
<p>Back in the journal, choose <span class="you">Post to the general ledger</span>. Until you do,
the entry sits in the journal and reaches no ledger and no trial balance. Where a line names a
customer or a supplier, post it to the subsidiary ledger as well.</p>
<div class="screen">Journals › Cash Payments Journal<br>[ Post to the general ledger ]</div>

<h3>5. Read the result</h3>
<p>Cash in the general ledger is now $60.00 lower, and the trial balance has moved with it. You
typed neither figure: both are worked out from the entry you posted.</p>
</section>

<section class="newpage">
<h2>The journals, and what each is for</h2>
<table><tr><th>Journal</th><th>Use it for</th></tr>{journal_rows}</table>
<p>A special journal has named columns, and it will refuse a line it has no column for. That
refusal is about the journal, not about the account: the general journal takes anything.</p>

<h2>Checkpoints</h2>
<p>A checkpoint asks for one figure from your own books. Type what you reached and choose
<span class="you">Check</span>. It says whether your figure agrees with the books you built, and
nothing about how you got there. Attempts are limited, so work it out before you try.</p>
<table><tr><th style="width:3em">#</th><th>It asks for</th></tr>{checkpoint_rows}</table>

<h2>What the app refuses, and why</h2>
<table>
  <tr><th>You will see</th><th>It means</th></tr>
  <tr><td>This entry does not balance</td>
      <td>Debits and credits differ. Arithmetic, not judgement.</td></tr>
  <tr><td>This journal has no column for that account</td><td>Either the account or the journal is
      not the one you want. Both are yours to decide.</td></tr>
  <tr><td>These books are read-only</td><td>You submitted, or the deadline passed. Your instructor
      can give the books back.</td></tr>
</table>
<p>A refusal is always mechanical. The app never comments on the accounts you chose or the
figures you entered, and it never reacts differently to a mistake it was built to expect.</p>

<h2>When you are stuck</h2>
<p>Read the document again before changing an entry: most of what looks like a problem with the
software is a detail on the paper, and the terms, the freight and the discount periods are all
printed there. <b>Reference</b> in the workspace holds this company's chart of accounts. After
that, ask your instructor, who can see where you are and what the app last refused.</p>

<div class="note"><b>Your figures are your own.</b> {esc(company)} comes in versions
{versions}, and they differ by design. A classmate's numbers will not match yours even where the
method is identical.</div>
</section>

</body></html>"""


WHAT_FOR = {
    "sales": "Sales on account. Not cash sales.",
    "purchases": "Anything bought on account, from inventory to office supplies.",
    "cash_receipts": "Every receipt of money, including cash sales and payments from customers.",
    "cash_payments": "Every payment of money: cheques, remittances, payroll.",
    "general": "Anything the four special journals have no column for.",
}

STEPS = [
    ("Documents", "Read each one and decide whether it is a transaction to record. "
     "<span class='you'>Record an entry</span> marks that decision; it does not write the entry. "
     "Where a document needs nothing, choose <span class='you'>No entry required</span> and say "
     "why. That reason is part of the work and it is marked."),
    ("Journals", "Pick the journal built for that kind of transaction, then enter the accounts "
     "and amounts."),
    ("Post", "Move the entries to the ledgers yourself, to the general ledger and to the "
     "subsidiary ledgers where a line names a customer or a supplier. Nothing posts itself."),
    ("Ledgers", "Derived from what you posted, so there is nothing to type. A balance that "
     "surprises you points at the entry or the posting behind it."),
    ("Trial balance", "Also derived. If the columns do not agree, something is unposted or an "
     "entry carries a figure it should not."),
    ("Checkpoints", "Test a figure you reached against the books you built."),
    ("Submit", "Hands the books in and makes them read-only. Handed in by accident? Your "
     "instructor can give them back."),
]


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    src = json.loads(source.read_text())

    from weasyprint import HTML  # laptop-only (T16); never imported by the app

    html = build_html(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=str(ROOT)).write_pdf(out)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
