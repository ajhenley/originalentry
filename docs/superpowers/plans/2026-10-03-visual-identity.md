# Visual Identity Restyle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle Original Entry to the supplied visual identity — two typefaces, a warm paper palette, 3px radii, and the app's first logo and favicon — without changing a single behaviour.

**Architecture:** The templates already name colours semantically (`text-muted` alone is 162 of 279 palette uses), so this is chiefly a Tailwind `@theme` redefinition. The risky part is that Tailwind emits *nothing* for an undefined utility, so a deleted token with a surviving reference renders unstyled with no error. The plan therefore builds a guard for exactly that first, adds new tokens before removing old ones, and never leaves the tree in a state where a token is referenced but undefined.

**Tech Stack:** Flask 3.1 + Jinja2, Tailwind CSS v4 (standalone CLI `bin/tailwindcss`, v4.1.14, gitignored; `dist/app.css` committed so deploys need no Node), pytest.

**Spec:** `docs/superpowers/specs/2026-10-03-visual-identity-design.md`

## Global Constraints

- **No behaviour changes.** No route, view, model, grading, or pack-handling change. All 721 existing tests must stay green.
- **Exactly one existing test may be edited:** `tests/integration/test_account_menu.py:180`, `text-navy` → `text-ink`. Its stated intent ("legible on cream") is unchanged.
- **Rebuild command:** `./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify`. The binary exists locally and is gitignored; `dist/app.css` **is** committed.
- **A control's border must never use `--color-rule`** (1.41:1). Controls use `--color-muted` (5.80:1). `rule` is for decorative dividers only, which WCAG 1.4.11 exempts.
- **No font CDN.** Faces are served from `static/fonts/`. The OFL requires each licence file travel with its font.
- **CSP:** `style-src 'self' 'nonce-…'`. No inline `style` attribute, ever. The company accent keeps its existing nonce'd `<style>` block.
- **Colour never means correctness (A7).** `notice` = mechanical states, `failure` = the app's own trouble, `company` = whose books these are. Nothing says whether work is any good.
- **Weights available:** Source Serif 4 at 400; Source Sans 3 at 400 and 600. There is no 500 and **no monospace face**.
- **Token values, verbatim:** `ink #292824`, `paper #FAF8F4`, `white #ffffff`, `muted #65615A`, `rule #D8D3C9`, `notice #805000`, `wash #FFF2D5`, `failure #A12B2B`, `tint #EAE6DE`, `company #1B3A5C`.
- Run the suite **one at a time**. Two concurrent pytest runs against the shared Neon Postgres deadlock.

## Review Focus

Five things the spec implies that no task above would otherwise test. Each has a test assigned to the task that owns the code.

1. **A pack accent invisible on the new ink chrome.** V13 checks `accent_hex` against **white only** (`validate.py:_v13_contrast` → `_contrast_against_white`). A pack shipping an accent near `#292824` passes V13 and renders a `bg-company` stripe indistinguishable from the `bg-ink` header beside it — destroying the one signal that tells a student whose books they are in (M3.2). Test in **Task 8**.
2. **A control boundary below 3:1.** `border-paper/25` on the "Switch company" summary is **2.21:1** on ink, and **2.12:1** on today's navy — a pre-existing WCAG 1.4.11 failure on a line this work edits anyway. Fixed and pinned in **Task 8**.
3. **A token referenced but undefined.** Tailwind emits no rule; the surface silently disappears. This is the plan's own central risk at Task 5. Test in **Task 1**.
4. **A missing font file falling back silently.** A renamed or absent woff2 drops to Georgia with no error. Test in **Task 1**.
5. **A retired colour name creeping back.** Nothing stops a future edit writing `text-navy`; it would emit nothing and lose the text colour. Test in **Task 5**.

---

## File Structure

| File | Responsibility | Task |
| --- | --- | --- |
| `tests/guards/test_stylesheet.py` | **Create.** All four appearance guards live in one module: they share the `app.css` parsing helpers, and splitting them would duplicate that. | 1, 3, 5 |
| `originalentry/static/fonts/` | Replace seven woff2 with three, plus two OFL licences. | 2 |
| `originalentry/static/img/` | **Create.** Logos, favicons, social card. | 2 |
| `originalentry/static/src/app.css` | Tokens, faces, base layer, 25 components. The only stylesheet. | 2, 3, 5, 6, 7 |
| `originalentry/static/dist/app.css` | Build output, committed. | 9 |
| `originalentry/templates/base.html` | `<head>`, body classes, skip link. | 2, 4 |
| `originalentry/templates/public/_header.html` | Wordmark replaces the `OE` tile. | 8 |
| `originalentry/templates/layouts/staff.html` | Console chrome: ink header, double rule. | 8 |
| `originalentry/templates/layouts/workspace.html` | Company chrome: ink header, accent stripe, control border fix. | 8 |
| `originalentry/templates/macros/tables.html` | Double-underline totals. | 7 |
| 48 templates + 5 JS files | The 88 palette-class renames and the 107 mono-site changes. | 4, 6 |
| `tests/integration/test_account_menu.py` | One assertion edit. | 4 |

---

## Task 1: The safety net

Build the guards **before** touching anything, so they catch mistakes the restyle itself introduces. Both must pass on the current tree — that is what proves they are correct rather than vacuous.

**Files:**
- Create: `tests/guards/test_stylesheet.py`

**Interfaces:**
- Produces: `_css_text() -> str`, `_defined_tokens() -> dict[str, str]` (token name without the `--color-` prefix → hex, lowercased), `PALETTE_PREFIXES: tuple[str, ...]`, `_scanned_files() -> list[pathlib.Path]`. Tasks 3 and 5 add tests to this module and reuse these.

- [ ] **Step 1: Write the two failing tests**

Create `tests/guards/test_stylesheet.py`:

```python
"""The stylesheet's own guards.

Tailwind v4 emits **nothing** for an undefined utility. `bg-papr` produces no rule, no build
error and no console warning: the surface simply loses its colour, and a person reading the page
sees a layout that looks finished and is wrong. The same silence covers a missing font file,
which falls back to Georgia without complaint.

These guards exist because a restyle is otherwise unverifiable by test. They do not judge whether
the design is good; they catch the three ways it can be silently broken.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
CSS = ROOT / "originalentry" / "static" / "src" / "app.css"
DIST = ROOT / "originalentry" / "static" / "dist" / "app.css"

#: Tailwind utility prefixes that can take a colour.
PALETTE_PREFIXES = (
    "bg", "text", "border", "ring", "from", "to", "via", "decoration",
    "outline", "divide", "placeholder", "accent", "caret", "fill", "stroke", "shadow",
)


def _css_text() -> str:
    return CSS.read_text(encoding="utf-8")


_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def _defined_tokens() -> dict[str, str]:
    """Every ``--color-NAME`` the stylesheet defines, mapped to its literal value."""
    found = {}
    for name, value in re.findall(r"--color-([a-z0-9-]+):\s*([^;]+);", _css_text()):
        found[name] = value.strip().lower()
    return found


def _token_hex(name: str) -> str:
    """The colour a token resolves to.

    ``company`` lives in the ``@theme inline`` block as ``var(--company-accent, #1b3a5c)``,
    because the real accent arrives from the pack at request time. Its fallback is the hex to
    measure, so take the first one in the value rather than assuming the whole value is a colour.
    """
    value = _defined_tokens()[name]
    found = _HEX.search(value)
    assert found, f"--color-{name} resolves to no literal hex: {value}"
    return found.group(0)


def _scanned_files() -> list[pathlib.Path]:
    roots = [
        ROOT / "originalentry" / "templates",
        ROOT / "originalentry" / "static" / "js",
    ]
    files: list[pathlib.Path] = []
    for root in roots:
        files.extend(p for p in root.rglob("*") if p.suffix in {".html", ".js"})
    assert files, "found no templates or scripts to scan — the paths are wrong"
    return files


def _utilities_used(token_names: set[str]) -> set[str]:
    """Palette utilities the markup asks for, e.g. ``{"text-muted", "bg-ink"}``.

    Built from the *defined* token names rather than by guessing which suffixes are colours:
    Tailwind's own vocabulary overlaps these prefixes heavily (`text-sm`, `border-b`,
    `shadow-lg`), so a scan that flagged every unrecognised suffix would be a maintenance
    burden full of false positives. This finds references to names we actually own.
    """
    pattern = re.compile(
        r"\b(?:%s)-(?:%s)\b"
        % ("|".join(PALETTE_PREFIXES), "|".join(sorted(map(re.escape, token_names))))
    )
    used: set[str] = set()
    for path in _scanned_files():
        used.update(pattern.findall(path.read_text(encoding="utf-8")))
    return used


def test_every_palette_class_used_reaches_the_built_css():
    """A token deleted from `@theme` while a template still names it loses the surface.

    The built stylesheet is the evidence: if `text-muted` is used and `.text-muted` is absent
    from `dist/app.css`, 162 elements render with no colour.
    """
    tokens = set(_defined_tokens())
    used = _utilities_used(tokens)
    assert used, "scan found no palette utilities at all — the pattern is broken"

    built = DIST.read_text(encoding="utf-8")
    missing = sorted(u for u in used if f".{u}" not in built)

    assert not missing, (
        "used in markup but not emitted by the build — rebuild, or the token is undefined: "
        + ", ".join(missing)
    )


def test_every_font_face_file_exists():
    """A renamed woff2 falls back to Georgia with no error anywhere."""
    srcs = re.findall(r'src:\s*url\("([^"]+)"\)', _css_text())
    assert srcs, "found no @font-face src rules"

    missing = [s for s in srcs if not (CSS.parent / s).resolve().is_file()]

    assert not missing, "@font-face points at files that do not exist: " + ", ".join(missing)
```

- [ ] **Step 2: Run them and confirm they PASS on the current tree**

Run: `.venv/bin/python -m pytest tests/guards/test_stylesheet.py -v`

Expected: **2 passed.** These guards must be green before the restyle begins — a guard that is red for pre-existing reasons cannot tell you whether your change broke something.

If `test_every_palette_class_used_reaches_the_built_css` fails here, `dist/app.css` is stale relative to `src/app.css`. Rebuild it and commit that separately before continuing.

- [ ] **Step 3: Watch each guard fail, then undo**

A guard that has never failed is not known to work. Do both, one at a time, reverting fully between them.

Mutation A — delete a token that markup depends on:
```bash
# in originalentry/static/src/app.css, comment out the --color-muted line, then:
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
.venv/bin/python -m pytest tests/guards/test_stylesheet.py::test_every_palette_class_used_reaches_the_built_css -v
```
Expected: FAIL naming `text-muted`. Then restore the line and rebuild.

Mutation B — break a font reference:
```bash
# in app.css, change outfit-400.woff2 to outfit-400-nope.woff2
.venv/bin/python -m pytest tests/guards/test_stylesheet.py::test_every_font_face_file_exists -v
```
Expected: FAIL naming the missing path. Then restore.

Confirm both guards are green again before committing.

- [ ] **Step 4: Commit**

```bash
git add tests/guards/test_stylesheet.py
git commit -m "test: guard the stylesheet against silent breakage

Tailwind emits nothing for an undefined utility and a missing woff2 falls
back to Georgia, both without any error. These two guards turn either
into a test failure. Both verified by watched mutation."
```

---

## Task 2: Identity assets

The app has no favicon and no logo today. These are its first.

**Files:**
- Create: `originalentry/static/img/` (9 files)
- Create: `originalentry/static/fonts/SourceSerif4-Regular.woff2`, `SourceSans3-Regular.woff2`, `SourceSans3-Semibold.woff2`, `SourceSerif4-OFL.txt`, `SourceSans3-OFL.txt`
- Delete: the seven existing woff2 files
- Modify: `originalentry/static/src/app.css` (the `@font-face` block and `--font-*` tokens)
- Modify: `originalentry/templates/base.html` (`<head>`)

**Interfaces:**
- Consumes: Task 1's `test_every_font_face_file_exists`, which must stay green through this task.
- Produces: `static/img/original-entry.svg`, `original-entry-white.svg`, `original-entry-reversed.svg`, `favicon.svg`, `favicon-16.png`, `favicon-32.png`, `favicon-180.png`, `favicon-512.png`, `social-1200x630.png`. Task 8 uses the first two.

- [ ] **Step 1: Copy the assets in**

The source directory is a sibling of the **main** checkout, not of your worktree. Derive it from the common git dir so this works from either:

```bash
SRC="$(cd "$(git rev-parse --git-common-dir)/../.." && pwd)/Original-Entry-Website-App-Design/assets"
test -f "$SRC/original-entry.svg" || { echo "design assets not found at $SRC"; exit 1; }
mkdir -p originalentry/static/img
cp "$SRC"/original-entry.svg "$SRC"/original-entry-white.svg \
   "$SRC"/original-entry-reversed.svg "$SRC"/favicon.svg \
   "$SRC"/favicon-16.png "$SRC"/favicon-32.png "$SRC"/favicon-180.png \
   "$SRC"/favicon-512.png "$SRC"/social-1200x630.png originalentry/static/img/
cp "$SRC"/SourceSerif4-Regular.woff2 "$SRC"/SourceSans3-Regular.woff2 \
   "$SRC"/SourceSans3-Semibold.woff2 \
   "$SRC"/SourceSerif4-OFL.txt "$SRC"/SourceSans3-OFL.txt originalentry/static/fonts/
```

Confirm 9 files in `img/` and 5 new in `fonts/`.

- [ ] **Step 2: Replace the font tokens and `@font-face` block in `app.css`**

In the `@theme` block, change the two faces this task replaces. **Leave `--font-mono` defined** — Task 6 removes its 107 call sites, and deleting the token here would unstyle the three `font-mono` utilities with nothing to catch it (the Task 1 guard watches colour prefixes, not font ones). With its `@font-face` gone it falls back to `ui-monospace`, which is a visible change but not a broken one, and Task 6 closes it properly.

```css
  --font-display: "Source Serif 4", Georgia, "Times New Roman", serif;
  --font-sans: "Source Sans 3", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: ui-monospace, "SF Mono", Menlo, monospace;
```

Replace the entire run of seven `@font-face` rules with three:

```css
@font-face {
  font-family: "Source Serif 4";
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url("../fonts/SourceSerif4-Regular.woff2") format("woff2");
}
@font-face {
  font-family: "Source Sans 3";
  font-style: normal;
  font-weight: 400;
  font-display: swap;
  src: url("../fonts/SourceSans3-Regular.woff2") format("woff2");
}
@font-face {
  font-family: "Source Sans 3";
  font-style: normal;
  font-weight: 600;
  font-display: swap;
  src: url("../fonts/SourceSans3-Semibold.woff2") format("woff2");
}
```

Keep the existing comment above the block explaining why the faces are self-hosted.

- [ ] **Step 3: Delete the old font files**

```bash
git rm originalentry/static/fonts/dm-serif-display-400.woff2 \
       originalentry/static/fonts/outfit-400.woff2 \
       originalentry/static/fonts/outfit-500.woff2 \
       originalentry/static/fonts/outfit-600.woff2 \
       originalentry/static/fonts/outfit-700.woff2 \
       originalentry/static/fonts/jetbrains-mono-400.woff2 \
       originalentry/static/fonts/jetbrains-mono-500.woff2
```

- [ ] **Step 4: Update `<head>` in `base.html`**

Replace the single `<link rel="preload">` line with the new preload plus the identity links. Insert after the `csrf-token` meta:

```html
  <meta name="description"
        content="Original Entry is practice in double-entry bookkeeping from source documents —
                 invoices, cheques and remittances — rather than a prepared list of transactions.">
  {# The faces are served from here, not a font CDN: a student opening a ledger should not also
     be announcing themselves to a third party. #}
  <link rel="preload" as="font" type="font/woff2" crossorigin
        href="{{ url_for('static', filename='fonts/SourceSans3-Regular.woff2') }}">
  <link rel="icon" href="{{ url_for('static', filename='img/favicon.svg') }}" type="image/svg+xml">
  <link rel="icon" href="{{ url_for('static', filename='img/favicon-32.png') }}" sizes="32x32">
  <link rel="apple-touch-icon" href="{{ url_for('static', filename='img/favicon-180.png') }}">
  <meta property="og:title" content="Original Entry">
  <meta property="og:description" content="Bookkeeping practice from the source documents.">
  <meta property="og:image" content="{{ url_for('static', filename='img/social-1200x630.png', _external=True) }}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{{ url_for('static', filename='img/social-1200x630.png', _external=True) }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='dist/app.css') }}">
```

- [ ] **Step 5: Rebuild and run the font guard**

```bash
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
.venv/bin/python -m pytest tests/guards/test_stylesheet.py -v
```
Expected: 2 passed. If the font guard fails, a path in Step 2 does not match a filename from Step 1.

- [ ] **Step 6: Confirm the assets are actually served**

```bash
.venv/bin/python -m pytest tests/integration -k "landing or header" -v
```
Expected: pass. Then verify the favicon and wordmark resolve through Flask's static route rather than only existing on disk:

```bash
.venv/bin/python -B -c "
from originalentry.app import create_app
app = create_app()
c = app.test_client()
for p in ('img/favicon.svg', 'img/original-entry.svg', 'fonts/SourceSans3-Regular.woff2'):
    r = c.get('/static/' + p)
    print(p, r.status_code, r.headers.get('Content-Type'))
    assert r.status_code == 200, p
"
```
Expected: three `200`s.

- [ ] **Step 7: Commit**

```bash
git add -A originalentry/static originalentry/templates/base.html
git commit -m "feat: the app's first logo, favicon and social card

Replaces DM Serif Display / Outfit / JetBrains Mono with Source Serif 4
and Source Sans 3, carrying both OFL licences as the licence requires.
Adds icon, apple-touch-icon, og:image and a description, none of which
this app has ever had. CSP needs no change: img-src already allows self."
```

---

## Task 3: Add the new tokens

Additive only. The retired tokens stay defined until Task 5, so the tree is never in a state where a template names an undefined colour.

**Files:**
- Modify: `originalentry/static/src/app.css` (`@theme`)
- Modify: `tests/guards/test_stylesheet.py` (add the contrast guard)

**Interfaces:**
- Consumes: `_defined_tokens()` from Task 1.
- Produces: tokens `ink, paper, white, muted, rule, notice, wash, failure, tint, company`.

- [ ] **Step 1: Write the failing contrast test**

Append to `tests/guards/test_stylesheet.py`:

```python
def _relative_luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: str, b: str) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


#: Every pair the interface actually renders, and the floor it must hold. 4.5 is AA for text;
#: 3.0 is AA for a control's boundary (WCAG 1.4.11). `rule` is absent on purpose: at 1.41:1 it
#: is a decorative divider, which 1.4.11 exempts, and a control that used it would be invisible.
CONTRAST_FLOORS = [
    ("ink", "paper", 4.5),
    ("ink", "white", 4.5),
    ("muted", "paper", 4.5),
    ("muted", "white", 4.5),
    ("notice", "wash", 4.5),
    ("notice", "paper", 4.5),
    ("failure", "white", 4.5),
    ("failure", "paper", 4.5),
    ("company", "paper", 4.5),
    ("paper", "ink", 4.5),
    ("white", "ink", 4.5),
]


def test_the_palette_holds_its_contrast_floors():
    """Lightening a token until text stops being readable must fail here, not in review."""
    tokens = _defined_tokens()
    failures = []
    for fg, bg, floor in CONTRAST_FLOORS:
        assert fg in tokens, f"--color-{fg} is not defined"
        assert bg in tokens, f"--color-{bg} is not defined"
        ratio = _contrast(_token_hex(fg), _token_hex(bg))
        if ratio < floor:
            failures.append(f"{fg} on {bg} is {ratio:.2f}:1, below {floor}:1")

    assert not failures, "; ".join(failures)


def test_a_field_borders_with_muted_not_the_divider_colour():
    """`rule` is 1.41:1 on paper: a field bordered with it has no visible edge.

    Asserted positively as well as negatively. "Does not mention rule" passes on a `.field` that
    mentions no colour at all — including one where the border was deleted outright — so the
    absence alone proves nothing.
    """
    css = _css_text()
    field_block = css[css.index(".field {") : css.index(".field:focus")]

    assert "--color-muted" in field_block, (
        ".field must border with --color-muted (5.80:1); found: " + field_block
    )
    assert "--color-rule" not in field_block, (
        ".field must not border with --color-rule (1.41:1), which leaves no visible edge"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/guards/test_stylesheet.py -k "contrast_floors or divider_colour" -v`

Expected, precisely:

- `test_the_palette_holds_its_contrast_floors` FAILS with `AssertionError: --color-white is not defined`. The first pair, `ink` on `paper`, resolves because both names exist today (`#1e2532` on `#ffffff`); the second asks for `white`, which the current theme has never defined — it calls that colour `paper`.
- `test_a_field_borders_with_muted_not_the_divider_colour` FAILS on the positive assertion, because `.field` currently borders with `--color-silver`. This is why the test asserts the positive: had it only checked that `rule` is absent, it would have passed today without proving anything.

Both must fail here. If either passes, the test is not measuring what its name claims.

- [ ] **Step 3: Add the new tokens to `@theme`**

Insert into the `@theme` block, leaving every existing colour in place for now:

```css
  /* ── The Original Entry palette ───────────────────────────────────────────────────────
     Ink carries the chrome, the headings and every action. Notice marks the mechanical states
     a student must see; failure is the app admitting its own trouble and never anything the
     student did; company marks whose books these are (A7, M3.2). */
  --color-ink: #292824;
  --color-paper: #faf8f4;
  --color-white: #ffffff;
  --color-muted: #65615a;
  --color-rule: #d8d3c9;      /* decorative dividers only — 1.41:1, never a control border */
  --color-notice: #805000;    /* also the focus ring: the material's focus colour is this hex */
  --color-wash: #fff2d5;
  --color-failure: #a12b2b;
  --color-tint: #eae6de;      /* the material's own #EAE6DE, unnamed there; hover and quiet fills */
```

Three of these names already exist with different values: `paper` (`#ffffff`), `rule` (`#e2e6ee`), `muted` (`#4a5568`). **Overwrite them with the new values and delete the old lines** — a duplicate `--color-paper` would take whichever came last and make the stylesheet unreadable. `ink` likewise moves from `#1e2532` to `#292824`.

This means `bg-paper`'s 3 uses turn cream for the duration of Tasks 3–4. That is the inversion, visible and temporary; Task 4 renames them to `bg-white`.

Leave `--color-company` exactly as it is, including its `@theme inline` block.

- [ ] **Step 4: Point `.field` at `muted` and run the guards**

In `app.css`, change `.field`'s border from `1.5px solid var(--color-silver)` to:

```css
    border: 1px solid var(--color-muted);
```

Then:
```bash
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
.venv/bin/python -m pytest tests/guards/test_stylesheet.py -v
```
Expected: **4 passed** (2 from Task 1, 2 added here).

- [ ] **Step 5: Watch the contrast guard fail**

Change `--color-muted` to `#8a867e`, rebuild, and run the contrast test. Expected: FAIL reporting `muted on paper` below 4.5:1. Restore `#65615a` and rebuild.

- [ ] **Step 6: Commit**

```bash
git add originalentry/static tests/guards/test_stylesheet.py
git commit -m "feat: define the Original Entry palette

Additive: the retired CityReady tokens stay defined until the templates
stop naming them, so no utility is ever referenced-but-undefined.

paper inverts here, from #ffffff to #FAF8F4. The three bg-paper uses read
cream until the next commit renames them to bg-white.

Pins every rendered contrast pair against its WCAG floor, and pins .field
to muted (5.80:1) because rule is a 1.41:1 divider that would leave a
field with no visible edge."
```

---

## Task 4: Rename the palette classes

88 occurrences across templates and JS. Mechanical, and the Task 1 guard proves nothing was left dangling.

**Files:**
- Modify: 48 templates under `originalentry/templates/`, 5 files under `originalentry/static/js/`
- Modify: `tests/integration/test_account_menu.py:180`

**Interfaces:**
- Consumes: the tokens added in Task 3.
- Produces: markup that names only current tokens. Task 5 can then delete the retired ones.

- [ ] **Step 1: Apply the renames**

Order matters: `bg-paper` → `bg-white` **must run before** `bg-cloud` → `bg-paper`, or the nine converted `bg-cloud` sites would be swept into `bg-white` too.

```bash
cd originalentry
FILES=$(find templates static/js -type f \( -name '*.html' -o -name '*.js' \))

# 1. bg-paper -> bg-white FIRST (3 uses: white panels)
sed -i '' 's/\bbg-paper\b/bg-white/g' $FILES
# 2. border-paper -> border-white (2 uses, same reasoning)
sed -i '' 's/\bborder-paper\b/border-white/g' $FILES
# 3. the hover variant before the bare one (11 uses)
sed -i '' 's/\bhover:bg-cloud\b/hover:bg-tint/g' $FILES
# 4. remaining bg-cloud -> bg-paper (9 uses)
sed -i '' 's/\bbg-cloud\b/bg-paper/g' $FILES
# 5. the rest
sed -i '' 's/\bborder-silver\b/border-rule/g' $FILES
sed -i '' 's/\bdivide-silver\b/divide-rule/g' $FILES
sed -i '' 's/\btext-navy\b/text-ink/g' $FILES
sed -i '' 's/\bbg-navy\b/bg-ink/g' $FILES
sed -i '' 's/\bborder-navy\b/border-ink/g' $FILES
sed -i '' 's/\bbg-cream\b/bg-paper/g' $FILES
sed -i '' 's/\btext-attention\b/text-notice/g' $FILES
sed -i '' 's/\bbg-attention\b/bg-notice/g' $FILES
sed -i '' 's/\btext-amber-deep\b/text-notice/g' $FILES
cd ..
```

`text-paper` (8 uses) is **deliberately left alone**: cream text on ink chrome is what the material's `.cover` specifies, so the new value makes those uses more correct, not less.

Then delete the console's teal stripe. It cannot wait for Task 8: `teal` is a retired name, and Task 5's guard fails on any that survive. In `originalentry/templates/layouts/staff.html`, remove this line entirely:

```html
  <div class="h-1.5 bg-teal"></div>
```

The console header is then an ink bar with no stripe until Task 8 gives it the double rule. `.double-rule` does not exist until Task 7, which is why this is a deletion now and a replacement later rather than one edit.

- [ ] **Step 2: Confirm the counts**

```bash
git diff --stat
grep -rcoE '\b(bg|text|border|divide)-(navy|teal|silver|cloud|cream|attention|amber-deep)\b' \
  originalentry/templates originalentry/static/js | grep -v ':0$' || echo "none remaining"
```
Expected: `none remaining`. Any file listed still carries a retired name and Task 5's guard will fail on it.

- [ ] **Step 3: Fix the one coupled test**

In `tests/integration/test_account_menu.py`, line 180:

```python
    assert "text-ink" in summary       # and legible on cream
```

The docstring and the comment stay as they are — the intent was never about navy.

- [ ] **Step 4: Rebuild and run the guards plus the affected tests**

```bash
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
.venv/bin/python -m pytest tests/guards/test_stylesheet.py tests/integration/test_account_menu.py -v
```
Expected: all pass. A failure in `test_every_palette_class_used_reaches_the_built_css` means a `sed` produced a name no token defines — read the names it lists.

- [ ] **Step 5: Commit**

```bash
git add originalentry tests/integration/test_account_menu.py
git commit -m "refactor: name the new palette in the markup

88 occurrences. bg-paper -> bg-white runs before bg-cloud -> bg-paper, or
the converted cloud sites would be swept into white as well.

text-paper is left alone on purpose: cream on ink chrome is what the
material specifies, so the new value makes those eight uses righter.

test_account_menu's text-navy assertion becomes text-ink; its stated
intent, legible on cream, is unchanged."
```

---

## Task 5: Delete the retired tokens

**Files:**
- Modify: `originalentry/static/src/app.css` (`@theme`)
- Modify: `tests/guards/test_stylesheet.py` (add the retired-name guard)

- [ ] **Step 1: Write the failing retired-name test**

Append to `tests/guards/test_stylesheet.py`:

```python
#: Retired with the CityReady palette. Nothing stops a later edit writing `text-navy`; Tailwind
#: would emit no rule for it and the text would lose its colour with no error anywhere. Navy
#: itself survives, but only as --color-company.
RETIRED = (
    "navy-deep", "navy-mid", "navy", "teal-bright", "teal-deep", "teal",
    "amber-deep", "amber", "coral", "cream", "cloud", "silver", "gray", "attention",
)


def test_no_retired_colour_name_survives():
    """Longest-first, so `navy-deep` is never reported as a bare `navy`."""
    pattern = re.compile(
        r"\b(?:%s)-(?:%s)\b" % ("|".join(PALETTE_PREFIXES), "|".join(RETIRED))
    )
    offences = []
    for path in _scanned_files():
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for hit in pattern.findall(line):
                offences.append(f"{path.relative_to(ROOT)}:{n} {hit}")

    assert not offences, "retired colour names in markup: " + "; ".join(offences)


def test_no_retired_token_is_still_defined():
    defined = set(_defined_tokens())
    lingering = sorted(defined & set(RETIRED))

    assert not lingering, "retired tokens still in @theme: " + ", ".join(lingering)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/guards/test_stylesheet.py -k retired -v`

Expected: `test_no_retired_colour_name_survives` **passes** (Task 4 cleared the markup), and `test_no_retired_token_is_still_defined` **FAILS**, listing `amber, amber-deep, cloud, coral, cream, gray, navy, navy-deep, navy-mid, silver, teal, teal-bright, teal-deep`.

- [ ] **Step 3: Delete the retired tokens from `@theme`**

Remove these lines entirely: `--color-navy`, `--color-navy-deep`, `--color-navy-mid`, `--color-teal`, `--color-teal-bright`, `--color-teal-deep`, `--color-amber`, `--color-amber-deep`, `--color-coral`, `--color-cream`, `--color-cloud`, `--color-silver`, `--color-gray`, `--color-attention`. Delete the CityReady comment block above them too; it describes a palette that no longer exists.

Several component rules still reference the deleted tokens — `.label-meta` and `.data-table thead th` use `--color-gray` and `--color-cloud`/`--color-silver` (**Task 6**); `.btn--primary` and `.nav-link[aria-current]` use `--color-teal-deep`, `.callout` uses `--color-teal`, `.field-label` uses `--color-navy` (**Task 7**). Between here and there they resolve to nothing, so those elements lose a colour.

**This is the one window in the plan where the tree is knowingly unstyled in places, and no guard catches it** — the Task 1 guard reads utilities in *markup*, and these are losses inside component CSS, where the rule still exists and only its value evaporates. Tasks 6 and 7 close it. Do not stop between Task 5 and Task 7 and conclude the restyle looks broken; finish the sequence. Step 4 below fixes the base layer immediately, because that one is page-wide.

- [ ] **Step 4: Point the base layer at the new tokens**

In `@layer base`, replace the three stale references:

```css
  html {
    font-family: var(--font-sans);
    color: var(--color-ink);
    background: var(--color-paper);
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }

  h1,
  h2,
  h3 {
    font-family: var(--font-display);
    color: var(--color-ink);
    line-height: 1.2;
    font-weight: 400;
  }

  /* Focus is the notice colour everywhere, including over a company's own accent bar, so it is
     never lost against a dark stripe (T10.5). At 6.46:1 on paper it is more visible than the
     teal ring it replaces. */
  :focus-visible {
    outline: 3px solid var(--color-notice);
    outline-offset: 3px;
    border-radius: 2px;
  }

  ::selection {
    background: var(--color-notice);
    color: var(--color-paper);
  }
```

Note `background: var(--color-paper)` in `html`, and `body` in `base.html` already carries `bg-paper` after Task 4 — both now mean cream, which agrees.

- [ ] **Step 5: Rebuild, run the guards and the full suite**

```bash
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
.venv/bin/python -m pytest tests/guards/test_stylesheet.py -v
.venv/bin/python -m pytest -q
```
Expected: guards **6 passed**; full suite **727 passed** (721 existing plus the 6 guards). Run the full suite **alone** — concurrent runs deadlock on the shared Postgres.

- [ ] **Step 6: Watch the retired-name guard fail**

Add `text-navy` to any class attribute in `originalentry/templates/public/landing.html`, run `pytest tests/guards/test_stylesheet.py -k retired -v`, confirm it FAILS naming that file and line, then remove it.

- [ ] **Step 7: Commit**

```bash
git add originalentry tests/guards/test_stylesheet.py
git commit -m "refactor: delete the retired CityReady tokens

Navy survives only as --color-company. A guard now fails if any retired
name returns to the markup or the theme, because Tailwind would emit no
rule for it and the colour would vanish silently.

Focus moves from a 2px teal ring to a 3px notice ring at 6.46:1 on paper,
more visible than what it replaces and still legible over a dark accent."
```

---

## Task 6: Typography

**Files:**
- Modify: `originalentry/static/src/app.css` (components `.label-meta`, `.label-section`, `.figure`, `.field--figure`, `.callout__label`, `.data-table thead th`; plus the two heading scales)
- Modify: 48 templates (the `font-medium` → `font-semibold` change and the 3 `font-mono` call sites)

- [ ] **Step 1: Delete `--font-mono` and replace the components that used it**

Remove the `--font-mono` line from `@theme` — Task 2 left it as a system-mono fallback, and this task removes its last caller. Then rewrite these six rules in `app.css`:

```css
  /* The ledger's own word for a cross-reference. Small, tracked, sentence-case — not shouted
     across the page. */
  .label-meta {
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--color-muted);
  }

  /* Used where a section genuinely needs naming, not above every heading. */
  .label-section {
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--color-notice);
  }

  /* Figures and account numbers. No face of its own: Source Sans 3's digits are equal-width by
     default (497/1000 em), so columns line up without a monospace face. The declaration stays as
     a statement of intent, and becomes load-bearing if a face is ever re-subset with tnum. */
  .figure {
    font-variant-numeric: tabular-nums lining-nums;
  }

  .field--figure {
    font-variant-numeric: tabular-nums lining-nums;
    text-align: right;
  }

  .callout__label {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-muted);
    display: block;
    margin-bottom: 0.2rem;
  }
```

And in `.data-table thead th`, drop `font-family: var(--font-mono)` and raise the weight:

```css
  .data-table thead th {
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--color-muted);
    background: var(--color-paper);
    border-bottom: 1px solid var(--color-ink);
    text-align: left;
  }
```

- [ ] **Step 2: Set body text to 17px**

The spec calls for 17px body text. Put it on `body`, **not** on `html`:

```css
  body {
    font-size: 1.0625rem; /* 17px */
  }
```

`html { font-size: 17px }` would reset the rem unit itself and silently inflate every rem-based Tailwind utility — `px-4`, `gap-6`, `max-w-5xl`, every `text-sm` — by 6.25%, re-spacing all 48 templates as a side effect of a type decision. On `body` it changes inherited text only, which is what was asked for. Elements carrying an explicit `text-sm`/`text-xs` keep their own size either way.

- [ ] **Step 3: Add the two heading scales**

The material's `h1: clamp(42px, 6vw, 76px)` suits a public page and is absurd above an entry grid. Add to `@layer base`, after the shared `h1, h2, h3` rule:

```css
  /* Public pages take the editorial scale; the workspace and console take an app scale. The
     material modulates its own examples the same way (.landing h3 at 48px, .journal h3 at 23px).
     `data-scale` is set on <body> by the layout, so no page has to remember. */
  [data-scale="page"] h1 {
    font-size: clamp(2.625rem, 6vw, 4.75rem);
    line-height: 1.08;
    letter-spacing: -0.025em;
  }
  [data-scale="page"] h2 { font-size: 2.25rem; line-height: 1.15; }
  [data-scale="page"] h3 { font-size: 1.5625rem; line-height: 1.25; }

  [data-scale="app"] h1 { font-size: 1.75rem; }
  [data-scale="app"] h2 { font-size: 1.4375rem; }
  [data-scale="app"] h3 { font-size: 1.1875rem; }
```

- [ ] **Step 4: Set the scale on `<body>`**

In `base.html`, add a block-overridable attribute to `<body>`:

```html
<body data-scale="{% block scale %}app{% endblock %}" class="min-h-screen bg-paper text-ink">
```

`app` is the default because 43 of the 48 templates are application screens. Then in each of the four public templates (`public/landing.html`, `public/how_it_works.html`, `public/privacy.html`, `public/terms.html`) add near the top:

```jinja
{% block scale %}page{% endblock %}
```

- [ ] **Step 5: Replace `font-medium` and the `font-mono` call sites**

```bash
cd originalentry
FILES=$(find templates static/js -type f \( -name '*.html' -o -name '*.js' \))
sed -i '' 's/\bfont-medium\b/font-semibold/g' $FILES
sed -i '' 's/ *\bfont-mono\b//g' $FILES
cd ..
```

There is no 500 face; a synthesized weight renders differently in every browser. `font-mono` is removed outright at its three call sites — the elements keep their size and tracking from the surrounding rules.

- [ ] **Step 6: Confirm no stale font reference remains**

```bash
grep -rn 'font-mono\|--font-mono\|font-medium' originalentry/static/src/app.css \
  originalentry/templates originalentry/static/js
```
Expected: no output.

- [ ] **Step 7: Rebuild and run the guards and suite**

```bash
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
.venv/bin/python -m pytest tests/guards/test_stylesheet.py -v
.venv/bin/python -m pytest -q
```
Expected: 6 guards pass; 727 pass.

- [ ] **Step 8: Commit**

```bash
git add originalentry
git commit -m "feat: two faces, two scales, no monospace

107 mono sites resolve without a mono face: Source Sans 3's digits are
equal-width by default, so ledger columns align on font-variant-numeric
alone. Labels become the material's folio treatment.

The 16 font-medium uses become font-semibold — there is no 500 face, and
a synthesized weight differs per browser.

Public pages take the editorial heading scale, the app a smaller one, via
data-scale on <body>. A 76px h1 above an entry grid is absurd."
```

---

## Task 7: Components

**Files:**
- Modify: `originalentry/static/src/app.css` (`@theme` radii, and the button, field, callout, table and nav components)
- Modify: `originalentry/templates/macros/tables.html`

- [ ] **Step 1: Set the radii**

In `@theme`, replace the three radius lines:

```css
  --radius-DEFAULT: 3px;
  --radius-lg: 3px;
  --radius-xl: 3px;
```

All three collapse to 3px deliberately: the material uses one radius everywhere, and keeping a scale would invite a 16px card back in. This single change shifts the feel more than the palette does — it is the difference between a SaaS card and a printed form.

- [ ] **Step 2: Rewrite the components that name deleted tokens**

```css
  .panel {
    background: var(--color-white);
    border: 1px solid var(--color-rule);
    border-radius: var(--radius-DEFAULT);
  }

  .data-table caption {
    font-family: var(--font-display);
    font-size: 1.05rem;
    color: var(--color-ink);
    text-align: left;
    padding: 0.875rem 0.875rem 0.5rem;
  }

  .data-table tbody td,
  .data-table tbody th {
    border-bottom: 1px solid var(--color-rule);
    color: var(--color-ink);
    font-weight: 400;
    text-align: left;
  }

  .data-table tbody tr:hover {
    background: var(--color-tint);
  }

  /* How a ruled book closes a column. */
  .data-table tfoot th,
  .data-table tfoot td {
    border-top: 1px solid var(--color-ink);
    border-bottom: 3px double var(--color-ink);
    color: var(--color-ink);
    font-weight: 600;
  }

  /* Ink acts, white retreats, outline is quietest. Teal's job is gone: there is one action
     colour now, and it is the same ink the text is set in. */
  .btn--primary {
    background: var(--color-ink);
    color: var(--color-paper);
  }

  .btn--primary:hover {
    background: #45433e;
  }

  .btn--secondary {
    background: var(--color-white);
    color: var(--color-ink);
    border-color: var(--color-ink);
  }

  .btn--secondary:hover {
    background: var(--color-tint);
  }

  .btn--outline {
    background: transparent;
    color: var(--color-ink);
    border-color: var(--color-muted);
  }

  .btn--outline:hover {
    border-color: var(--color-ink);
  }

  .field-label {
    display: block;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--color-ink);
    margin-bottom: 0.25rem;
  }

  .field:focus {
    outline: none;
    border-color: var(--color-ink);
    box-shadow: 0 0 0 3px var(--color-wash);
  }

  .callout {
    border-left: 3px solid var(--color-muted);
    background: var(--color-white);
    border-radius: 0 var(--radius-DEFAULT) var(--radius-DEFAULT) 0;
    padding: 0.875rem 1.125rem;
    font-size: 0.9rem;
    color: var(--color-ink);
  }

  .callout--attention {
    border-left-color: var(--color-notice);
    background: var(--color-wash);
    color: var(--color-notice);
  }

  .callout--trouble {
    border-left-color: var(--color-failure);
    background: var(--color-white);
    color: var(--color-failure);
  }

  .callout--attention .callout__label {
    color: var(--color-notice);
  }

  .callout--trouble .callout__label {
    color: var(--color-failure);
  }

  .nav-link[aria-current="page"] {
    background: rgb(255 255 255 / 0.18);
    color: var(--color-white);
    font-weight: 600;
  }
```

Also reduce `.btn`'s border from `2px solid transparent` to `1px solid transparent` to match the 3px radius and the material's `11px 20px` padding proportions.

`.nav-link`'s base and `:hover` rules are unchanged: they are already expressed in white-with-alpha for dark chrome, which is still exactly their job.

- [ ] **Step 3: Check no component references a deleted token**

```bash
grep -nE 'color-(navy|teal|amber|coral|cream|cloud|silver|gray|attention)' \
  originalentry/static/src/app.css
```
Expected: no output.

- [ ] **Step 4: Add the double rule**

Append to `@layer components` in `app.css`:

```css
  /* The material's signature device: two hairlines in the current colour, six pixels apart.
     Replaces the solid 6px stripe wherever the stripe sat on a ground it cannot contrast with. */
  .double-rule {
    border-top: 1px solid currentColor;
    border-bottom: 1px solid currentColor;
    height: 6px;
    width: 100%;
  }
```

- [ ] **Step 5: Verify the totals row actually gets the double underline**

`macros/tables.html` already puts totals in `<tfoot>`, so Step 2 reaches them with no template change. Confirm it, and that the macro's own classes still resolve:

```bash
.venv/bin/python -m pytest tests/integration -k "trial_balance or ledger or journal" -v
```
Expected: pass.

Then confirm the rule is in the built CSS rather than assuming it:
```bash
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
grep -c 'double' originalentry/static/dist/app.css
```
Expected: at least `1`.

- [ ] **Step 6: Run the guards and suite**

```bash
.venv/bin/python -m pytest tests/guards/test_stylesheet.py -v
.venv/bin/python -m pytest -q
```
Expected: 6 guards pass; 727 pass.

- [ ] **Step 7: Commit**

```bash
git add originalentry
git commit -m "feat: restyle the components to ink and paper

One action colour now, and it is the ink the text is set in. Radii
collapse from 8/12/16px to a single 3px: this does more to shift the feel
than the palette does.

Totals close with a 3px double underline, the way a ruled book closes a
column. Adds .double-rule, the material's signature device."
```

---

## Task 8: Chrome

**Files:**
- Modify: `originalentry/templates/public/_header.html`
- Modify: `originalentry/templates/layouts/staff.html`
- Modify: `originalentry/templates/layouts/workspace.html`
- Modify: `originalentry/packs/validate.py` (V13)
- Modify: `tests/unit/test_packs.py` (the V13 test)

**Interfaces:**
- Consumes: `static/img/original-entry.svg` and `original-entry-white.svg` from Task 2; `.double-rule` from Task 7.

- [ ] **Step 1: Put the wordmark in the public header**

In `public/_header.html`, replace the two `<span>`s inside the landing anchor with the real wordmark. It is 502×106, so `h-8` renders it 151px wide:

```html
  <a class="flex items-center" href="{{ url_for('public.landing') }}">
    <img class="h-8 w-auto"
         src="{{ url_for('static', filename='img/original-entry.svg') }}"
         width="502" height="106" alt="Original Entry">
  </a>
```

The `alt` carries the name, so the adjacent text span is now redundant and is removed with it. `width`/`height` are given so the header does not reflow while the SVG loads.

- [ ] **Step 2: Restyle the console chrome**

In `layouts/staff.html`, replace the whole `{% block chrome %}` body. Task 4 already deleted the teal stripe and renamed the header to `bg-ink`; this puts the reversed wordmark in place of the text title and closes the header with the double rule:

```jinja
{% block chrome %}
<header class="bg-ink text-paper">
  <div data-shell class="mx-auto flex {{ shell_width }} flex-wrap items-center gap-4 px-4 py-3">
    <p class="mr-auto flex items-baseline gap-2">
      <img class="h-6 w-auto"
           src="{{ url_for('static', filename='img/original-entry-white.svg') }}"
           width="502" height="106" alt="Original Entry">
      <span class="label-meta text-paper/70">console</span>
    </p>
    <nav aria-label="Console" class="flex flex-wrap gap-1">
      <a href="{{ url_for('staff.index') }}" class="nav-link"
         {% if request.path == url_for('staff.index') %}aria-current="page"{% endif %}>Assignments</a>
      <a href="{{ url_for('staff.catalogue') }}" class="nav-link"
         {% if request.path == url_for('staff.catalogue') %}aria-current="page"{% endif %}>Catalogue</a>
      {% with tone = 'dark' %}{% include "_account_menu.html" with context %}{% endwith %}
    </nav>
  </div>
  <div data-shell class="mx-auto {{ shell_width }} px-4 pb-3">
    <div class="double-rule text-paper/40" aria-hidden="true"></div>
  </div>
</header>
{% endblock %}
```

The `<nav>` is reproduced unchanged so you can replace the block wholesale rather than patching around it. The teal stripe is gone because on an ink header it would be invisible; `text-paper/40` gives the double rule 3.50:1 against ink, and `currentColor` in `.double-rule` picks that up. Update the module docstring at the top of the file — it says "the chrome is navy with a teal rule", which is no longer true:

```jinja
{# The instructor's console (I1–I5): five screens, no settings page. Plain chrome on purpose —
   ink with a paper double rule, so it never reads as any one company's books. #}
```

- [ ] **Step 3: Restyle the workspace chrome and fix the control border**

In `layouts/workspace.html`, the header becomes `bg-ink text-paper` (done by Task 4's `bg-navy` → `bg-ink`). Two further edits:

The `bg-company` stripe stays exactly as it is — it is the one thing that is not ink, and it is how a student knows whose books they are in. Update its comment, which says "not navy":

```jinja
  {# The company's own colour is the one thing that is not ink: it is how a student knows whose
     books they are in at a glance (M3.2). #}
```

Then fix the pre-existing contrast failure on the "Switch company" control. Change:

```html
      <summary class="nav-link cursor-pointer list-none border border-paper/25">Switch company</summary>
```

to:

```html
      <summary class="nav-link cursor-pointer list-none border border-paper/40">Switch company</summary>
```

`paper/25` on ink is 2.21:1 — below the 3:1 WCAG 1.4.11 requires for a control's boundary. It fails today against navy too, at 2.12:1, so this is a pre-existing defect on a line this work touches. `paper/40` is 3.50:1. (`/35` is 3.01:1, too close to the line to leave.)

- [ ] **Step 4: Write the failing V13 test**

V13 checks a pack's accent against **white only**. The accent's real job is the `bg-company` stripe on the ink header, where a dark accent disappears. Add to `tests/unit/test_packs.py`, beside the existing V13 test:

```python
def test_v13_accent_invisible_on_the_chrome_is_flagged():
    """An accent near the chrome's own ink passes a white-only check and then cannot be seen.

    The company stripe sits on the ink header, and it is the only thing telling a student whose
    books they are in (M3.2). #2E2C28 clears 4.5:1 against white easily and is indistinguishable
    from #292824 beside it.
    """
    data = _pack_dict()
    data["company"]["accent_hex"] = "#2E2C28"
    problems = validate.validate_pack(schema.load_pack(data))
    assert "V13" in _rules(problems)
```

- [ ] **Step 5: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_packs.py::test_v13_accent_invisible_on_the_chrome_is_flagged -v`

Expected: FAIL — no V13 problem is raised, because `#2E2C28` against white is well over 4.5:1.

- [ ] **Step 6: Extend V13**

In `originalentry/packs/validate.py`, replace `_v13_contrast`:

```python
#: The chrome the company stripe sits on. An accent must be distinguishable from it, or the one
#: signal that says whose books these are disappears into the header (M3.2).
_CHROME_INK = "#292824"


def _v13_contrast(pack: Pack, problems: list[Problem]) -> None:
    accent = pack.company.accent_hex
    against_white = _contrast_against_white(accent)
    if against_white < 4.5:
        problems.append(
            Problem(
                "company.accent_hex",
                "V13",
                f"Accent colour contrast against white is {against_white:.2f}:1, below 4.5:1.",
            )
        )
    against_chrome = _contrast_between(accent, _CHROME_INK)
    if against_chrome < 3.0:
        problems.append(
            Problem(
                "company.accent_hex",
                "V13",
                f"Accent colour contrast against the chrome is {against_chrome:.2f}:1, "
                "below 3:1 — the company stripe would not be visible on the header.",
            )
        )
```

`_contrast_against_white` at `validate.py:535` currently inlines the luminance arithmetic and hardcodes white's luminance as `1.0`. Split the luminance out and express both ratios through one helper, so the arithmetic exists once. The existing `_srgb_to_linear` is reused as-is, and the parameter keeps the file's own spelling, `hex_color`:

```python
def _luminance(hex_color: str) -> float:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return (
        0.2126 * _srgb_to_linear(r)
        + 0.7152 * _srgb_to_linear(g)
        + 0.0722 * _srgb_to_linear(b)
    )


def _contrast_between(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _contrast_against_white(hex_color: str) -> float:
    return _contrast_between(hex_color, "#ffffff")
```

`_contrast_against_white` keeps its name and signature, so `_v13_contrast` is the only caller that changes. Confirm the refactor is behaviour-preserving before adding the new rule:

```bash
.venv/bin/python -m pytest tests/unit/test_packs.py -k v13 -v
```
Expected at this point: the **existing** V13 test still passes and the new one still fails. If the existing test breaks, the refactor is wrong — white's luminance is exactly `1.0`, so `_contrast_between(x, "#ffffff")` must reproduce the old formula.

- [ ] **Step 7: Confirm both V13 tests pass and no shipped pack now fails**

```bash
.venv/bin/python -m pytest tests/unit/test_packs.py -k v13 -v
```
Expected: both pass.

Then check the real packs, because a new rule that rejects shipped content is a broken rule:

```bash
.venv/bin/python -B -c "
import json, pathlib
from originalentry.packs import validate, schema
for p in sorted(pathlib.Path('packs').glob('*/source.json')):
    data = json.loads(p.read_text())
    problems = validate.validate_pack(schema.load_pack(data))
    v13 = [x for x in problems if x.rule == 'V13']
    print(p.parent.name, data['company']['accent_hex'], 'V13:', v13 or 'clean')
"
```
Expected: every pack `clean`. If one fails, stop — report the pack and its accent rather than loosening the threshold.

- [ ] **Step 8: Rebuild, run the guards and the full suite**

```bash
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
.venv/bin/python -m pytest tests/guards/test_stylesheet.py -v
.venv/bin/python -m pytest -q
```
Expected: 6 guards pass; 728 pass (727 plus the new V13 test).

- [ ] **Step 9: Commit**

```bash
git add originalentry tests/unit/test_packs.py
git commit -m "feat: ink chrome, the real wordmark, and a V13 that checks the chrome

The console's teal stripe becomes the material's double rule: on an ink
header a teal stripe is invisible.

V13 only ever checked a pack accent against white, but the accent's job
is the company stripe on the ink header. An accent near #292824 passed
and then could not be seen, losing the one signal that says whose books
these are. Now checked against both, at 4.5:1 and 3:1.

Fixes a pre-existing WCAG 1.4.11 failure while here: the Switch company
control's border was 2.21:1 on ink and 2.12:1 on the navy it replaces.
paper/40 is 3.50:1."
```

---

## Task 9: Build, verify, and look at it

**Files:**
- Modify: `originalentry/static/dist/app.css` (the committed build output)

- [ ] **Step 1: Rebuild from clean and confirm the output changed**

```bash
rm originalentry/static/dist/app.css
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
wc -c originalentry/static/dist/app.css
```
Expected: a single-line file, non-empty. A near-zero size means the `@source` globs no longer match the templates.

- [ ] **Step 2: Confirm the new palette actually reached the build**

```bash
for t in ink paper white muted rule notice wash failure tint company; do
  printf '%-10s %s\n' "$t" "$(grep -c "color-$t" originalentry/static/dist/app.css)"
done
grep -c 'navy\|teal\|coral\|cloud\|silver' originalentry/static/dist/app.css
```
Expected: a non-zero count for each new token, and `0` for the retired group.

- [ ] **Step 3: Run the whole suite, alone**

```bash
.venv/bin/python -m pytest -q
```
Expected: **728 passed**. Nothing else may be running against the database: two concurrent suites deadlock on the shared Neon Postgres.

Do not pass `--timeout`; `pytest-timeout` is not installed and the flag kills the run with exit 4.

- [ ] **Step 4: Render the pages and look at them**

The public pages need no database rows, so a local server is safe and touches nothing:

```bash
.venv/bin/python -m flask --app originalentry.app:create_app run --port 5001 &
```

Visit and screenshot `/`, `/how-it-works`, `/privacy`, `/terms`, and the sign-in page — each at full width, at 320px, and at 200% zoom. Look for: the wordmark rendering at the right size, the ink stripe present, headings at the editorial scale, body at 17px, focus rings visible on every link and control when tabbing.

Then stop the server.

**Report what you see, including anything wrong. Do not assert it looks right.** A restyle's final judge is the eye, and a plan cannot promise that outcome in advance.

- [ ] **Step 5: Hand the authenticated screens to the owner**

The workspace and console need a signed-in session against the live database, which holds the owner's own test workspaces. Do not sign in as them. Instead, record in the commit message that these four views need the owner's eye:

- a workspace with a source document open (company stripe, the accent against ink chrome)
- a journal entry grid (figures aligned without a mono face, at 320px)
- a trial balance (the double-underline total)
- the console (the paper double rule under the wordmark)

**Print output is also unverified**, as the spec states. The material specifies print at length and it matters for paper-mode assignments.

- [ ] **Step 6: Commit the build**

```bash
git add originalentry/static/dist/app.css
git commit -m "build: rebuild the committed stylesheet

dist/app.css is committed so deploys need no Node (A29). Rebuilt from a
clean slate; the retired palette appears nowhere in the output.

Public pages checked by eye at full width, 320px and 200% zoom. The
workspace, journal grid, trial balance, console and all print output
remain unverified: they need a signed-in session against the live
database, which holds real test work."
```

---

## Notes for the executor

**Work in a worktree.** Use `superpowers:using-git-worktrees` before Task 1. Do not restyle on `main`.

**Never use bare `git stash`.** The stash stack is shared across worktrees and other sessions may push or pop concurrently. If you need to set work aside, commit it to a scratch branch.

**`bin/tailwindcss` is gitignored and already present** at v4.1.14 for Darwin arm64. Do not fetch it, and do not commit it. If it is missing, `./bin/get-tailwind.sh` fetches it, but that needs network and only the arm64 checksum is filled in.

**Rebuild after every CSS edit before running the guards.** `test_every_palette_class_used_reaches_the_built_css` reads `dist/app.css`, so a stale build makes it fail for a reason that has nothing to do with your change.

**Do not touch the live database.** No task in this plan needs it. `flask packs import`, `flask packs migrate --apply` and `flask grade assignment` all write to a shared Postgres holding real work and are not part of this plan.
