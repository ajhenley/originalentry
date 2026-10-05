"""Turning a pack version into the company chrome the workspace layout needs (T3.3, T10.1).

Kept tiny and pure so templates and the decorator share one source of the accent, monogram,
period label and subsidiary kinds.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ContentPack, PackVersion

# "job" would otherwise fall to the generic "Jobs"; a cabinet shop's third ledger is its job cost
# sheets, which is what the paper set and the booklet call them.
_KIND_LABELS = {"customer": "Customers", "supplier": "Suppliers", "job": "Job cost sheets"}


@dataclass(frozen=True)
class Company:
    slug: str
    name: str
    accent_hex: str
    monogram: str
    period_label: str
    subsidiary_kinds: tuple[str, ...]


def kind_label(kind: str) -> str:
    return _KIND_LABELS.get(kind, kind.replace("_", " ").title() + "s")


def build_company(pack_version: PackVersion, content_pack: ContentPack) -> Company:
    manifest = pack_version.manifest or {}
    kinds: list[str] = []
    for account in manifest.get("accounts", []):
        sk = account.get("subsidiary_kind")
        if sk and sk not in kinds:
            kinds.append(sk)
    return Company(
        slug=content_pack.slug,
        name=content_pack.company_name,
        accent_hex=pack_version.accent_hex,
        monogram=pack_version.monogram,
        period_label=pack_version.period_start.strftime("%B %Y"),
        subsidiary_kinds=tuple(kinds),
    )
