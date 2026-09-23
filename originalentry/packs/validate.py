"""Pack validation (T5.4). Shared by the upload screen, ``flask packs validate`` and
``flask packs import``. Reports **every** problem with its JSON path, not just the first.

Pydantic (``schema.load_pack``) covers V1's parse step. This module adds every cross-field and
cross-file rule, including the V9 replay. Three rules cannot live here because they are not about
the pack's own fields, and they run where their evidence is: **V16** (zip safety) in
``zip_reader``, and **V12** (image bytes) and **V14** (version and checksum against the
catalogue) in ``importing``. Anything still unwritten is listed in :data:`DEFERRED_RULES` rather
than silently skipped.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

from .schema import KNOWN_FORMAT_VERSIONS, AnswerKey, Pack

# Grading component keys the engine knows (T8.2). Used by V15.
KNOWN_COMPONENTS = frozenset(
    {
        "triage",
        "journal_selection",
        "entry_accuracy",
        "posting_completeness",
        "subsidiary_agreement",
        "adjustment_form",
        "adjustment_amounts",
        "statements_structure",
        "statements_figures",
        "closing",
    }
)

# Rules implemented elsewhere as their prerequisites land (documented, never silently skipped).
DEFERRED_RULES: dict[str, str] = {}

# Rules that run outside this module, where their evidence is.
ELSEWHERE = {
    "V12": "importing._v12_images",
    "V14": "importing._v14_catalogue",
    "V16": "zip_reader.read_pack_zip",
}


@dataclass(frozen=True)
class Problem:
    path: str  # JSON path, e.g. "accounts[3].number"
    rule: str  # e.g. "V2"
    message: str


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dups: list[str] = []
    for v in values:
        if v in seen and v not in dups:
            dups.append(v)
        seen.add(v)
    return dups


def validate_pack(pack: Pack, keys: dict[str, AnswerKey] | None = None) -> list[Problem]:
    """Return every problem found. An empty list means the pure rules pass."""
    problems: list[Problem] = []
    account_numbers = {a.number for a in pack.accounts}
    party_codes = {p.code for p in pack.parties}
    variant_codes = {v.code for v in pack.variants}
    statement_sections = set(pack.statement_sections)

    _v1_format(pack, problems)
    _v2_uniqueness(pack, problems)
    _v3_references(pack, account_numbers, party_codes, variant_codes, problems)
    _v4_statements(pack, statement_sections, problems)
    _v6_v7_openings(pack, account_numbers, party_codes, problems)
    _v10_guided(pack, problems)
    _v5_roles(pack, problems)
    _v13_contrast(pack, problems)
    _v15_rubric(pack, problems)

    if keys is not None:
        _keys_references(pack, keys, account_numbers, party_codes, problems)
        _v8_entries_fit_their_journal(pack, keys, problems)
        _v10_coverage(pack, keys, problems)
        _v11_signatures_and_adjustments(pack, keys, problems)
        _v9_replay(pack, keys, problems)

    return problems


REQUIRED_ROLES = ("retained_earnings", "income_summary")


def _v5_roles(pack: Pack, problems: list[Problem]) -> None:
    """The roles the engine finds accounts by, since it never names an account number (A21)."""
    for role in REQUIRED_ROLES:
        holders = [a.number for a in pack.accounts if role in a.roles]
        if len(holders) != 1:
            problems.append(
                Problem(
                    "accounts", "V5",
                    f"Exactly one account must carry the role {role!r}; "
                    f"{len(holders)} do ({', '.join(holders) or 'none'}).",
                )
            )

    for kind in sorted({p.kind for p in pack.parties}):
        controls = [a.number for a in pack.accounts if a.subsidiary_kind == kind]
        if len(controls) != 1:
            problems.append(
                Problem(
                    "accounts", "V5",
                    f"Exactly one account must be the control account for {kind!r}; "
                    f"{len(controls)} are ({', '.join(controls) or 'none'}).",
                )
            )


def _v8_entries_fit_their_journal(
    pack: Pack, keys: dict[str, AnswerKey], problems: list[Problem]
) -> None:
    """Each expected entry balances, and a special journal holds only what it has columns for."""
    journals = {j.key: j for j in pack.journals}

    for variant_code, key in keys.items():
        for index, entry in enumerate(key.expected_entries):
            path = f"answer_keys.{variant_code}.expected_entries[{index}]"
            debits = sum(line.debit or 0 for line in entry.lines)
            credits = sum(line.credit or 0 for line in entry.lines)
            if debits != credits:
                problems.append(
                    Problem(path, "V8",
                            f"The entry does not balance: {debits} debit, {credits} credit.")
                )
            if len(entry.lines) < 2:
                problems.append(Problem(path, "V8", "An entry needs at least two lines."))

            journal = journals.get(entry.journal)
            if journal is None or journal.kind != "special":
                continue
            for line in entry.lines:
                side = "debit" if line.debit else "credit"
                allowed = any(
                    column.side == side
                    and (column.account == line.account or column.account is None)
                    for column in journal.columns
                )
                if not allowed:
                    problems.append(
                        Problem(
                            path, "V8",
                            f"{journal.name} has no {side} column for account {line.account}.",
                        )
                    )


def _v11_signatures_and_adjustments(
    pack: Pack, keys: dict[str, AnswerKey], problems: list[Problem]
) -> None:
    """A signature the key itself triggers would report every student for it (T8.5)."""
    for variant_code, key in keys.items():
        entries_by_document: dict[str, list] = {}
        for entry in key.expected_entries:
            entries_by_document.setdefault(entry.document, []).append(entry)

        for signature in key.error_signatures:
            path = f"answer_keys.{variant_code}.error_signatures.{signature.key}"
            detect = signature.detect or {}
            kind = detect.get("type")
            if kind not in ("entry_line", "entry_amount", "balance_delta"):
                problems.append(Problem(path, "V11", f"Unknown detect type {kind!r}."))
                continue
            if kind == "balance_delta":
                if not detect.get("deltas"):
                    problems.append(Problem(path, "V11", "A balance_delta signature needs deltas."))
                continue

            document = detect.get("document")
            if not key.triage.get(document, False):
                problems.append(
                    Problem(path, "V11",
                            f"{document} is not a document the key records an entry for.")
                )
                continue
            for entry in entries_by_document.get(document, []):
                for line in entry.lines:
                    side = "debit" if line.debit else "credit"
                    if line.account != detect.get("account") or side != detect.get("side"):
                        continue
                    if kind == "entry_line" or (line.debit or line.credit) == detect.get("amount"):
                        problems.append(
                            Problem(path, "V11",
                                    "The key's own entry for this document matches this "
                                    "signature, so every student would be reported for it.")
                        )

        for index, adjustment in enumerate(key.adjustments):
            path = f"answer_keys.{variant_code}.adjustments[{index}]"
            if adjustment.amount_basis == "independent" and adjustment.amount is None:
                problems.append(
                    Problem(path, "V11", "An independent adjustment needs its amount.")
                )
            if adjustment.amount_basis == "dependent" and not adjustment.base_account:
                problems.append(
                    Problem(path, "V11",
                            "A dependent adjustment needs the base_account its figure follows "
                            "from, so the grader sees the student's own balance.")
                )
            if not adjustment.pattern:
                problems.append(Problem(path, "V11", "An adjustment needs its pattern."))


def _v9_replay(pack: Pack, keys: dict[str, AnswerKey], problems: list[Problem]) -> None:
    """A2 at upload: replay each variant's key through the engine and confirm it reproduces
    ``expected_balances`` to the cent. Skipped for a variant whose balances depend on a
    ``dependent`` adjustment (its amount is not in the key)."""
    from ..ledger import engine
    from . import replay  # local import: keeps ledger out of the module's import graph until used

    for variant_code, key in keys.items():
        if any(a.amount_basis == "dependent" for a in key.adjustments):
            continue
        try:
            snapshot = replay.build_replay_snapshot(pack, key)
        except Exception as exc:  # a malformed journal/key surfaces as a V9 problem, not a crash
            problems.append(
                Problem(f"answer_keys.{variant_code}", "V9", f"Replay failed: {exc}")
            )
            continue
        for stage, expected in key.expected_balances.items():
            if stage not in engine.STAGE_KINDS:
                continue
            actual = engine.balances(snapshot, stage)
            for number, want in expected.items():
                got = actual.get(number, 0)
                if got != want:
                    problems.append(
                        Problem(
                            f"answer_keys.{variant_code}.expected_balances.{stage}.{number}",
                            "V9",
                            f"Replay gives {got} cents, key says {want}.",
                        )
                    )


def _v1_format(pack: Pack, problems: list[Problem]) -> None:
    if pack.format_version not in KNOWN_FORMAT_VERSIONS:
        problems.append(
            Problem("format_version", "V1", f"Unknown format_version {pack.format_version}.")
        )


def _v2_uniqueness(pack: Pack, problems: list[Problem]) -> None:
    checks = [
        ("accounts[].number", [a.number for a in pack.accounts]),
        ("parties[].code", [p.code for p in pack.parties]),
        ("documents[].ref", [d.ref for d in pack.documents]),
        ("variants[].code", [v.code for v in pack.variants]),
        ("journals[].key", [j.key for j in pack.journals]),
        ("checkpoints[].key", [c.key for c in pack.checkpoints]),
    ]
    for path, values in checks:
        for dup in _duplicates(values):
            problems.append(Problem(path, "V2", f"Duplicate value {dup!r}."))


def _v3_references(
    pack: Pack,
    account_numbers: set[str],
    party_codes: set[str],
    variant_codes: set[str],
    problems: list[Problem],
) -> None:
    for ji, journal in enumerate(pack.journals):
        for ci, col in enumerate(journal.columns):
            if col.account is not None and col.account not in account_numbers:
                problems.append(
                    Problem(
                        f"journals[{ji}].columns[{ci}].account",
                        "V3",
                        f"Account {col.account!r} does not exist.",
                    )
                )
    for variant, ob in pack.opening_balances.items():
        if variant not in variant_codes:
            problems.append(
                Problem(f"opening_balances.{variant}", "V3", f"Unknown variant {variant!r}.")
            )
        for number in ob.accounts:
            if number not in account_numbers:
                problems.append(
                    Problem(
                        f"opening_balances.{variant}.accounts.{number}",
                        "V3",
                        f"Account {number!r} does not exist.",
                    )
                )
        for code in ob.parties:
            if code not in party_codes:
                problems.append(
                    Problem(
                        f"opening_balances.{variant}.parties.{code}",
                        "V3",
                        f"Party {code!r} does not exist.",
                    )
                )
    for di, doc in enumerate(pack.documents):
        for variant in doc.variants:
            if variant not in variant_codes:
                problems.append(
                    Problem(
                        f"documents[{di}].variants.{variant}",
                        "V3",
                        f"Unknown variant {variant!r}.",
                    )
                )


def _v4_statements(pack: Pack, statement_sections: set[str], problems: list[Problem]) -> None:
    for ai, acct in enumerate(pack.accounts):
        if acct.statement_section is not None and acct.statement_section not in statement_sections:
            problems.append(
                Problem(
                    f"accounts[{ai}].statement_section",
                    "V4",
                    f"Section {acct.statement_section!r} is not in statement_sections.",
                )
            )
    for si, stmt in enumerate(pack.statements):
        subtotal_keys = {st.key for st in stmt.subtotal_types}
        for section in stmt.allowed_sections:
            if section not in statement_sections:
                problems.append(
                    Problem(
                        f"statements[{si}].allowed_sections",
                        "V4",
                        f"Section {section!r} is not in statement_sections.",
                    )
                )
        for required in stmt.required_subtotals:
            if required not in subtotal_keys:
                problems.append(
                    Problem(
                        f"statements[{si}].required_subtotals",
                        "V4",
                        f"required_subtotal {required!r} is not a declared subtotal_type.",
                    )
                )


def _v6_v7_openings(
    pack: Pack, account_numbers: set[str], party_codes: set[str], problems: list[Problem]
) -> None:
    party_kind = {p.code: p.kind for p in pack.parties}
    controls = [a for a in pack.accounts if a.subsidiary_kind]
    for variant in pack.variants:
        ob = pack.opening_balances.get(variant.code)
        if ob is None:
            problems.append(
                Problem(
                    f"opening_balances.{variant.code}",
                    "V6",
                    f"No opening balances for variant {variant.code!r}.",
                )
            )
            continue
        total = sum(ob.accounts.get(n, 0) for n in account_numbers)
        if total != 0:
            problems.append(
                Problem(
                    f"opening_balances.{variant.code}.accounts",
                    "V6",
                    f"Opening balances do not sum to zero (off by {total} cents).",
                )
            )
        # V7: party openings sum to their control account's opening, per kind.
        for control in controls:
            party_sum = sum(
                cents
                for code, cents in ob.parties.items()
                if party_kind.get(code) == control.subsidiary_kind
            )
            control_open = ob.accounts.get(control.number, 0)
            if party_sum != control_open:
                problems.append(
                    Problem(
                        f"opening_balances.{variant.code}.parties",
                        "V7",
                        f"{control.subsidiary_kind} party openings ({party_sum}) do not equal "
                        f"control account {control.number} opening ({control_open}).",
                    )
                )


def _v10_guided(pack: Pack, problems: list[Problem]) -> None:
    guided = [d.ref for d in pack.documents if d.guided]
    if len(guided) > 2:
        problems.append(
            Problem("documents[].guided", "V10", f"At most two documents may be guided ({guided}).")
        )


def _v10_coverage(pack: Pack, keys: dict[str, AnswerKey], problems: list[Problem]) -> None:
    checkpoint_keys = [c.key for c in pack.checkpoints]
    doc_refs = [d.ref for d in pack.documents]
    for variant_code, key in keys.items():
        for ck in checkpoint_keys:
            if ck not in key.checkpoints:
                problems.append(
                    Problem(
                        f"answer_keys.{variant_code}.checkpoints",
                        "V10",
                        f"Checkpoint {ck!r} has no answer.",
                    )
                )
        for ref in doc_refs:
            if ref not in key.triage:
                problems.append(
                    Problem(
                        f"answer_keys.{variant_code}.triage",
                        "V10",
                        f"Document {ref!r} has no triage value.",
                    )
                )


def _v13_contrast(pack: Pack, problems: list[Problem]) -> None:
    ratio = _contrast_against_white(pack.company.accent_hex)
    if ratio < 4.5:
        problems.append(
            Problem(
                "company.accent_hex",
                "V13",
                f"Accent colour contrast against white is {ratio:.2f}:1, below 4.5:1.",
            )
        )


def _v15_rubric(pack: Pack, problems: list[Problem]) -> None:
    for ri, component in enumerate(pack.rubric.components):
        if component.key not in KNOWN_COMPONENTS:
            problems.append(
                Problem(
                    f"rubric.components[{ri}].key",
                    "V15",
                    f"Unknown rubric component {component.key!r}.",
                )
            )


def _keys_references(
    pack: Pack,
    keys: dict[str, AnswerKey],
    account_numbers: set[str],
    party_codes: set[str],
    problems: list[Problem],
) -> None:
    for variant_code, key in keys.items():
        base = f"answer_keys.{variant_code}"
        for ei, entry in enumerate(key.expected_entries):
            for li, line in enumerate(entry.lines):
                if line.account not in account_numbers:
                    problems.append(
                        Problem(
                            f"{base}.expected_entries[{ei}].lines[{li}].account",
                            "V3",
                            f"Account {line.account!r} does not exist.",
                        )
                    )
                if line.party is not None and line.party not in party_codes:
                    problems.append(
                        Problem(
                            f"{base}.expected_entries[{ei}].lines[{li}].party",
                            "V3",
                            f"Party {line.party!r} does not exist.",
                        )
                    )
        for adji, adj in enumerate(key.adjustments):
            for pi, pat in enumerate(adj.pattern):
                if pat.account not in account_numbers:
                    problems.append(
                        Problem(
                            f"{base}.adjustments[{adji}].pattern[{pi}].account",
                            "V3",
                            f"Account {pat.account!r} does not exist.",
                        )
                    )
            if adj.base_account is not None and adj.base_account not in account_numbers:
                problems.append(
                    Problem(
                        f"{base}.adjustments[{adji}].base_account",
                        "V3",
                        f"Account {adj.base_account!r} does not exist.",
                    )
                )


def _srgb_to_linear(channel: int) -> float:
    c = channel / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _contrast_against_white(hex_color: str) -> float:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    luminance = (
        0.2126 * _srgb_to_linear(r)
        + 0.7152 * _srgb_to_linear(g)
        + 0.0722 * _srgb_to_linear(b)
    )
    return (1.0 + 0.05) / (luminance + 0.05)


# ── W1: the four words, in the pack's own text ──────────────────────────────────────────

# The same four words the interface guard keeps out of the templates and the scripts (A7). A
# company's documents are read by students, so they are held to the same rule.
#
# Word boundaries matter: "copyright" is not "right", and "corrected" is not "correct".
BANNED_WORDS = re.compile(r"\b(correct|incorrect|right|wrong)\b", re.IGNORECASE)

# A money figure typed with a single decimal place: 4390.4 where 4,390.40 was meant. Anchored so
# that "2/10" and "6.1" are left alone, and so that a properly written 4,390.40 does not match.
LOOSE_MONEY = re.compile(r"(?<![\d./])\d{3,}\.\d(?![\d.])")

W2_MESSAGE = (
    'This text writes a figure as "{figure}". A student reads the sentence, not the field beside '
    "it, and a money amount with one decimal place is read as the wrong number or copied as one. "
    "Write it the way it should be recorded."
)

W1_MESSAGE = (
    'This text says "{word}". The app never tells a student their work is right or wrong — it '
    "says what it found and what it could not do. Consider rewording."
)


def _strings(node, path: str) -> Iterator[tuple[str, str]]:
    """Every string in the pack, with the JSON path it sits at."""
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, (list, tuple)):
        for i, value in enumerate(node):
            yield from _strings(value, f"{path}[{i}]")


def warn_pack(pack: Pack) -> Iterator[Problem]:
    """W1 and W2 — warn about pack text a student would be misled by.

    W1 — text that tells a student they are right or wrong.

    A **warning**, never a refusal: "a correcting entry" is ordinary accounting prose, and the
    author is the one who can tell an instruction from a term of art. Refusing would put this
    module in the business of judging someone's writing.

    Only the pack is read. Answer keys are staff-only (D6 rule 6) — a signature named "Recorded
    the wrong amount" is diagnosis for an instructor and never reaches a student.
    """
    seen: set[str] = set()
    loose: set[str] = set()
    for path, text in _strings(pack.model_dump(mode="json"), ""):
        found = BANNED_WORDS.search(text)
        if found and path not in seen:
            seen.add(path)
            yield Problem(path=path, rule="W1", message=W1_MESSAGE.format(word=found.group(0)))
        figure = LOOSE_MONEY.search(text)
        if figure and path not in loose:
            loose.add(path)
            yield Problem(path=path, rule="W2",
                          message=W2_MESSAGE.format(figure=figure.group(0)))
