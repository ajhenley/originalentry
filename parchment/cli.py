"""Flask CLI commands (T13.2). The break-glass paths for when email is down, and staff creation.

    flask staff add <email> --role instructor|grader
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
from .models import ROLE_GRADER, ROLE_INSTRUCTOR, User


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
    @click.option("--role", type=click.Choice([ROLE_INSTRUCTOR, ROLE_GRADER]), required=True)
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
        user = _find_user(email)
        if user is None:
            raise click.ClickException(f"No account for {email}.")
        raw_token, code = tokens.issue_token(db.session, email, user_id=user.id)
        db.session.commit()
        base = app.extensions["parchment_config"].APP_BASE_URL.rstrip("/")
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
    def packs_migrate(assignment_pub: str, to_version: int, apply_it: bool) -> None:
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
                db.session, assignment, to_version, dry_run=not apply_it, actor=None
            )
        except MigrationRefused as refused:
            db.session.rollback()
            raise click.ClickException(refused.message) from refused

        click.echo(f"v{report.from_version} → v{report.to_version}: "
                   f"{report.workspaces} workspace(s), {report.entry_lines} line(s).")
        if not report.feasible:
            db.session.rollback()
            for label, missing in [("accounts", report.missing_accounts),
                                   ("parties", report.missing_parties),
                                   ("documents", report.missing_documents),
                                   ("variants", report.missing_variants)]:
                if missing:
                    click.echo(f"  missing {label}: {', '.join(missing)}", err=True)
            raise click.ClickException("Not feasible: some content students used is gone.")
        if report.applied:
            db.session.commit()
            click.echo("Migrated.")
        else:
            db.session.rollback()
            click.echo("Dry run only — re-run with --apply to migrate.")

    app.cli.add_command(staff)
    app.cli.add_command(auth)
    app.cli.add_command(packs)
