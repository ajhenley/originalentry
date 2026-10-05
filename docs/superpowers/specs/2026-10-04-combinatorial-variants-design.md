# Combinatorial variants design

**Date:** 4 October 2026 · revised 5 October 2026 after a critical pass

## Intent

Give every student a set nobody has been issued before, make that a guarantee rather than a
probability, and let a pack be reused across terms without last term's answers helping this term's
students.

**For online completion only.** Paper mode cannot be served by this design — see Out of scope.

### What the owner asked for

> each student gets a unique set, i can reuse sets across terms, and I can reduce authoring
> effort. This is for online completion. Additionally, the system can track which versions have
> been assigned to someone so it is a certainty, not just a probability.

Three of the four are delivered. **This does not reduce authoring effort** — today's three variants
come almost free from two driver numbers, and the toggles below are hand-authored. Image cost rises
too. What you buy is uniqueness and reuse; what you pay is authoring and assets. The trade is
deliberate and should be re-examined if either cost bites.

## The three levers

The first draft of this spec optimised the wrong number. These are independent and must be reasoned
about separately:

> **images = documents × states-per-document** — linear, and the real cost
> **combinations ≈ states ^ independent-groups** — exponential, and essentially free
> **sharing = 1 ÷ states** — the chance two students see an identical render of a given document

Anti-collusion depends on **sharing**, not on the combination count. A design can have 65,536
combinations and still show two classmates the same invoice 87% of the time.

| design | images | combinations | sharing |
| --- | --- | --- | --- |
| today — 3 drivers, 1 group | 186 | 3 | 33% |
| rejected first draft — 16 toggled documents, 46 fixed | 78 | 65,536 | **87%** |
| full partition, 2 states | 124 | 32,768 | 50% |
| 2 drivers × toggles — 4 states | 248 | 65,536 | 25% |
| **chosen: 3 drivers × toggles — 6 states** | **372** | **98,304** | **17%** |

The first draft made sharing *worse than today* while appearing to improve everything. It was
rejected for that reason, and the row is kept here so the mistake is not repeated.

## The design

**Six states per document: the existing three drivers, times a two-state toggle.**

- The three drivers (`P1`, `QTY`) stay exactly as they are and keep moving every figure in the set.
- Every document additionally belongs to exactly one **toggle group** — roughly fifteen groups
  across sixty-two documents.
- A student's set is one driver value and one bit per group: `3 × 2^15 = 98,304` combinations.

**Every document belongs to a group. There is no fixed remainder.** That is what the first draft got
wrong: leaving forty-six documents invariant meant one photograph burned them permanently, for every
student and every future term.

### Groups are whole economic events

A transaction is already several pieces of paper. In Riverbend v6:

    D02     Customer purchase order CC-7741   kind=customer_po     entry=False
    D02-2   Invoice 4871                      kind=sales_invoice   entry=True
    D02-3   Bill of lading BL-20411           kind=bill_of_lading  entry=False

and a remittance settles it later. Change the invoice's quantity and the bill of lading, the
remittance, the customer's subsidiary ledger and the trial balance all move.

So **a group must contain the whole economic event, settlement included.** Otherwise a document is
touched by two groups and needs twelve renders rather than six, and the linear image cost is gone.

> **Each document belongs to exactly one toggle group.**

Fifteen groups across sixty-two documents averages four documents per group, which the v6 structure
supports. **The exact grouping must be confirmed while authoring, not assumed** — if the real number
of independent economic events is twelve, the space is `3 × 2^12 = 12,288`, still ample.

### Judgement toggles: three, at most

A figure toggle changes amounts. A judgement toggle changes whether a document needs an entry at
all — the pedagogically interesting case, and the one the owner asked for.

It is only safe where flipping to "no entry" removes nothing downstream. Counted against v6:

| kind | n | safe for a judgement toggle? |
| --- | --- | --- |
| customer PO, bill of lading, purchase order, receiving report | 20 | no — each is half of an economic event |
| time card | 6 | no — feeds the payroll entry on `D24` |
| petty cash voucher | 5 | no — feeds the petty cash reimbursement |
| **void cheque, request for quote, price list** | **3** | **yes** |

So the design is **figures throughout, plus at most three judgement toggles.** The owner chose
"both kinds, chosen per transaction"; this is the honest ceiling on the second kind.

## Model

### A combination *is* a Variant

`PackAsset` is keyed by `(pack_version_id, path)` — **not** by variant — and `Variant` is `code` +
`label` + `driver_values` (JSONB). So a combination materialises as an ordinary `Variant` row,
created when a student is allocated a set:

- `code` — the driver letter plus the group bits, e.g. `B-3F7A`. Four hex characters carry fifteen
  bits; `String(20)` has room.
- `driver_values` — the driver plus the group states.
- its `AnswerKey` — computed and stored at the moment the variant is created.

Thirty students means thirty variant rows, not 98,304.

**Untouched in shape:** grading, checkpoints, the workspace model, the image route, student views,
marks export, the ledger engine.

**Changed:** the pack schema (gains `groups`), the generator (renders six states per document,
enforces the partition), the importer (does not pre-create variants for a grouped pack), allocation
(a new policy), and validation (the rules below).

**Checkpoints need no work.** They carry a `measure` — `{"account": "105"}` — not a figure, and the
answer key has no checkpoint section. Expected values are derived from the ledger, so they compose
with any combination. Verified against the v6 source rather than assumed.

### Pack source

```yaml
groups:
  G1:  kind: figures    owns: [D02, D02-2, D02-3, D04]   # the whole economic event
  G12: kind: judgement  owns: [N01]                      # terminal — nothing downstream
entry_count_band: [27, 29]
```

A document's per-variant map becomes a per-state map, `doc.states["B0"]`, carrying the render for
driver B with that group's bit clear. A pack declares **either** `variants` **or** `groups`.

## Allocation

The uniqueness guarantee is already in the schema: `Variant` carries
`UniqueConstraint("pack_version_id", "code")`. If a combination is materialised only at allocation,
then "a row with this code exists" **is** "this combination has been issued", enforced by the
database under concurrency. No tracking table.

A fourth variant policy, `unique`, joins `round_robin`, `random` and `manual`. Only that policy
allocates combinations, so every existing assignment behaves exactly as it does now.

1. Draw a driver value and one bit per group.
2. Compute how many documents need an entry; redraw if outside `entry_count_band`.
3. Insert the `Variant` row; on a unique-constraint collision, redraw. This mirrors the existing
   retry loop in `new_join_code`.
4. Compute and store the `AnswerKey`.
5. Point the workspace at the variant.

### Exhaustion must be loud

When every in-band combination is issued, **refuse to create the workspace** and say so:
*"this pack has issued all N of its combinations."* Silently reusing one would break the exact
guarantee the feature exists to provide, invisibly.

With three judgement toggles and a ±1 band, roughly half the space is in band — about **49,000
usable** at fifteen groups. The generator prints the exact in-band count at build time so the
ceiling is known before a term starts.

### Workload fairness

Judgement toggles change how many documents need an entry. The rubric computes
`per_document = points / len(documents)`, so the score stays fair, but the effort does not.

**Decision: bound the drift** via the authored `entry_count_band`. With only three judgement
toggles the achievable spread is small, so this constraint is nearly free — it is a guard, not a
significant restriction on the space.

## Validation

You cannot test 98,304 combinations. You do not have to.

**Balance is compositional.** The trial balance is the sum of each group's chosen entries. If every
group's states each balance internally, every combination balances — by addition, not enumeration.
The same argument carries the subsidiary-to-control tie (V7), provided a group's party postings sit
inside the group, which the whole-economic-event rule enforces.

> **2 × groups × drivers checks replace 3 × 2^15.** Ninety checks at fifteen groups.

New rules:

1. **Partition** — every document belongs to exactly one group. Static.
2. **No dependents** — a judgement group owns only terminal documents. Static, from the entry graph.
3. **Per-state balance** — each group's states balance independently, for each driver value, and a
   group's party postings are matched inside it.
4. **Band achievable** — at least one combination falls inside `entry_count_band`; print the exact
   in-band count.

Plus twenty random combinations built end to end. A compositional proof is only as good as its
premise, and the sample is what tests the premise.

## Costs, plainly

| | today | this design |
| --- | --- | --- |
| Images | 186 | **372** (2x) |
| Authoring | 2 driver numbers | 2 driver numbers + ~15 authored alternate economic events |
| Combinations | 3 | 98,304 |
| Sharing | 33% | 17% |

### Storage: measured, and it is the repo that pays, not Postgres

An earlier draft of this spec estimated 200 KB per render and flagged Postgres.
Both were wrong. Measured against the live database:

| | measured |
| --- | --- |
| whole database | 34 MB |
| `pack_asset` — 359 rows | 22 MB |
| average render | **58 kB** (max 152 kB) |
| Riverbend v6 — 186 renders | 14 MB |
| **projected — 372 renders** | **~28 MB per pack version** |

**Postgres is comfortable.** Neon's free tier is 0.5 GB and any paid tier is
10 GB+, so twenty-eight megabytes a version is not a constraint. `PackAsset.data`
is already a `deferred` column precisely so a ledger query never drags image
bytes along with it, and growing what the column holds does not touch that path.
Assets of an unpinned version are also deletable: `riverbend v5` and
`alderfinch v2` carry 171 assets between them with zero live workspaces pointing
at either. Storage you can prune is not a ceiling.

**The git repository is the asymmetric cost.** Renders are committed —
264 PNGs today, of which Riverbend's 186 are 14.8 MB, in a 30 MB object store.
PNGs do not delta-compress, so each grouped version adds roughly 30 MB to
history permanently. An unpinned `PackAsset` row can be deleted; a committed
blob cannot be removed without rewriting history. At ten grouped versions that
is a ~330 MB clone, against 280 MB in Postgres with a 10 GB allowance.

There is also no `.slugignore`, so those bytes ship in the Heroku slug, which is
most of its 54.9 MB against Heroku's 500 MB hard limit.

> **Recommendation, independent of this design:** add a `.slugignore` excluding
> `packs/*/documents/`. The running app never reads `packs/` — the image route
> serves bytes from `PackAsset`, and `packs/` is build-time input to
> `scripts/build_pack.py`. The sole runtime reference is `cli.py` reading
> `riverbend-demo/source.json`, 12 kB with no images. This drops ~20 MB from the
> slug today and keeps it flat as versions accumulate.

Whether grouped-pack renders should be committed at all is a decision this
design should make deliberately rather than inherit. They are reproducible from
`source.json` by the generator, and the authoritative copy already lives in
Postgres.

## Coexistence and migration

Existing packs keep `variants` and are untouched. A grouped pack is a **new pack version**, so
immutability holds and Riverbend v6 — which carries live student work — is unaffected. No migration
of existing assignments is offered.

## Out of scope

- **Paper mode.** 98,304 printed booklets is the thing this design cannot do. The generator should
  refuse a paper-mode assignment on a grouped pack rather than silently serving text alternatives.
- **Converting the existing A/B/C packs.**
- **Reducing authoring effort** — see Intent.

## Consequences to plan for

- `scripts/build_walkthrough.py` builds one instructor answer-key PDF per version. That becomes
  per-student, generated on demand. Automatic grading is unaffected; any workflow relying on printed
  per-version keys changes.
- A student's workspace header shows `Version {{ variant_code }}`. With codes like `B-3F7A` that
  wants a friendlier label.

## What the first draft got wrong

Recorded so the reasoning is not lost and the mistakes are not repeated.

1. **It optimised combinations and ignored sharing**, producing a design with 65,536 combinations
   and 87% sharing — worse than the 33% it replaced. Leaving forty-six documents invariant was a
   permanent leak across all terms, written up as one table row.
2. **It offered judgement toggles without counting whether they were possible.** Three documents
   qualify, not the implied sixteen.
3. **It deferred the in-band arithmetic** to build time instead of doing it.
4. **It left checkpoints unexamined.** They turned out to be fine, but that was luck, not diligence.
5. **It guessed at storage instead of measuring it**, overstating per-render size by 3.4x and
   flagging Postgres — which has ample headroom — while missing the committed-to-git cost, which is
   the one that cannot be undone.
