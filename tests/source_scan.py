"""Ask the syntax tree what a function calls, instead of asking its text.

Shared because the lesson was learned twice. ``tests/guards/test_practice_chokepoint.py`` spent
four rounds discovering that a text-matching guard does not converge -- each round closed the
spelling it was shown while a new one was already open -- and
``tests/integration/test_practice_screens.py`` then found the same thing from the other side: a
substring check reported ``staff.practice_grade`` as reaching a workspace through
``_workspace_or_404`` because that function's docstring *explains at length* that it does not.
A guard whose whole value is being auditable had printed a loud, confident, false diagnosis.

The third instance is why this file exists rather than a third copy of the helper:
``test_practice_write_gates.test_neither_gate_decides_it_alone`` asserted
``"is_own_practice" in inspect.getsource(gate)`` over the two write gates. ``_check_gates``
mentions ``is_own_practice`` in prose two comments below the call, so deleting the call and
keeping the comment left the guard green -- the one gate-agreement guard on the branch, defeated
by the code it inspects. "A second definition is how they drift" is the thesis of the test it
was guarding; it applied to the guard too.

So: one definition, asked of the tree, where prose cannot be mistaken for code.
"""

from __future__ import annotations

import ast
import inspect
import textwrap


def called_name(func: ast.AST) -> str | None:
    """The bare name a call is written with: ``f(...)`` and ``mod.f(...)`` both answer ``f``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def calls(source, name: str) -> bool:
    """Whether ``source`` really **calls** ``name``. Takes a function or its text.

    A mention in a docstring, a comment or a string literal is not a call and answers False.
    """
    text = source if isinstance(source, str) else inspect.getsource(source)
    return any(isinstance(node, ast.Call) and called_name(node.func) == name
               for node in ast.walk(ast.parse(textwrap.dedent(text))))
