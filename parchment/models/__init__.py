"""ORM models (D2–D4). Importing this package registers every table on ``db.metadata`` so
Flask-Migrate can see them. Grouped Content / People / Work per T2.
"""

from .content import (
    Account,
    AccountOpeningBalance,
    ContentPack,
    PackVersion,
    Party,
    PartyOpeningBalance,
    SourceDocument,
    Variant,
)
from .people import (
    ROLE_GRADER,
    ROLE_INSTRUCTOR,
    ROLE_STUDENT,
    ROLES,
    Enrollment,
    Section,
    User,
)
from .work import (
    KIND_ADJUSTING,
    KIND_CLOSING,
    KIND_REGULAR,
    LATE_ACCEPT,
    LATE_CLOSED,
    TARGET_GENERAL,
    TARGET_SUBSIDIARY,
    ActivityEvent,
    Assignment,
    Disposition,
    EntryLine,
    JournalEntry,
    JournalEntryRevision,
    PostingRun,
    PostingRunEntry,
    Workspace,
)

__all__ = [
    # people
    "User",
    "Section",
    "Enrollment",
    "ROLE_STUDENT",
    "ROLE_GRADER",
    "ROLE_INSTRUCTOR",
    "ROLES",
    # content
    "ContentPack",
    "PackVersion",
    "Variant",
    "Account",
    "Party",
    "SourceDocument",
    "AccountOpeningBalance",
    "PartyOpeningBalance",
    # work
    "Assignment",
    "Workspace",
    "Disposition",
    "JournalEntry",
    "JournalEntryRevision",
    "EntryLine",
    "PostingRun",
    "PostingRunEntry",
    "ActivityEvent",
    "KIND_REGULAR",
    "KIND_ADJUSTING",
    "KIND_CLOSING",
    "TARGET_GENERAL",
    "TARGET_SUBSIDIARY",
    "LATE_CLOSED",
    "LATE_ACCEPT",
]
