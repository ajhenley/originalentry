"""Handing out a variant by hand (I1.3).

An assignment gives out its variants in turn, at random, or by hand. "By hand" is for the
instructor who wants to know exactly who has which figures — a resit, or two students sitting
next to each other.

Until they say, the student has no figures and the write path refuses with
:data:`~originalentry.messages.WAITING_FOR_VARIANT`, which says that and nothing else.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Variant, Workspace
from . import staff_actions

ASSIGN_VARIANT = "assign_variant"

NO_SUCH_VARIANT = "That is not one of this company's variants."
ALREADY_STARTED = (
    "This student has already recorded work, so their figures cannot be changed underneath them. "
    "Archive the workspace and start a fresh one instead."
)


class VariantRefused(Exception):
    """A variant that cannot be handed out. Mechanical, like every refusal in this app."""


def assign_variant(
    session: Session, workspace: Workspace, variant_code: str, *, actor=None
) -> Workspace:
    """Give this student the named variant of their own company.

    Refused once they have recorded anything: their figures would change under them and everything
    already recorded would have been against the old ones. The remedy then is a fresh set of books
    (I1.12), which is deliberate rather than silent.
    """
    variant_id = session.scalars(
        select(Variant.id).where(
            # Scoped to this workspace's own pack version, so figures from another company can
            # never be handed out (D6 rule 4).
            Variant.pack_version_id == workspace.pack_version_id,
            Variant.code == variant_code,
        )
    ).one_or_none()
    if variant_id is None:
        raise VariantRefused(NO_SUCH_VARIANT)
    if variant_id == workspace.variant_id:
        return workspace  # the same one again changes nothing

    from .multicompany import has_started

    if has_started(session, workspace):
        raise VariantRefused(ALREADY_STARTED)

    workspace.variant_id = variant_id
    session.flush()
    staff_actions.record(
        session, actor, ASSIGN_VARIANT, "workspace", workspace.id,
        detail={"variant": variant_code},
    )
    return workspace


def variants_for(session: Session, pack_version_id: int) -> list[str]:
    return list(
        session.scalars(
            select(Variant.code)
            .where(Variant.pack_version_id == pack_version_id)
            .order_by(Variant.code)
        )
    )
