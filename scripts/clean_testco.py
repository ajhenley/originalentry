#!/usr/bin/env python3
"""Dev-only: remove leftover ``testco*`` fixture data from the shared Neon dev database.

The DB integration tests seed fixed fixture slugs (testco-alpha, …) and roll back. If a run is
interrupted — or two runs execute against the same database at once — a committed fixture can be
left behind, and then every test that seeds that slug collides on the unique
``(content_pack_id, version)``. This deletes the whole graph for any ``testco%`` company so the
suite starts clean. Never run against production.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from parchment.app import create_app  # noqa: E402
from parchment.extensions import db  # noqa: E402


def clean() -> None:
    app = create_app()
    with app.app_context():
        if app.extensions["parchment_config"].IS_PRODUCTION:
            raise SystemExit("Refusing to run against production.")
        existing = set(
            db.session.execute(
                text("select table_name from information_schema.tables where table_schema='public'")
            ).scalars()
        )
        cps = db.session.execute(
            text("select id from content_pack where slug like 'testco%'")
        ).scalars().all()
        if not cps:
            print("No testco fixture data.")
            return
        pvs = db.session.execute(
            text("select id from pack_version where content_pack_id = any(:c)"), {"c": cps}
        ).scalars().all() or [0]
        ws = db.session.execute(
            text("select id from workspace where pack_version_id = any(:p)"), {"p": pvs}
        ).scalars().all() or [0]
        asg = db.session.execute(
            text("select distinct assignment_id from workspace where id = any(:w)"), {"w": ws}
        ).scalars().all() or [0]
        stu = db.session.execute(
            text("select distinct student_id from workspace where id = any(:w)"), {"w": ws}
        ).scalars().all() or [0]
        secs = db.session.execute(
            text("select distinct section_id from assignment where id = any(:a)"), {"a": asg}
        ).scalars().all() or [0]

        def run(sql, params):
            db.session.execute(text(sql), params)

        run("delete from entry_line where workspace_id = any(:w)", {"w": ws})
        run("delete from journal_entry_revision where entry_id in "
            "(select id from journal_entry where workspace_id = any(:w))", {"w": ws})
        if "posting_run_entry" in existing:
            run("delete from posting_run_entry where posting_run_id in "
                "(select id from posting_run where workspace_id = any(:w))", {"w": ws})
        for t in ("posting_run", "disposition", "checkpoint_attempt", "activity_event"):
            if t in existing:
                run(f"delete from {t} where workspace_id = any(:w)", {"w": ws})
        if "statement_line" in existing:
            run("delete from statement_line where draft_id in "
                "(select id from statement_draft where workspace_id = any(:w))", {"w": ws})
            run("delete from statement_draft where workspace_id = any(:w)", {"w": ws})
        for t in ("grade_override", "grade_comment", "grade_run"):
            if t in existing:
                run(f"delete from {t} where workspace_id = any(:w)", {"w": ws})
        run("delete from journal_entry where workspace_id = any(:w)", {"w": ws})
        if "staff_action" in existing:
            run("delete from staff_action where target_table='workspace' and target_id = any(:w)",
                {"w": ws})
        run("delete from workspace where id = any(:w)", {"w": ws})
        for t in ("assignment_choice", "assignment_checkpoint", "assignment_override"):
            if t in existing:
                run(f"delete from {t} where assignment_id = any(:a)", {"a": asg})
        run("delete from assignment where id = any(:a)", {"a": asg})
        run("delete from account_opening_balance where variant_id in "
            "(select id from variant where pack_version_id = any(:p))", {"p": pvs})
        run("delete from party_opening_balance where variant_id in "
            "(select id from variant where pack_version_id = any(:p))", {"p": pvs})
        for t in ("answer_key", "pack_asset", "source_document", "account", "party", "variant"):
            if t in existing:
                run(f"delete from {t} where pack_version_id = any(:p)", {"p": pvs})
        if "section_pack_availability" in existing:
            run("delete from section_pack_availability where content_pack_id = any(:c)", {"c": cps})
        if "staff_action" in existing:
            run("delete from staff_action where target_table='pack_version' and target_id = any(:p)",
                {"p": pvs})
        run("delete from pack_version where id = any(:p)", {"p": pvs})
        run("delete from content_pack where id = any(:c)", {"c": cps})
        if "login_token" in existing:
            run("delete from login_token where user_id = any(:s)", {"s": stu})
            # A join token that was never verified has user_id NULL but references the section.
            run("delete from login_token where join_section_id = any(:sec)", {"sec": secs})
        run("delete from enrollment where user_id = any(:s)", {"s": stu})
        run("delete from enrollment where section_id = any(:sec)", {"sec": secs})
        run("delete from section where id = any(:sec)", {"sec": secs})
        run('delete from "user" where id = any(:s)', {"s": stu})
        db.session.commit()
        print(f"Cleaned testco fixtures: packs={cps} versions={pvs} workspaces={ws}")


if __name__ == "__main__":
    clean()
