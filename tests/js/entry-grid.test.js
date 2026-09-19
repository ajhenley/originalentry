// The entry grid's arithmetic (T10.3): parse to integer cents, format, and total — the same rules
// as money.py, so the browser's live total agrees with the server to the cent.
//
//   node --test tests/js/

import assert from "node:assert/strict";
import test from "node:test";

import { formatCents, parseCents, totals } from "../../parchment/static/js/entry-grid.js";

test("parseCents accepts the shapes money.py accepts", () => {
  assert.equal(parseCents("1234.5"), 123450);
  assert.equal(parseCents("1,234.50"), 123450);
  assert.equal(parseCents("$1,234.50"), 123450);
  assert.equal(parseCents("5"), 500);
  assert.equal(parseCents("0.01"), 1);
});

test("parseCents rejects what money.py rejects", () => {
  for (const bad of ["1.234", "-5", "(5)", "1,23", "12,34", "", "abc", "1.2.3"]) {
    assert.equal(parseCents(bad), null, bad);
  }
});

test("formatCents groups and pads", () => {
  assert.equal(formatCents(123450), "1,234.50");
  assert.equal(formatCents(5), "0.05");
  assert.equal(formatCents(0), "0.00");
});

test("totals balance when debits equal credits", () => {
  const t = totals([
    { debit: "1,200.00", credit: "" },
    { debit: "", credit: "1,200.00" },
  ]);
  assert.equal(t.debitCents, 120000);
  assert.equal(t.creditCents, 120000);
  assert.equal(t.balanced, true);
  assert.equal(t.differenceCents, 0);
});

test("totals report the gap when out of balance", () => {
  const t = totals([
    { debit: "1,200.00", credit: "" },
    { debit: "", credit: "1,000.00" },
  ]);
  assert.equal(t.balanced, false);
  assert.equal(t.differenceCents, 20000);
});

test("an empty grid is not 'balanced'", () => {
  assert.equal(totals([{ debit: "", credit: "" }]).balanced, false);
});
