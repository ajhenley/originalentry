"""Pack import: turn a validated pack into content rows (T5.5).

``import_content`` is the shared core used by the upload screen and ``flask packs import``. It
seeds the normalised content tables (account, party, document, variant, opening balances) and
stores the rest of ``pack.json`` — journals, statements, checkpoints, reference, rubric — in
``pack_version.manifest`` (jsonb). Answer keys are imported alongside once the grading phase adds
the ``answer_key`` table; this function handles content only.

Pack versions are immutable once used; callers enforce V14 (new version, new checksum) before
importing. This function assumes a validated pack (call ``validate.validate_pack`` first).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Account,
    AccountOpeningBalance,
    ContentPack,
    PackVersion,
    Party,
    PartyOpeningBalance,
    SourceDocument,
    Variant,
)
from . import schema


def import_content(session: Session, pack: schema.Pack, source_sha256: str) -> PackVersion:
    content_pack = session.scalars(
        select(ContentPack).where(ContentPack.slug == pack.company.slug)
    ).one_or_none()
    if content_pack is None:
        content_pack = ContentPack(
            slug=pack.company.slug,
            company_name=pack.company.name,
            course_tags=list(pack.company.course_tags),
        )
        session.add(content_pack)
        session.flush()

    pv = PackVersion(
        content_pack_id=content_pack.id,
        version=pack.version,
        status="ready",
        period_start=pack.period.start,
        period_end=pack.period.end,
        fiscal_year_end=pack.period.fiscal_year_end,
        accent_hex=pack.company.accent_hex,
        monogram=pack.company.monogram,
        scope_tags=list(pack.company.scope_tags),
        has_images=any(
            any(v.image for v in d.variants.values()) for d in pack.documents
        ),
        # The whole pack (as JSON) is the manifest; the engine reads journals from it.
        manifest=pack.model_dump(mode="json"),
        source_sha256=source_sha256,
    )
    session.add(pv)
    session.flush()

    variant_id: dict[str, int] = {}
    for v in pack.variants:
        row = Variant(
            pack_version_id=pv.id, code=v.code, label=v.label, driver_values=dict(v.drivers)
        )
        session.add(row)
        session.flush()
        variant_id[v.code] = row.id

    account_id: dict[str, int] = {}
    for a in pack.accounts:
        row = Account(
            pack_version_id=pv.id,
            number=a.number,
            name=a.name,
            account_type=a.type,
            normal_balance=a.normal_balance,
            statement_section=a.statement_section,
            roles=list(a.roles),
            subsidiary_kind=a.subsidiary_kind,
            sort_order=a.sort_order,
        )
        session.add(row)
        session.flush()
        account_id[a.number] = row.id

    party_id: dict[str, int] = {}
    for p in pack.parties:
        row = Party(
            pack_version_id=pv.id, code=p.code, kind=p.kind, name=p.name, address=p.address
        )
        session.add(row)
        session.flush()
        party_id[p.code] = row.id

    for d in pack.documents:
        session.add(
            SourceDocument(
                pack_version_id=pv.id,
                ref=d.ref,
                display_ref=d.display_ref,
                doc_type=d.type,
                doc_date=d.date,
                received_seq=d.received_seq,
                guided=d.guided,
                guidance=d.guidance,
            )
        )

    for variant_code, ob in pack.opening_balances.items():
        vid = variant_id.get(variant_code)
        if vid is None:
            continue
        for number, cents in ob.accounts.items():
            if number in account_id:
                session.add(
                    AccountOpeningBalance(
                        account_id=account_id[number], variant_id=vid, balance_cents=cents
                    )
                )
        for code, cents in ob.parties.items():
            if code in party_id:
                session.add(
                    PartyOpeningBalance(
                        party_id=party_id[code], variant_id=vid, balance_cents=cents
                    )
                )

    session.flush()
    return pv
