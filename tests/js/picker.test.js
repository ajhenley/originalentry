// The picker's matching (T10.3, M3.6): normalise to letters and digits, then substring-match on
// the label or the value — so "4871" finds "Invoice 4871" and "112" finds account 112.
//
//   node --test tests/js/

import assert from "node:assert/strict";
import test from "node:test";

import { filterOptions, normalize } from "../../originalentry/static/js/picker.js";

const ACCOUNTS = [
  { value: "112", label: "112 · Accounts Receivable" },
  { value: "401", label: "401 · Sales Revenue" },
  { value: "611", label: "611 · Depreciation Expense" },
];
const DOCS = [
  { value: "INV-4871", label: "Invoice 4871" },
  { value: "CHQ-208", label: "Cheque 208" },
];

test("normalize keeps only letters and digits, lower-cased", () => {
  assert.equal(normalize("INV-4871"), "inv4871");
  assert.equal(normalize("112 · Accounts Receivable"), "112accountsreceivable");
});

test("an account matches by number or by name", () => {
  assert.deepEqual(filterOptions(ACCOUNTS, "112").map((o) => o.value), ["112"]);
  assert.deepEqual(filterOptions(ACCOUNTS, "receiv").map((o) => o.value), ["112"]);
  assert.deepEqual(filterOptions(ACCOUNTS, "sales").map((o) => o.value), ["401"]);
});

test("a document matches any part of its reference", () => {
  assert.deepEqual(filterOptions(DOCS, "4871").map((o) => o.value), ["INV-4871"]);
  assert.deepEqual(filterOptions(DOCS, "cheque").map((o) => o.value), ["CHQ-208"]);
});

test("an empty query returns everything; a miss returns nothing", () => {
  assert.equal(filterOptions(ACCOUNTS, "").length, 3);
  assert.equal(filterOptions(ACCOUNTS, "zzz").length, 0);
});
