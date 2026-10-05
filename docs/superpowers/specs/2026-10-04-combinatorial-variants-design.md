# Combinatorial variants design

**Date:** 4 October 2026

## Intent

Give every student a set nobody else has ever been issued, and make that a guarantee rather than
a probability. Reuse a pack across terms without last term's answers helping this term's students.

Today a pack carries three fixed variants (A, B, C) generated from two drivers, and every student
gets one of three. The proposal replaces that, for packs that opt in, with **N independent binary
toggles**, so a student's set is one of 2^N combinations.

Throughout, **N** is the number of toggles a pack declares. Sixteen is used for illustration;
the Sizing section recommends choosing N from real enrolment.

**For online completion only.** Paper mode is out of scope and cannot be served by this design —
see Out of scope.

### What the owner asked for, in their words

> each student gets a unique set, i can reuse sets across terms, and I can reduce authoring
> effort. This is for online completion. Additionally, the system can track which versions have
> been assigned to someone so it is a certainty, not just a probability.

Three of those four are delivered. The fourth is not, and the owner should hold this spec to that:
**this does not reduce authoring effort.** Today's three variants come almost free, because two
driver numbers generate all three. N hand-authored toggles is *more* authoring. What falls is the
image cost; what rises is authoring. The trade is deliberate and is the price of the guarantee.

## The constraint that shapes everything

Answers are cheap. The generator already computes every figure by replaying authored entries
through the app's own ledger engine, so drivers could take fifty values tomorrow at no authoring
cost.

**Images are what cannot scale.** A document must be rendered for every distinct version of its
content. Naively, 65,536 combinations × 62 documents is four million renders.

The design dodges that by making variation **per-document binary**: each document has at most two
renders, and a student's set is *composed*, never pre-rendered. Images stay linear while
combinations grow exponentially.

That yields the rule the whole design rests on:

> **Each document may be touched by at most one toggle.**

A document whose content depends on two toggles needs four renders; three toggles, eight. The N
toggles must therefore **partition** the documents.

### Measured, for Riverbend v6

Illustrative, at sixteen toggles — the counts scale with N:

| | Today (3 variants) | Sixteen toggles |
| --- | --- | --- |
| Images | 186 | 78 |
| Distinct sets | 3 | 65,536 |
| Documents differing between two students | 62 of 62 | ~8 of 62 |

The last row is the honest cost. Today two students share no identical document. Under this they
share roughly 54 of 62: the *combination* is unique, but most individual documents are not.
Copying a classmate's trial balance still fails; copying their entry for one document often works.

## Toggles cascade, and the clusters must contain the cascade

A transaction is already several pieces of paper. In Riverbend v6, ten groups hold three documents
each, and their triage answers differ within the group:

    D02     Customer purchase order CC-7741   kind=customer_po     entry=False
    D02-2   Invoice 4871                      kind=sales_invoice   entry=True
    D02-3   Bill of lading BL-20411           kind=bill_of_lading  entry=False

and a remittance settles it later.

Change the invoice's quantity and the bill of lading, the remittance, the customer's subsidiary
ledger and the trial balance all move. So **a toggle's cluster must contain the whole economic
event, settlement included** — otherwise a document is touched by two toggles and needs four
renders.

Change the *judgement* — invoice becomes a quotation — and the receivable never exists, so the
remittance must vanish or become something else. Hence the second rule: judgement toggles are
permitted only on **terminal** documents, ones nothing downstream depends on (a void cheque, a
time card, a price list, an unaccepted quotation).

## Model

### A combination *is* a Variant

`PackAsset` is keyed by `(pack_version_id, path)` — **not** by variant. `Variant` is `code` +
`label` + `driver_values` (JSONB). Therefore a combination can be materialised as an ordinary
`Variant` row, created on demand when a student is allocated a set:

- `code` — the combination, 16 bits as 4 hex characters (`String(20)` has room)
- `driver_values` — the toggle states
- its `AnswerKey` — computed and stored at the moment the variant is created

Thirty students means thirty variant rows, not 65,536.

**Everything downstream is untouched in shape.** `workspace.variant_id` still points at a variant;
`grading/checkpoints.py` still reads `AnswerKey` by `(pack_version_id, variant_id)`; the image
route still resolves a path; marks export, the ledger engine and the student views do not change.

### Pack source

The source gains a `toggles` section. Each toggle declares the documents it owns:

```yaml
toggles:
  T1:  kind: figures    owns: [D02, D02-2, D02-3, D04]   # the whole economic event
  T7:  kind: judgement  owns: [N02]                      # terminal — nothing downstream
entry_count_band: [27, 29]
```

A document's per-variant map becomes a per-option map:

| today | proposed |
| --- | --- |
| `doc.variants["A"].image` | `doc.options["0"].image` |
| three renders per document | two renders, and only for toggled documents |

A pack declares **either** `variants` **or** `toggles`, never both.

## Allocation

The uniqueness guarantee is already in the schema: `Variant` carries
`UniqueConstraint("pack_version_id", "code")`. If a combination is materialised *only* at
allocation, then "a row with this code exists" **is** "this combination has been issued", and the
database enforces it under concurrency. No tracking table is needed.

A fourth variant policy, `unique`, joins `round_robin`, `random` and `manual`. Only that policy
triggers combination allocation, so every existing assignment behaves exactly as it does today.

Allocating one student's set:

1. Draw N bits at random.
2. Compute how many documents that combination asks for an entry on; redraw if it falls outside
   `entry_count_band`.
3. Insert the `Variant` row. If the unique constraint fires, another allocation took it mid-flight
   — redraw. This mirrors the existing retry loop in `new_join_code`.
4. Compute and store the `AnswerKey` for those bits.
5. Point the workspace at the variant.

### Exhaustion must be loud

When every in-band combination has been issued, **refuse to create the workspace** and tell the
instructor plainly: *"this pack has issued all 1,024 of its combinations."*

Silently reusing a combination would break the exact guarantee this feature exists to provide, and
would do it invisibly. The generator prints the exact in-band count at build time, so the ceiling
is known before a term starts rather than when a student cannot join.

### Workload fairness

Judgement toggles change how many documents need an entry, so students face different workloads.
The rubric computes `per_document = points / len(documents)`, so the *score* stays fair, but the
*effort* does not.

**Decision: bound the drift.** The authored `entry_count_band` constrains allocation to
combinations within a narrow range (for example ±1). This keeps nearly all the combination space,
puts the constraint in the allocator rather than in authoring, and is one predicate that can be
tightened later.

Rejected: pairing every entry-removing toggle with an entry-adding one (costs half the space), and
accepting unbounded drift (a student who gets four fewer documents will notice).

## Sizing

16 toggles is 65,536, but with the uniqueness guarantee you need only more combinations than
students you will ever have. Ten toggles is 1,024; eight is 256. A class of 30 across eight terms
is 240.

**Build the mechanism for N, choose N from real enrolment.** Authoring ten toggles costs 62% of
sixteen and still never repeats. More toggles can be authored later; the combination space grows
without touching the code.

## Validation

You cannot test 65,536 combinations. You do not have to.

**Balance is compositional.** The trial balance is the fixed entries plus the sum of each toggle's
chosen entries. If every toggle's two states are each internally balanced, every combination
balances — by addition, not enumeration. The same argument carries the subsidiary-to-control tie
(V7), provided each cluster's party postings sit inside the cluster, which the whole-economic-event
rule already enforces.

> **2N checks replace 2^N.** Two states × N toggles — 20 checks at ten toggles, 32 at sixteen.

New rules:

1. **Partition** — every document is owned by at most one toggle. Static check.
2. **No dependents** — a judgement toggle owns only terminal documents. Static check against the
   entry graph.
3. **Per-toggle balance** — each toggle's two states balance independently, and each cluster's
   party postings are matched within the cluster.
4. **Band achievable** — at least one combination falls inside `entry_count_band`; print the exact
   in-band count.

Plus a sample of twenty random combinations built end to end. A compositional proof is only as good
as its premise, and the sample is what tests the premise.

## Coexistence and migration

Existing packs keep `variants` and are untouched. A toggle pack is a **new pack version**, so
immutability holds and Riverbend v6 — which carries live student work — is unaffected. No migration
of existing assignments is required or offered.

## Out of scope

- **Paper mode.** 1,024 printed booklets is the thing this design cannot do. Packs using toggles
  are screen-mode only, and the generator should refuse a paper-mode assignment on a toggle pack
  rather than silently serving text alternatives.
- **Converting the existing A/B/C packs.**
- **Reducing authoring effort** — see Intent. This costs more authoring, not less.

## Consequence the owner should plan for

`scripts/build_walkthrough.py` builds one instructor answer-key PDF per version. With 1,024
versions that becomes per-student, generated on demand. Automatic grading is unaffected — it reads
the stored `AnswerKey` — but any workflow that relies on printed per-version keys changes.
