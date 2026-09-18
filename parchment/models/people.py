"""People tables (D2). Core chain and the staff audit trail; login_token lands with auth."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db
from ..ids import new_public_id

ROLE_STUDENT = "student"
ROLE_GRADER = "grader"
ROLE_INSTRUCTOR = "instructor"
ROLES = (ROLE_STUDENT, ROLE_GRADER, ROLE_INSTRUCTOR)


class User(db.Model):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(10), unique=True, default=new_public_id)
    email: Mapped[str] = mapped_column(String(320))
    given_name: Mapped[str] = mapped_column(String(120), default="")
    family_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(16), default=ROLE_STUDENT)
    session_epoch: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sign_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # unique(lower(email)) — case-insensitive uniqueness (D2).
        Index("uq_user_lower_email", func.lower(email), unique=True),
    )

    # Flask-Login integration.
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_active(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        # Bind the session to the epoch so `flask auth revoke` invalidates every device.
        return f"{self.public_id}:{self.session_epoch}"


class Section(db.Model):
    __tablename__ = "section"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(10), unique=True, default=new_public_id)
    name: Mapped[str] = mapped_column(String(200))
    term: Mapped[str] = mapped_column(String(60), default="")
    course_tag: Mapped[str] = mapped_column(String(60), default="")
    join_code: Mapped[str] = mapped_column(String(40), unique=True)
    join_code_active: Mapped[bool] = mapped_column(Boolean, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Enrollment(db.Model):
    __tablename__ = "enrollment"

    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    student_number: Mapped[str | None] = mapped_column(String(60))
    source: Mapped[str] = mapped_column(String(20), default="join_code")  # join_code | roster

    section: Mapped[Section] = relationship()
    user: Mapped[User] = relationship()
    # The composite primary key already enforces one enrollment per (section, user).

class StaffAction(db.Model):
    """What staff did, and why (D2).

    Reopening a workspace, overriding a mark, releasing a section: each is recorded with the
    reason given at the time. The detail holds ids and counts, never personal data.
    """

    __tablename__ = "staff_action"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    action: Mapped[str] = mapped_column(String(40))
    target_table: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_staff_action_target", "target_table", "target_id", "created_at"),)



__all__ = [
    "User",
    "Section",
    "Enrollment",
    "ROLE_STUDENT",
    "ROLE_GRADER",
    "ROLE_INSTRUCTOR",
    "ROLES",
    "StaffAction",
]
