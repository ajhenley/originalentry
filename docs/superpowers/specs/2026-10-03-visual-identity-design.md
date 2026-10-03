# Visual identity design

**Date:** 3 October 2026
**Source material:** `../Original-Entry-Website-App-Design/` (design.html, design-system.css,
assets/brand.css, fonts, logos, favicons, social card)

## Intent

Restyle Original Entry to the supplied visual identity. The graphic look changes; the product
does not. No screen is added, removed, or made to behave differently, and no copy makes a claim
the app does not already honour.

### Scope boundary, and why it is drawn here

The supplied material is not a stylesheet. It is a product specification with a five-phase
delivery plan whose Phase 1 is *"Product audit: resolve proposed-versus-existing behaviours
before promising them in copy."* It closes with five **open decisions** — every one of which this
codebase has already decided and shipped:

| The document's open question | What the code already does |
| --- | --- |
| How students access and select assigned practice sets | `Assignment.company_policy` fixed/choice, `variant_policy`, `AssignmentChoice` |
| Whether posting is manual or derived | Manual — `PostingRun` exists, `posting_completeness` is 20 marks |
| Whether revisions replace records or keep history | Visible history — `JournalEntryRevision`, `Disposition.superseded_at` |
| What draft persistence and recovery are supported | `save.js` plus `Workspace.version` optimistic concurrency |
| What student data instructors can view and export | `staff/` blueprint, `GradeRun`/`GradeOverride`, marks CSV |

The document was written without sight of the built product. Adopting it wholesale would
re-litigate behaviour that is live and has student work on it. **This spec takes the visual layer
only.** The five decisions stand as the code already made them.

## Why this identity suits the product

The palette is warm paper, ink, and a brown-amber notice. Read without context that is a
generated-design cliché. Read in context it is the craft's own vocabulary: students work from
printed source documents, and the material names its devices `folio`, `paper`, `double` rule.
The brief pins this direction, and the brief wins.

## Verified facts

These were measured, not assumed. They are recorded because three of them changed the design.

**Contrast** (computed WCAG 2.1 ratios):

| Pair | Ratio | |
| --- | --- | --- |
| `ink` on `paper` | 13.91:1 | body text |
| `muted` on `paper` | 5.80:1 | secondary text, 162 uses |
| `muted` on `white` | 6.16:1 | secondary on a panel |
| `notice` on `wash` | 6.17:1 | notice in its own wash |
| `notice` on `paper` | 6.46:1 | notice on the page |
| `failure` on `white` | 7.25:1 | the app's own trouble |
| `failure` on `paper` | 6.84:1 | |
| `company` on `paper` | 10.96:1 | company heading |
| `paper` on `ink` | 13.91:1 | reversed chrome |
| `rule` on `paper` | 1.41:1 | **decorative dividers only** |

Every text pair clears AA. The document's two quoted figures (`notice/wash` 6.17:1,
`failure/paper` 6.84:1) reproduce exactly, so its own measurements are trustworthy.

`rule` at 1.41:1 is correct and intended: the material uses `--muted` (5.80:1) for input borders
and reserves `--rule` for decorative dividers, which WCAG 1.4.11 exempts. **A control's border
must never use `rule`.**

**Fonts.** `SourceSans3-Regular/Semibold.woff2` carry `onum` but **no `tnum` and no `lnum`**;
`SourceSerif4-Regular.woff2` carries both. This does not matter: default digit advances are
equal-width in all three faces (497, 497, 513 per 1000 em), so figures align in columns without
the feature. `font-variant-numeric` is kept as a declaration of intent, correct if a face is ever
re-subset.

Weights available: Source Serif 4 at 400; Source Sans 3 at 400 and 600. **There is no 500 and no
monospace face.**

**Build.** `bin/tailwindcss` v4.1.14 is present locally and gitignored; `dist/app.css` is
committed so deployment needs no Node (A29). The CSS rebuilds offline:

```
./bin/tailwindcss -i originalentry/static/src/app.css -o originalentry/static/dist/app.css --minify
```

**Test coupling.** Exactly one test asserts a palette class: `tests/integration/
test_account_menu.py:180` asserts `text-navy`, for the stated reason "legible on cream". V13's
accent-contrast rule concerns pack accents, not the app palette, and is untouched.

## Token layer

The classes in the templates are already semantic — `text-muted` alone is 162 of 279 palette
uses — so this is chiefly a `@theme` redefinition, not a template rewrite.

### The inversion

`paper` means opposite things in the two systems. Today `--color-paper` is `#ffffff` and
`--color-cream` is `#FAF8F4`. The material has `--paper: #FAF8F4` and `--white: #fff`. A naive
value swap would silently turn every white panel cream, with nothing failing.

It affects **three** sites, not thirteen: `text-paper` (8 uses, cream text on dark chrome) is
*more* correct under the new value, because the material's `.cover` sets exactly
`background: ink; color: paper`. Only `bg-paper` (3 uses, white panels) must become `bg-white`.

### The new `@theme` palette

```css
--color-ink:     #292824;   /* chrome, body text, buttons */
--color-paper:   #FAF8F4;   /* the page */
--color-white:   #ffffff;   /* panels */
--color-muted:   #65615A;   /* secondary text; also control borders */
--color-rule:    #D8D3C9;   /* decorative dividers only */
--color-notice:  #805000;   /* mechanical states */
--color-wash:    #FFF2D5;   /* the notice's own background */
--color-failure: #A12B2B;   /* the app's own trouble, never the student's */
--color-tint:    #EAE6DE;   /* hover and quiet fills */
--color-company: #1B3A5C;   /* fallback; real value from the pack */
```

`--color-focus` is not a separate token: the material's focus colour is `#805000`, identical to
`notice`, so `:focus-visible` uses `--color-notice` rather than carrying a duplicate.

`--color-tint: #EAE6DE` is the one token added. The value is the material's own — it appears
twice (`button.secondary:hover`, `.usage`) without a name. The eleven `hover:bg-cloud` sites need
it, because cream on white is too faint to register as a hover.

`@theme inline { --color-company: var(--company-accent, #1B3A5C) }` is unchanged: the accent
arrives from the pack as validated hex (V13) via a nonce'd `<style>` block.

### Retired

`navy`, `navy-deep`, `navy-mid`, `teal`, `teal-bright`, `teal-deep`, `amber`, `amber-deep`,
`coral`, `cream`, `cloud`, `silver`, `attention`. Navy survives **only** as `--color-company`.

### Rename map

All mechanical. Counts are current occurrences in `templates/` and `static/js/`.

| From | To | Count |
| --- | --- | --- |
| `border-silver` | `border-rule` | 25 |
| `hover:bg-cloud` | `hover:bg-tint` | 11 |
| `bg-cloud` (static) | `bg-paper` | 9 |
| `text-navy` | `text-ink` | 9 |
| `bg-navy` | `bg-ink` | 7 |
| `bg-paper` | `bg-white` | 3 |
| `text-attention` | `text-notice` | 17 |
| `text-amber-deep` | `text-notice` | 2 |
| `border-navy` | `border-ink` | 1 |
| `bg-cream` | `bg-paper` | 1 |
| `divide-silver` | `divide-rule` | 1 |
| `bg-attention` | `bg-notice` | 1 |
| `bg-teal` | the double rule (see Chrome) | 1 |

That is **88 occurrences renamed**.

Left untouched, by design — **191 occurrences**: `text-muted` (162), `text-paper` (8),
`text-ink` (7), `bg-company` (4), `divide-rule` (3), `border-rule` (2), `border-paper` (2),
`bg-rule` (2), `border-company` (1).

88 + 191 = 279, the full palette-class census.

## Typography

```css
--font-display: "Source Serif 4", Georgia, "Times New Roman", serif;   /* 400 */
--font-sans:    "Source Sans 3", system-ui, -apple-system, sans-serif; /* 400, 600 */
```

`--font-mono` is **deleted**. 107 sites currently depend on it:

- `.figure` (76) — drops `font-family`; keeps `font-variant-numeric: tabular-nums lining-nums`.
  Safe: digits are equal-width by default.
- `.label-meta` (21) and `.label-section` (7) — become the material's `.folio`: 12px, weight 600,
  `letter-spacing: .07em`, uppercase, sans. `.label-section` keeps its wider `.16em` tracking.
- `font-mono` at the call site (3) — removed.

The 16 `font-medium` (500) uses become `font-semibold` (600). There is no 500 face, and a
synthesized weight is visibly wrong and differs per browser.

**Two scales.** The material's `h1: clamp(42px, 6vw, 76px)` suits a public page and is absurd
above an entry grid; the material itself modulates (`.landing h3` 48px, `.journal h3` 23px).

| | h1 | h2 | h3 |
| --- | --- | --- | --- |
| Public pages | `clamp(42px, 6vw, 76px)`, lh 1.08, ls −.025em | 36px, lh 1.15 | 25px, lh 1.25 |
| Workspace and console | 28px | 23px | 19px |

Body: 17px / 1.55 (from browser-default size / 1.6).

Headings move from navy to **ink**. Navy is now exclusively the company accent; navy headings
would read as company markers.

Border radius: 8/12/16px → **3px**. This shifts the feel more than the palette does — it is the
difference between a SaaS card and a printed form.

## Components

The 25 existing components keep their names and roles; values change.

| Component | Change |
| --- | --- |
| `.panel` | `white` on a 1px `rule` hairline, radius 3px |
| `.callout--attention` | `notice` on `wash`, left border `notice` |
| `.callout--trouble` | `failure` on `white` |
| `.btn--primary` | `ink` ground, `paper` text, hover `#45433E` |
| `.btn--secondary` | `white` ground, `ink` text, hover `tint` |
| `.btn--outline` | 1px `ink`, transparent ground |
| `.field` | 1px **`muted`** border (never `rule`), radius 3px, min-height 44px |
| `.data-table thead th` | `ink` bottom rule, weight 600 |
| `.data-table tbody tr:hover` | `tint` |
| `.data-table tfoot` | **`border-bottom: 3px double var(--color-ink)`**, weight 600 |
| `.nav-link` | unchanged role: light text at 75% on dark chrome only |
| `.label-meta`, `.label-section` | become `.folio` (see Typography) |
| `:focus-visible` | 3px `notice` outline, 3px offset (was 2px teal / 2px) |

Three devices arrive from the material. Each encodes information rather than decorating:

- **The double rule** — `border-top`/`border-bottom` 1px currentColor, 6px tall. The material's
  signature, and exactly the height of the existing app bars.
- **Double-underline totals** — how a ruled book closes a column. Into `macros/tables.html`'s
  `tfoot`, which today has no distinguishing treatment.
- **`.folio`** — the ledger's own word for a cross-reference.

## Identity assets

The app currently has **no favicon and no logo**. These are its first.

Copied into `originalentry/static/`:

- `fonts/SourceSerif4-Regular.woff2`, `fonts/SourceSans3-Regular.woff2`,
  `fonts/SourceSans3-Semibold.woff2`, plus `SourceSerif4-OFL.txt` and `SourceSans3-OFL.txt`
  (the OFL requires the licence travel with the fonts)
- `img/original-entry.svg` (ink on transparent), `img/original-entry-white.svg` (white on dark),
  `img/original-entry-reversed.svg` (cream on navy)
- `img/favicon.svg`, `img/favicon-16.png`, `img/favicon-32.png`, `img/favicon-180.png`,
  `img/favicon-512.png`
- `img/social-1200x630.png`

Deleted: the seven current woff2 files (`dm-serif-display-400`, `outfit-400/500/600/700`,
`jetbrains-mono-400/500`).

The `OE` monogram tile in `_header.html` becomes the real wordmark: `original-entry.svg` on light
pages, `original-entry-white.svg` on ink chrome. **`-reversed.svg` has no in-app home** — the
workspace accent is a per-pack validated hex and that file has `#1B3A5C` baked in. It ships for
social use.

`<head>` in `base.html` gains `icon`, `apple-touch-icon`, `og:image`, `twitter:image` and a
`description`. The font preload changes from `outfit-400.woff2` to `SourceSans3-Regular.woff2`.
CSP needs no change: `img-src 'self' data:` already covers these.

## Chrome

The 6px stripe keeps its job of saying which context you are in.

| Context | Now | Becomes |
| --- | --- | --- |
| Public pages (4 templates) | `h-1.5 bg-navy` | `h-1.5 bg-ink` |
| Instructor console | `bg-navy` header + `h-1.5 bg-teal` | `bg-ink` header + the double rule in `paper` beneath the title |
| Student workspace | `h-1.5 bg-company` | **unchanged** |

The console's teal stripe would vanish against an ink header, which is why it becomes the double
rule — and the material pairs precisely that way: `.cover` on ink with `.double` in
`currentColor`.

## Verification

A restyle is largely not unit-testable. Rather than write checks that pass without proving
anything, this spec names what genuinely fails when broken, and what only an eye can judge.

Four new guards, each with the mutation that must make it fail:

1. **Retired-name guard** — greps `templates/` and `static/js/` for the 13 retired tokens; fails
   if any survive. *Mutation: re-add `text-navy` to a template.*
2. **Token-existence guard** — the highest-value one. Tailwind emits **nothing** for an undefined
   utility like `bg-nonexistent`: the element renders unstyled with no error anywhere. This
   extracts every palette utility from the templates and asserts each resolves to a defined
   `--color-*`. *Mutation: write `bg-papr` in a template.*
3. **Contrast guard** — asserts the pairs in Verified Facts hold ≥ 4.5:1, computed from the token
   values in `app.css`. *Mutation: lighten `--color-muted` to `#8A867E`.*
4. **Font-file guard** — asserts every `@font-face` `src` resolves to a file on disk, so a
   missing woff2 cannot fall back to Georgia silently. *Mutation: rename a woff2.*

Existing suite: all 721 tests must stay green, proving no behaviour moved. One edit —
`test_account_menu.py:180` `text-navy` → `text-ink`, its "legible on cream" intent unchanged.

By eye, reported honestly rather than asserted: the public landing, a workspace with a source
document, a trial balance, and the console — each at full width, at 320px, and at 200% zoom.

**Not verified here:** print output, which the material specifies at length and which matters for
paper-mode assignments. Flagged for the owner's own check.

## Out of scope

- Any change to routes, views, models, grading, or pack handling.
- The material's proposed public-site architecture (Home, How it works) as *new pages*.
- The five open decisions, which the shipped product has already answered.
- Dark mode. The material does not specify one and the app has none.
