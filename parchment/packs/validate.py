"""Pack validation (T5.4). Shared by the upload screen, ``flask packs validate`` and
``flask packs import``. Reports **every** problem with its JSON path, not just the first.

Pydantic (``schema.load_pack``) covers V1's parse step. This module adds the cross-field and
cross-file rules. The rules that need the ledger engine or the database (V9 replay, V12 image
bytes, V14 version/checksum, V16 zip safety) are listed in :data:`DEFERRED_RULES` and wired in
as their prerequisites land; they are intentionally not silently skipped.
"""

from __future__ import annotations

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
DEFERRED_RULES = {
    "V5": "Required roles exist once; control roles where parties of that kind exist",
    "V8": "Each expected entry balances and uses only accounts its journal's columns allow",
    "V11": "Key entries trigger no signature; signature/adjustment shape rules",
    "V12": "Screen packs: a real PNG ≤2MB per document per variant, alt text, text alternative",
    "V14": "Version higher than any existing; zip checksum new",
    "V16": "Zip safety: no absolute/.. paths, ≤200MB uncompressed, ≤2000 entries",
    "W1": "Warn on pack text containing correct/incorrect/right/wrong",
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
    _v13_contrast(pack, problems)
    _v15_rubric(pack, problems)

    if keys is not None:
        _keys_references(pack, keys, account_numbers, party_codes, problems)
        _v10_coverage(pack, keys, problems)
        _v9_replay(pack, keys, problems)

    return problems


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
