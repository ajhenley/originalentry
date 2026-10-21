"""Who may write to a workspace. One definition, consulted by both write gates.

This application has **two** independent write gates, and they must never disagree:

* ``decorators.workspace_view`` sets ``g.read_only``, which the chapter-problem routes and the
  journal screens consult through ``student.views._guard_writable``;
* ``services.write._check_gates`` refuses, inside the single write entry point, any actor who is
  not the owning student -- and every practice-set write (entries, dispositions, posting,
  statements, submit) goes through it.

Relax one and not the other and the feature is half working: chapter problems become writable
while every practice-set write is still refused, with nothing on screen to say which gate said
no. So the rule lives here, in one function, and both gates call it.

**A leaf module, deliberately.** It imports nothing from the application. ``services/write.py``
already defers its ``accommodations`` import to call time to dodge a cycle, so a home with no app
imports at all is the only one that is safe for both callers.
"""

from __future__ import annotations


def is_own_practice(workspace, actor) -> bool:
    """Whether this is ``actor``'s own practice copy -- a workspace they may work as a student.

    A practice copy is an ordinary workspace whose ``staff_practice`` flag is set and whose
    ``student_id`` is the teacher's own id. It is private to its owner: another teacher, a grader
    and an admin are all just staff looking at somebody else's books, and get False.

    **Null-safe on both arguments, and that is load-bearing.** ``app._register_audit`` consults
    this from an ``@app.after_request`` hook that runs for every response, including the many
    requests that never set ``g.workspace``; the hook swallows exceptions because "logging must
    never turn a good response into an error", so an ``AttributeError`` on ``None.staff_practice``
    would not raise -- it would silently stop the durable audit trail recording anything. The
    actor is guarded the same way, for an anonymous caller or one that was never signed in.
    """
    if workspace is None or actor is None:
        return False
    if not getattr(workspace, "staff_practice", False):
        return False
    return getattr(actor, "id", None) == workspace.student_id
