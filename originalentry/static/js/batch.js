// Grading a whole section, a few workspaces at a time (T8.6).
//
// A section of forty is graded in batches so no request comes near the platform's limit. Each
// batch is an ordinary POST to the same endpoint the button already posts to; the server grades
// the next few, commits them, and says how many are left. This file just keeps asking until there
// are none, and shows a bar and a count while it does.
//
// Without this file the button still works: it posts once, grades a batch, and the instructor
// presses it again. This adds the asking-again and the bar — never a different way of working.
//
// Because each batch is committed before the answer is sent, closing the tab loses nothing. The
// count starts from what the server reports, so reopening the screen and pressing Grade again
// carries on from where it stopped.
//
// The decision — keep going, stop, or stop because nothing is happening — is a pure function so
// it can be tested under `node --test tests/js/` without a browser.

/** Read the counts the server put on its answer. `null` when there are none to read. */
export function readProgress(answer) {
  if (!answer || answer.status < 200 || answer.status >= 300) return null;
  const read = (name) => {
    const raw =
      answer.headers?.get(name) ?? answer.headers?.get(name.toLowerCase()) ?? null;
    if (raw === null || raw === "") return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  };
  const graded = read("X-Graded");
  const total = read("X-Total");
  const remaining = read("X-Remaining");
  if (graded === null || total === null || remaining === null) return null;
  // Where this batch stopped. Empty when it graded nothing, and then the cursor does not move.
  return { graded, total, remaining, after: read("X-After") };
}

/**
 * What to do after one batch, given what has been graded so far.
 *
 * `continue` — there is more to grade and the last batch got some of it done.
 * `done`      — the section is graded.
 * `stalled`   — work remains but the batch graded none of it. Asking again would only ask
 *               forever, so the run stops and says so.
 * `failed`    — the server stumbled or said nothing we can read. What was graded is kept.
 */
export function planFor(progress, alreadyDone) {
  const done = Number.isFinite(alreadyDone) ? alreadyDone : 0;
  if (progress === null) {
    return { kind: "failed", done, total: null, after: null };
  }

  const { graded, total, remaining, after } = progress;
  // Never count down and never count past the end: two answers can arrive out of order, and a
  // bar that goes backwards reads as work being undone.
  const counted = Math.min(Math.max(done + graded, done), total);

  if (remaining <= 0) return { kind: "done", done: total, total, after };
  if (graded <= 0) return { kind: "stalled", done: counted, total, after };
  return { kind: "continue", done: counted, total, after };
}

/** Fill the count the page gave us. The wording is the page's; this only puts numbers in it. */
export function countText(template, done, total) {
  if (!template) return "";
  return template.replace("{done}", String(done)).replace("{total}", String(total));
}

// ── the page ────────────────────────────────────────────────────────────────────────────
// Everything below touches the document. The decisions above do not.

const BATCH_HEADER = "X-Batch";

function wire(form) {
  const bar = document.querySelector(form.dataset.batchProgress || "");
  const label = document.querySelector(form.dataset.batchCount || "");
  const template = label?.dataset.template || "";
  const words = {
    stalled: label?.dataset.stalled || "",
    failed: label?.dataset.failed || "",
  };

  form.addEventListener("submit", async (event) => {
    if (!window.fetch) return; // let the ordinary post happen
    event.preventDefault();

    const button = form.querySelector("button[type=submit]");
    if (button) button.disabled = true;
    if (bar) bar.hidden = false;

    let done = 0;
    let total = null;
    let after = null;
    for (;;) {
      const body = new FormData(form);
      // Where the last batch stopped. Without it every batch grades the same workspaces again.
      if (after !== null) body.set("after", String(after));

      let answer = null;
      try {
        answer = await fetch(form.action, {
          method: "POST",
          body,
          headers: { [BATCH_HEADER]: "1" },
          credentials: "same-origin",
        });
      } catch {
        answer = null; // the request never arrived
      }

      const plan = planFor(readProgress(answer), done);
      done = plan.done;
      total = plan.total ?? total;
      after = plan.after ?? after;
      if (bar && total) {
        bar.max = total;
        bar.value = done;
      }
      if (label) label.textContent = countText(template, done, total ?? done);

      if (plan.kind === "continue") continue;
      if (label && plan.kind === "stalled" && words.stalled) {
        label.textContent += ` ${words.stalled}`;
      }
      if (label && plan.kind === "failed" && words.failed) {
        label.textContent += ` ${words.failed}`;
      }
      break;
    }

    if (button) button.disabled = false;
    // The list behind the bar is now out of date whatever happened, so show the marks.
    window.location.reload();
  });
}

if (typeof document !== "undefined") {
  document.querySelectorAll("form[data-batch]").forEach(wire);
}
