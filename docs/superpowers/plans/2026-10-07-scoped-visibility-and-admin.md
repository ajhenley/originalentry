# Scoped Visibility and Admin Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop every teacher from seeing every student's marks and books, add an admin role that
can, and give admins a screen for adding and removing teachers.

**Architecture:** Section ownership is a `(section, staff)` join table. One helper,
`may_see_section`, is consulted by four chokepoints — `workspace_view`, `_assignment_or_404`, a new
`_section_or_404`, and three queries with no id in the path — and holds the only read of the
`SCOPED_VISIBILITY` flag. A bidirectional test walks `app.url_map` so no route is scoped by
accident or left out by forgetting.

**Tech Stack:** Flask 3.1, SQLAlchemy 2.0, Flask-Migrate/Alembic, Flask-Login, pytest against real
Postgres (Neon).

**Spec:** `docs/superpowers/specs/2026-10-07-admin-and-staff-accounts-design.md`

## Global Constraints

Copied from the spec. Every task's requirements implicitly include these.

- **Refusals are `abort(404)`, never 403.** A refusal that confirms the page exists tells a prober
  something. This is why `staff_view` and `workspace_view` already do it.
- **`may_see_section` is the only place `SCOPED_VISIBILITY` is read.** A flag checked inline at a
  call site can leave half the routes scoped and half not.
- **`SCOPED_VISIBILITY` defaults to `True`**, and while it is off the app logs a warning at startup
  and the console shows a banner on every page.
- **Admins are staff.** `STAFF_ROLES` becomes `{grader, instructor, admin}`; admin is additive, so
  every route a teacher reaches an admin reaches too.
- **One definition of the role sets.** `decorators.py` owns `STAFF_ROLES` and `ADMIN_ROLES`;
  `auth/views.py:47` deletes its duplicate and imports instead.
- **Roles offered in the UI are Teacher and Admin.** `grader` is never offered; existing grader
  accounts keep working and display as Teacher.
- **Nothing is deleted on deactivation**, including `SectionStaff` rows.
- **`abort(404)` must mean "scoping refused"** on scoped routes, because the admission half of the
  matrix cannot otherwise tell a refusal from an honest miss.
- **Migration head is `a1c4e7b92f30`.** New revisions chain from it.
- **Tests run against real Postgres and take roughly 85 minutes for the full suite.** Run the file
  you are working on per step; run the suite at a task's end.

## Review Focus

Five failure modes the spec implies that no obvious test covers. Each has its test named in the
task that owns the code.

1. **A teacher creates an assignment with a *new* section and immediately cannot see it** — because
   `create_section` made the section but attached nobody. *Pinned in Task 2.*
2. **An invite to an address differing only in case** collides with the `uq_user_lower_email`
   index and raises instead of refusing politely. *Pinned in Task 5.*
3. **A teacher with no sections** sees an empty console and cannot tell it from an outage.
   *Pinned in Task 4.*
4. **A section whose only teacher was deactivated** becomes invisible to everyone but admins, with
   nothing saying so. *Pinned in Task 6.*
5. **`SCOPED_VISIBILITY` left off** in production, with the privacy control absent and nobody
   noticing. *Pinned in Task 3.*

---

### Task 0: Make the assignment form survive its own rejection

A prerequisite, not a follow-on. Task 4 adds a rejection path to this form, and of its fifteen
fields the seven text and date boxes repopulate while **all eight selects, radios and tick boxes
silently reset to their defaults** — which is how a validation error on one field produced
*"Choose the company this assignment uses"* for a company that had been chosen. Adding another
refusal to a form that loses its state turns one refusal into a mystery.

**Files:**
- Modify: `originalentry/templates/staff/assignment_new.html`
- Test: `tests/integration/test_assignment_setup.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks import. The form now round-trips `company_policy`,
  `pack_version_id`, `choice_pack_version_ids`, `section_choice`, `section_id`, `mode`,
  `late_policy` and `variant_policy` through a 422.

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/test_assignment_setup.py`:

```python
def test_a_rejected_form_keeps_every_control_the_user_set(client, session, instructor, pack_version,
                                                          section):
    """A validation error on one field must not silently reset the other fourteen.

    This is the bug that told an instructor to "Choose the company this assignment uses" about a
    company they had chosen: the error was a late cut-off, the re-render dropped the company, and
    the second submit complained about the company.
    """
    client.sign_in(instructor)

    response = client.post("/staff/assignments/new", data={
        "title": "Riverbend, section B",
        "company_policy": "fixed",
        "pack_version_id": str(pack_version.id),
        "section_choice": "existing",
        "section_id": str(section.id),
        "mode": "paper",
        "variant_policy": "manual",
        "late_policy": "accept_late"   # LATE_ACCEPT; "accept" is not a real value,
        "due_at": "2026-12-15T17:00",
        "late_until": "2026-12-01T17:00",      # before the due date: the one real error
    })

    assert response.status_code == 422
    page = response.get_data(as_text=True)
    assert "Late work needs a cut-off after the due date" in page

    # Every control the user set must come back set.
    assert f'value="{pack_version.id}" selected' in page or \
           f'value="{pack_version.id}"  selected' in page, "the company was dropped"
    assert f'value="{section.id}" selected' in page, "the section was dropped"
    assert 'value="paper" selected' in page, "the documents mode was dropped"
    assert 'value="manual" selected' in page, "the version policy was dropped"
    assert 'value="accept" selected' in page, "the late policy was dropped"
    assert 'value="fixed" checked' in page, "the company policy radio was dropped"
    assert 'value="existing" checked' in page, "the section choice radio was dropped"
    assert 'value="Riverbend, section B"' in page, "the title was dropped"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_assignment_setup.py::test_a_rejected_form_keeps_every_control_the_user_set -v`

Expected: FAIL on `"the company was dropped"` — the first assertion past the status check.

- [ ] **Step 3: Make every control read from `values`**

In `assignment_new.html`, each of the eight controls gains the conditional the text inputs already
have. The company select, as the pattern:

```jinja
<select id="pack_version_id" name="pack_version_id" class="field mt-1">
  <option value="">Choose a company</option>
  {% for entry in catalogue %}
  {# values is a form MultiDict, so its ids are strings; entry.id is an int. #}
  <option value="{{ entry.id }}"
          {% if values.get('pack_version_id') == entry.id|string %}selected{% endif %}>
    {{ entry.label }}</option>
  {% endfor %}
</select>
```

Apply the same shape to `section_id` and to `mode`, `variant_policy` and `late_policy`; the
radios `company_policy` and `section_choice` take `{% if values.get('company_policy', 'fixed') ==
'fixed' %}checked{% endif %}` so the default survives a first render; and
`choice_pack_version_ids` is a `getlist`:

```jinja
<input type="checkbox" name="choice_pack_version_ids" value="{{ entry.id }}"
       {% if entry.id|string in values.getlist('choice_pack_version_ids') %}checked{% endif %}>
```

> `values` is `{}` on the GET, and a plain dict has no `getlist`. Pass `values=request.form` on the
> POST path (already done) and `values=MultiDict()` on the GET path, so the template has one shape
> to read.

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_assignment_setup.py -v`
Expected: PASS, and the other tests in the file still pass.

- [ ] **Step 5: Commit**

```bash
git add originalentry/templates/staff/assignment_new.html originalentry/staff/views.py \
        tests/integration/test_assignment_setup.py
git commit -m "fix: a rejected assignment form keeps what you typed in

Of fifteen fields, the seven text and date boxes repopulated and all
eight selects, radios and tick boxes reset to their defaults. So a late
cut-off before the due date came back as an error about the cut-off, the
company silently emptied, and the next submit said to choose the company
you had already chosen.

A prerequisite for scoping, which adds a second rejection path to this
form: a form that loses its state on refusal turns one refusal into a
mystery."
```

---

### Task 1: The admin role, and one definition of who counts as staff

**Files:**
- Modify: `originalentry/models/people.py:23-26`
- Modify: `originalentry/decorators.py:25`
- Create: `originalentry/decorators_admin.py`
- Modify: `originalentry/auth/views.py:47` (delete the duplicate)
- Modify: `originalentry/cli.py:33`
- Modify: `originalentry/services/staff_actions.py`
- Test: `tests/guards/test_structure.py`, `tests/integration/test_admin_role.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ROLE_ADMIN = "admin"`; `ROLES` gains it; `decorators.STAFF_ROLES` (now
  `{grader, instructor, admin}`); `decorators.ADMIN_ROLES` (`{admin}`);
  `decorators_admin.admin_view(view)` setting `_is_admin_view = True`; and the action constants
  `staff_actions.STAFF_INVITED`, `STAFF_ROLE_CHANGED`, `STAFF_DEACTIVATED`, `STAFF_REACTIVATED`,
  `SECTION_STAFF_ADDED`, `SECTION_STAFF_REMOVED`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_admin_role.py`:

```python
"""The admin role, and the one definition of who counts as staff."""

from originalentry import decorators
from originalentry.auth import views as auth_views
from originalentry.models import ROLE_ADMIN, ROLE_GRADER, ROLE_INSTRUCTOR, ROLES


def test_admin_is_a_role_and_is_declared():
    assert ROLE_ADMIN == "admin"
    assert ROLE_ADMIN in ROLES


def test_admin_counts_as_staff():
    """Additive: every route a teacher reaches, an admin reaches."""
    assert decorators.STAFF_ROLES == frozenset({ROLE_GRADER, ROLE_INSTRUCTOR, ROLE_ADMIN})
    assert decorators.ADMIN_ROLES == frozenset({ROLE_ADMIN})


def test_who_counts_as_staff_is_defined_exactly_once():
    """auth/views.py kept its own copy of STAFF_ROLES. Two definitions of who counts as staff is
    a latent security bug, and duplication of this kind has already caused a defect here."""
    assert auth_views.STAFF_ROLES is decorators.STAFF_ROLES


def test_admin_fits_the_role_column():
    from originalentry.models.people import User
    assert len(ROLE_ADMIN) <= User.__table__.c.role.type.length
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/integration/test_admin_role.py -v`
Expected: FAIL — `ImportError: cannot import name 'ROLE_ADMIN'`.

- [ ] **Step 3: Add the role and collapse the duplicate**

`originalentry/models/people.py`:

```python
ROLE_STUDENT = "student"
ROLE_GRADER = "grader"
ROLE_INSTRUCTOR = "instructor"
ROLE_ADMIN = "admin"
# Declared, and read by nothing today -- cli.py hand-writes its own choices. Keeping it honest
# costs nothing; deriving the CLI's choices from it is the better fix, in step 5 below.
ROLES = (ROLE_STUDENT, ROLE_GRADER, ROLE_INSTRUCTOR, ROLE_ADMIN)
```

Add `ROLE_ADMIN` to that module's `__all__` and to `models/__init__.py`'s imports and `__all__`,
beside `ROLE_INSTRUCTOR`.

`originalentry/decorators.py`:

```python
STAFF_ROLES = frozenset({ROLE_GRADER, ROLE_INSTRUCTOR, ROLE_ADMIN})
ADMIN_ROLES = frozenset({ROLE_ADMIN})
```

`originalentry/auth/views.py` — delete line 47's `STAFF_ROLES = {ROLE_GRADER, ROLE_INSTRUCTOR}` and
import it instead:

```python
from ..decorators import STAFF_ROLES
```

No cycle: `decorators` imports from `models`, and nothing imports `auth`.

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/python -m pytest tests/integration/test_admin_role.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add `admin_view`, the CLI choice, and the audit constants**

Create `originalentry/decorators_admin.py`, mirroring `decorators_staff.py`:

```python
"""``admin_view``: the guard on routes only an administrator may reach.

404 rather than 403, for the reason ``staff_view`` already gives: a refusal that confirms the page
exists is a refusal that tells a prober something.
"""

from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

from .decorators import ADMIN_ROLES


def admin_view(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role not in ADMIN_ROLES:
            abort(404)
        return view(*args, **kwargs)

    wrapped._is_admin_view = True
    return wrapped
```

`originalentry/cli.py:33` — derive the choices from the declaration rather than repeating it:

```python
from .models import ROLES, ROLE_STUDENT
...
@click.option("--role", type=click.Choice([r for r in ROLES if r != ROLE_STUDENT]), required=True)
```

`originalentry/services/staff_actions.py` — add beside the existing five:

```python
STAFF_INVITED = "staff_invited"
STAFF_ROLE_CHANGED = "staff_role_changed"
STAFF_DEACTIVATED = "staff_deactivated"
STAFF_REACTIVATED = "staff_reactivated"
SECTION_STAFF_ADDED = "section_staff_added"
SECTION_STAFF_REMOVED = "section_staff_removed"
```

- [ ] **Step 6: Run the guard and auth suites**

Run: `.venv/bin/python -m pytest tests/guards/ tests/integration/test_auth.py tests/integration/test_admin_role.py -q`
Expected: PASS. `tests/guards/test_structure.py` still passes because no route has changed yet.

- [ ] **Step 7: Commit**

```bash
git add originalentry/models/ originalentry/decorators.py originalentry/decorators_admin.py \
        originalentry/auth/views.py originalentry/cli.py originalentry/services/staff_actions.py \
        tests/integration/test_admin_role.py
git commit -m "feat: an admin role, and one definition of who counts as staff

Admin is additive: STAFF_ROLES gains it, so every route a teacher
reaches an admin reaches too, and ADMIN_ROLES is what the four
restricted things will check.

auth/views.py kept its own copy of STAFF_ROLES and now imports the one
in decorators.py. Two definitions of who counts as staff is a latent
security bug rather than untidiness, and duplication of exactly this
kind has already caused a defect here.

The CLI's --role choices now derive from ROLES instead of repeating it,
which is the same mistake one size down."
```

---

### Task 2: Section ownership, the migration, and the backfill

**Files:**
- Modify: `originalentry/models/people.py` (add `SectionStaff` beside `Enrollment`)
- Modify: `originalentry/models/__init__.py`
- Create: `migrations/versions/<hash>_section_staff.py`
- Modify: `originalentry/services/assignments.py:54-61` (`create_section` attaches its actor)
- Test: `tests/integration/test_section_staff.py`

**Interfaces:**
- Consumes: `staff_actions.SECTION_STAFF_ADDED` from Task 1.
- Produces: `SectionStaff` with columns `section_id`, `user_id` (composite primary key),
  `added_at`, `added_by_id`; and `create_section(session, *, name, term, course_tag=None, actor=None)`
  now attaching `actor` to the new section when `actor` is staff.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_section_staff.py`:

```python
"""Who teaches a section."""

from originalentry.extensions import db
from originalentry.models import ROLE_INSTRUCTOR, Section, SectionStaff, User
from originalentry.services.assignments import create_section


def test_a_section_can_have_two_teachers(session, instructor):
    """Co-teaching is why this is a join table and not a column on Section."""
    other = User(email="second@example.edu", role=ROLE_INSTRUCTOR)
    session.add(other)
    section = create_section(session, name="ACCT1010 A", term="Spring", actor=instructor)
    session.add(SectionStaff(section_id=section.id, user_id=other.id, added_by_id=instructor.id))
    session.flush()

    teachers = set(session.scalars(
        db.select(SectionStaff.user_id).filter_by(section_id=section.id)).all())
    assert teachers == {instructor.id, other.id}


def test_creating_a_section_attaches_the_person_who_created_it(session, instructor):
    """Review Focus 1. Without this, a teacher creating an assignment with a NEW section makes a
    section nobody teaches -- and is refused from the thing they just made, one request later."""
    section = create_section(session, name="ACCT1010 B", term="Spring", actor=instructor)
    session.flush()

    attached = session.scalar(db.select(SectionStaff.user_id).filter_by(
        section_id=section.id, user_id=instructor.id))
    assert attached == instructor.id, "the creating teacher does not teach their own new section"


def test_creating_a_section_without_an_actor_attaches_nobody(session):
    """The CLI and the fixtures create sections with no actor; that must not explode."""
    section = create_section(session, name="Imported", term="Spring", actor=None)
    session.flush()
    assert session.scalars(
        db.select(SectionStaff).filter_by(section_id=section.id)).all() == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_section_staff.py -v`
Expected: FAIL — `ImportError: cannot import name 'SectionStaff'`.

- [ ] **Step 3: Add the model**

In `originalentry/models/people.py`, directly after `Enrollment` (whose shape this mirrors):

```python
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
```

Add `"SectionStaff"` to that module's `__all__`, and to `models/__init__.py`'s imports and
`__all__` beside `Enrollment`.

- [ ] **Step 4: Attach the creating teacher**

`originalentry/services/assignments.py`, in `create_section`, after the existing `session.flush()`:

```python
    # The person who made it teaches it. Without this, a teacher who creates an assignment with a
    # new section has made a section nobody teaches, and scoping refuses them from the thing they
    # just created on the very next request.
    if actor is not None and getattr(actor, "role", None) in STAFF_ROLES:
        session.add(SectionStaff(section_id=section.id, user_id=actor.id, added_by_id=actor.id))
        session.flush()
        staff_actions.record(session, actor, staff_actions.SECTION_STAFF_ADDED,
                             "section", section.id, detail={"user_id": actor.id})
```

- [ ] **Step 5: Run them to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_section_staff.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 6: Write the migration**

Create `migrations/versions/b8e4a2c71f09_section_staff.py`, following the hand-written style of
`e94b17c6d205_staff_action.py`:

```python
"""section_staff: who teaches a section

Ownership did not exist before this. Every staff member could see every student's marks and
books, because nothing recorded whose section a section was.

The backfill attaches every existing section to every account that currently holds a staff role,
so the day this deploys behaves exactly as the day before it: nobody is locked out of a class
mid-term by a migration. It also means **deploying this does not close the leak** -- an admin
closes it by pruning the attachments on the people screen.

Revision ID: b8e4a2c71f09
Revises: a1c4e7b92f30
Create Date: 2026-10-07 08:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'b8e4a2c71f09'
down_revision = 'a1c4e7b92f30'
branch_labels = None
depends_on = None

STAFF_ROLES = ('grader', 'instructor', 'admin')


def upgrade():
    op.create_table(
        'section_staff',
        sa.Column('section_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
                  nullable=False),
        sa.Column('added_by_id', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['section_id'], ['section.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['added_by_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('section_id', 'user_id'),
    )
    op.create_index('ix_section_staff_user', 'section_staff', ['user_id'])

    # Every section to every current staff member: a deliberate no-op on behaviour.
    op.execute(sa.text("""
        INSERT INTO section_staff (section_id, user_id)
        SELECT s.id, u.id
        FROM section s
        CROSS JOIN "user" u
        WHERE u.role IN :roles
        ON CONFLICT DO NOTHING
    """).bindparams(sa.bindparam('roles', value=STAFF_ROLES, expanding=True)))


def downgrade():
    op.drop_index('ix_section_staff_user', table_name='section_staff')
    op.drop_table('section_staff')
```

The index on `user_id` is what `my_section_ids` reads once per request.

- [ ] **Step 7: Apply it and check the backfill**

```bash
.venv/bin/flask db upgrade
.venv/bin/flask shell -c "
from originalentry.extensions import db
from originalentry.models import Section, SectionStaff, User
from originalentry.decorators import STAFF_ROLES
staff = db.session.scalars(db.select(User).where(User.role.in_(STAFF_ROLES))).all()
sections = db.session.scalars(db.select(Section)).all()
rows = db.session.scalars(db.select(SectionStaff)).all()
print(f'{len(sections)} sections x {len(staff)} staff = {len(sections)*len(staff)} expected, {len(rows)} rows')
"
```
Expected: the row count equals sections × staff. If there is one staff account, the backfill is
already correct and there is nothing to prune later.

> **This writes to the live database.** It is additive and reversible (`flask db downgrade`), but
> it is the one step in this plan that touches real data. Do it when nobody is mid-assignment.

- [ ] **Step 8: Commit**

```bash
git add originalentry/models/ migrations/versions/b8e4a2c71f09_section_staff.py \
        originalentry/services/assignments.py tests/integration/test_section_staff.py
git commit -m "feat: section_staff, so a section has teachers

Ownership did not exist: nothing recorded whose section a section was,
which is why every staff member could see every student's marks. A join
table rather than a column, because a course is commonly co-taught and a
teaching assistant has to be attachable to one section rather than all.

create_section attaches whoever created it. Without that, a teacher who
creates an assignment with a new section has made a section nobody
teaches, and is refused from the thing they just made one request later.

The backfill attaches every section to every current staff member, so
the day this deploys behaves exactly as the day before. Which means
deploying it does not close the leak -- pruning does."
```

---

### Task 3: One helper, and a switch that says when it is off

**Files:**
- Modify: `originalentry/decorators.py` (add `my_section_ids`, `may_see_section`)
- Modify: `originalentry/config.py` (add `SCOPED_VISIBILITY`)
- Modify: `originalentry/app.py` (startup warning)
- Test: `tests/integration/test_scoping_helper.py`

**Interfaces:**
- Consumes: `SectionStaff` (Task 2), `ADMIN_ROLES` (Task 1).
- Produces: `decorators.my_section_ids() -> frozenset[int]`, cached on `g._my_section_ids`; and
  `decorators.may_see_section(section_id: int) -> bool`, the only reader of
  `config["SCOPED_VISIBILITY"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_scoping_helper.py`:

```python
"""may_see_section, and the switch that turns it off."""

import pytest
from flask import g
from originalentry.decorators import may_see_section, my_section_ids
from originalentry.extensions import db
from originalentry.models import ROLE_ADMIN, SectionStaff


def test_a_teacher_sees_a_section_they_teach(app, session, instructor, section):
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    with app.test_request_context():
        _login(instructor)
        assert may_see_section(section.id) is True


def test_a_teacher_does_not_see_a_section_they_do_not_teach(app, session, instructor, section):
    with app.test_request_context():
        _login(instructor)
        assert may_see_section(section.id) is False


def test_an_admin_sees_every_section(app, session, instructor, section):
    instructor.role = ROLE_ADMIN
    session.flush()
    with app.test_request_context():
        _login(instructor)
        assert may_see_section(section.id) is True


def test_the_sections_are_loaded_once_per_request(app, session, instructor, section):
    """workspace_view runs on every /w/ route and a console page checks several times."""
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    with app.test_request_context():
        _login(instructor)
        first = my_section_ids()
        assert my_section_ids() is first, "the per-request cache was not used"


def test_the_switch_opens_everything(app, session, instructor, section):
    """Review Focus 5. The flag is a supported state in which the privacy control is absent."""
    with app.test_request_context():
        _login(instructor)
        assert may_see_section(section.id) is False
        app.config["SCOPED_VISIBILITY"] = False
        g.pop("_my_section_ids", None)
        assert may_see_section(section.id) is True
    app.config["SCOPED_VISIBILITY"] = True


def test_the_switch_being_off_is_logged_at_startup(caplog):
    """A supported state in which the privacy control is absent must not be a quiet one."""
    from originalentry.app import create_app
    import logging
    with caplog.at_level(logging.WARNING):
        app = create_app()
        app.config["SCOPED_VISIBILITY"] = False
        create_app()      # a second build with the flag off in the environment
    # The real assertion lives in the implementation: see step 3's note on reading it from config.
```

> **On that last test:** `create_app` reads config from the environment, so exercising the warning
> means setting `SCOPED_VISIBILITY=0` in `os.environ` before the call and asserting the record.
> Write it that way; the sketch above shows the intent, not the mechanism.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_scoping_helper.py -v`
Expected: FAIL — `ImportError: cannot import name 'may_see_section'`.

- [ ] **Step 3: Add the helper, the config and the warning**

`originalentry/decorators.py`:

```python
def my_section_ids() -> frozenset[int]:
    """The sections this staff member teaches, loaded once per request.

    Cached on ``g`` because workspace_view runs on every /w/ route and a console page checks
    several times: one query per request, not one per check.
    """
    if not hasattr(g, "_my_section_ids"):
        g._my_section_ids = frozenset(db.session.scalars(
            db.select(SectionStaff.section_id).filter_by(user_id=current_user.id)
        ).all())
    return g._my_section_ids


def may_see_section(section_id: int) -> bool:
    """Whether the signed-in staff member may see this section's students.

    One function, because a scoping rule implemented in four places is a scoping rule with four
    chances to differ. The flag is read here and nowhere else for the same reason: a half-disabled
    guard is worse than either state.
    """
    if not current_app.config["SCOPED_VISIBILITY"]:
        return True
    if current_user.role in ADMIN_ROLES:
        return True
    return section_id in my_section_ids()
```

`originalentry/config.py`, beside the other booleans:

```python
        # Off means every staff member sees every student's work. It exists because scoping can
        # lock every teacher out of every class at once, and this change deploys mid-term: with
        # it, a misfire is a config change rather than a code deploy under pressure.
        self.SCOPED_VISIBILITY = _flag(os.environ.get("SCOPED_VISIBILITY"), default=True)
```

`originalentry/app.py`, in `create_app` after the config is attached:

```python
    if not app.config["SCOPED_VISIBILITY"]:
        app.logger.warning(
            "SCOPED_VISIBILITY is off: every staff member can see every student's work.")
```

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_scoping_helper.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add originalentry/decorators.py originalentry/config.py originalentry/app.py \
        tests/integration/test_scoping_helper.py
git commit -m "feat: may_see_section, and a switch that announces itself

One function, because a scoping rule written in four places is a scoping
rule with four chances to differ -- and the flag is read here and nowhere
else for the same reason: half-scoped is worse than either state.

The sections a staff member teaches are loaded once per request and
cached on g, because workspace_view runs on every /w/ route and a console
page checks several times.

SCOPED_VISIBILITY defaults on and logs a warning while it is off. A
supported state in which the privacy control is absent must not be a
quiet one: somebody flips it at 2am to unblock a class and nobody flips
it back."
```

---

### Task 4: Enforce it, in four places, and prove it in both directions

The task where a mistake is a leak. Four chokepoints, three queries, one banner, and a matrix that
walks `app.url_map` so no route is scoped by accident or missed by forgetting.

**Files:**
- Modify: `originalentry/decorators.py` (`workspace_view`, ~line 45)
- Modify: `originalentry/staff/views.py:73-81` (`_assignment_or_404`), `:82-117` (`index`),
  `:457-470` (`assignment_new`), `:472-549` (`assignment_create`), and lines 570, 587, 609, 648
  (replaced by `_section_or_404`)
- Modify: `originalentry/staff/views.py` (`catalogue_upload` gains `@admin_view`)
- Modify: `originalentry/templates/staff/assignments.html` (hide the admin-only control; banner)
- Create: `tests/guards/test_scoping.py`
- Test: `tests/integration/test_scoped_console.py`

**Interfaces:**
- Consumes: `may_see_section` (Task 3), `admin_view` (Task 1), `SectionStaff` (Task 2).
- Produces: `staff.views._section_or_404(section_id: int) -> Section`, used by the four section
  routes; and the guard contract that **`abort(404)` on a scoped route means scoping refused**,
  which the admission half of the matrix depends on.

- [ ] **Step 1: Write the failing matrix**

Create `tests/guards/test_scoping.py`:

```python
"""Is every route scoped, in both directions.

tests/guards/test_structure.py asks whether every route carries its guard. This asks the next
question: whether the guard refuses the right people and admits the right people. Driven off
app.url_map rather than a list, because the first draft of the spec behind this counted
chokepoints instead of enumerating routes and missed twenty-nine of them.
"""

import pytest
from flask import url_for

# Routes that are not section-scoped, and WHY. Two different reasons, kept apart: a reviewer
# auditing this list has to be able to tell which one applies to which name.
UNOWNED = {                 # nobody's data; any staff member may see these
    "staff.catalogue": "a company pack belongs to no section",
    "staff.answer_key_print": "an answer key is teaching material, not student data",
}
ADMIN_ONLY = {              # owned, but gated by role rather than by section
    "staff.catalogue_upload": "cohort-wide, so admin-only",
    "staff.people": "staff management",
    "staff.people_add": "staff management",
    "staff.people_role": "staff management",
    "staff.people_sections": "staff management",
}
EXEMPT = UNOWNED | ADMIN_ONLY

# Only needed by the refusal half: both guards abort before any view body reads these.
PLACEHOLDERS = {"key": "sales", "ref": "D01", "entry_id": "1", "statement_type": "trial_balance",
                "kind": "customer", "section": "chart", "run_id": "1",
                "pack_version_id": "1", "variant_code": "A"}


def test_every_exempt_name_is_a_real_route(app):
    """An exempt name matching no endpoint silently stops excluding anything.

    Rename a route and this fails, rather than the allowlist quietly ceasing to mean what it says.
    """
    known = {rule.endpoint for rule in app.url_map.iter_rules()}
    missing = sorted(set(EXEMPT) - known)
    assert not missing, f"exempt names matching no route: {missing}"


def _scoped_rules(app):
    for rule in app.url_map.iter_rules():
        if not (rule.rule.startswith("/staff") or rule.rule.startswith("/w/")):
            continue
        if rule.endpoint in EXEMPT:
            continue
        yield rule


def _walk(client, app, ids):
    """Every scoped route, once per method, with these ids. Returns {"GET staff.x": status}."""
    seen = {}
    with app.test_request_context():
        for rule in _scoped_rules(app):
            args = {**PLACEHOLDERS, **ids}
            url = url_for(rule.endpoint, **{k: args[k] for k in rule.arguments})
            for method in sorted(rule.methods & {"GET", "POST"}):
                seen[f"{method} {rule.endpoint}"] = client.open(url, method=method).status_code
    return seen


def test_a_teacher_from_another_section_is_refused_everywhere(client, app, foreign, outsider):
    """Placeholder ids suffice: the guard aborts before any view body reads them."""
    client.sign_in(outsider)
    leaked = [r for r, code in _walk(client, app, foreign).items() if code != 404]
    assert not leaked, "did not refuse a foreign teacher:\n  " + "\n  ".join(leaked)


def test_the_sections_own_teacher_is_refused_nowhere(client, app, worked, owner):
    """The other half, and the half that breaks teaching rather than privacy.

    Without it, an implementation returning 404 to everybody passes the test above clean on every
    route. `worked` holds real ids from tests/perfect_student.py, so a 404 here can only mean the
    scoping turned away someone it should have admitted. Any other status -- 200, 302, 400, 422 --
    means the route was entered, which is all this asserts.
    """
    client.sign_in(owner)
    refused = [r for r, code in _walk(client, app, worked).items() if code == 404]
    assert not refused, "refused the section's own teacher:\n  " + "\n  ".join(refused)


def test_an_admin_is_refused_nowhere(client, app, worked, admin):
    client.sign_in(admin)
    refused = [r for r, code in _walk(client, app, worked).items() if code == 404]
    assert not refused, "refused an admin:\n  " + "\n  ".join(refused)
```

The `foreign`, `outsider`, `worked`, `owner` and `admin` fixtures go in
`tests/guards/conftest.py`.

> **Two things these fixtures must get right, both learned in Task 0.**
>
> **They commit.** `assignment_create` calls `db.session.rollback()` before re-rendering a refused
> form, which wipes anything created inside the test's transaction. `tests/conftest.py:33-37` binds
> the Session with `join_transaction_mode="create_savepoint"`, so a fixture that calls
> `session.commit()` releases a savepoint rather than the outer transaction: the row survives the
> view's rollback and teardown still removes it. Do not reach for a pre-existing row and skip when
> there is none — a test that skips is a test that can stop running unnoticed.
>
> **`outsider` is a brand-new account.** Task 2's backfill attached every section to every staff
> member who existed when it ran, so no pre-existing account teaches nothing. Create one. `foreign` is a dict of `{"assignment", "workspace", "company_slug",
"section_id"}` for a section `outsider` does not teach; `worked` is the same keys for a section
`owner` does teach, built by `tests/perfect_student.py:build()` so every inner id is real.

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/guards/test_scoping.py -v`
Expected: `test_a_teacher_from_another_section_is_refused_everywhere` FAILS listing ~52 routes
that returned 200 — nothing is scoped yet. `test_every_exempt_name_is_a_real_route` also fails on
the five `staff.people*` names, which Task 5 creates; add them to `EXEMPT` only once they exist, or
mark that one test `xfail(strict=True)` until Task 5 and remove the marker there.

- [ ] **Step 3: Scope `workspace_view`** — 29 routes in one place

In `originalentry/decorators.py`, replace the staff branch:

```python
        is_owner = ws.student_id == current_user.id
        is_staff = current_user.role in STAFF_ROLES
        if not (is_owner or is_staff):
            abort(404)
```

with:

```python
        is_owner = ws.student_id == current_user.id
        # Staff see a student's books only for a section they teach. An admin sees all of them.
        # One scalar to reach the section; may_see_section caches the rest per request.
        is_staff = current_user.role in STAFF_ROLES and may_see_section(
            db.session.scalar(db.select(Assignment.section_id).filter_by(id=ws.assignment_id)))
        if not (is_owner or is_staff):
            abort(404)
```

`Assignment` joins the imports from `.models`. Everything downstream — the read-only banner naming
whose books these are, archived books staying open to staff (I2.4) — is unchanged and keeps working
for a teacher's own students.

- [ ] **Step 4: Scope the console** — 16 + 4 routes, two helpers

`_assignment_or_404`, at `staff/views.py:73`:

```python
def _assignment_or_404(public_id: str) -> Assignment:
    assignment = db.session.execute(
        db.select(Assignment).filter_by(public_id=public_id, archived_at=None)
    ).scalar_one_or_none()
    # 404 and not 403, as everywhere else here: a refusal that confirms the assignment exists
    # tells a teacher about a colleague's section.
    if assignment is None or not may_see_section(assignment.section_id):
        abort(404)
    return assignment
```

Add `_section_or_404` beside it, replacing the four identical inline lookups at lines 570, 587,
609 and 648:

```python
def _section_or_404(section_id: int) -> Section:
    section = db.session.get(Section, section_id)
    if section is None or not may_see_section(section.id):
        abort(404)
    return section
```

- [ ] **Step 5: Scope the three queries with no id in the path**

`index` (`:82`) — the assignment list joins the join table, unless the viewer is an admin:

```python
    query = db.select(Assignment).where(Assignment.archived_at.is_(None))
    if current_app.config["SCOPED_VISIBILITY"] and current_user.role not in ADMIN_ROLES:
        query = query.join(
            SectionStaff, SectionStaff.section_id == Assignment.section_id
        ).where(SectionStaff.user_id == current_user.id)
```

`assignment_new` (`:457`) and the error re-render in `assignment_create` (`:516`) — the section
dropdown lists only sections you teach:

```python
def _my_sections():
    query = db.select(Section).where(Section.archived_at.is_(None))
    if current_app.config["SCOPED_VISIBILITY"] and current_user.role not in ADMIN_ROLES:
        query = query.join(
            SectionStaff, SectionStaff.section_id == Section.id
        ).where(SectionStaff.user_id == current_user.id)
    return db.session.scalars(query.order_by(Section.name)).all()
```

And `assignment_create` verifies the **posted** id, because filtering the dropdown is not a
permission check — a crafted POST would otherwise plant an assignment in a colleague's section.
After the existing section lookup at `:506`:

```python
        if section is not None and not may_see_section(section.id):
            errors["section_id"] = "That section is not one you teach."
```

A form error at 422, not a 404: this route is reached by submitting a form, and a 404 on a form you
are legitimately filling in is baffling. Task 0 is what makes that re-render keep your answers.

- [ ] **Step 6: Gate the upload, and say when the switch is off**

`catalogue_upload` gains `@admin_view` in place of `@staff_view`. In
`templates/staff/catalogue.html`, wrap the upload form in
`{% if current_user.role in admin_roles %}`, so a teacher does not meet a 404 by clicking a button
that was rendered for them. Expose `admin_roles` through a context processor or pass it from the
view — one of the two, consistently.

In `templates/staff/base.html` (or whichever template the console's chrome lives in):

```jinja
{% if not config.SCOPED_VISIBILITY %}
<p class="callout callout--trouble">Scoped visibility is off: every member of staff can see every
  student's work.</p>
{% endif %}
```

A log line is read by whoever went looking; a banner is read by the next person to open the
console.

- [ ] **Step 7: Write the ordinary cases a matrix cannot express**

Create `tests/integration/test_scoped_console.py`:

```python
def test_a_co_teacher_sees_the_same_marks(client, session, section, owner, second_teacher, worked):
    """Two rows in section_staff, one section, the same view of it."""
    session.add(SectionStaff(section_id=section.id, user_id=second_teacher.id))
    session.flush()
    client.sign_in(second_teacher)
    assert client.get(f"/staff/grading/{worked['assignment']}").status_code == 200


def test_a_teacher_can_still_open_their_own_students_books(client, owner, worked):
    """workspace_view deliberately opens a student's books to staff, with a banner naming whose
    they are (I2.4). Scoping must not break marking in the name of securing it."""
    response = client.sign_in(owner) or client.get(
        f"/w/{worked['workspace']}/{worked['company_slug']}/journals")
    assert response.status_code == 200
    assert b"whose books" in response.data or b"viewing" in response.data.lower()


def test_a_teacher_with_no_sections_is_told_so(client, instructor):
    """Review Focus 3. An empty dashboard and no explanation reads as an outage."""
    client.sign_in(instructor)
    page = client.get("/staff/").get_data(as_text=True)
    assert "no sections" in page.lower() or "not teaching" in page.lower()


def test_a_crafted_create_naming_another_teachers_section_is_refused(client, owner, foreign,
                                                                     pack_version):
    """Filtering the dropdown is not a permission check."""
    client.sign_in(owner)
    response = client.post("/staff/assignments/new", data={
        "title": "Not mine", "company_policy": "fixed",
        "pack_version_id": str(pack_version.id),
        "section_choice": "existing", "section_id": str(foreign["section_id"]),
    })
    assert response.status_code == 422
    assert "not one you teach" in response.get_data(as_text=True)


def test_the_marks_csv_and_the_diagnostics_export_are_scoped(client, outsider, foreign):
    """The two routes that hand student data out in bulk."""
    client.sign_in(outsider)
    for path in (f"/staff/grading/{foreign['assignment']}/marks.csv",
                 f"/staff/diagnostics/{foreign['assignment']}/export.csv"):
        assert client.get(path).status_code == 404, path
```

Task 4's empty-state assertion needs the dashboard to say something when a teacher teaches
nothing; add that line to `assignments.html` in step 6.

- [ ] **Step 8: Run the matrix and the cases**

Run: `.venv/bin/python -m pytest tests/guards/test_scoping.py tests/integration/test_scoped_console.py -v`
Expected: PASS. Then with the switch off, to prove it inverts:

```bash
SCOPED_VISIBILITY=0 .venv/bin/python -m pytest tests/guards/test_scoping.py::test_a_teacher_from_another_section_is_refused_everywhere -v
```
Expected: FAIL, listing every scoped route — which is the switch working. Do not leave it set.

- [ ] **Step 9: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`
Expected: green. This is the task most likely to break something unrelated, because it changes a
decorator on 29 routes and a lookup used by 16.

- [ ] **Step 10: Commit**

```bash
git add originalentry/decorators.py originalentry/staff/views.py originalentry/templates/staff/ \
        tests/guards/test_scoping.py tests/guards/conftest.py \
        tests/integration/test_scoped_console.py
git commit -m "feat: a teacher sees their own sections and no others

Four chokepoints. workspace_view covers twenty-nine /w/ routes -- the
bigger leak, where a teacher read a student's actual journals and
ledgers rather than their marks. _assignment_or_404 covers sixteen
console routes, a new _section_or_404 covers four, and three queries
with no id in the path are scoped where they are built.

assignment_create verifies the posted section id, because filtering the
dropdown is not a permission check: a crafted POST would otherwise plant
an assignment in a colleague's section. It refuses as a 422 form error
rather than a 404, since the route is reached by submitting a form.

The matrix runs both ways. Refusing a foreign teacher can use
placeholder ids because the guards abort before any view body reads
them; admitting the section's own teacher cannot, so it uses real ids
from perfect_student and asserts not-404 rather than 200. Without the
second direction, returning 404 to everybody would pass clean on every
route -- and locking a teacher out of their own class in week nine is
the failure that gets noticed first."
```

---

### Task 5: The people screen

**Files:**
- Modify: `originalentry/staff/views.py` (four routes)
- Create: `originalentry/templates/staff/people.html`
- Create: `originalentry/services/staffing.py`
- Modify: `tests/guards/test_scoping.py` (remove the Task 4 xfail; the `staff.people*` names are real now)
- Test: `tests/integration/test_people_screen.py`

**Interfaces:**
- Consumes: `admin_view` (Task 1), `SectionStaff` (Task 2), `may_see_section` (Task 3),
  the `STAFF_*`/`SECTION_STAFF_*` action constants (Task 1).
- Produces endpoints named exactly as Task 4's `ADMIN_ONLY` expects: `staff.people` (GET),
  `staff.people_add` (POST `/staff/people`), `staff.people_role`
  (POST `/staff/people/<public_id>/role`), `staff.people_sections`
  (POST `/staff/people/<public_id>/sections`). Plus
  `services.staffing.invite(session, *, email, role, given, family, actor) -> User` raising
  `StaffingRefused`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_people_screen.py`:

```python
"""Adding, re-roling and section-attaching staff, from inside the app."""

import pytest
from originalentry.extensions import db
from originalentry.models import ROLE_ADMIN, ROLE_INSTRUCTOR, ROLE_STUDENT, SectionStaff, User
from originalentry.services.staffing import StaffingRefused, invite


def test_inviting_an_unknown_address_creates_the_account_and_sends_one_email(
        session, admin, mail_outbox):
    user = invite(session, email="new.teacher@example.edu", role=ROLE_INSTRUCTOR,
                  given="Nia", family="Okafor", actor=admin)
    session.flush()
    assert user.role == ROLE_INSTRUCTOR
    assert len(mail_outbox) == 1


def test_inviting_an_address_that_already_has_a_student_account_is_refused(session, admin, student):
    """One address being a student with marks and a teacher who reads a section's marks is an
    integrity problem, not an inconvenience. A teaching assistant is who hits this."""
    with pytest.raises(StaffingRefused) as refused:
        invite(session, email=student.email, role=ROLE_INSTRUCTOR, given="", family="", actor=admin)
    assert "student" in str(refused.value).lower()
    assert "separate" in str(refused.value).lower(), "the refusal must say what to do instead"


def test_inviting_an_address_that_differs_only_in_case_is_refused_politely(
        session, admin, student):
    """Review Focus 2. uq_user_lower_email makes this a duplicate; it must come back as a refusal
    rather than an IntegrityError from the flush."""
    with pytest.raises(StaffingRefused):
        invite(session, email=student.email.upper(), role=ROLE_INSTRUCTOR,
               given="", family="", actor=admin)


def test_inviting_an_existing_staff_address_does_not_issue_a_second_token(
        session, admin, instructor, mail_outbox):
    with pytest.raises(StaffingRefused) as refused:
        invite(session, email=instructor.email, role=ROLE_INSTRUCTOR,
               given="", family="", actor=admin)
    assert "already" in str(refused.value).lower()
    assert mail_outbox == []


def test_an_invite_is_not_throttled_by_the_per_ip_limit(session, admin, mail_outbox):
    """The ceiling is thirty an hour on the caller's IP, which would throttle an admin adding a
    department from one desk. The per-address limits that protect the recipient still apply."""
    for n in range(35):
        invite(session, email=f"t{n}@example.edu", role=ROLE_INSTRUCTOR,
               given="", family="", actor=admin)
        session.flush()
    assert len(mail_outbox) == 35


def test_an_admin_cannot_change_their_own_role(client, admin):
    client.sign_in(admin)
    response = client.post(f"/staff/people/{admin.public_id}/role", data={"role": ROLE_INSTRUCTOR})
    assert admin.role == ROLE_ADMIN
    assert b"your own" in response.data.lower() or response.status_code == 422


def test_the_last_admin_cannot_be_demoted(client, session, admin, second_admin):
    """Checked in the transaction, so two admins demoting each other cannot both succeed."""
    client.sign_in(admin)
    client.post(f"/staff/people/{second_admin.public_id}/role", data={"role": ROLE_INSTRUCTOR})
    session.flush()
    client.sign_in(second_admin)   # now a teacher; cannot reach the screen at all
    assert client.get("/staff/people").status_code == 404


def test_attaching_a_section_puts_it_on_that_teachers_dashboard(client, session, admin,
                                                                instructor, section):
    client.sign_in(admin)
    client.post(f"/staff/people/{instructor.public_id}/sections",
                data={"section_id": str(section.id), "attach": "1"})
    session.flush()
    client.sign_in(instructor)
    assert section.name in client.get("/staff/").get_data(as_text=True)


def test_a_teacher_cannot_reach_the_people_screen(client, instructor):
    client.sign_in(instructor)
    assert client.get("/staff/people").status_code == 404
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_people_screen.py -v`
Expected: FAIL — `ModuleNotFoundError: originalentry.services.staffing`.

- [ ] **Step 3: Write the service**

Create `originalentry/services/staffing.py`:

```python
"""Adding and re-roling staff from inside the app.

Until now a teacher account existed only if somebody ran ``flask staff add`` on the production
dyno, which wrote no audit record and sent no email.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import email as auth_email, tokens
from ..decorators import ADMIN_ROLES, STAFF_ROLES
from ..models import ROLE_STUDENT, User
from . import staff_actions


class StaffingRefused(Exception):
    """Said to an administrator, so it names the conflict and what to do instead."""


def _by_email(session: Session, email: str) -> User | None:
    """Case-insensitively, because uq_user_lower_email is: a lookup that is not would create a
    duplicate the index then refuses, turning a polite refusal into an IntegrityError."""
    return session.scalars(
        select(User).where(func.lower(User.email) == email.strip().lower())).first()


def invite(session: Session, *, email: str, role: str, given: str, family: str, actor) -> User:
    existing = _by_email(session, email)
    if existing is not None and existing.role == ROLE_STUDENT:
        raise StaffingRefused(
            f"{existing.email} already has a student account. A teacher who is also a student "
            f"here needs a separate staff address, so that one person's marks and another's "
            f"marking never share a sign-in.")
    if existing is not None:
        raise StaffingRefused(
            f"{existing.email} already has a staff account. Change their role instead.")

    user = User(email=email.strip(), role=role, given_name=given, family_name=family)
    session.add(user)
    session.flush()

    # ip=None on purpose: the per-IP ceiling is thirty an hour and would throttle an admin adding
    # a department from one desk. The per-address limits, which protect the recipient, still
    # apply -- the guard in _enforce_rate_limits is `if ip_hash:`.
    raw_token, code = tokens.issue_token(session, user.email, user_id=user.id, ip=None)
    auth_email.send_sign_in_email(user.email, _link(raw_token), code)
    staff_actions.record(session, actor, staff_actions.STAFF_INVITED, "user", user.id,
                         detail={"role": role})
    return user
```

`_link` builds `{APP_BASE_URL}/auth/verify/{raw_token}` the way `cli.py:issue_link` does.

> **Known limitation to carry into the flash message:** that token lives fifteen minutes, so a
> teacher invited at 5pm finds a dead link next morning. Their account exists, so ordinary sign-in
> works; the flash says the link is short-lived and that signing in works regardless.

- [ ] **Step 4: Write the four routes and the template**

All four carry `@admin_view`. `people` lists staff with their sections and a count of how many
sections are attached to how many teachers — the outstanding pruning from Task 2's backfill, made
visible rather than remembered. `people_role` enforces both invariants:

```python
    if target.id == current_user.id:
        flash("You cannot change your own role.")
        return back
    if target.role in ADMIN_ROLES and new_role not in ADMIN_ROLES:
        remaining = db.session.scalar(select(func.count(User.id)).where(
            User.role.in_(ADMIN_ROLES), User.id != target.id,
            User.deactivated_at.is_(None)))          # the column arrives in Task 6
        if not remaining:
            flash("That is the last administrator. Make someone else an administrator first.")
            return back
```

Until Task 6 lands, drop the `deactivated_at` clause; add it there.

**Both routes write their audit record**, which Task 1 added the constants for and nothing has
used yet — `STAFF_ROLE_CHANGED` on a successful re-role, and `SECTION_STAFF_ADDED` /
`SECTION_STAFF_REMOVED` on each attach and detach:

```python
    staff_actions.record(session, current_user, staff_actions.STAFF_ROLE_CHANGED, "user",
                         target.id, detail={"from": target.role, "to": new_role})
```

This is the whole traceability gain of moving staff management in-app: `flask staff add` wrote
nothing at all. A constant declared and never recorded would leave that gain on the table.

- [ ] **Step 5: Run them to verify they pass**

Run: `.venv/bin/python -m pytest tests/integration/test_people_screen.py -v`
Expected: PASS.

- [ ] **Step 6: Remove Task 4's marker and run the guards**

The five `staff.people*` names in `ADMIN_ONLY` are real endpoints now, so
`test_every_exempt_name_is_a_real_route` passes on its own; delete the `xfail` added in Task 4.

Run: `.venv/bin/python -m pytest tests/guards/ -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add originalentry/services/staffing.py originalentry/staff/views.py \
        originalentry/templates/staff/people.html tests/integration/test_people_screen.py \
        tests/guards/test_scoping.py
git commit -m "feat: add and re-role staff from inside the app

A teacher account existed only if somebody ran flask staff add on the
production dyno, which wrote no audit record and sent no email. Now an
administrator adds one, the account is created, and the invite reuses
the sign-in email the app already sends.

ip=None on that issue_token, deliberately: the per-IP ceiling is thirty
an hour and would throttle an admin adding a department from one desk,
while the per-address limits that protect the recipient still apply.

An address that already has a student account is refused and told why. A
teacher who is also a student here needs a separate staff address, so
that one person's marks and another's marking never share a sign-in --
and the lookup is case-insensitive, because uq_user_lower_email is, and
a lookup that is not turns a polite refusal into an IntegrityError.

The screen is also where Task 2's backfill gets corrected, and it says
how much is left to correct."
```

---

### Task 6: Deactivation

**Files:**
- Modify: `originalentry/models/people.py` (add `deactivated_at`, fix `is_active`)
- Create: `migrations/versions/<hash>_user_deactivated_at.py`
- Modify: `originalentry/app.py:185-190` (the session loader)
- Modify: `originalentry/auth/views.py:142` (after `consume_code` matches)
- Modify: `originalentry/staff/views.py` (a deactivate/reactivate route)
- Modify: `originalentry/services/staffing.py`
- Test: `tests/integration/test_deactivation.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `User.deactivated_at`; `User.is_active` returning `self.deactivated_at is None`; and
  `services.staffing.deactivate(session, *, target, actor)` / `reactivate(...)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/test_deactivation.py`:

```python
"""Taking access away, without taking the record away."""

import pytest
from originalentry.extensions import db
from originalentry.models import SectionStaff, StaffAction
from originalentry.services.staffing import StaffingRefused, deactivate, reactivate


def test_a_valid_code_from_a_deactivated_account_is_refused_with_a_reason(
        client, session, instructor, admin):
    """A matching code proves they receive that mailbox, so naming the state tells them nothing
    they should not know. E1 governs the request step, which is untouched."""
    deactivate(session, target=instructor, actor=admin)
    session.flush()
    code = _issue_code_for(session, instructor)
    response = client.post("/auth/code", data={"email": instructor.email, "code": code})
    assert b"no longer active" in response.data


def test_the_request_step_is_identical_for_active_deactivated_and_unknown_addresses(
        client, session, instructor, admin):
    """The E1 guarantee, tested directly rather than assumed."""
    deactivate(session, target=instructor, actor=admin)
    session.flush()
    bodies = {
        name: client.post("/auth/sign-in", data={"email": address}).get_data(as_text=True)
        for name, address in (("deactivated", instructor.email),
                              ("unknown", "nobody@example.edu"))
    }
    assert bodies["deactivated"] == bodies["unknown"]


def test_a_live_session_dies_on_the_next_request(client, session, instructor, admin):
    client.sign_in(instructor)
    assert client.get("/staff/").status_code == 200
    deactivate(session, target=instructor, actor=admin)
    session.flush()
    assert client.get("/staff/").status_code in (302, 401, 404)


def test_their_record_survives_including_their_sections(session, instructor, admin, section):
    """Review Focus 4. Those rows are the only answer to who taught this class last term."""
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    deactivate(session, target=instructor, actor=admin)
    session.flush()

    assert session.scalar(db.select(SectionStaff.user_id).filter_by(
        section_id=section.id, user_id=instructor.id)) == instructor.id
    assert session.scalars(db.select(StaffAction).filter_by(
        action="staff_deactivated", target_id=instructor.id)).first() is not None


def test_a_section_whose_only_teacher_left_says_it_needs_one(client, session, admin, instructor,
                                                             section):
    """Review Focus 4, the other half: nobody should have to remember which sections these are."""
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    deactivate(session, target=instructor, actor=admin)
    session.flush()
    client.sign_in(admin)
    page = client.get("/staff/people").get_data(as_text=True)
    assert "needs a teacher" in page.lower()


def test_reactivation_needs_a_fresh_sign_in_and_gives_the_sections_back(
        client, session, instructor, admin, section):
    session.add(SectionStaff(section_id=section.id, user_id=instructor.id))
    session.flush()
    deactivate(session, target=instructor, actor=admin)
    reactivate(session, target=instructor, actor=admin)
    session.flush()
    assert instructor.deactivated_at is None
    assert session.scalar(db.select(SectionStaff.user_id).filter_by(
        section_id=section.id, user_id=instructor.id)) == instructor.id


def test_you_cannot_deactivate_yourself_or_the_last_admin(session, admin):
    with pytest.raises(StaffingRefused):
        deactivate(session, target=admin, actor=admin)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/integration/test_deactivation.py -v`
Expected: FAIL — `ImportError: cannot import name 'deactivate'`.

- [ ] **Step 3: Add the column, the migration, and stop `is_active` lying**

`originalentry/models/people.py`:

```python
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

and:

```python
    @property
    def is_active(self) -> bool:
        return self.deactivated_at is None
```

Migration `<hash>_user_deactivated_at.py`, `down_revision = 'b8e4a2c71f09'`:

```python
def upgrade():
    op.add_column('user', sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('user', 'deactivated_at')
```

- [ ] **Step 4: Block the session and the code**

`originalentry/app.py`, in the user loader after the epoch check:

```python
        # One chokepoint for both a live session and a new sign-in.
        if user.deactivated_at is not None:
            return None
```

`originalentry/auth/views.py`, after `consume_code` returns a match:

```python
        if row is not None and row.user_id is not None:
            user = db.session.get(User, row.user_id)
            if user is not None and user.deactivated_at is not None:
                flash("That account is no longer active. Ask your administrator.")
                return redirect(url_for("auth.sign_in"))
```

The *request* step gets no special case at all: a deactivated address appears to be sent a code
exactly like any other, which is what keeps E1 intact.

- [ ] **Step 5: Write the service functions**

In `staffing.py`:

```python
def deactivate(session: Session, *, target: User, actor) -> User:
    if target.id == getattr(actor, "id", None):
        raise StaffingRefused("You cannot deactivate your own account.")
    if target.role in ADMIN_ROLES:
        remaining = session.scalar(select(func.count(User.id)).where(
            User.role.in_(ADMIN_ROLES), User.id != target.id, User.deactivated_at.is_(None)))
        if not remaining:
            raise StaffingRefused(
                "That is the last active administrator. Make someone else an administrator first.")
    target.deactivated_at = func.now()
    target.session_epoch = (target.session_epoch or 0) + 1   # every device, now
    session.flush()
    staff_actions.record(session, actor, staff_actions.STAFF_DEACTIVATED, "user", target.id)
    return target
```

`reactivate` clears the stamp and records `STAFF_REACTIVATED`. Neither touches `SectionStaff`:
those rows are the only record of who taught a class, and a DELETE on offboarding is how
*"who was teaching ACCT1010 last spring?"* becomes unanswerable.

Add the `deactivated_at.is_(None)` clause to Task 5's last-admin check now that the column exists.

- [ ] **Step 6: Run them, then the whole suite**

Run: `.venv/bin/python -m pytest tests/integration/test_deactivation.py -v`
Expected: PASS.

Run: `.venv/bin/python -m pytest -q`
Expected: green.

- [ ] **Step 7: Commit**

```bash
git add originalentry/models/ migrations/versions/ originalentry/app.py \
        originalentry/auth/views.py originalentry/staff/views.py \
        originalentry/services/staffing.py tests/integration/test_deactivation.py
git commit -m "feat: deactivate a staff account without erasing them

There was no way to lock anyone out: is_active was hardcoded True, and
flask auth revoke only ended their sessions -- they signed straight back
in. Now a stamp blocks both, in the session loader, which is one
chokepoint for a live session and a new sign-in alike.

A matching code gets a reason rather than a shrug. That does not
contradict E1: E1 governs the request step, which is untouched, and
someone holding a valid code has proved they receive that mailbox.

Nothing is deleted, including their section_staff rows. Those rows are
the only answer to who taught a class last term, and a DELETE on
offboarding is how that question becomes unanswerable. A section whose
only teacher has gone says it needs one, so nobody has to remember which
ones they are."
```

---

## What this plan does not do

From the spec's Out of scope, repeated so an implementer does not drift into it: gating the CLI
(it cannot be role-gated — shell access is the permission); pack import, diff and migrate as admin
screens; giving `grader` real limits; splitting admin into manage-accounts and read-everything;
auditing admin reads; a teacher adding their own co-teacher; deactivating students; and a dedicated
invite email with a multi-day token.

One thing the spec names that this plan deliberately leaves alone: `release_marks` still has no
guard against releasing half-graded work. Scoping limits the blast radius to one section. Worth
fixing, separately.
