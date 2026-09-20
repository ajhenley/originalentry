"""Service-layer refusals. A ``WriteRefused`` carries a student-facing message (from
``messages``) and is shown as-is; it never leaks internals.
"""

from __future__ import annotations


class WriteRefused(Exception):
    """A mechanical refusal (out of balance, already posted, read-only, …). ``message`` is a
    finished student-facing string."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)
