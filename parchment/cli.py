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

    app.cli.add_command(staff)
    app.cli.add_command(auth)
