"""Grading: the pure ``grade(work, pack, key)`` engine and its components (T8).

Answer keys never leave ``grading/`` and ``staff/`` (D6 rule 6). ``grading.checkpoints.evaluate``
is the one name the student blueprint may import (T3.1); it returns a boolean and never lets an
answer value reach a template or response (T8.3).
"""

from .engine import ENGINE_VERSION, grade

__all__ = ["grade", "ENGINE_VERSION"]
