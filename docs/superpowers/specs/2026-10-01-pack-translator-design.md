# Bringing the other practice sets online — design

**Status:** approved in outline, not yet planned
**Date:** 1 October 2026
**First company:** Alder & Finch Veterinary Clinic

## The problem, stated accurately

Original Entry serves one company. Three exist on paper. The obvious reading is that two more
packs need authoring, and that reading is wrong in a way worth setting down before any work
starts.

`scripts/build_riverbend.py` exists to translate the paper set into `packs/riverbend/source.json`.
Its own docstring promises: *"The master model in the paper set is the source of truth (PRD §7):
transactions are authored there, once, and this script only translates. Run it again after the
practice set changes and the pack follows."*

It has not run in some time. The directory it reads, `Riverbend-Paper-Practice-Set/03-Source/`,
was refactored into `practicesets/` and no longer exists. The documented command raises
`FileNotFoundError`. So the 117 KB `source.json` that students work against today has no working
path back to the model that produced it, and nothing noticed.

The evidence that this already cost something: when a money figure printed as `4390.4` had to be
corrected, it was corrected **by editing the JSON by hand**, three times, once per variant, on
branch `pack-figures`. The upstream model in `practicesets/companies/riverbend.py:555` already
formats that figure as `{remit:,.2f}` and has for longer than the fix has existed. A working
translator would have emitted the right text without anyone touching the pack. The hand-edit was
not a divergence from the bridge; it was a symptom of the bridge being dead.

So this work repairs a bridge, proves it against the pack already in service, and only then uses
it for a second company.

## What is already true, and needs no work

Established by reading the app rather than assuming:

- **Original Entry is already multi-company.** `ContentPack`, `PackVersion`,
  `SectionPackAvailability`, `AssignmentChoice` and `services/multicompany.py` are generic and
  keyed off `pack.company.slug`. Riverbend is named in exactly one code path: the hardcoded demo
  source in `flask seed demo` (`cli.py:256-277`), which is out of scope here.
- **The grading engine knows nothing about merchandising.** No reference to inventory, COGS or any
  stock account appears anywhere under `grading/`. Its ten components are generic.
- **Journals are data.** `source.json` carries the journal list with its columns; no journal key is
  hardcoded in the app.

A service business with a Fees Journal and no Purchases Journal is therefore a *content* problem,
not an engine problem. That is the premise this design rests on, and §"Where this could still be
wrong" says what would falsify it.

## The three sets are not the same size

The sequencing follows from this table, which corrects an earlier assumption that Thornemeadow —
sharing Riverbend's four journals — was the gentler second company.

| | Period | Adjustments | Journals | Type |
| --- | --- | --- | --- | --- |
| Riverbend (live) | 1–15 Dec | 0 | 4 | merchandiser |
| **Alder & Finch** | **1–7 Dec** | **0** | **3** | **service** |
| Thorne & Meadow | 1–31 Dec | 6 | 4 | merchandiser |

The live pack stops at the unadjusted trial balance; its rubric uses five of the engine's ten
components. Thorne & Meadow is a full month carrying six adjustments, so it would be the first
pack ever to exercise `adjustment_form`, `adjustment_amounts`, the V11 adjustment rules and
probably statements and closing — none of which has run against real authored content.

Alder & Finch is one week with no adjustments. Its only novelty is the journal shape, which is
data. **It is the smaller set, and it goes first.**

## What gets built

Three pieces, each with one responsibility.

### `scripts/build_pack.py` — generic machinery

Takes a company slug and the path to `practicesets`, imports `generators/model.py` and
`generators/errors.py` with `PRACTICESET_COMPANY` set, and writes `source.json`. It reads figures
and invents none, which is the contract inherited from the script it replaces.

It locates `practicesets` by argument, defaulting to the sibling checkout, and **fails loudly with
a message naming what is missing** when it cannot find it. A missing dependency must stop the run
with an explanation, never degrade quietly. The old script's silent rot is the argument for it.
(The pattern was taken from `docket/engine_bridge.py` in the practicesets repo, which was removed
with the paralegal set on 3 October 2026. The principle stands without the example.)

### `packs/<slug>/profile.py` — what is about the pack, not about the company

Per company, roughly forty lines: slug, display name, accent hex, monogram, course and scope tags,
and the journal column semantics — key, label, side, posting account, subsidiary kind.

**Why these do not live in the company module.** The practicesets repo is paper-only by decision,
and should stay so. More practically, the paper `JOURNALS` structure encodes *layout* — column
widths, page counts, printed labels like `'(105) / (401)'` — while the pack needs *posting
semantics*. Deriving the second from the first means parsing account numbers out of display
strings, which works until a label is reworded. The profile states the semantics outright.

The consequence that matters: Alder & Finch's three-journal shape needs no change to the
translator, only a different profile.

### A test that the bridge still carries weight

A test regenerates Riverbend and asserts the result matches the committed `source.json`. This is
the piece that would have caught the present failure — a documented command crashing for an
unknown length of time with nothing watching.

## The calibration gate

**Before any Alder & Finch work**, regenerate Riverbend with the repaired translator and diff
against the `source.json` in service today. Adjudicate every difference as a later fix or as
drift. The gate's purpose is that the tool proves itself against a known-good target before it is
trusted with content nobody can check — the same discipline that made the derivability audit
trustworthy only after it was calibrated against Riverbend and its six complaints were shown to be
false positives.

The branch matters: `pack-figures` carries the corrected `4,390.40` text and `main` does not, so
the calibration target is the `pack-figures` version. Since the upstream model already formats
that figure correctly, a working translator should reproduce it, and **that specific line is the
sharpest single test of whether the bridge works**.

If the diff shows the online Riverbend has silently diverged from the paper set in any other
respect, that is a finding worth having on its own merits, independent of this work.

## Validation is the real test of the service shape

Alder & Finch goes through the existing path unchanged: `scripts/generate_pack.py` →
`flask packs validate` → `flask packs import`. Two rules carry the weight:

- **V8** — an entry may only post to accounts a special journal's columns allow. A Fees Journal
  with no COGS column is what exercises this.
- **V5** — exactly one control account per party kind. The clinic has clients, not customers.

**V9** replays the authored key through the real ledger engine and must reproduce every balance to
the cent, so a service set that passes has been proved against the engine, not merely shaped
correctly.

## Where this could still be wrong

Stated plainly, because the premise above is load-bearing:

- The engine has no merchandising assumption **that grep can see**. A three-journal pack has never
  been imported. V8 and V9 are where that would surface, and they surface it as a refusal rather
  than as something a student meets.
- The translator's journal handling is written for four journals and a perpetual-inventory
  narrative. Generalising it is the bulk of the work and the likeliest place for a hidden
  assumption.
- Variants are authored, not derived: each carries its own opening balances, document text and
  answer key. Three variants of a service set is three times the content to be wrong.

## Not in this piece of work

- **Thorne & Meadow**, which needs the adjustment and statement side of the format exercised
  properly, and deserves its own design.
- **Adjustments, statements and closing** in the pack format generally.
- The hardcoded Riverbend path in `flask seed demo`.
- Any change to the practicesets repo. It stays paper-only and stays the source of the figures.

## Sequence

1. Repair and generalise the translator; make a missing `practicesets` a loud failure.
2. **Calibrate against Riverbend.** Adjudicate every difference. Nothing proceeds until this is
   understood.
3. Lock it with the regeneration test, so the bridge cannot rot again unobserved.
4. Write the Alder & Finch profile; generate, validate, import.
5. Work a variant through the browser as a student before it is offered to anyone.

Step 2 is the one that can invalidate the rest.
