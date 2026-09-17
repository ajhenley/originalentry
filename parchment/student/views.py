"""Student-facing screens: read-only ledger/trial-balance views (derived through the engine, T6)
and the write path — journalising, posting, subsidiary posting, reversal and voiding (T3.4, T6.4).
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from ..decorators import workspace_view
from ..extensions import db
from ..forms.entries import AccountInfo, EntryContext, parse_general_entry
from ..ledger import STAGE_KINDS, balances, subsidiary_proof, trial_balance
from ..ledger.engine import TrialBalanceRow
from ..ledger.snapshot import load_snapshot
from ..models import (
    Account,
    Assignment,
    ContentPack,
    JournalEntry,
    PackVersion,
    Party,
    PostingRun,
    SourceDocument,
    Workspace,
)
from ..presentation import kind_label
from ..services import WriteRefused, workspace_write
from ..services.entries import record_entry, void_entry
from ..services.posting import (
    active_posted_entry_ids,
    post_entry_subsidiary,
    post_journal_general,
    post_journal_subsidiary_all,
    reverse_run,
)

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


# ── Journalising and posting (write path) ────────────────────────────────────────────────

def _journals(manifest):
    return manifest.get("journals", [])


def _journal_or_404(key):
    for j in _journals(g.pack_version.manifest or {}):
        if j["key"] == key:
            return j
    abort(404)


def _period_label(pv):
    start, end = pv.period_start, pv.period_end
    if start.month == end.month:
        return f"{start.strftime('%B')} {start.day}–{end.day}"
    return f"{start.strftime('%B %-d')} – {end.strftime('%B %-d')}"


def _accounts(pv_id):
    return list(
        db.session.scalars(
            db.select(Account).where(Account.pack_version_id == pv_id).order_by(Account.sort_order)
        )
    )


def _parties(pv_id):
    return list(
        db.session.scalars(
            db.select(Party).where(Party.pack_version_id == pv_id).order_by(Party.code)
        )
    )


def _documents(pv_id):
    return list(
        db.session.scalars(
            db.select(SourceDocument)
            .where(SourceDocument.pack_version_id == pv_id)
            .order_by(SourceDocument.received_seq)
        )
    )


def _entry_context(journal_key):
    pv = g.pack_version
    accounts = _accounts(pv.id)
    return EntryContext(
        journal_key=journal_key,
        accounts={a.number: AccountInfo(a.number, a.subsidiary_kind) for a in accounts},
        party_codes={p.code for p in _parties(pv.id)},
        period_start=pv.period_start,
        period_end=pv.period_end,
        period_label=_period_label(pv),
        document_refs={d.ref for d in _documents(pv.id)},
    )


def _guard_writable():
    if g.read_only:
        flash(g.read_only_message or "These books are read-only. Your work is saved.")
        return False
    return True


@bp.get("/w/<workspace>/<company_slug>/journals")
@workspace_view
def journals():
    manifest = g.pack_version.manifest or {}
    posted_general = active_posted_entry_ids(db.session, g.workspace, "general")
    rows = []
    for j in _journals(manifest):
        entries = list(
            db.session.scalars(
                db.select(JournalEntry).where(
                    JournalEntry.workspace_id == g.workspace.id,
                    JournalEntry.journal_key == j["key"],
                    JournalEntry.voided_at.is_(None),
                )
            )
        )
        unposted = sum(1 for e in entries if e.id not in posted_general)
        rows.append({"key": j["key"], "name": j["name"], "kind": j["kind"],
                     "count": len(entries), "unposted": unposted})
    return render_template("student/journals.html", journals=rows)


@bp.get("/w/<workspace>/<company_slug>/journals/<key>")
@workspace_view
def journal(key):
    journal_cfg = _journal_or_404(key)
    posted_general = active_posted_entry_ids(db.session, g.workspace, "general")
    posted_sub = active_posted_entry_ids(db.session, g.workspace, "subsidiary")
    account_name = {a.id: f"{a.number} {a.name}" for a in _accounts(g.pack_version.id)}
    party_name = {p.id: p.name for p in _parties(g.pack_version.id)}
    entries = list(
        db.session.scalars(
            db.select(JournalEntry)
            .where(JournalEntry.workspace_id == g.workspace.id, JournalEntry.journal_key == key)
            .order_by(JournalEntry.seq)
        )
    )
    rows = []
    for e in entries:
        lines = [
            {
                "account": account_name.get(line.account_id, ""),
                "party": party_name.get(line.party_id) if line.party_id else None,
                "debit_cents": line.debit_cents,
                "credit_cents": line.credit_cents,
            }
            for line in sorted(e.lines, key=lambda x: x.line_no)
        ]
        rows.append({
            "public_id": e.public_id,
            "seq": e.seq,
            "date": e.entry_date,
            "kind": e.kind,
            "voided": e.voided_at is not None,
            "posted_general": e.id in posted_general,
            "posted_subsidiary": e.id in posted_sub,
            "has_party": any(line.party_id for line in e.lines),
            "lines": lines,
        })
    runs = list(
        db.session.scalars(
            db.select(PostingRun)
            .where(PostingRun.workspace_id == g.workspace.id, PostingRun.journal_key == key,
                   PostingRun.reversed_at.is_(None))
            .order_by(PostingRun.target, PostingRun.ordinal)
        )
    )
    return render_template("student/journal.html", journal=journal_cfg, entries=rows, runs=runs)


@bp.get("/w/<workspace>/<company_slug>/journals/<key>/entries/new")
@workspace_view
def entry_new(key):
    journal_cfg = _journal_or_404(key)
    return render_template(
        "student/entry_form.html",
        journal=journal_cfg,
        accounts=_accounts(g.pack_version.id),
        parties=_parties(g.pack_version.id),
        documents=_documents(g.pack_version.id),
        period=_entry_context(key),
        errors={},
        values={},
        line_range=range(1, 9),
    )


@bp.post("/w/<workspace>/<company_slug>/journals/<key>/entries/new")
@workspace_view
def entry_create(key):
    journal_cfg = _journal_or_404(key)
    if not _guard_writable():
        return redirect(url_for("student.journal", workspace=g.workspace.public_id,
                                company_slug=g.company.slug, key=key))
    result = parse_general_entry(request.form, _entry_context(key))
    if not result.ok:
        return render_template(
            "student/entry_form.html",
            journal=journal_cfg,
            accounts=_accounts(g.pack_version.id),
            parties=_parties(g.pack_version.id),
            documents=_documents(g.pack_version.id),
            period=_entry_context(key),
            errors={f: m for f, m in result.errors},
            error_list=[m for _, m in result.errors],
            values=request.form,
            line_range=range(1, 9),
        ), 422
    command = result.command
    try:
        workspace_write(
            db.session, g.workspace.public_id, current_user,
            activity_kind="save",
            mutate=lambda s, ws: record_entry(s, ws, command),
            detail={"journal": key, "client_key": command.client_key},
        )
        flash("Entry recorded.")
    except WriteRefused as refused:
        flash(refused.message)
    return redirect(url_for("student.journal", workspace=g.workspace.public_id,
                            company_slug=g.company.slug, key=key))


def _write_and_flash(activity_kind, mutate, ok_message, redirect_key=None):
    try:
        workspace_write(db.session, g.workspace.public_id, current_user,
                        activity_kind=activity_kind, mutate=mutate)
        flash(ok_message)
    except WriteRefused as refused:
        flash(refused.message)


@bp.post("/w/<workspace>/<company_slug>/journals/<key>/post")
@workspace_view
def post_general(key):
    _journal_or_404(key)
    if _guard_writable():
        _write_and_flash("post", lambda s, ws: post_journal_general(s, ws, key),
                         "Journal posted to the general ledger.")
    return redirect(url_for("student.journal", workspace=g.workspace.public_id,
                            company_slug=g.company.slug, key=key))


@bp.post("/w/<workspace>/<company_slug>/journals/<key>/post-subsidiary")
@workspace_view
def post_subsidiary_all(key):
    _journal_or_404(key)
    if _guard_writable():
        _write_and_flash("post", lambda s, ws: post_journal_subsidiary_all(s, ws, key),
                         "Posted to the subsidiary ledgers.")
    return redirect(url_for("student.journal", workspace=g.workspace.public_id,
                            company_slug=g.company.slug, key=key))


@bp.post("/w/<workspace>/<company_slug>/entries/<entry_id>/post-subsidiary")
@workspace_view
def post_entry_sub(entry_id):
    key = request.form.get("journal_key", "")
    if _guard_writable():
        _write_and_flash("post", lambda s, ws: post_entry_subsidiary(s, ws, entry_id),
                         "Entry posted to the subsidiary ledger.")
    return redirect(url_for("student.journal", workspace=g.workspace.public_id,
                            company_slug=g.company.slug, key=key))


@bp.post("/w/<workspace>/<company_slug>/entries/<entry_id>/void")
@workspace_view
def entry_void(entry_id):
    key = request.form.get("journal_key", "")
    reason = (request.form.get("reason") or "").strip() or "Voided by the student."
    if _guard_writable():
        _write_and_flash("save", lambda s, ws: void_entry(s, ws, entry_id, reason),
                         "Entry voided. Nothing was destroyed.")
    return redirect(url_for("student.journal", workspace=g.workspace.public_id,
                            company_slug=g.company.slug, key=key))


@bp.post("/w/<workspace>/<company_slug>/postings/<run_id>/reverse")
@workspace_view
def posting_reverse(run_id):
    key = request.form.get("journal_key", "")
    reason = (request.form.get("reason") or "").strip() or "Reversed by the student."
    if _guard_writable():
        _write_and_flash("reverse", lambda s, ws: reverse_run(s, ws, run_id, reason),
                         "Posting reversed. The entries are unposted again.")
    return redirect(url_for("student.journal", workspace=g.workspace.public_id,
                            company_slug=g.company.slug, key=key))
