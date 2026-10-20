"""The accounting-concept vocabulary, and what it is attached to.

The app can say how a student did; without this it cannot say what the class does not understand,
because nothing knows that "allowed a discount on an invoice already past its discount period" and
"treated an unearned 2% deduction as a sales discount" are both about cash discounts.

Two tables rather than a field in each pack source. Tagging is metadata about pedagogy, not
content, and it is revised as an instructor learns what the dashboard tells them: a pack field
would make every revision a ``flask packs import`` against the database that holds real student
work, to change a label. It would also mean authoring each signature's concept once per variant,
since error signatures live on ``AnswerKey``.

Nothing under ``grading/`` may import this module -- a concept tag must never become an input to a
grade. ``tests/guards/test_import_boundaries.py`` enforces it.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db

#: The two axes the vocabulary runs on, and they are measured differently. A process concept is
#: scored, so its mastery is a share of marks. A topic concept is recognised from an error
#: signature, which carries no marks -- and absence of a signature is not evidence of
#: understanding, because detection bails on empty books -- so topic concepts are counted in
#: students, never expressed as a percentage.
GROUP_PROCESS = "process"
GROUP_TOPIC = "topic"
GROUPS = (GROUP_PROCESS, GROUP_TOPIC)

#: What a tag can point at. Checkpoints are deliberately absent: they are pass/fail rather than
#: scored, and their keys are pack-local, so no seed could name one.
KIND_COMPONENT = "component"
KIND_SIGNATURE = "signature"
KINDS = (KIND_COMPONENT, KIND_SIGNATURE)


class Concept(db.Model):
    """One accounting idea an instructor would name out loud.

    One app-wide list, so Riverbend and Ashgrove are comparable and so are two instructors'
    sections -- the comparison is the whole reason the vocabulary is central rather than
    per-pack, and it cannot be recovered later if packs are allowed to drift apart on naming.

    ``retired_at`` rather than a delete: a concept can stop being offered without orphaning the
    tags that already point at it or the history that was measured against it.
    """

    __tablename__ = "concept"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), unique=True)
    label: Mapped[str] = mapped_column(String(120))
    group: Mapped[str] = mapped_column(String(10))  # process | topic
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConceptTag(db.Model):
    """One artifact, one concept.

    ``artifact_key`` is a rubric component key or an error-signature key, and both are a *global*
    vocabulary: ``earlydisc`` appears in both Riverbend and Alder & Finch and means the same thing
    in each. So one row tags it everywhere it occurs, which is what makes cross-pack comparison
    come for free rather than needing a join through pack versions.
    """

    __tablename__ = "concept_tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    concept_id: Mapped[int] = mapped_column(ForeignKey("concept.id"))
    artifact_kind: Mapped[str] = mapped_column(String(10))  # component | signature
    artifact_key: Mapped[str] = mapped_column(String(60))

    __table_args__ = (
        # One artifact has at most one concept; a second tag would make mastery depend on which
        # row a query happened to read first.
        UniqueConstraint("artifact_kind", "artifact_key", name="uq_concept_tag_artifact"),
        # Every report resolves tags by kind and key, so this is the index it reads.
        Index("ix_concept_tag_kind_key", "artifact_kind", "artifact_key"),
    )
