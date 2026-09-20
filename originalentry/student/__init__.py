"""The student blueprint. May import services, ledger, forms, messages, and only
``grading.checkpoints.evaluate`` (T3.1)."""

from .views import bp

__all__ = ["bp"]
