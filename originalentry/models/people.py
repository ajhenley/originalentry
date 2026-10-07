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
ROLE_ADMIN = "admin"
# The one list of roles; the CLI's --role choices derive from it.
ROLES = (ROLE_STUDENT, ROLE_GRADER, ROLE_INSTRUCTOR, ROLE_ADMIN)


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


class SectionStaff(db.Model):
    """Who teaches a section.

    A join table rather than an owner column on Section, because a course is commonly co-taught
    and because a teaching assistant has to be attachable to one section rather than to all of
    them. One teacher is one row.

    ``added_by_id`` is here so the audit can answer who granted access, which a role column on
    the user cannot.
    """

    __tablename__ = "section_staff"

    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))

    section: Mapped[Section] = relationship()


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


# Token purposes (E2).
PURPOSE_SIGN_IN = "sign_in"
PURPOSE_JOIN = "join"
PURPOSE_STAFF_CODE = "staff_code"


class LoginToken(db.Model):
    """A pending sign-in (E2). Stores only hashes — never a token, a code, an email in clear, or a
    raw IP. A row proves someone asked to sign in as ``email``; consuming it starts the session.

    ``ip_hash`` is an HMAC of the client IP, used only to rate-limit and never displayed. For a
    join (E4) the row also carries the section and the name the person gave, so verifying the link
    is what creates the account — nobody is enrolled at an address they cannot receive mail at.
    Rows are purged 30 days after creation (OPS-7)."""

    __tablename__ = "login_token"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    purpose: Mapped[str] = mapped_column(String(20), default=PURPOSE_SIGN_IN)
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)  # sha256 of the link
    code_hash: Mapped[str] = mapped_column(String(64))  # HMAC of the six-digit code
    code_attempts: Mapped[int] = mapped_column(BigInteger, default=0)
    ip_hash: Mapped[str | None] = mapped_column(String(64))  # HMAC of the client IP
    join_section_id: Mapped[int | None] = mapped_column(ForeignKey("section.id"))
    join_given_name: Mapped[str | None] = mapped_column(String(120))
    join_family_name: Mapped[str | None] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_login_token_email", func.lower(email), "created_at"),
        Index("ix_login_token_ip", "ip_hash", "created_at"),
    )


__all__ = [
    "User",
    "Section",
    "Enrollment",
    "SectionStaff",
    "ROLE_STUDENT",
    "ROLE_GRADER",
    "ROLE_INSTRUCTOR",
    "ROLE_ADMIN",
    "ROLES",
    "StaffAction",
    "LoginToken",
    "PURPOSE_SIGN_IN",
    "PURPOSE_JOIN",
    "PURPOSE_STAFF_CODE",
]
