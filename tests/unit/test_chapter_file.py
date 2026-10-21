"""The chapter file: what it accepts, what it refuses, and what it translates to.

The format exists so an instructor can write a chapter of problems in one file without learning
the pack source. That only works if the validator is honest about mistakes: a format that accepts
a problem which then cannot be graded has moved the failure somewhere the author cannot see it.

Two properties matter more than any single rule. Every fault is reported, not just the first --
fixing ten problems one import at a time is the difference between a usable format and an
unusable one. And amounts are cents, which is the trap this format sets for a human, so an error
about a figure says it both ways.

No database: the parse and the translation are pure, which is what lets these run in a tenth of a
second.
"""

from __future__ import annotations

import pytest
from originalentry.packs import schema, validate
from originalentry.problems import chapter

VALID = """
textbook: OpenStax Principles of Financial Accounting
chapter: 3
chapter_label: Analyzing and Recording Transactions
accounts:
  - {number: "101", name: Cash, type: asset, normal_balance: debit}
  - {number: "150", name: Equipment, type: asset, normal_balance: debit}
  - {number: "201", name: Accounts Payable, type: liability, normal_balance: credit}
  - {number: "140", name: Supplies, type: asset, normal_balance: debit}
problems:
  - ref: P3-01
    date: 2026-10-05
    concept: debit_credit
    stem: >
      On 5 October the business bought equipment for $4,800, paying $1,800 cash and
      agreeing to pay the rest later. Record the entry.
    entry:
      - {account: "150", debit: 480000}
      - {account: "101", credit: 180000}
      - {account: "201", credit: 300000}
    signatures:
      - key: supplies_not_equipment
        label: Something bought to use for years recorded as supplies, which are used up
        detect: {type: entry_line, document: P3-01, account: "140", side: debit}
  - ref: P3-02
    date: 2026-10-08
    concept: debit_credit
    stem: On 8 October the business paid $1,200 of what it owed. Record the entry.
    entry:
      - {account: "201", debit: 120000}
      - {account: "101", credit: 120000}
"""


def _without(text: str, line_fragment: str) -> str:
    """The valid chapter minus the line containing `line_fragment`."""
    kept = [line for line in text.splitlines() if line_fragment not in line]
    assert len(kept) < len(text.splitlines()), f"{line_fragment!r} matched no line"
    return "\n".join(kept)


def _refusal(text: str) -> list[str]:
    with pytest.raises(chapter.ChapterRefused) as refused:
        chapter.parse(text)
    return list(refused.value.problems)


# ── the valid chapter ──────────────────────────────────────────────────────────────────

def test_the_valid_chapter_parses():
    parsed = chapter.parse(VALID)

    assert parsed.textbook == "OpenStax Principles of Financial Accounting"
    assert parsed.chapter == 3
    assert [p.ref for p in parsed.problems] == ["P3-01", "P3-02"]
    assert parsed.problems[0].stem.startswith("On 5 October")
    assert parsed.problems[0].signatures[0].key == "supplies_not_equipment"


def test_the_slug_comes_from_the_textbook_and_the_chapter():
    """Identity, and therefore re-import: the same chapter of the same book is the same pack."""
    parsed = chapter.parse(VALID)

    assert parsed.slug.endswith("-ch3")
    assert len(parsed.slug) <= 80, "content_pack.slug is String(80)"
    assert parsed.slug == chapter.parse(VALID.replace("chapter_label: Analyzing and Recording "
                                                      "Transactions",
                                                      "chapter_label: Something Else")).slug


# ── the figures ────────────────────────────────────────────────────────────────────────

def test_an_unbalanced_entry_is_refused():
    """Debits must equal credits."""
    broken = VALID.replace('{account: "201", credit: 300000}', '{account: "201", credit: 300001}')

    problems = _refusal(broken)

    assert any("P3-01" in p for p in problems)
    assert any("does not balance" in p for p in problems)


def test_an_unbalanced_entry_reports_cents_and_dollars():
    """A YAML author writing dollars where cents are wanted is the likeliest mistake this format
    invites, and `480000 != 4800` reads like nonsense until you know that."""
    broken = VALID.replace('{account: "150", debit: 480000}', '{account: "150", debit: 4800}')

    problems = " ".join(_refusal(broken))

    assert "4800" in problems
    assert "$48.00" in problems, "the figure was not also given in dollars"
    assert "$4,800.00" in problems, "the other side was not also given in dollars"


def test_a_line_with_neither_a_debit_nor_a_credit_is_refused():
    broken = VALID.replace('{account: "101", credit: 180000}', '{account: "101"}')

    assert any("neither a debit nor a credit" in p for p in _refusal(broken))


def test_a_line_with_both_a_debit_and_a_credit_is_refused():
    broken = VALID.replace('{account: "101", credit: 180000}',
                           '{account: "101", debit: 1, credit: 180000}')

    assert any("both" in p for p in _refusal(broken))


def test_an_entry_of_one_line_is_refused():
    broken = VALID.replace("""    entry:
      - {account: "201", debit: 120000}
      - {account: "101", credit: 120000}""", """    entry:
      - {account: "201", debit: 0}""")

    assert any("at least two lines" in p for p in _refusal(broken))


# ── the references ─────────────────────────────────────────────────────────────────────

def test_an_account_the_file_does_not_declare_is_refused():
    broken = VALID.replace('{account: "150", debit: 480000}', '{account: "999", debit: 480000}')

    problems = _refusal(broken)

    assert any("999" in p for p in problems)
    assert any("P3-01" in p for p in problems)


def test_a_duplicate_ref_is_refused():
    """Two problems with one ref would share a document, and the second would overwrite the
    first's entry."""
    broken = VALID.replace("ref: P3-02", "ref: P3-01")

    assert any("P3-01" in p and "more than once" in p for p in _refusal(broken))


def test_a_signature_naming_another_document_is_refused():
    """A detect pointing at a problem that is not in the file never fires, so the misconception it
    describes is one the screen silently cannot name."""
    broken = VALID.replace("document: P3-01, account: \"140\"", "document: P3-99, account: \"140\"")

    assert any("P3-99" in p for p in _refusal(broken))


def test_a_duplicate_account_number_is_refused():
    broken = VALID.replace('{number: "140", name: Supplies, type: asset, normal_balance: debit}',
                           '{number: "101", name: Supplies, type: asset, normal_balance: debit}')

    assert any("101" in p and "more than once" in p for p in _refusal(broken))


# ── the prose and the metadata ─────────────────────────────────────────────────────────

def test_an_empty_stem_is_refused():
    """A problem with no prose is a problem no student can answer."""
    broken = VALID.replace("stem: On 8 October the business paid $1,200 of what it owed. "
                           "Record the entry.", 'stem: "  "')

    assert any("P3-02" in p and "stem" in p for p in _refusal(broken))


def test_a_problem_with_no_concept_is_refused():
    """The concept is what the importer tags the problem's signatures with; without one the
    mistakes block cannot name what a student misunderstood."""
    broken = _without(VALID, "concept: debit_credit")

    assert any("concept" in p for p in _refusal(broken))


def test_a_missing_top_level_field_is_refused():
    assert any("textbook" in p for p in _refusal(_without(VALID, "textbook:")))


def test_an_unknown_top_level_field_is_refused():
    """The same reason the pack schema is extra="forbid": a typo must be an import failure, not a
    line that is silently ignored."""
    broken = VALID.replace("chapter: 3", "chapter: 3\nchaptr_label: typo")

    assert any("chaptr_label" in p for p in _refusal(broken))


def test_an_unknown_field_on_a_problem_is_refused():
    broken = VALID.replace("    concept: debit_credit\n    stem: On 8 October",
                           "    concept: debit_credit\n    points: 5\n    stem: On 8 October")

    assert any("points" in p for p in _refusal(broken))


def test_a_chapter_with_no_problems_is_refused():
    assert any("problems" in p for p in _refusal("""
textbook: A Book
chapter: 1
chapter_label: Nothing
accounts: [{number: "101", name: Cash, type: asset, normal_balance: debit}]
problems: []
"""))


def test_text_that_is_not_yaml_is_refused_without_a_traceback():
    assert any("YAML" in p for p in _refusal("textbook: [unclosed"))


# ── every fault, not just the first ────────────────────────────────────────────────────

def test_every_problem_is_reported_not_just_the_first():
    """A chapter with three bad problems reports three. Fixing them one import at a time is the
    difference between a usable format and an unusable one."""
    broken = (VALID
              .replace('{account: "201", credit: 300000}', '{account: "201", credit: 300001}')
              .replace("stem: On 8 October the business paid $1,200 of what it owed. "
                       "Record the entry.", 'stem: " "')
              .replace('{account: "101", credit: 120000}', '{account: "888", credit: 120000}'))

    problems = _refusal(broken)

    assert any("does not balance" in p for p in problems)
    assert any("stem" in p for p in problems)
    assert any("888" in p for p in problems)


# ── the translation ────────────────────────────────────────────────────────────────────

def test_the_translation_produces_a_pack_the_schema_accepts():
    """The real gate: extra="forbid" rejects a field the schema does not know, and V15 rejects a
    rubric component KNOWN_COMPONENTS does not know."""
    pack_source, key_source = chapter.to_pack_source(chapter.parse(VALID), version=1)

    pack = schema.load_pack(pack_source)
    key = schema.load_answer_key(key_source)

    assert validate.validate_pack(pack, {"A": key}) == []


def test_the_translation_marks_the_pack_as_a_problem_set():
    pack_source, _ = chapter.to_pack_source(chapter.parse(VALID), version=1)

    assert pack_source["company"]["chapter_ordinal"] == 3
    assert pack_source["company"]["textbook"] == "OpenStax Principles of Financial Accounting"
    assert pack_source["company"]["chapter_label"] == "Analyzing and Recording Transactions"


def test_the_translation_gives_every_problem_a_document_with_its_stem():
    pack_source, _ = chapter.to_pack_source(chapter.parse(VALID), version=1)

    documents = {d["ref"]: d for d in pack_source["documents"]}
    assert set(documents) == {"P3-01", "P3-02"}
    assert documents["P3-01"]["stem"].startswith("On 5 October")
    assert [d["received_seq"] for d in pack_source["documents"]] == [1, 2]


def test_the_translation_fills_triage_for_every_problem():
    """V10 wants a triage value for every document; V17 forbids a no-entry reason on one that
    takes an entry. Every problem takes an entry, so every value is True and there are no
    reasons at all."""
    _, key_source = chapter.to_pack_source(chapter.parse(VALID), version=1)

    assert key_source["triage"] == {"P3-01": True, "P3-02": True}
    assert key_source.get("triage_reasons", {}) == {}


def test_the_translation_scores_the_chapter_with_the_new_component_only():
    """A chapter graded by any existing component would be marked out of every problem."""
    pack_source, _ = chapter.to_pack_source(chapter.parse(VALID), version=1)

    assert [c["key"] for c in pack_source["rubric"]["components"]] == ["problems_best_n"]


def test_the_translation_carries_every_signature_into_the_key():
    _, key_source = chapter.to_pack_source(chapter.parse(VALID), version=1)

    assert [s["key"] for s in key_source["error_signatures"]] == ["supplies_not_equipment"]


def test_the_translation_takes_the_period_from_the_problem_dates():
    pack_source, _ = chapter.to_pack_source(chapter.parse(VALID), version=1)

    assert pack_source["period"]["start"] == "2026-10-05"
    assert pack_source["period"]["end"] == "2026-10-08"


def test_the_translation_carries_the_version_it_is_given():
    """import_pack_zip refuses a version that does not advance, so the caller computes this from
    what is already in the catalogue."""
    pack_source, _ = chapter.to_pack_source(chapter.parse(VALID), version=7)

    assert pack_source["version"] == 7


def test_the_translation_adds_the_role_accounts_the_validator_demands():
    """V5 requires exactly one account carrying `retained_earnings` and one `income_summary`. No
    chapter problem touches either, so an author must not have to know they exist."""
    pack_source, _ = chapter.to_pack_source(chapter.parse(VALID), version=1)

    for role in ("retained_earnings", "income_summary"):
        holders = [a["number"] for a in pack_source["accounts"] if role in a.get("roles", [])]
        assert len(holders) == 1, f"{role}: {holders}"


def test_the_translation_does_not_duplicate_a_role_account_the_chapter_declares():
    """An author who does declare one must not end up with two, which V5 refuses."""
    declared = VALID.replace(
        '  - {number: "140", name: Supplies, type: asset, normal_balance: debit}',
        '  - {number: "140", name: Supplies, type: asset, normal_balance: debit}\n'
        '  - {number: "301", name: Owner Capital, type: equity, normal_balance: credit,\n'
        '     roles: [retained_earnings]}')

    pack_source, key_source = chapter.to_pack_source(chapter.parse(declared), version=1)

    holders = [a["number"] for a in pack_source["accounts"]
               if "retained_earnings" in a.get("roles", [])]
    assert holders == ["301"]
    assert validate.validate_pack(schema.load_pack(pack_source),
                                  {"A": schema.load_answer_key(key_source)}) == []


def test_the_zip_has_the_layout_import_pack_zip_reads():
    """pack.json at the root and answer_keys/<code>.json beside it (packs/zip_reader.py)."""
    import zipfile

    pack_source, key_source = chapter.to_pack_source(chapter.parse(VALID), version=1)

    with zipfile.ZipFile(chapter.to_zip(pack_source, {"A": key_source})) as bundle:
        assert set(bundle.namelist()) == {"pack.json", "answer_keys/A.json"}


def test_the_same_chapter_makes_the_same_zip():
    """import_pack_zip refuses a repeat source_sha256, which is only a meaningful check if the
    bytes are a function of the content and not of the dict ordering of the moment."""
    first, first_key = chapter.to_pack_source(chapter.parse(VALID), version=1)
    second, second_key = chapter.to_pack_source(chapter.parse(VALID), version=1)

    assert (chapter.to_zip(first, {"A": first_key}).getvalue()
            == chapter.to_zip(second, {"A": second_key}).getvalue())
