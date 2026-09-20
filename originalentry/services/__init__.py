"""Services: the only code that writes work tables (T3.1). Blueprints call these with typed
commands; services never touch Flask request objects.
"""

from . import staff_actions
from .errors import WriteRefused
from .write import workspace_write

__all__ = ["workspace_write", "WriteRefused", "staff_actions"]
