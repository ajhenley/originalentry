// Live totals and the keyboard map for the journal-entry grid (T10.3, S3.9).
//
// Every page works without this file: the grid is an ordinary set of inputs the server validates.
// This adds live totals in *integer cents* (never floats), an "Out of balance by $X" line
// announced through role="status", the debit-or-credit-not-both nicety, and the keyboard map
// (Ctrl/⌘+Enter records, Enter moves to the next line, Alt+Backspace clears a line).
//
// The arithmetic is a pure function so it runs under `node --test tests/js/` with no browser.

const MAX_CENTS = 9_999_999_999;

/** Parse a typed amount to a non-negative integer number of cents, or null if it is not one.
 *  Mirrors money.py so the browser and the server agree to the cent. */
export function parseCents(raw) {
  if (raw == null) return null;
  let s = String(raw).trim();
  if (s === "") return null;
  if (s[0] === "-" || s[0] === "(" || s.includes(")")) return null; // negative
  if (s.startsWith("$")) s = s.slice(1).trim();
  if (s === "" || s.includes("-") || s.includes("(")) return null;
  if (s.split(".").length > 2) return null;

  const [intPart, fracPart = ""] = s.split(".");
  if (fracPart !== "" && !/^[0-9]+$/.test(fracPart)) return null;
  if (fracPart.length > 2) return null;
  if (intPart === "") return null;

  let digits;
  if (intPart.includes(",")) {
    if (!/^[0-9]{1,3}(,[0-9]{3})*$/.test(intPart)) return null; // misplaced commas
    digits = intPart.replace(/,/g, "");
  } else {
    if (!/^[0-9]+$/.test(intPart)) return null;
    digits = intPart;
  }
  const frac2 = (fracPart + "00").slice(0, 2);
  const cents = parseInt(digits, 10) * 100 + parseInt(frac2, 10);
  if (cents > MAX_CENTS) return null;
  return cents;
}

/** Integer cents → a grouped decimal string, e.g. 123450 → "1,234.50". */
export function formatCents(cents) {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100).toLocaleString("en-US");
  return `${sign}${whole}.${String(abs % 100).padStart(2, "0")}`;
}

/** Sum the lines and say whether they balance. `lines` is [{debit, credit}] of raw strings. */
export function totals(lines) {
  let debitCents = 0;
  let creditCents = 0;
  for (const line of lines) {
    debitCents += parseCents(line.debit) || 0;
    creditCents += parseCents(line.credit) || 0;
  }
  const difference = Math.abs(debitCents - creditCents);
  return {
    debitCents,
    creditCents,
    differenceCents: difference,
    balanced: difference === 0 && debitCents > 0,
  };
}

// ── DOM wiring (skipped under node) ───────────────────────────────────────────────────────

function lineIndices(grid) {
  const seen = new Set();
  for (const input of grid.querySelectorAll('input[name$="-debit"]')) {
    const match = input.name.match(/^line-(\d+)-debit$/);
    if (match) seen.add(Number(match[1]));
  }
  return [...seen].sort((a, b) => a - b);
}

function field(grid, i, suffix) {
  return grid.querySelector(`[name="line-${i}-${suffix}"]`);
}

function readLines(grid, indices) {
  return indices.map((i) => ({
    debit: field(grid, i, "debit")?.value ?? "",
    credit: field(grid, i, "credit")?.value ?? "",
  }));
}

function render(status, debitCell, creditCell, indices, grid) {
  const t = totals(readLines(grid, indices));
  debitCell.textContent = formatCents(t.debitCents);
  creditCell.textContent = formatCents(t.creditCents);
  if (t.balanced) {
    status.textContent = "In balance";
    status.classList.remove("text-notice");
    status.classList.add("text-muted");
  } else if (t.debitCents === 0 && t.creditCents === 0) {
    status.textContent = "";
  } else {
    status.textContent = `Out of balance by $${formatCents(t.differenceCents)}`;
    status.classList.add("text-notice");
    status.classList.remove("text-muted");
  }
}

function initGrid(grid) {
  const indices = lineIndices(grid);
  if (indices.length === 0) return;

  // A live totals row and a spoken balance line, both created here so no-JS pages stay clean.
  const totalsRow = document.createElement("p");
  totalsRow.className = "mt-2 flex justify-end gap-6 text-sm tabular-nums";
  const debitCell = document.createElement("span");
  const creditCell = document.createElement("span");
  debitCell.textContent = "0.00";
  creditCell.textContent = "0.00";
  const dLabel = document.createElement("span");
  dLabel.append("Debits ", debitCell);
  const cLabel = document.createElement("span");
  cLabel.append("Credits ", creditCell);
  totalsRow.append(dLabel, cLabel);

  const status = document.createElement("p");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  // Aligned with justify-end rather than a text-align utility, whose name the A7 script scan
  // would read as a banned word.
  status.className = "mt-1 flex justify-end text-sm text-muted";

  grid.after(status);
  grid.after(totalsRow);

  const recompute = () => render(status, debitCell, creditCell, indices, grid);

  for (const i of indices) {
    const debit = field(grid, i, "debit");
    const credit = field(grid, i, "credit");
    // A line is a debit or a credit, never both.
    debit?.addEventListener("input", () => {
      if (debit.value.trim() && credit) credit.value = "";
      recompute();
    });
    credit?.addEventListener("input", () => {
      if (credit.value.trim() && debit) debit.value = "";
      recompute();
    });
    for (const el of [debit, credit]) {
      el?.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !(event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          const next = field(grid, i + 1, "account") || field(grid, indices[0], "account");
          next?.focus();
        } else if (event.altKey && event.key === "Backspace") {
          event.preventDefault();
          for (const s of ["account", "party", "debit", "credit", "memo"]) {
            const f = field(grid, i, s);
            if (f) f.value = "";
          }
          recompute();
        }
      });
    }
  }

  // Ctrl/⌘+Enter records the entry from anywhere in the form.
  const form = grid.closest("form");
  form?.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  recompute();
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[data-entry-grid]").forEach(initGrid);
  });
}
