// What save.js decides, given an answer from the server (T7.4, A26).
//
// The decision is kept apart from the page on purpose: the part that must never be wrong — when
// to retry, when to give up, when the work must be kept for later — is a pure function, and this
// file runs it under node's own test runner. No browser, no toolchain, no npm.
//
//   node --test tests/js/

import assert from "node:assert/strict";
import test from "node:test";

import { BACKOFF_MS, delayFor, planFor } from "../../originalentry/static/js/save.js";

const answer = (status, headers = {}) => ({ status, headers: new Map(Object.entries(headers)) });

test("a saved entry sends the browser where the server says", () => {
  const plan = planFor(answer(200, { "X-Redirect-To": "/w/abc/co/journals/general" }));

  assert.equal(plan.kind, "navigate");
  assert.equal(plan.to, "/w/abc/co/journals/general");
});

test("a saved entry that arrived late says the tab has fallen behind", () => {
  const plan = planFor(answer(200, { "X-Redirect-To": "/x", "X-Workspace-Stale": "1" }));

  assert.equal(plan.kind, "navigate");
  assert.equal(plan.stale, true);
});

test("a refusal comes back as the form, and is not retried", () => {
  const plan = planFor(answer(422));

  assert.equal(plan.kind, "replace");
  assert.equal(plan.retry, false);
});

test("closed books are not retried either — there is nothing to retry", () => {
  const plan = planFor(answer(423, { "X-Redirect-To": "/w/abc/co/journals/general" }));

  assert.equal(plan.kind, "navigate");
  assert.equal(plan.retry, false);
});

test("an expired session keeps the entry and goes to sign in", () => {
  const plan = planFor(answer(401, { "X-Redirect-To": "/auth/sign-in" }));

  assert.equal(plan.kind, "sign-in");
  assert.equal(plan.keepDraft, true);
  assert.equal(plan.to, "/auth/sign-in");
});

test("a server that is having trouble is retried", () => {
  for (const status of [500, 502, 503, 504]) {
    const plan = planFor(answer(status));
    assert.equal(plan.kind, "retry", `status ${status}`);
    assert.equal(plan.keepDraft, true);
  }
});

test("no answer at all — the network dropped — is retried", () => {
  const plan = planFor(null);

  assert.equal(plan.kind, "retry");
  assert.equal(plan.keepDraft, true);
});

test("anything else is shown to the student rather than swallowed", () => {
  const plan = planFor(answer(418));

  assert.equal(plan.kind, "stuck");
  assert.equal(plan.keepDraft, true);
});

test("the wait between tries grows, then settles", () => {
  const waits = [0, 1, 2, 3, 4, 5, 9].map(delayFor);

  assert.deepEqual(waits.slice(0, BACKOFF_MS.length), BACKOFF_MS);
  assert.equal(delayFor(9), BACKOFF_MS[BACKOFF_MS.length - 1]);
  assert.ok(waits.every((wait, i) => i === 0 || wait >= waits[i - 1]));
});
