"""Public IDs: random 10-character base32 strings, never sequential integers (T3.2).

A public ID appears in URLs; a sequential integer would leak counts and let a probe walk the
space. base32 (Crockford-ish, no padding) is URL-safe and case-insensitive to type.
"""

from __future__ import annotations

import secrets

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # 32 chars, no i/l/o/u to avoid confusion
_LENGTH = 10


def new_public_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
