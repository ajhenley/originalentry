// Saving without losing anything (T7.4, S3.10, A26).
//
// The failure this app is designed against is a student losing an entry the night before a
// deadline. So a form marked data-save is submitted through here instead of by the browser: if the
// network drops or the server stumbles, the fields stay exactly as they were, the entry is kept in
// this browser as well, and the save is tried again. Because every save carries a client_key, and
// the server treats the same key twice as one entry, retrying is always safe.
//
// Without this file every one of those forms is an ordinary POST that works. This adds the
// retrying, the keeping and the banner — never a different way of working.
//
// The decision — retry, replace, navigate, give up — is a pure function so it can be tested under
// `node --test tests/js/` without a browser.

export const BACKOFF_MS = [2000, 4000, 8000, 16000, 30000];
export const RETRY_STATUSES = new Set([500, 502, 503, 504, 507, 522, 524]);
export const DRAFT_PREFIX = "parchment.draft.";

/** How long to wait before the nth retry. It grows, then settles at the last step. */
export function delayFor(attempt) {
  return BACKOFF_MS[Math.min(attempt, BACKOFF_MS.length - 1)];
}

function header(answer, name) {
  if (!answer || !answer.headers) return null;
  return answer.headers.get(name) ?? answer.headers.get(name.toLowerCase()) ?? null;
}

/**
 * What to do about one answer from the server.
 *
 * `null` means the request never arrived — the network dropped, or the page is offline.
 */
export function planFor(answer) {
  if (!answer) {
    return { kind: "retry", retry: true, keepDraft: true };
  }

  const to = header(answer, "X-Redirect-To");
  const savedAt = header(answer, "X-Saved-At");

  if (answer.status >= 200 && answer.status < 300) {
    return {
      kind: "navigate",
      retry: false,
      keepDraft: false,
      to,
      savedAt,
      stale: header(answer, "X-Workspace-Stale") === "1",
    };
  }
  if (answer.status === 401) {
    return { kind: "sign-in", retry: false, keepDraft: true, to };
  }
  if (answer.status === 422) {
    return { kind: "replace", retry: false, keepDraft: true };
  }
  if (answer.status === 423) {
    // The books are closed or read-only. There is nothing to retry, and the student needs to
    // read why — so the entry stays kept, and the page says where to look.
    return { kind: "navigate", retry: false, keepDraft: true, to };
  }
  if (RETRY_STATUSES.has(answer.status)) {
    return { kind: "retry", retry: true, keepDraft: true };
  }
  return { kind: "stuck", retry: false, keepDraft: true };
}

// ── the page ────────────────────────────────────────────────────────────────────────────

function banner() {
  return document.getElementById("connection-banner");
}

// The words themselves live in messages.py and are rendered onto the banner, so the interface has
// one place its strings live and the A7 guard sees them all (Part I §4).
function words() {
  const data = banner()?.dataset ?? {};
  return {
    retrying: data.retrying ?? "",
    stale: data.stale ?? "",
    stuck: data.stuck ?? "",
    unreachable: (time) => (data.unreachable ?? "").replace("{time}", time),
  };
}

function say(text, tone = "muted") {
  const region = banner();
  if (!region) return;
  region.textContent = text;
  region.className = text
    ? `px-4 py-2 text-sm ${tone === "attention" ? "bg-attention/10 text-attention" : "text-muted"}`
    : "";
}

function timeNow() {
  return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Everything typed into the form, so it can be put back. */
function draftOf(form) {
  const data = new FormData(form);
  const draft = {};
  for (const [name, value] of data.entries()) {
    if (name !== "csrf_token" && typeof value === "string") draft[name] = value;
  }
  return draft;
}

function draftKey(form) {
  const key = form.querySelector("[name='client_key']")?.value || "form";
  return `${DRAFT_PREFIX}${window.location.pathname}.${key}`;
}

// Storage can be unavailable — a private window, blocked site data — and that must not stop a
// save. The offline copy is a convenience; the server is the record.
function keep(form) {
  try {
    window.localStorage.setItem(draftKey(form), JSON.stringify(draftOf(form)));
  } catch {
    /* no offline copy this time */
  }
}

function forget(form) {
  try {
    window.localStorage.removeItem(draftKey(form));
  } catch {
    /* nothing to forget */
  }
}

function restore(form) {
  let saved = null;
  try {
    saved = window.localStorage.getItem(draftKey(form));
  } catch {
    return;
  }
  if (!saved) return;
  let draft;
  try {
    draft = JSON.parse(saved);
  } catch {
    return;
  }
  for (const [name, value] of Object.entries(draft)) {
    const field = form.elements.namedItem(name);
    if (field && !field.value) field.value = value;
  }
}

function replaceForm(form, html) {
  const parsed = new DOMParser().parseFromString(html, "text/html");
  const fresh = parsed.querySelector("form[data-save]");
  if (!fresh) {
    form.submit(); // the answer was not a form we understand: let the browser have it
    return;
  }
  form.replaceWith(fresh);
  enhance(fresh);
  const summary = document.querySelector("[role='alert']");
  if (summary) {
    summary.setAttribute("tabindex", "-1");
    summary.focus();
  }
}

async function send(form) {
  const body = new FormData(form);
  try {
    const response = await fetch(form.action, {
      method: "POST",
      body,
      headers: { "X-Parchment-Save": "1" },
      credentials: "same-origin",
    });
    return { response, plan: planFor(response) };
  } catch {
    return { response: null, plan: planFor(null) };
  }
}

function enhance(form) {
  if (form.dataset.saveReady === "1") return;
  form.dataset.saveReady = "1";
  restore(form);

  let attempt = 0;
  let sending = false;
  let lastSaved = null;

  async function attemptSave() {
    if (sending) return;
    sending = true;
    keep(form);
    const { response, plan } = await send(form);
    sending = false;

    if (!plan.keepDraft) forget(form);

    switch (plan.kind) {
      case "navigate":
        lastSaved = plan.savedAt;
        if (plan.stale) say(words().stale, "attention");
        window.location.assign(plan.to || window.location.href);
        return;
      case "sign-in":
        window.location.assign(plan.to || "/auth/sign-in");
        return;
      case "replace":
        say("");
        replaceForm(form, await response.text());
        return;
      case "retry": {
        const wait = delayFor(attempt);
        attempt += 1;
        const said = words();
        say(
          attempt >= 3
            ? said.unreachable(lastSaved ? new Date(lastSaved).toLocaleTimeString() : timeNow())
            : said.retrying,
          "attention",
        );
        window.setTimeout(attemptSave, wait);
        return;
      }
      default:
        say(words().stuck, "attention");
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    attempt = 0;
    say(words().retrying);
    attemptSave();
  });

  // Keep what is typed, so a closed tab or a crash costs nothing either.
  form.addEventListener("input", () => keep(form));
}

if (typeof document !== "undefined") {
  document.querySelectorAll("form[data-save]").forEach(enhance);
}
