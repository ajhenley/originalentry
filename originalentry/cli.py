"""Flask CLI commands (T13.2). The break-glass paths for when email is down, and staff creation.

    flask staff add <email> --role grader|instructor|admin
    flask auth issue-link <email>     # prints a sign-in link + code for an existing user
    flask auth revoke <email>         # bumps session_epoch, signing out every device
"""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import AppGroup
from sqlalchemy import func, select

from .auth import tokens
from .extensions import db
from .models import ROLE_INSTRUCTOR, ROLE_STUDENT, ROLES, User


def _find_user(email: str) -> User | None:
    return db.session.scalars(
        select(User).where(func.lower(User.email) == email.strip().lower())
    ).one_or_none()


def register_cli(app: Flask) -> None:
    staff = AppGroup("staff", help="Staff accounts.")
    auth = AppGroup("auth", help="Break-glass sign-in and revocation.")
    packs = AppGroup("packs", help="Content packs.")

    @staff.command("add")
    @click.argument("email")
    @click.option(
        "--role", type=click.Choice([r for r in ROLES if r != ROLE_STUDENT]), required=True
    )
    @click.option("--given", default="", help="Given name.")
    @click.option("--family", default="", help="Family name.")
    def staff_add(email: str, role: str, given: str, family: str) -> None:
        user = _find_user(email)
        if user is None:
            user = User(email=email.strip(), role=role, given_name=given, family_name=family)
            db.session.add(user)
            action = "created"
        else:
            user.role = role
            action = "updated"
        db.session.commit()
        click.echo(f"{email} {action} as {role}.")

    @auth.command("issue-link")
    @click.argument("email")
    def issue_link(email: str) -> None:
        """Print a sign-in link and code for an existing account.

        This is the break-glass path, used when email is down and somebody is locked out. It is
        read in a terminal at the worst possible moment, so every refusal it can meet — including
        the sign-in rate limit — comes back as one plain sentence rather than a traceback.
        """
        user = _find_user(email)
        if user is None:
            raise click.ClickException(f"No account for {email}.")
        try:
            raw_token, code = tokens.issue_token(db.session, email, user_id=user.id)
        except tokens.RateLimited as limited:
            db.session.rollback()
            raise click.ClickException(str(limited)) from limited
        db.session.commit()
        base = app.extensions["originalentry_config"].APP_BASE_URL.rstrip("/")
        click.echo(f"Link: {base}/auth/verify/{raw_token}")
        click.echo(f"Code: {code}")
        click.echo("Both expire in 15 minutes and can be used once.")

    @auth.command("revoke")
    @click.argument("email")
    def revoke(email: str) -> None:
        user = _find_user(email)
        if user is None:
            raise click.ClickException(f"No account for {email}.")
        user.session_epoch = (user.session_epoch or 0) + 1
        db.session.commit()
        click.echo(f"Signed out every device for {email}.")

    @packs.command("import")
    @click.argument("zip_path")
    def packs_import(zip_path: str) -> None:
        """Import a pack zip through the direct endpoint (CLI fallback for large packs, T5.5)."""
        from .packs.importing import PackImportRefused, import_pack_zip

        with open(zip_path, "rb") as fh:
            try:
                version = import_pack_zip(db.session, fh, actor=None)
            except PackImportRefused as refused:
                db.session.rollback()
                click.echo("Import refused:", err=True)
                for problem in refused.problems:
                    click.echo(f"  [{problem.rule}] {problem.path}: {problem.message}", err=True)
                raise SystemExit(1) from refused
        db.session.commit()
        click.echo(f"Imported pack version id {version.id}.")

    @packs.command("migrate")
    @click.option("--assignment", "assignment_pub", required=True, help="Assignment public id.")
    @click.option("--to-version", type=int, required=True)
    @click.option("--apply", "apply_it", is_flag=True, help="Apply (default is a dry run).")
    @click.option("--accept-identity-changes", "accept_identity", is_flag=True,
                  help="Proceed even though refs the student used now name different documents. "
                       "Their recorded work will be reattached. Read `flask packs diff` first.")
    def packs_migrate(
        assignment_pub: str, to_version: int, apply_it: bool, accept_identity: bool
    ) -> None:
        """Migrate a running assignment to a newer version of its company (dry-run by default)."""
        from sqlalchemy import select as _select

        from .models import Assignment
        from .packs.migrate import MigrationRefused, migrate_assignment

        assignment = db.session.scalars(
            _select(Assignment).where(Assignment.public_id == assignment_pub)
        ).one_or_none()
        if assignment is None:
            raise click.ClickException(f"No assignment {assignment_pub}.")
        try:
            report = migrate_assignment(
                db.session, assignment, to_version, dry_run=not apply_it, actor=None,
                accept_identity_changes=accept_identity,
            )
        except MigrationRefused as refused:
            db.session.rollback()
            raise click.ClickException(refused.message) from refused

        click.echo(f"v{report.from_version} → v{report.to_version}: "
                   f"{report.workspaces} workspace(s), {report.entry_lines} line(s).")
        # Printed whether or not the override made the migration proceed: an accepted identity
        # change is still something that happened, and the operator needs to see it either way —
        # not only on the path where it still blocks.
        for change in report.changed_identity:
            prefix = "accepted" if report.changed_identity_accepted else "refused"
            click.echo(f"  {prefix}: {change.ref} {change.field}: "
                       f"{change.was} -> {change.now}",
                       err=not report.changed_identity_accepted)
        if not report.feasible:
            db.session.rollback()
            for label, missing in [("accounts", report.missing_accounts),
                                   ("parties", report.missing_parties),
                                   ("documents", report.missing_documents),
                                   ("variants", report.missing_variants)]:
                if missing:
                    click.echo(f"  missing {label}: {', '.join(missing)}", err=True)
            # Name the actual cause: missing content and a changed identity are different
            # problems with different remedies, and an operator told "something is gone" when
            # nothing is will go looking for deleted content that was never there.
            content_missing = bool(report.missing_accounts or report.missing_parties
                                    or report.missing_documents or report.missing_variants)
            identity_blocks = bool(report.changed_identity) and not report.changed_identity_accepted
            reasons = []
            if content_missing:
                reasons.append("some content students used is gone")
            if identity_blocks:
                reasons.append(
                    "refs the student used now name different documents "
                    "(--accept-identity-changes proceeds anyway)"
                )
            raise click.ClickException(f"Not feasible: {'; '.join(reasons)}.")
        if report.applied:
            db.session.commit()
            click.echo("Migrated.")
        else:
            db.session.rollback()
            click.echo("Dry run only — re-run with --apply to migrate.")

    @packs.command("diff")
    @click.option("--company", "slug", required=True, help="Company slug, e.g. riverbend.")
    @click.option("--from", "from_version", type=int, required=True)
    @click.option("--to", "to_version", type=int, required=True)
    def packs_diff(slug: str, from_version: int, to_version: int) -> None:
        """What a migration between two versions would do to the refs students hold.

        Read-only. `flask packs migrate` refuses when a ref a student used changed meaning; this
        shows the whole picture before anyone is migrated, including refs nobody has touched yet.
        """
        from sqlalchemy import select as _select

        from .models import ContentPack, PackVersion
        from .packs.migrate import documents_by_ref, triage_by_variant
        from .packs.version_diff import identity_changes

        pack = db.session.scalars(
            _select(ContentPack).where(ContentPack.slug == slug)
        ).one_or_none()
        if pack is None:
            raise click.ClickException(f"No company {slug!r} in the catalogue.")

        def _version(n: int) -> PackVersion:
            pv = db.session.scalars(
                _select(PackVersion).where(PackVersion.content_pack_id == pack.id,
                                           PackVersion.version == n)
            ).one_or_none()
            if pv is None:
                raise click.ClickException(f"{slug} has no version {n} in the catalogue.")
            return pv

        old_pv, new_pv = _version(from_version), _version(to_version)
        old_docs = documents_by_ref(db.session, old_pv)
        new_docs = documents_by_ref(db.session, new_pv)

        added = sorted(set(new_docs) - set(old_docs))
        removed = sorted(set(old_docs) - set(new_docs))
        changes = identity_changes(
            old_docs, new_docs,
            triage_by_variant(db.session, old_pv), triage_by_variant(db.session, new_pv),
        )

        click.echo(f"{slug} v{from_version} -> v{to_version}: "
                   f"{len(old_docs)} documents -> {len(new_docs)}")
        if added:
            click.echo(f"  added ({len(added)}): {', '.join(added)}")
        if removed:
            click.echo(f"  removed ({len(removed)}): {', '.join(removed)}")
        if not changes:
            click.echo("  no document changed what it denotes")
            return
        flipped_refs = {c.ref for c in changes if c.field == "triage"}
        click.echo(f"  {len({c.ref for c in changes})} ref(s) changed meaning, "
                   f"{len(flipped_refs)} of them flipping a triage answer")
        for change in changes:
            click.echo(f"    {change.ref} {change.field}: {change.was} -> {change.now}")

    @packs.command("validate")
    @click.argument("zip_path")
    def packs_validate(zip_path: str) -> None:
        """Validate a pack zip against every rule, without writing anything."""
        from .packs import schema
        from .packs.importing import _v12_images
        from .packs.validate import validate_pack, warn_pack
        from .packs.zip_reader import PackZipRefused, read_pack_zip

        with open(zip_path, "rb") as fh:
            try:
                bundle = read_pack_zip(fh)
            except PackZipRefused as refused:
                raise click.ClickException(str(refused)) from refused
        try:
            pack = schema.load_pack(bundle.pack)
        except Exception as exc:
            raise click.ClickException(f"pack.json: {exc}") from exc
        keys = {code: schema.load_answer_key(p) for code, p in bundle.keys.items()}
        problems = list(validate_pack(pack, keys or None)) + _v12_images(pack, bundle)
        if problems:
            for p in problems:
                click.echo(f"  [{p.rule}] {p.path}: {p.message}", err=True)
            raise click.ClickException(f"{len(problems)} problem(s).")

        # Warnings do not refuse the pack; the author decides (W1).
        warnings = list(warn_pack(pack))
        for w in warnings:
            click.echo(f"  [{w.rule}] {w.path}: {w.message}")
        click.echo("Valid." if not warnings else f"Valid, with {len(warnings)} warning(s).")

    def _assignment(pub: str):
        from .models import Assignment

        a = db.session.scalars(
            select(Assignment).where(Assignment.public_id == pub)
        ).one_or_none()
        if a is None:
            raise click.ClickException(f"No assignment {pub}.")
        return a

    grade = AppGroup("grade", help="Grading, without the web time limit.")

    @grade.command("assignment")
    @click.argument("assignment_pub")
    def grade_assignment(assignment_pub: str) -> None:
        """Grade every workspace of an assignment."""
        from .services.grades import grade_section

        graded, total, _ = grade_section(db.session, _assignment(assignment_pub), actor=None)
        db.session.commit()
        click.echo(f"Graded {len(graded)} of {total} workspace(s).")

    export = AppGroup("export", help="Exports.")

    @export.command("marks")
    @click.argument("assignment_pub")
    @click.option("--preset", type=click.Choice(["generic", "canvas"]), default="generic")
    @click.option("--out", type=click.Path(), default=None, help="Write to a file (else stdout).")
    def export_marks(assignment_pub: str, preset: str, out: str | None) -> None:
        """Export a marks CSV (generic or Canvas-style; both carry late_hours + status)."""
        from pathlib import Path

        from .services.marks_export import marks_csv

        text = marks_csv(db.session, _assignment(assignment_pub), preset)
        if out:
            Path(out).write_text(text)
            click.echo(f"Wrote {out}.")
        else:
            click.echo(text)

    seed = AppGroup("seed", help="Staging fixtures.")

    @seed.command("staging")
    @click.option("--students", type=int, default=5)
    def seed_staging(students: int) -> None:
        """Create a staging section with fake students (refused in production)."""
        from .models import Assignment, ContentPack, PackVersion, User
        from .services.assignments import create_assignment, create_section, join_with_code

        if app.extensions["originalentry_config"].IS_PRODUCTION:
            raise click.ClickException("Refusing to seed staging in production.")

        section = create_section(db.session, name="Staging section", term="Staging")
        made = []
        for i in range(1, students + 1):
            user = User(email=f"student{i}@staging.example.edu", role="student",
                        given_name=f"Student{i}", family_name="Staging")
            db.session.add(user)
            made.append(user)
        db.session.flush()

        newest = db.session.scalars(
            select(PackVersion, ContentPack)
            .join(ContentPack, PackVersion.content_pack_id == ContentPack.id)
            .order_by(PackVersion.id.desc()).limit(1)
        ).first()
        if newest is not None:
            create_assignment(db.session, section=section, title="Staging assignment",
                              pack_version=newest)
            for user in made:
                join_with_code(db.session, code=section.join_code, student=user)
            note = "with an assignment on the newest catalogue pack"
        else:
            existing = db.session.scalars(select(Assignment).limit(1)).first()  # noqa: F841
            note = "no pack in the catalogue yet — upload one, then students can join"
        db.session.commit()
        click.echo(f"Seeded '{section.name}' (join {section.join_code}), "
                   f"{len(made)} students, {note}.")

    @seed.command("demo")
    def seed_demo() -> None:
        """Put a company, a section, an instructor and a student in the database to click through.

        It builds Riverbend Supply Co. from ``packs/riverbend-demo/source.json`` through the real
        generator and the real importer, so what you click through is a pack the app would have
        accepted on upload — not a fixture wired in behind the validator's back.

        Safe to run twice, and it uses its own company slug so it never collides with the packs
        the tests import. Refused in production.
        """
        import hashlib
        import json
        from datetime import UTC, datetime, timedelta
        from pathlib import Path

        from .generator import GeneratorError, build
        from .models import ContentPack, PackVersion, Section, Workspace
        from .packs import schema
        from .packs.importer import import_answer_keys, import_content
        from .services.assignments import create_assignment, create_section, join_with_code

        if app.extensions["originalentry_config"].IS_PRODUCTION:
            raise click.ClickException("Refusing to seed demo data in production.")

        source_path = Path(app.root_path).parent / "packs" / "riverbend-demo" / "source.json"
        if not source_path.exists():
            raise click.ClickException(f"No authoring source at {source_path}.")

        def person(email: str, **fields) -> User:
            user = _find_user(email)
            if user is None:
                user = User(email=email, **fields)
                db.session.add(user)
                db.session.flush()
            return user

        instructor = person("instructor@demo.test", role=ROLE_INSTRUCTOR,
                            given_name="Dana", family_name="Okonjo")
        student = person("student@demo.test", role="student",
                         given_name="Sam", family_name="Rivera")

        source = json.loads(source_path.read_text())
        slug = source["company"]["slug"]
        existing = db.session.scalars(
            select(ContentPack).where(ContentPack.slug == slug)
        ).one_or_none()
        if existing is None:
            try:
                generated = build(source)  # paper pack: no Pillow needed
            except GeneratorError as bad:
                raise click.ClickException(str(bad)) from bad
            digest = hashlib.sha256(
                json.dumps(generated.pack, sort_keys=True).encode()
            ).hexdigest()
            version = import_content(db.session, schema.load_pack(generated.pack), digest)
            import_answer_keys(db.session, version, generated.keys)
            click.echo(f"Built and imported {slug} v{version.version}.")
        else:
            version = db.session.scalars(
                select(PackVersion).where(PackVersion.content_pack_id == existing.id)
                .order_by(PackVersion.version.desc())
            ).first()
            click.echo(f"{slug} is already in the catalogue.")

        name = "ACCT 1010 · demo"
        section = db.session.scalars(
            select(Section).where(Section.name == name)
        ).one_or_none()
        if section is None:
            section = create_section(db.session, name=name, term="Fall 2026", actor=instructor)
            create_assignment(
                db.session, section=section, title="December cycle", pack_version=version,
                mode="screen" if version.has_images else "paper",
                due_at=datetime.now(UTC) + timedelta(days=14), actor=instructor,
            )
        join_with_code(db.session, code=section.join_code, student=student)
        db.session.commit()

        workspace = db.session.scalars(
            select(Workspace).where(Workspace.student_id == student.id,
                                    Workspace.archived_at.is_(None))
        ).first()
        click.echo("")
        click.echo(f"  join code:   {section.join_code}")
        click.echo("  instructor:  instructor@demo.test")
        click.echo("  student:     student@demo.test")
        if workspace is not None:
            click.echo(f"  their books: /w/{workspace.public_id}/{slug}/")
        click.echo("  sign in with `flask auth issue-link <email>`.")

    purge = AppGroup("purge", help="Retention deletion (OPS-7).")

    @purge.command("section")
    @click.argument("section_id", type=int)
    @click.option("--confirm", is_flag=True, help="Required: this hard-deletes.")
    def purge_section_cmd(section_id: int, confirm: bool) -> None:
        """Hard-delete a section's work, grades, enrolments and orphaned students (OPS-7)."""
        from .models import Section
        from .services.purge import purge_section

        if not confirm:
            raise click.ClickException("Add --confirm to hard-delete this section's data.")
        section = db.session.get(Section, section_id)
        if section is None:
            raise click.ClickException(f"No section {section_id}.")
        summary = purge_section(db.session, section, actor=None)
        db.session.commit()
        click.echo(f"Purged section {section_id}: {summary.assignments} assignment(s), "
                   f"{summary.workspaces} workspace(s), {summary.students_removed} student(s).")

    @app.cli.command("replay-key")
    @click.option("--pack", "slug", required=True, help="Company slug.")
    @click.option("--variant", default=None, help="One variant code (else all).")
    def replay_key(slug: str, variant: str | None) -> None:
        """A2 against the live database: replay each key and confirm the balances to the cent."""
        from .ledger import balances
        from .models import AnswerKey, ContentPack, PackVersion, Variant
        from .packs import schema
        from .packs.replay import build_replay_snapshot

        cp = db.session.scalars(
            select(ContentPack).where(ContentPack.slug == slug)
        ).one_or_none()
        if cp is None:
            raise click.ClickException(f"No company {slug}.")
        pv = db.session.scalars(
            select(PackVersion).where(PackVersion.content_pack_id == cp.id)
            .order_by(PackVersion.version.desc()).limit(1)
        ).first()
        pack = schema.load_pack(pv.manifest)

        variant_code = {v.id: v.code for v in db.session.scalars(
            select(Variant).where(Variant.pack_version_id == pv.id))}
        keys = db.session.scalars(
            select(AnswerKey).where(AnswerKey.pack_version_id == pv.id)
        ).all()
        failures = 0
        for key_row in keys:
            code = variant_code.get(key_row.variant_id, "?")
            if variant and code != variant:
                continue
            key = schema.load_answer_key(key_row.payload)
            snapshot = build_replay_snapshot(pack, key)
            for stage, expected in key.expected_balances.items():
                actual = balances(snapshot, stage)
                for number, want in expected.items():
                    if actual.get(number, 0) != want:
                        failures += 1
                        click.echo(f"  {code}/{stage}/{number}: "
                                   f"{actual.get(number, 0)} != {want}", err=True)
            click.echo(f"  {slug} v{pv.version} variant {code}: replayed")
        if failures:
            raise click.ClickException(f"{failures} balance mismatch(es).")
        click.echo("A2 holds: every balance matches the key.")

    app.cli.add_command(staff)
    app.cli.add_command(auth)
    app.cli.add_command(packs)
    app.cli.add_command(grade)
    app.cli.add_command(export)
    app.cli.add_command(seed)
    app.cli.add_command(purge)
