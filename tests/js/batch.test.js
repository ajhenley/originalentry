// What batch.js decides between one batch of grading and the next (T8.6).
//
// Grading a section of forty happens a few workspaces at a time, so no request comes near the
// limit. The part that must never be wrong — keep going, stop, or stop because nothing is
// happening — is a pure function, and this file runs it under node's own test runner.
//
//   node --test tests/js/

import assert from "node:assert/strict";
import test from "node:test";

import { countText, planFor, readProgress } from "../../originalentry/static/js/batch.js";

const answer = (status, headers = {}) => ({ status, headers: new Map(Object.entries(headers)) });

const progress = (graded, total, remaining, after = 1) =>
  answer(200, {
    "X-Graded": String(graded),
    "X-Total": String(total),
    "X-Remaining": String(remaining),
    "X-After": String(after),
  });

test("a batch that leaves work to do asks for another", () => {
  const plan = planFor(readProgress(progress(5, 40, 35)), 0);

  assert.equal(plan.kind, "continue");
  assert.equal(plan.done, 5);
  assert.equal(plan.total, 40);
});

test("the count carries across batches", () => {
  const plan = planFor(readProgress(progress(5, 40, 30)), 5);

  assert.equal(plan.done, 10);
  assert.equal(plan.kind, "continue");
});

test("a batch that finishes the section stops", () => {
  const plan = planFor(readProgress(progress(5, 40, 0)), 35);

  assert.equal(plan.kind, "done");
  assert.equal(plan.done, 40);
});

test("a batch that grades nothing while work remains stops rather than looping", () => {
  // The failure this guards against: a workspace the engine cannot grade, asked for forever.
  const plan = planFor(readProgress(progress(0, 40, 12)), 28);

  assert.equal(plan.kind, "stalled");
  assert.equal(plan.done, 28);
});

test("a server that stumbles stops the run and keeps what was graded", () => {
  const plan = planFor(readProgress(answer(503)), 15);

  assert.equal(plan.kind, "failed");
  assert.equal(plan.done, 15);
});

test("a request that never arrived stops the run", () => {
  const plan = planFor(readProgress(null), 15);

  assert.equal(plan.kind, "failed");
  assert.equal(plan.done, 15);
});

test("a refusal is not treated as progress", () => {
  const plan = planFor(readProgress(answer(403)), 0);

  assert.equal(plan.kind, "failed");
  assert.equal(plan.done, 0);
});

test("the count never goes backwards", () => {
  // Two answers racing, the later one older. The screen must not count down.
  const plan = planFor(readProgress(progress(0, 40, 40)), 20);

  assert.equal(plan.done, 20);
});

test("the count is never more than the section holds", () => {
  const plan = planFor(readProgress(progress(50, 40, 0)), 38);

  assert.equal(plan.done, 40);
});

test("an answer with no counts in it is a failure, not a silent stop", () => {
  const plan = planFor(readProgress(answer(200)), 7);

  assert.equal(plan.kind, "failed");
  assert.equal(plan.done, 7);
});

test("the count reads as words a person would say", () => {
  assert.equal(countText("Graded {done} of {total}.", 25, 40), "Graded 25 of 40.");
});

test("the wording comes from the page, never from this file", () => {
  // Every string a person reads lives in messages.py and arrives as a data attribute.
  assert.equal(countText("", 1, 2), "");
});

// ── Carrying the cursor ─────────────────────────────────────────────────────────────────
//
// Each batch says where it stopped. Without sending that back, the next request would grade the
// same workspaces again and the section could never be finished.

test("a batch says where the next one should start", () => {
  const plan = planFor(readProgress(progress(5, 40, 35, 105)), 0);

  assert.equal(plan.after, 105);
});

test("the cursor is carried even when the run is over", () => {
  const plan = planFor(readProgress(progress(5, 40, 0, 140)), 35);

  assert.equal(plan.kind, "done");
  assert.equal(plan.after, 140);
});

test("a batch that graded nothing leaves the cursor where it was", () => {
  const plan = planFor(readProgress(progress(0, 40, 12, "")), 28);

  assert.equal(plan.after, null);
});
