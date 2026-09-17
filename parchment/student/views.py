"""Student-facing screens. The read-only ledger and trial-balance views derive everything from
the engine (T6); the write path (journalising, posting) lands in phase 2.
"""

from __future__ import annotations

from flask import Blueprint, abort, g, render_template, request
from flask_login import current_user, login_required

from ..decorators import workspace_view
from ..extensions import db
from ..ledger import STAGE_KINDS, balances, subsidiary_proof, trial_balance
from ..ledger.engine import TrialBalanceRow
from ..ledger.snapshot import load_snapshot
from ..models import Assignment, ContentPack, PackVersion, Workspace
from ..presentation import kind_label

bp = Blueprint("student", __name__)

_STATUS_LABELS = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "submitted": "Submitted",
}

_STAGES = [
    {"key": "unadjusted", "label": "Unadjusted"},
    {"key": "adjusted", "label": "Adjusted"},
    {"key": "post_closing", "label": "Post-closing"},
]
_STAGE_LABEL = {s["key"]: s["label"] for s in _STAGES}


@bp.get("/")
@login_required
def home():
    rows = db.session.execute(
        db.select(Workspace, Assignment, ContentPack)
        .join(Assignment, Workspace.assignment_id == Assignment.id)
        .join(PackVersion, Workspace.pack_version_id == PackVersion.id)
        .join(ContentPack, PackVersion.content_pack_id == ContentPack.id)
        .where(Workspace.student_id == current_user.id, Workspace.archived_at.is_(None))
        .order_by(Assignment.title)
    ).all()
    workspaces = [
        {
            "public_id": ws.public_id,
            "company_name": cp.company_name,
            "company_slug": cp.slug,
            "assignment_title": asg.title,
            "status_label": _STATUS_LABELS.get(ws.status, ws.status),
        }
        for ws, asg, cp in rows
    ]
    return render_template("student/home.html", workspaces=workspaces)


@bp.get("/w/<workspace>/<company_slug>/")
@workspace_view
def overview():
    return render_template("student/overview.html")


@bp.get("/w/<workspace>/<company_slug>/trial-balance", endpoint="trial_balance")
@workspace_view
def trial_balance_view():
    stage = request.args.get("stage", "unadjusted")
    if stage not in STAGE_KINDS:
        stage = "unadjusted"
    snapshot = load_snapshot(db.session, g.workspace)
    tb = trial_balance(snapshot, stage)
    return render_template(
        "student/trial_balance.html",
        tb=tb,
        stage=stage,
        stage_label=_STAGE_LABEL[stage],
        stages=_STAGES,
    )


@bp.get("/w/<workspace>/<company_slug>/ledgers/general")
@workspace_view
def general_ledger():
    snapshot = load_snapshot(db.session, g.workspace)
    bals = balances(snapshot, "adjusted")
    rows = []
    for number, bal in bals.items():
        if bal == 0:
            continue
        account = snapshot.accounts.get(number)
        name = account.name if account else number
        sort = account.sort_order if account else 0
        rows.append(
            TrialBalanceRow(number, name, bal if bal > 0 else 0, -bal if bal < 0 else 0, sort)
        )
    rows.sort(key=lambda r: (r.sort_order, r.account_number))
    return render_template("student/ledger_general.html", rows=rows)


@bp.get("/w/<workspace>/<company_slug>/ledgers/<kind>")
@workspace_view
def subsidiary(kind):
    if kind not in g.company.subsidiary_kinds:
        abort(404)
    snapshot = load_snapshot(db.session, g.workspace)
    proof = subsidiary_proof(snapshot, kind)
    return render_template(
        "student/subsidiary.html",
        kind=kind,
        kind_label_value=kind_label(kind),
        proof=proof,
    )
