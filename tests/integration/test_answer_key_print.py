"""The instructor's answer key, on one page to print (I5.3).

What an instructor marking on paper needs in their hand: which documents take an entry and which
do not, the entry each one takes, the adjustments, the figure each checkpoint is looking for, and
the balances the period should end on.

It is staff-only, and being staff-only is the whole security story: this page is the answers.
"""

import copy
import re
import secrets

import pytest
from originalentry.models import ContentPack, User, Variant
from originalentry.packs import schema
from originalentry.packs.importer import import_answer_keys, import_content
from sqlalchemy import select

from tests.packs import testco_alpha

pytestmark = pytest.mark.db


# A document that takes no entry — a quotation is not a transaction. The stock fixture has none,
# and triage is half of what an instructor marks, so the key has to be able to say "nothing here".
QUOTE = {
    "ref": "QUO-1",
    "display_ref": "Quotation 1",
    "type": "other",
    "date": "2026-12-08",
    "received_seq": 3,
    "variants": {"A": {"text_alternative": {"fields": [["Customer", "Firstborn Supply"]],
                                            "lines": []}}},
}


#  F3: the reason a filed document needs no entry, so it can be told apart from the stray
#  reason below -- the one no rendered row may ever carry, because INV-1 takes an entry.
FILED_REASON = "Quoted, not ordered; no transaction has happened."
STRAY_REASON = "This must never reach the page: INV-1 takes an entry."


@pytest.fixture
def key(session, client):
    data = copy.deepcopy(testco_alpha.PACK)
    data["company"]["slug"] = f"key-{secrets.token_hex(3)}"
    data["documents"] = [*data["documents"], copy.deepcopy(QUOTE)]
    answer = copy.deepcopy(testco_alpha.KEY_A)
    answer.setdefault("triage", {})[QUOTE["ref"]] = False
    answer["triage_reasons"] = {QUOTE["ref"]: FILED_REASON, "INV-1": STRAY_REASON}
    pv = import_content(session, schema.load_pack(data), source_sha256=secrets.token_hex(32))
    import_answer_keys(session, pv, {"A": schema.load_answer_key(answer)})
    pack = session.get(ContentPack, pv.content_pack_id)
    instructor = User(email=f"ki-{secrets.token_hex(3)}@example.edu", role="instructor")
    student = User(email=f"ks-{secrets.token_hex(3)}@example.edu", role="student")
    session.add_all([instructor, student])
    session.commit()
    return pv, pack, instructor, student


def _url(pv, code="A"):
    return f"/staff/catalogue/{pv.id}/key/{code}"


def test_a_student_cannot_reach_the_answers(client, key):
    pv, _, _, student = key
    client.sign_in(student)

    assert client.get(_url(pv)).status_code in (403, 404)


def test_it_lists_the_documents_that_take_no_entry(client, key):
    """The judgement being tested is triage, so the key has to show both answers."""
    pv, _, instructor, _ = key
    client.sign_in(instructor)

    body = client.get(_url(pv)).get_data(as_text=True)

    assert "No entry" in body


def test_it_states_the_reason_a_filed_document_needs_no_entry(client, key):
    """printable_key's own docstring says an instructor needs a document "with the entry it
    takes (or the fact that it takes none)" -- the fact alone used to print as a bare "No entry"
    with nothing saying why. triage_reasons is V17's own field for that reason (F3)."""
    pv, _, instructor, _ = key
    client.sign_in(instructor)

    body = client.get(_url(pv)).get_data(as_text=True)

    assert FILED_REASON in body


def test_no_reason_prints_on_a_document_that_takes_an_entry(client, key):
    """A reason recorded against a document that takes an entry (a broken key -- V17 would
    refuse it) must never render. printable_key only ever sets KeyDocument.reason where
    takes_entry is False, so a reason reaching an entered document's row would mean that
    contract broke, not that the template failed to double-guard it."""
    pv, _, instructor, _ = key
    client.sign_in(instructor)

    body = client.get(_url(pv)).get_data(as_text=True)

    assert STRAY_REASON not in body


def test_it_shows_each_expected_entry_in_money(client, key):
    pv, _, instructor, _ = key
    client.sign_in(instructor)

    body = client.get(_url(pv)).get_data(as_text=True)

    assert re.search(r"\d,\d\d\d\.\d\d|\d+\.\d\d", body), "figures are not in money"


def test_it_names_accounts_rather_than_leaving_bare_numbers(client, key):
    pv, _, instructor, _ = key
    client.sign_in(instructor)

    body = client.get(_url(pv)).get_data(as_text=True)

    assert "Accounts Receivable" in body


def test_it_shows_the_adjustments_and_the_checkpoint_figures(client, key):
    pv, _, instructor, _ = key
    client.sign_in(instructor)

    body = client.get(_url(pv)).get_data(as_text=True)

    assert "Adjustments" in body
    assert "Checkpoint" in body


def test_a_variant_with_no_key_is_not_there(client, key):
    pv, _, instructor, _ = key
    client.sign_in(instructor)

    assert client.get(_url(pv, "ZZ")).status_code == 404


def test_the_catalogue_links_to_every_variants_key(client, session, key):
    """A key nothing links to is a key nobody prints."""
    pv, _, instructor, _ = key
    client.sign_in(instructor)
    codes = list(session.scalars(select(Variant.code).where(Variant.pack_version_id == pv.id)))

    body = client.get("/staff/catalogue").get_data(as_text=True)

    assert codes, "the fixture has no variants"
    for code in codes:
        assert _url(pv, code) in body
