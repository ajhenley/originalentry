"""The manufacturer: Ashgrove Millwork, 1-18 December.

The paper practice set is the source of truth and scripts/build_pack.py only translates it. What
this guards is that the translation stayed faithful: the figures the app derives by replaying the
key through its own ledger engine must equal the figures in the paper solution, to the cent, for
all three versions.

If those ever disagree, a student marked by this app and a student marked from the printed key
would receive different marks for the same work.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from originalentry.generator import build
from originalentry.packs import schema
from originalentry.packs.validate import validate_pack

SOURCE = Path(__file__).resolve().parents[2] / "packs" / "ashgrove" / "source.json"

# Computed from the practicesets model with its own trial_balance, which is what prints the
# solution set's Checkpoint Answers page. cp1 Accounts Receivable, cp2 Cash, cp3 Accounts Payable
# (a credit balance, asked as a positive figure), cp4 Work in Process.
PAPER = {
    "A": {"cp1": Decimal("13230.00"), "cp2": Decimal("12749.80"),
          "cp3": Decimal("12214.00"), "cp4": Decimal("2310.00")},
    "B": {"cp1": Decimal("13530.00"), "cp2": Decimal("12397.00"),
          "cp3": Decimal("12354.00"), "cp4": Decimal("2394.00")},
    "C": {"cp1": Decimal("13830.00"), "cp2": Decimal("12044.20"),
          "cp3": Decimal("12494.00"), "cp4": Decimal("2478.00")},
}


@pytest.fixture(scope="module")
def generated():
    return build(json.loads(SOURCE.read_text()), render_images=False)


def test_the_pack_passes_every_rule(generated):
    pack = schema.load_pack(generated.pack)
    loaded_keys = {code: schema.load_answer_key(k) for code, k in generated.keys.items()}

    assert validate_pack(pack, loaded_keys) == []


def test_the_checkpoints_match_the_paper_solution(generated):
    for code, expected in PAPER.items():
        checkpoints = generated.keys[code]["checkpoints"]
        for key, figure in expected.items():
            assert Decimal(checkpoints[key]) / 100 == figure, f"{code} {key}"


def test_no_checkpoint_can_be_passed_by_copying(generated):
    """Three versions exist to make copying visible. A checkpoint that answers the same in all
    three cannot do that. Every one of this set's four moves with the drivers, the Work in Process
    control included -- its materials are sized on QTY so the versions differ all the way through."""
    for key in ("cp1", "cp2", "cp3", "cp4"):
        answers = {generated.keys[code]["checkpoints"][key] for code in ("A", "B", "C")}
        assert len(answers) == 3, f"{key} answers the same in more than one version"


def test_the_payables_control_is_asked_as_a_positive_figure(generated):
    """Accounts Payable is a liability, stored with a negative sign. A student reads the balance
    off a trial balance's credit column and writes it as a positive number; asking them for a
    negative one is a question about this app, not about accounting."""
    for code in ("A", "B", "C"):
        assert generated.keys[code]["checkpoints"]["cp3"] > 0


def test_the_parties_are_customers_suppliers_and_jobs_only(generated):
    """A sole proprietorship: the owner's withdrawal is an equity movement, never a party in a
    subsidiary ledger. The parties are the shop's customers, its suppliers and its jobs -- and the
    proprietor is none of them, so M. Ashgrove must not appear among them."""
    assert {p["kind"] for p in generated.pack["parties"]} == {"customer", "supplier", "job"}
    names = " ".join(p["name"].lower() for p in generated.pack["parties"])
    assert "ashgrove" not in names


def test_the_manufacturer_keeps_its_three_inventory_accounts(generated):
    """What makes this a manufacturer rather than a merchandiser, carried into the pack's chart."""
    names = {a["number"]: a["name"].lower() for a in generated.pack["accounts"]}
    assert "raw materials inventory" in names["111"]
    assert "work in process" in names["112"]
    assert "finished goods inventory" in names["113"]
    assert "merchandise inventory" not in set(names.values())


# ── The job cost sheet subsidiary ledger ─────────────────────────────────────────────────
#
# Work in Process is the manufacturer's third subsidiary ledger. These prove the pack wires it the
# way the app grades it: by replaying the key through the real ledger engine and asking the same
# subsidiary_proof the subsidiary_agreement grading component asks, for a student who worked the key
# exactly. A control that did not tie to its sheets would be the fourth checkpoint failing for
# everyone, or a job the student could not post to.

from originalentry.ledger import engine  # noqa: E402
from originalentry.packs import replay  # noqa: E402

VARIANTS = ("A", "B", "C")


def test_work_in_process_is_a_job_subsidiary_control(generated):
    wip = next(a for a in generated.pack["accounts"] if a["number"] == "112")
    assert wip["subsidiary_kind"] == "job"
    jobs = [p for p in generated.pack["parties"] if p["kind"] == "job"]
    assert {p["code"] for p in jobs} == {"J-114", "J-115", "J-117"}


def _proof(generated, code):
    pack = schema.load_pack(generated.pack)
    key = schema.load_answer_key(generated.keys[code])
    snapshot = replay.build_replay_snapshot(pack, key)
    return engine.subsidiary_proof(snapshot, "job")


@pytest.mark.parametrize("code", VARIANTS)
def test_the_job_sheets_tie_to_the_work_in_process_control(generated, code):
    """The invariant the paper set proves by hand, now proved through the app's own engine: the sum
    of the open cost sheets equals the Work in Process control, to the cent, for a perfect student."""
    proof = _proof(generated, code)
    assert proof.agrees, (
        f"variant {code}: control {proof.control_balance_cents}, sheets {proof.party_total_cents}"
    )


@pytest.mark.parametrize("code", VARIANTS)
def test_a_delivered_job_closes_its_sheet_and_the_open_one_is_the_control(generated, code):
    """J-114 is built, finished and invoiced; J-115 is finished and sits in finished goods; J-117 is
    still on the bench. So two sheets close to nil and the third is the whole of ending Work in
    Process -- which is what the schedule's last line reports and the fourth checkpoint measures."""
    proof = _proof(generated, code)
    sheets = {row.party_code: row.balance_cents for row in proof.party_rows}
    assert sheets["J-114"] == 0
    assert sheets["J-115"] == 0
    assert sheets["J-117"] > 0
    assert sheets["J-117"] == proof.control_balance_cents


@pytest.mark.parametrize("code", VARIANTS)
def test_every_other_subsidiary_ledger_still_ties(generated, code):
    """Adding a third ledger must not disturb the two that were already right."""
    pack = schema.load_pack(generated.pack)
    key = schema.load_answer_key(generated.keys[code])
    snapshot = replay.build_replay_snapshot(pack, key)
    for kind in ("customer", "supplier"):
        assert engine.subsidiary_proof(snapshot, kind).agrees, f"{code}: {kind} no longer ties"
