"""What each pack profile refuses about itself, proved rather than asserted by hand.

``check()`` in packs/*/profile.py is this branch's own defence against its own defect class: a
document, column or label that disagrees with the chart while every figure stays right, which
nothing downstream can see. Three rounds of fixes went into those guards, and every one of them
was proved at a terminal and then left uncommitted — putting ``return`` at the top of both
``check()`` functions left the whole suite passing. These tests are that induction, written down.

Each case builds one bad state in memory on a freshly loaded copy of the profile and asserts both
that it exits and what it says, so a test fails for the reason its name gives rather than because
some unrelated guard happened to fire first. Nothing here touches a file on disk.
"""

from __future__ import annotations

import copy
import importlib.util
import itertools
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRACTICESETS = ROOT.parent / "practicesets"
ALLOW_NO_SETS = os.environ.get("PACK_TRANSLATOR_ALLOW_NO_SETS") == "1"

# Both companies. Riverbend is in front of students; the clinic is new. A guard that holds for
# one and not the other is the shape of defect this file exists to catch.
PROFILES = ("riverbend", "alderfinch")

# Only the clinic states its payroll account names as a profile constant the chart is checked
# against; Riverbend's payroll stub still spells them inline, so it has no such guard to test.
# test_only_these_profiles_declare_payroll_labels keeps that gap visible rather than silent.
PAYROLL_PROFILES = ("alderfinch",)

# Both packs now take their document list from the envelope's manifest, so both check() functions
# accept one and both cross-check GUIDANCE against what was printed. Riverbend was the gap this
# tuple existed to keep visible, and it closed when its pack was rebuilt from its own envelope.
# test_only_these_profiles_check_against_a_manifest still guards the shape: a profile that gains
# the parameter without the cross-check is reported, and so is one that moves to the manifest
# while this file still has no case for it. The order is PROFILES' own, which is what that test
# compares against.
MANIFEST_PROFILES = ("riverbend", "alderfinch")

# A number no chart in this repository uses, and a sequence number no pack has a document for.
ABSENT_ACCOUNT = "997"
ABSENT_SEQUENCE = 997
# The same, for a profile whose guidance is keyed by the manifest's own ref. Both are keyed that
# way today; the int sentinel is kept because _absent_guidance_key has to pick one and a profile
# with no envelope would key by received_seq again. A sentinel of the wrong type works until a
# check sorts the two kinds of key together, which `stray` does — and then the refusal comes out
# as a TypeError.
ABSENT_REF = "ZZ-not-printed"

_counter = itertools.count()


def _require_sets():
    """Absence of the practice sets fails rather than skips.

    check() is only meaningful against the real chart and the real transaction list, so these
    tests need the sibling checkout. Left as a skip they would vanish in any environment without
    it — which is every CI run this repository has — and the suite would report green having
    tested none of the guards it exists to defend.
    """
    if PRACTICESETS.is_dir():
        return
    if ALLOW_NO_SETS:
        pytest.skip("PACK_TRANSLATOR_ALLOW_NO_SETS=1")
    pytest.fail(
        f"The practice sets are not at {PRACTICESETS}, so the tests that prove each profile's "
        f"check() still refuses a bad profile cannot run. Check practicesets out beside this "
        f"repository, or set PACK_TRANSLATOR_ALLOW_NO_SETS=1 to accept the gap knowingly."
    )


def _script():
    """scripts/ is not a package, so the module is loaded by path."""
    spec = importlib.util.spec_from_file_location(
        "build_pack", ROOT / "scripts" / "build_pack.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _profile(slug: str):
    """A private copy of one profile, loaded by path under a name of its own.

    Each test gets its own module object so the bad state it builds cannot reach another test,
    and so nothing is ever written back to packs/<slug>/profile.py.
    """
    path = ROOT / "packs" / slug / "profile.py"
    spec = importlib.util.spec_from_file_location(
        f"{slug}_profile_{next(_counter)}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _loaded(slug: str):
    """One profile and the real model it claims to describe."""
    _require_sets()
    script = _script()
    model, _errors = script.load_model(script.require_practicesets(PRACTICESETS), slug)
    return _profile(slug), model


def _refusal(profile, model) -> str:
    """check() must exit, and the message is what the caller is left with."""
    with pytest.raises(SystemExit) as caught:
        profile.check(model)
    message = str(caught.value)
    assert profile.COMPANY["slug"] in message, message
    return message


def _absent_guidance_key(profile):
    """A key no document has, of the kind this profile keys guidance by.

    Both packs key by the manifest's own ref (strings) now that both are built from a printed
    envelope. The int branch stays for a profile built without one, which keys by received_seq.
    """
    keys = set(profile.GUIDANCE) | set(profile.GUIDED_SEQUENCES)
    return ABSENT_REF if all(isinstance(key, str) for key in keys) else ABSENT_SEQUENCE


def _first_column_with_an_account(journals):
    """The journals, deep-copied, and one column of them that names an account."""
    journals = copy.deepcopy(journals)
    for journal in journals:
        for column in journal.get("columns", []):
            if column.get("account") is not None:
                return journals, journal, column
    raise AssertionError("no journal column names an account, so there is nothing to check")


@pytest.mark.parametrize("slug", PROFILES)
def test_the_profile_as_shipped_is_accepted(slug):
    """The control. Every case below mutates one thing; this says the rest is sound, so a
    failure there is the mutation and not the profile."""
    profile, model = _loaded(slug)

    assert profile.check(model) is None


@pytest.mark.parametrize("slug", PROFILES)
def test_a_special_cased_transaction_that_does_not_exist_is_refused(slug):
    """extra_fields() special-cases transaction numbers by literal. A company with fewer
    transactions makes those branches dead, silently, and the document detail disappears."""
    profile, model = _loaded(slug)
    profile._SPECIAL_TRANSACTIONS = set(profile._SPECIAL_TRANSACTIONS) | {ABSENT_SEQUENCE}

    message = _refusal(profile, model)

    assert "no transaction numbered" in message, message
    assert str(ABSENT_SEQUENCE) in message, message


@pytest.mark.parametrize("slug", PROFILES)
def test_a_journal_column_naming_an_account_off_the_chart_is_refused(slug):
    profile, model = _loaded(slug)
    journals, journal, column = _first_column_with_an_account(profile.JOURNALS)
    column["account"] = ABSENT_ACCOUNT
    profile.JOURNALS = journals

    message = _refusal(profile, model)

    assert f"column {column['key']!r} names account {ABSENT_ACCOUNT}" in message, message
    assert "not in the chart" in message, message
    assert journal["key"] in message, message
    assert "Nothing was written" in message, message


@pytest.mark.parametrize("slug", PROFILES)
def test_a_journal_column_labelled_against_the_chart_is_refused(slug):
    """The account exists; only the words a student reads disagree with it. Every figure is
    still right, which is why nothing but this guard can see it."""
    profile, model = _loaded(slug)
    journals, journal, column = _first_column_with_an_account(profile.JOURNALS)
    chart = model.ACCT_NAME[int(column["account"])]
    column["label"] = "Delivery Van Dr"
    assert profile._bare(column["label"]) != profile._bare(chart)
    profile.JOURNALS = journals

    message = _refusal(profile, model)

    assert f"column {column['key']!r} is labelled 'Delivery Van Dr'" in message, message
    assert f"does not match the chart's {chart!r}" in message, message
    assert journal["key"] in message, message
    assert "Nothing was written" in message, message


@pytest.mark.parametrize("slug", PROFILES)
def test_a_checkpoint_on_an_account_off_the_chart_is_refused(slug):
    profile, model = _loaded(slug)
    checkpoints = copy.deepcopy(profile.CHECKPOINTS)
    checkpoints[0]["measure"]["account"] = ABSENT_ACCOUNT
    profile.CHECKPOINTS = checkpoints

    message = _refusal(profile, model)

    assert f"checkpoint {checkpoints[0]['key']} measures account {ABSENT_ACCOUNT}" in message, \
        message
    assert "not in the chart" in message, message
    assert "Nothing was written" in message, message


@pytest.mark.parametrize("slug", PAYROLL_PROFILES)
def test_a_payroll_label_that_disagrees_with_the_chart_is_refused(slug):
    """One account, one name. The packet once called 511 three different things across the
    chart, the reference page and the document a student actually reads."""
    profile, model = _loaded(slug)
    number = sorted(profile.PAYROLL_LABELS)[0]
    chart = model.ACCT_NAME[number]
    profile.PAYROLL_LABELS = dict(profile.PAYROLL_LABELS) | {number: "Sales salaries"}
    assert profile._bare("Sales salaries") != profile._bare(chart)

    message = _refusal(profile, model)

    assert f"calls account {number} 'Sales salaries'" in message, message
    assert f"the chart calls it {chart!r}" in message, message
    assert "Nothing was written" in message, message


def test_only_these_profiles_declare_payroll_labels():
    """The payroll-label guard can only be tested where the profile states the labels. If a
    profile gains PAYROLL_LABELS, it needs that guard and this file needs the case for it."""
    _require_sets()
    declared = tuple(s for s in PROFILES if hasattr(_profile(s), "PAYROLL_LABELS"))

    assert declared == PAYROLL_PROFILES, (
        f"{declared} declare PAYROLL_LABELS but only {PAYROLL_PROFILES} are checked here. "
        f"Add the profile to PAYROLL_PROFILES once its check() compares the labels to the chart."
    )


@pytest.mark.parametrize("slug", PROFILES)
def test_a_guided_document_with_no_guidance_is_refused(slug):
    """A guided document with no guidance is worse than an unguided one: the student is told to
    expect help and shown an empty space."""
    profile, model = _loaded(slug)
    absent = _absent_guidance_key(profile)
    profile.GUIDED_SEQUENCES = set(profile.GUIDED_SEQUENCES) | {absent}

    message = _refusal(profile, model)

    assert f"document [{absent!r}]".replace("'", "") in message.replace("'", ""), message
    assert "GUIDANCE says nothing" in message, message
    assert "Nothing was written" in message, message


@pytest.mark.parametrize("slug", PROFILES)
def test_guidance_for_a_document_that_is_never_guided_is_refused(slug):
    """The other direction. Words nobody reads mean the guidance was written for a document
    that has since stopped being guided, and the guided ones may now be bare."""
    profile, model = _loaded(slug)
    absent = _absent_guidance_key(profile)
    profile.GUIDANCE = dict(profile.GUIDANCE) | {absent: "Words nobody will read."}

    message = _refusal(profile, model)

    assert f"GUIDANCE has text for document [{absent!r}]".replace("'", "") \
        in message.replace("'", ""), message
    assert "never guided" in message, message
    assert "Nothing was written" in message, message


def _manifest_of(profile, guided=None):
    """A manifest shaped the way ``build_pack.py`` loads it, holding the guided refs it names.

    ``check(model, manifest)`` reads nothing but ``entry["ref"]``, so this is all a manifest
    needs to be for the coverage check; building a real one would need the practice set's
    gendocs.py and a renderer and would say nothing more.
    """
    refs = sorted(profile.GUIDANCE) if guided is None else guided
    return [{"ref": ref} for ref in refs]


@pytest.mark.parametrize("slug", MANIFEST_PROFILES)
def test_the_profile_as_shipped_is_accepted_against_the_envelope(slug):
    """The control for the case below: GUIDANCE as shipped names documents the envelope prints."""
    profile, model = _loaded(slug)

    assert profile.check(model, _manifest_of(profile)) is None


@pytest.mark.parametrize("slug", MANIFEST_PROFILES)
def test_guidance_for_a_document_the_envelope_does_not_print_is_refused(slug):
    """The check that replaced the two GUIDANCE/GUIDED_SEQUENCES ones, and had no test at all.

    GUIDANCE is keyed by the manifest's own refs so that adding a document to the envelope cannot
    move the guidance onto a different one. The cost is that renaming or dropping a printed
    artefact leaves GUIDANCE pointing at a ref nothing prints — and the two constants agreeing
    with each other cannot see that, because they would simply agree on the wrong thing.
    """
    profile, model = _loaded(slug)
    manifest = _manifest_of(profile)
    dropped = manifest.pop()["ref"]          # the envelope stops printing one guided document

    with pytest.raises(SystemExit) as caught:
        profile.check(model, manifest)

    message = str(caught.value)
    assert profile.COMPANY["slug"] in message, message
    assert f"GUIDANCE guides ['{dropped}']" in message, message
    assert "manifest does not contain" in message, message
    assert "Nothing was written" in message, message


def test_only_these_profiles_check_against_a_manifest():
    """A profile that moves to the envelope's manifest needs the coverage check, and this file
    needs the case for it. Checked by behaviour rather than by signature: a check() that ignores
    the manifest it is handed would pass a signature test."""
    _require_sets()
    accepting = []
    ignoring = []
    for slug in PROFILES:
        profile, model = _loaded(slug)
        try:
            profile.check(model, [{"ref": "nothing-is-guided-by-this"}])
        except TypeError:
            continue                          # check(model) only — no manifest path at all
        except SystemExit:
            accepting.append(slug)            # refused a manifest covering none of GUIDANCE
            continue
        # Took the manifest and returned happily on one that covers none of GUIDANCE. That is
        # the signature of a manifest check without the check, and counting it as "accepting"
        # is what made this test the signature test its docstring disclaims.
        ignoring.append(slug)
    assert not ignoring, (
        f"{tuple(ignoring)} accept a manifest argument and pass one that covers none of "
        f"GUIDANCE. The parameter is there; the cross-check is not."
    )
    assert tuple(accepting) == MANIFEST_PROFILES, (
        f"{tuple(accepting)} accept a manifest but only {MANIFEST_PROFILES} are checked here. "
        f"Add the profile once its check() cross-checks GUIDANCE against what was printed."
    )


# Two cases stood here: test_d16s_printed_returned_item_total_is_cross_checked_against_the_books
# and test_d23s_printed_arithmetic_is_cross_checked_against_the_books, with a _tamper_account
# helper that nudged one line of one transaction so the guard they proved had something to
# refuse. Both guards were deleted with the extra_fields branches they defended: D16's returned
# item and D23's remittance arithmetic are no longer printed from the profile at all, so there is
# no second copy of either figure for the model to drift away from.
#
# What those two cases were really defending -- a figure a student reads off a document
# disagreeing with the figure the key expects for it -- is now
# test_every_cash_document_prints_the_figure_the_key_expects in
# tests/unit/test_riverbend_pack.py, which asserts it from the artefact's own text against the
# committed answer key rather than from one profile literal against another.
