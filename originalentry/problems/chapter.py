"""The chapter file: parse it, refuse it loudly, translate it to a pack source.

An instructor writes one file per chapter and imports it with one command. The pack source that
comes out the other end has to satisfy every validator in ``packs.validate``, including several an
author has no reason to know about -- V5 wants exactly one account carrying ``retained_earnings``
and one carrying ``income_summary``, V10 wants a triage value for every document, V13 wants an
accent colour that passes contrast. Everything of that kind is synthesised here, so the file holds
only what the problems are.

Pure: no session, no app context. The one check that needs the database -- that a ``concept`` names
a live ``Concept`` -- lives in ``importing``, which is what lets every test of this module run in
a tenth of a second.

**Every fault is reported, not just the first.** An author fixing ten problems one import at a
time is an author who stops using the format.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date

#: The pack format this translates to.
FORMAT_VERSION = 1

#: A problem set is graded entirely by one component, so its points are the whole mark. 100 makes
#: a chapter's marks read as percentages wherever they are shown.
RUBRIC_POINTS = 100

#: One variant. The PRD's generated figure variants are a non-goal for this project, and a second
#: variant would need the generator a chapter file deliberately does not have.
VARIANT = "A"

#: Dark slate: 10.35:1 against white, well clear of V13's 4.5:1 floor. A problem set's company is
#: a stub that appears nowhere a student looks, so the colour is ours to fix.
ACCENT_HEX = "#334155"

JOURNAL = {"key": "general", "name": "General Journal", "ref_prefix": "J", "kind": "general"}

TOP_LEVEL_REQUIRED = ("textbook", "chapter", "chapter_label", "accounts", "problems")
TOP_LEVEL_OPTIONAL = ("slug",)
PROBLEM_REQUIRED = ("ref", "date", "concept", "stem", "entry")
PROBLEM_OPTIONAL = ("signatures",)
ACCOUNT_REQUIRED = ("number", "name", "type", "normal_balance")
ACCOUNT_OPTIONAL = ("roles", "statement_section", "subsidiary_kind", "sort_order")
SIGNATURE_REQUIRED = ("key", "label", "detect")
SIGNATURE_OPTIONAL = ()

#: The roles ``validate._v5_roles`` demands, and the accounts synthesised to carry them when the
#: chapter declares none. No chapter problem touches either, so an author must not have to know.
SYNTHETIC_ROLES = (
    ("retained_earnings", "9900", "Retained Earnings", "equity", "credit"),
    ("income_summary", "9910", "Income Summary", "equity", "credit"),
)


class ChapterRefused(Exception):
    """Every fault found in one chapter file, so they can be fixed in one pass."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = tuple(problems)
        super().__init__(f"{len(self.problems)} problem(s): " + "; ".join(self.problems))


@dataclass(frozen=True)
class Line:
    account: str
    debit: int | None = None
    credit: int | None = None


@dataclass(frozen=True)
class Signature:
    key: str
    label: str
    detect: dict


@dataclass(frozen=True)
class ChapterProblem:
    ref: str
    date: date
    concept: str
    stem: str
    entry: tuple[Line, ...]
    signatures: tuple[Signature, ...] = ()


@dataclass(frozen=True)
class Chapter:
    textbook: str
    chapter: int
    chapter_label: str
    accounts: tuple[dict, ...]
    problems: tuple[ChapterProblem, ...]
    slug: str

    @property
    def concepts(self) -> frozenset[str]:
        return frozenset(problem.concept for problem in self.problems)


def money(cents: int) -> str:
    """Cents as dollars, for an error message. The format invites writing 4800 for $4,800."""
    return f"${cents / 100:,.2f}"


def slugify(textbook: str, chapter_number: int) -> str:
    """Identity: the same chapter of the same book is the same pack, whatever its label says.

    Truncated to fit ``content_pack.slug``, which is String(80).
    """
    stem = re.sub(r"[^a-z0-9]+", "-", textbook.lower()).strip("-")
    suffix = f"-ch{chapter_number}"
    return stem[: 80 - len(suffix)].rstrip("-") + suffix


# ── parsing ────────────────────────────────────────────────────────────────────────────

def parse(text: str) -> Chapter:
    """Read a chapter file, or raise :class:`ChapterRefused` with every fault in it."""
    import yaml  # local: keeps PyYAML out of the app's boot path, which only the CLI needs

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as invalid:
        raise ChapterRefused([f"The file is not valid YAML: {invalid}"]) from invalid

    if not isinstance(raw, dict):
        raise ChapterRefused(["The file must be a mapping with textbook, chapter and problems."])

    faults: list[str] = []
    _check_keys(raw, TOP_LEVEL_REQUIRED, TOP_LEVEL_OPTIONAL, "the file", faults)

    accounts = _accounts(raw.get("accounts"), faults)
    declared = {account["number"] for account in accounts}
    problems = _problems(raw.get("problems"), declared, faults)

    chapter_number = raw.get("chapter")
    if not isinstance(chapter_number, int):
        faults.append(f"chapter must be a whole number, not {chapter_number!r}.")

    if faults:
        raise ChapterRefused(faults)

    textbook = str(raw["textbook"])
    return Chapter(
        textbook=textbook,
        chapter=chapter_number,
        chapter_label=str(raw["chapter_label"]),
        accounts=tuple(accounts),
        problems=tuple(problems),
        slug=str(raw.get("slug") or slugify(textbook, chapter_number)),
    )


def _check_keys(node: dict, required, optional, where: str, faults: list[str]) -> None:
    """Both directions: a missing field and a misspelt one are the same mistake to an author."""
    for field in required:
        if field not in node:
            faults.append(f"{where}: {field} is required.")
    unknown = sorted(set(node) - set(required) - set(optional))
    for field in unknown:
        faults.append(f"{where}: {field!r} is not a field this format has.")


def _accounts(raw, faults: list[str]) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        faults.append("accounts: the chapter must declare the accounts its problems touch.")
        return []

    accounts: list[dict] = []
    seen: set[str] = set()
    for index, node in enumerate(raw):
        where = f"accounts[{index}]"
        if not isinstance(node, dict):
            faults.append(f"{where}: must be a mapping.")
            continue
        _check_keys(node, ACCOUNT_REQUIRED, ACCOUNT_OPTIONAL, where, faults)
        number = str(node.get("number", "")).strip()
        if not number:
            continue
        if number in seen:
            faults.append(f"accounts: account {number} is declared more than once.")
            continue
        seen.add(number)
        accounts.append({**node, "number": number})
    return accounts


def _problems(raw, declared: set[str], faults: list[str]) -> list[ChapterProblem]:
    if not isinstance(raw, list) or not raw:
        faults.append("problems: the chapter must hold at least one problem.")
        return []

    problems: list[ChapterProblem] = []
    seen: set[str] = set()
    for index, node in enumerate(raw):
        if not isinstance(node, dict):
            faults.append(f"problems[{index}]: must be a mapping.")
            continue
        ref = str(node.get("ref", "")).strip()
        where = ref or f"problems[{index}]"
        _check_keys(node, PROBLEM_REQUIRED, PROBLEM_OPTIONAL, where, faults)
        if not ref:
            continue
        if ref in seen:
            faults.append(f"{ref}: this ref appears more than once.")
            continue
        seen.add(ref)
        problems.append(_problem(node, ref, declared, faults))

    # Checked after every ref is known, so a signature may point at a later problem.
    refs = {problem.ref for problem in problems}
    for problem in problems:
        for signature in problem.signatures:
            named = signature.detect.get("document")
            if named and named not in refs:
                faults.append(
                    f"{problem.ref}: signature {signature.key!r} detects on {named}, which is "
                    f"not a problem in this file, so it can never fire."
                )
    return problems


def _problem(node: dict, ref: str, declared: set[str], faults: list[str]) -> ChapterProblem:
    stem = str(node.get("stem") or "")
    if not stem.strip():
        faults.append(f"{ref}: stem is empty; a problem with no prose cannot be answered.")

    concept = str(node.get("concept") or "").strip()
    if not concept:
        faults.append(f"{ref}: concept is required; it is what tags the problem's signatures.")

    when = node.get("date")
    if not isinstance(when, date):
        faults.append(f"{ref}: date must be a date, like 2026-10-05, not {when!r}.")
        when = date(1970, 1, 1)

    return ChapterProblem(
        ref=ref,
        date=when,
        concept=concept,
        stem=" ".join(stem.split()),
        entry=tuple(_entry(node.get("entry"), ref, declared, faults)),
        signatures=tuple(_signatures(node.get("signatures"), ref, faults)),
    )


def _entry(raw, ref: str, declared: set[str], faults: list[str]) -> list[Line]:
    if not isinstance(raw, list):
        faults.append(f"{ref}: entry must be a list of lines.")
        return []
    if len(raw) < 2:
        faults.append(f"{ref}: an entry needs at least two lines.")

    lines: list[Line] = []
    debits = credits = 0
    for index, node in enumerate(raw):
        if not isinstance(node, dict):
            faults.append(f"{ref}: entry line {index + 1} must be a mapping.")
            continue
        unknown = sorted(set(node) - {"account", "debit", "credit"})
        for field in unknown:
            faults.append(f"{ref}: entry line {index + 1} has no field {field!r}.")

        account = str(node.get("account", "")).strip()
        if account and account not in declared:
            faults.append(
                f"{ref}: entry line {index + 1} uses account {account}, which the chapter's "
                f"accounts do not declare."
            )
        debit, credit = node.get("debit"), node.get("credit")
        if debit and credit:
            faults.append(f"{ref}: entry line {index + 1} has both a debit and a credit.")
        elif not debit and not credit:
            faults.append(f"{ref}: entry line {index + 1} has neither a debit nor a credit.")
        debits += debit or 0
        credits += credit or 0
        lines.append(Line(account=account, debit=debit, credit=credit))

    if debits != credits:
        faults.append(
            f"{ref}: the entry does not balance: {debits} cents ({money(debits)}) debit against "
            f"{credits} cents ({money(credits)}) credit. Amounts are in cents."
        )
    return lines


def _signatures(raw, ref: str, faults: list[str]) -> list[Signature]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        faults.append(f"{ref}: signatures must be a list.")
        return []

    signatures: list[Signature] = []
    for index, node in enumerate(raw):
        where = f"{ref}: signature {index + 1}"
        if not isinstance(node, dict):
            faults.append(f"{where} must be a mapping.")
            continue
        _check_keys(node, SIGNATURE_REQUIRED, SIGNATURE_OPTIONAL, where, faults)
        detect = node.get("detect")
        if not isinstance(detect, dict):
            faults.append(f"{where}: detect must be a mapping.")
            detect = {}
        signatures.append(Signature(
            key=str(node.get("key") or ""),
            label=" ".join(str(node.get("label") or "").split()),
            detect=detect,
        ))
    return signatures


# ── translation ────────────────────────────────────────────────────────────────────────

def to_pack_source(ch: Chapter, *, version: int) -> tuple[dict, dict]:
    """The chapter as ``(pack.json, answer_keys/A.json)``.

    ``version`` is a parameter rather than something computed here: ``_v14_catalogue`` refuses a
    version that does not advance, and the highest existing one is a database fact. Keeping it out
    means this function stays pure.
    """
    dates = sorted(problem.date for problem in ch.problems)

    pack = {
        "format_version": FORMAT_VERSION,
        "company": {
            "slug": ch.slug,
            "name": f"{ch.chapter_label} (chapter {ch.chapter})",
            "accent_hex": ACCENT_HEX,
            "monogram": f"C{ch.chapter}"[:3],
            "course_tags": [],
            "scope_tags": [],
            "textbook": ch.textbook,
            "chapter_label": ch.chapter_label,
            "chapter_ordinal": ch.chapter,
        },
        "version": version,
        "period": {
            "start": dates[0].isoformat(),
            "end": dates[-1].isoformat(),
            "fiscal_year_end": dates[-1].isoformat(),
        },
        "statement_sections": [],
        "accounts": _pack_accounts(ch),
        "parties": [],
        "variants": [{"code": VARIANT, "label": "Problems", "drivers": {}}],
        "opening_balances": {VARIANT: {"accounts": {}, "parties": {}}},
        "journals": [dict(JOURNAL)],
        "documents": [
            {
                "ref": problem.ref,
                "display_ref": problem.ref,
                "type": "problem",
                "date": problem.date.isoformat(),
                "received_seq": index,
                "stem": problem.stem,
            }
            for index, problem in enumerate(ch.problems, start=1)
        ],
        "checkpoints": [],
        "statements": [],
        "reference": [],
        "rubric": {"components": [{"key": "problems_best_n", "points": RUBRIC_POINTS}]},
    }

    key = {
        "variant": VARIANT,
        # Every problem takes an entry, so every triage value is True -- and V17 forbids a
        # no-entry reason on a document that takes one, so there are no reasons at all.
        "triage": {problem.ref: True for problem in ch.problems},
        "designated_journal_documents": {problem.ref: JOURNAL["key"] for problem in ch.problems},
        "expected_entries": [
            {
                "document": problem.ref,
                "journal": JOURNAL["key"],
                "kind": "regular",
                "lines": [_key_line(line) for line in problem.entry],
            }
            for problem in ch.problems
        ],
        "adjustments": [],
        "expected_balances": {},
        "checkpoints": {},
        "error_signatures": [
            {"key": signature.key, "label": signature.label, "detect": signature.detect}
            for problem in ch.problems
            for signature in problem.signatures
        ],
    }
    return pack, key


def _key_line(line: Line) -> dict:
    out: dict = {"account": line.account}
    if line.debit:
        out["debit"] = line.debit
    if line.credit:
        out["credit"] = line.credit
    return out


def _pack_accounts(ch: Chapter) -> list[dict]:
    """The chapter's accounts, plus whichever role accounts V5 is still missing.

    ``statement_section`` is dropped: V4 requires any section named to be in
    ``statement_sections``, and a problem set has no statements to put one in.
    """
    accounts = [
        {
            "number": account["number"],
            "name": account["name"],
            "type": account["type"],
            "normal_balance": account["normal_balance"],
            "roles": list(account.get("roles", [])),
            "sort_order": account.get("sort_order", index),
        }
        for index, account in enumerate(ch.accounts, start=1)
    ]
    taken = {account["number"] for account in accounts}
    held = {role for account in accounts for role in account["roles"]}

    for role, number, name, type_, normal_balance in SYNTHETIC_ROLES:
        if role in held:
            continue
        while number in taken:
            number = str(int(number) + 1)
        taken.add(number)
        accounts.append({
            "number": number, "name": name, "type": type_,
            "normal_balance": normal_balance, "roles": [role],
            "sort_order": 9000 + len(accounts),
        })
    return accounts


def to_zip(pack: dict, keys: dict[str, dict]) -> io.BytesIO:
    """The layout ``packs.zip_reader`` reads: ``pack.json`` and ``answer_keys/<code>.json``.

    Deterministic -- sorted keys, fixed timestamps, no compression metadata that varies -- because
    ``import_pack_zip`` refuses a repeat ``source_sha256``, and that check only means anything if
    the bytes are a function of the content.
    """
    buffer = io.BytesIO()
    members = [("pack.json", pack)] + [
        (f"answer_keys/{code}.json", keys[code]) for code in sorted(keys)
    ]
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, json.dumps(payload, indent=2, sort_keys=True))
    buffer.seek(0)
    return buffer
