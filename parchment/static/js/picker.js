// A filtering combobox over a native <select> (T10.3, M3.6, A17).
//
// Progressive enhancement: the native <select> stays in the form and keeps its value, so without
// JavaScript everything works. This lays an ARIA 1.2 combobox on top so a student can type part of
// an account number or name — or any part of a document reference — and choose with the keyboard.
//
// The matching is a pure function, tested under `node --test tests/js/`.

/** Letters and digits only, lower-cased — so "INV-4871" and "inv 4871" match "4871". */
export function normalize(s) {
  return String(s ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** Options whose value or label contains the query (normalised). Empty query returns all. */
export function filterOptions(options, query) {
  const q = normalize(query);
  if (!q) return options;
  return options.filter(
    (o) => normalize(o.label).includes(q) || normalize(o.value).includes(q)
  );
}

// ── DOM wiring (skipped under node) ───────────────────────────────────────────────────────

let counter = 0;

function optionsOf(select) {
  return [...select.options]
    .filter((o) => o.value !== "")
    .map((o) => ({ value: o.value, label: o.textContent.trim() }));
}

function labelText(select) {
  const explicit = select.id && document.querySelector(`label[for="${select.id}"]`);
  return (explicit?.textContent || select.getAttribute("aria-label") || select.name || "").trim();
}

function initPicker(select) {
  const options = optionsOf(select);
  const id = `picker-${(counter += 1)}`;

  // Hide the native control from view and AT; it still submits the chosen value.
  select.classList.add("sr-only");
  select.setAttribute("tabindex", "-1");
  select.setAttribute("aria-hidden", "true");

  const wrap = document.createElement("div");
  wrap.className = "relative";

  const input = document.createElement("input");
  input.type = "text";
  input.setAttribute("role", "combobox");
  input.setAttribute("aria-expanded", "false");
  input.setAttribute("aria-autocomplete", "list");
  input.setAttribute("aria-controls", `${id}-list`);
  input.setAttribute("aria-label", labelText(select));
  input.autocomplete = "off";
  input.className = "w-full rounded border border-rule px-2 py-1";
  const chosen = select.options[select.selectedIndex];
  if (chosen && chosen.value) input.value = chosen.textContent.trim();

  const list = document.createElement("ul");
  list.id = `${id}-list`;
  list.setAttribute("role", "listbox");
  list.className =
    "absolute z-10 mt-1 hidden max-h-60 w-full overflow-auto rounded border border-rule bg-paper text-sm shadow";

  wrap.append(input, list);
  select.after(wrap);

  let active = -1;
  let shown = [];

  const close = () => {
    list.classList.add("hidden");
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    active = -1;
  };

  const commit = (option) => {
    select.value = option ? option.value : "";
    input.value = option ? option.label : "";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    close();
  };

  const paint = () => {
    list.innerHTML = "";
    if (shown.length === 0) {
      const empty = document.createElement("li");
      empty.className = "px-2 py-1 text-muted";
      empty.textContent = "No matches";
      list.append(empty);
    }
    shown.forEach((option, i) => {
      const li = document.createElement("li");
      li.id = `${id}-opt-${i}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", i === active ? "true" : "false");
      li.className = `cursor-pointer px-2 py-1 ${i === active ? "bg-rule/50" : ""}`;
      li.textContent = option.label;
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        commit(option);
      });
      list.append(li);
    });
    if (active >= 0) input.setAttribute("aria-activedescendant", `${id}-opt-${active}`);
    else input.removeAttribute("aria-activedescendant");
  };

  const open = () => {
    shown = filterOptions(options, input.value);
    active = -1;
    list.classList.remove("hidden");
    input.setAttribute("aria-expanded", "true");
    paint();
  };

  input.addEventListener("input", () => {
    open();
    if (input.value.trim() === "") commit(null);
  });
  input.addEventListener("focus", open);
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (list.classList.contains("hidden")) open();
      active = Math.min(active + 1, shown.length - 1);
      paint();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      active = Math.max(active - 1, 0);
      paint();
    } else if (event.key === "Enter") {
      if (!list.classList.contains("hidden") && active >= 0) {
        event.preventDefault();
        commit(shown[active]);
      }
    } else if (event.key === "Escape") {
      close();
    }
  });
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("select[data-picker]").forEach(initPicker);
  });
}
