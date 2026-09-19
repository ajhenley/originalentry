"""Student-facing screens: read-only ledger/trial-balance views (derived through the engine, T6)
and the write path — journalising, posting, subsidiary posting, reversal and voiding (T3.4, T6.4).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from .. import messages, money
from ..decorators import workspace_view
from ..extensions import db
from ..forms.entries import AccountInfo, EntryContext, parse_general_entry
from ..forms.statements import StatementContext, parse_statement
from ..grading.checkpoints import evaluate as evaluate_checkpoint
from ..ledger import STAGE_KINDS, balances, subsidiary_proof, trial_balance
from ..ledger.engine import TrialBalanceRow
from ..ledger.snapshot import load_snapshot
from ..models import (
    Account,
    Assignment,
    ContentPack,
    Enrollment,
    JournalEntry,
    PackAsset,
    PackVersion,
    Party,
    PostingRun,
    SourceDocument,
    Variant,
    Workspace,
)
from ..presentation import kind_label
from ..services import WriteRefused, multicompany, workspace_write
from ..services.activity import record_refused_save
from ..services.assignments import JoinRefused, join_with_code
from ..services.checkpoints import checkpoint_state, record_attempt
from ..services.dispositions import current_dispositions, set_disposition
from ..services.entries import record_entry, void_entry
from ..services.grades import final_marks
from ..services.posting import (
    active_posted_entry_ids,
    post_entry_subsidiary,
    post_journal_general,
    post_journal_subsidiary_all,
    reverse_run,
)
from ..services.record import workspace_record
from ..services.statements import (
    draft_rows,
    load_draft,
    own_figures,
    save_statement,
    statement_counts,
)
from ..services.submit import submit_workspace

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
    return render_template("student/home.html", workspaces=workspaces,
                           choices=_pending_company_choices())


def _pending_company_choices():
    """Open choice assignments the student is enrolled in but has not yet picked a company for."""
    now = datetime.now(UTC)
    chosen = {
        ws.assignment_id
        for ws in db.session.scalars(
            db.select(Workspace).where(
                Workspace.student_id == current_user.id, Workspace.archived_at.is_(None)
            )
        )
    }
    rows = db.session.execute(
        db.select(Assignment)
        .join(Enrollment, Enrollment.section_id == Assignment.section_id)
        .where(
            Enrollment.user_id == current_user.id,
            Assignment.company_policy == "choice",
            Assignment.archived_at.is_(None),
        )
        .order_by(Assignment.title)
    ).scalars()
    pending = []
    for asg in rows:
        if asg.id in chosen:
            continue
        if asg.opens_at is not None and asg.opens_at > now:
            continue
        pending.append({"public_id": asg.public_id, "title": asg.title})
    return pending


# ── Joining a section ────────────────────────────────────────────────────────────────────

@bp.get("/join")
@login_required
def join_form():
    return render_template("student/join.html")


@bp.post("/join", endpoint="join")
@login_required
def join_submit():
    try:
        workspaces = join_with_code(db.session, code=request.form.get("code"),
                                   student=current_user)
    except JoinRefused as refused:
        db.session.rollback()
        flash(refused.message)
        return render_template("student/join.html"), 422

    db.session.commit()
    if workspaces:
        flash("You are enrolled. Your books are ready.")
    else:
        flash("You are enrolled. Nothing has opened yet — check back when your instructor says.")
    return redirect(url_for("student.home"))


# ── Choosing a company (M2.3, tension 4) ─────────────────────────────────────────────────

def _choice_assignment_or_404(public_id: str) -> Assignment:
    assignment = db.session.scalars(
        db.select(Assignment).where(
            Assignment.public_id == public_id,
            Assignment.company_policy == "choice",
            Assignment.archived_at.is_(None),
        )
    ).one_or_none()
    if assignment is None:
        abort(404)
    # The student must be enrolled in the assignment's section to see it.
    enrolled = db.session.scalars(
        db.select(Enrollment).where(
            Enrollment.section_id == assignment.section_id,
            Enrollment.user_id == current_user.id,
        )
    ).one_or_none()
    if enrolled is None:
        abort(404)
    return assignment


def _company_of(pack_version_id: int) -> ContentPack:
    pv = db.session.get(PackVersion, pack_version_id)
    return db.session.get(ContentPack, pv.content_pack_id)


def _live_workspace(assignment_id: int):
    return db.session.scalars(
        db.select(Workspace).where(
            Workspace.assignment_id == assignment_id,
            Workspace.student_id == current_user.id,
            Workspace.archived_at.is_(None),
        )
    ).one_or_none()


@bp.get("/a/<assignment>/choose")
@login_required
def choose(assignment: str):
    found = _choice_assignment_or_404(assignment)
    existing = _live_workspace(found.id)
    if existing is not None:
        cp = _company_of(existing.pack_version_id)
        return redirect(url_for("student.overview", workspace=existing.public_id,
                                company_slug=cp.slug))
    options = multicompany.company_options(db.session, found)
    return render_template("student/choose.html", assignment=found, options=options)


@bp.post("/a/<assignment>/choose", endpoint="choose_submit")
@login_required
def choose_submit(assignment: str):
    found = _choice_assignment_or_404(assignment)
    try:
        pack_version_id = int(request.form.get("pack_version_id", ""))
    except ValueError:
        flash("Choose a company to continue.")
        return redirect(url_for("student.choose", assignment=assignment))
    try:
        workspace = multicompany.choose_company(
            db.session, found, current_user, pack_version_id=pack_version_id
        )
    except multicompany.ChoiceRefused as refused:
        db.session.rollback()
        flash(refused.message)
        return redirect(url_for("student.choose", assignment=assignment))
    db.session.commit()
    cp = _company_of(workspace.pack_version_id)
    flash("Your books are ready.")
    return redirect(url_for("student.overview", workspace=workspace.public_id,
                            company_slug=cp.slug))


@bp.get("/w/<workspace>/<company_slug>/")
@workspace_view
def overview():
    docs = _documents(g.pack_version.id)
    triaged = len(current_dispositions(db.session, g.workspace))
    return render_template("student/overview.html", triaged=triaged, total=len(docs))


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


@bp.get("/w/<workspace>/<company_slug>/print")
@workspace_view
def print_record():
    record = workspace_record(
        db.session, g.workspace, g.pack_version.manifest or {}, g.company.subsidiary_kinds
    )
    return render_template("print/workspace.html", record=record)


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


# ── Documents and dispositions (triage) ──────────────────────────────────────────────────

def _variant_code():
    variant = db.session.get(Variant, g.workspace.variant_id)
    return variant.code if variant else None


def _manifest_document(ref):
    for d in (g.pack_version.manifest or {}).get("documents", []):
        if d["ref"] == ref:
            return d
    return None


@bp.get("/w/<workspace>/<company_slug>/documents")
@workspace_view
def documents():
    docs = _documents(g.pack_version.id)
    current = current_dispositions(db.session, g.workspace)
    rows = []
    for d in docs:
        disp = current.get(d.id)
        rows.append({
            "ref": d.ref,
            "display_ref": d.display_ref,
            "doc_type": d.doc_type,
            "date": d.doc_date,
            "guided": d.guided,
            "status": disp.choice if disp else None,
            "reason": disp.reason if disp else None,
        })
    triaged = sum(1 for r in rows if r["status"])
    return render_template("student/documents.html", documents=rows,
                           triaged=triaged, total=len(rows))


@bp.get("/w/<workspace>/<company_slug>/documents/<ref>")
@workspace_view
def document(ref):
    doc = db.session.execute(
        db.select(SourceDocument).where(
            SourceDocument.pack_version_id == g.pack_version.id, SourceDocument.ref == ref
        )
    ).scalar_one_or_none()
    if doc is None:
        abort(404)
    manifest_doc = _manifest_document(ref) or {}
    variant_doc = (manifest_doc.get("variants") or {}).get(_variant_code(), {})
    text_alt = variant_doc.get("text_alternative") or {"fields": [], "lines": []}
    current = current_dispositions(db.session, g.workspace).get(doc.id)
    assignment = db.session.get(Assignment, g.workspace.assignment_id)
    screen_mode = assignment is not None and assignment.mode == "screen"
    return render_template(
        "student/document.html",
        doc=doc,
        guidance=doc.guidance if doc.guided else None,
        alt_text=variant_doc.get("alt"),
        text_alt=text_alt,
        # The image is shown only in screen mode, and only when the pack brought one (S2.1/S2.2).
        has_image=bool(screen_mode and variant_doc.get("image")),
        disposition=current,
        error=None,
    )


@bp.get("/w/<workspace>/<company_slug>/documents/<ref>/image")
@workspace_view
def document_image(ref):
    """The document itself. Inside the workspace, so it is never guessable from a URL (T11)."""
    assignment = db.session.get(Assignment, g.workspace.assignment_id)
    if assignment is None or assignment.mode != "screen":
        abort(404)

    manifest_doc = _manifest_document(ref) or {}
    path = ((manifest_doc.get("variants") or {}).get(_variant_code(), {}) or {}).get("image")
    if not path:
        abort(404)

    asset = db.session.execute(
        db.select(PackAsset).where(
            PackAsset.pack_version_id == g.pack_version.id, PackAsset.path == path
        )
    ).scalar_one_or_none()
    if asset is None:
        abort(404)

    response = make_response(asset.data)
    response.headers["Content-Type"] = asset.content_type
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.post("/w/<workspace>/<company_slug>/documents/<ref>/disposition")
@workspace_view
def disposition(ref):
    if not _guard_writable():
        return redirect(url_for("student.document", workspace=g.workspace.public_id,
                                company_slug=g.company.slug, ref=ref))
    choice = request.form.get("choice", "")
    reason = request.form.get("reason", "")
    try:
        workspace_write(
            db.session, g.workspace.public_id, current_user,
            activity_kind="disposition",
            mutate=lambda s, ws: set_disposition(s, ws, ref, choice, reason),
            detail={"document": ref, "choice": choice},
        )
        flash("Saved.")
    except WriteRefused as refused:
        flash(refused.message)
    return redirect(url_for("student.document", workspace=g.workspace.public_id,
                            company_slug=g.company.slug, ref=ref))


# ── Journalising and posting (write path) ────────────────────────────────────────────────

# ── The save protocol (T7.2, T7.4) ───────────────────────────────────────────────────────
# Every form here is an ordinary POST that works on its own. When save.js is running it adds one
# header, and the answer carries three more: where to go next, when the work was saved, and the
# workspace version, so a second tab can be told it has fallen behind.

SAVE_HEADER = "X-Parchment-Save"


def _is_save_request() -> bool:
    return bool(request.headers.get(SAVE_HEADER))


def _save_headers(response, redirect_to: str | None = None, submitted_version=None):
    workspace = getattr(g, "workspace", None)
    if workspace is not None:
        response.headers["X-Workspace-Version"] = str(workspace.version)
        try:
            if submitted_version is not None and int(submitted_version) < workspace.version - 1:
                # Someone else — another tab of theirs — has written since this form was drawn.
                response.headers["X-Workspace-Stale"] = "1"
        except (TypeError, ValueError):
            pass
    response.headers["X-Saved-At"] = datetime.now(UTC).isoformat(timespec="seconds")
    if redirect_to:
        response.headers["X-Redirect-To"] = redirect_to
    return response


def _saved(redirect_to: str, submitted_version=None):
    """Saved. Without the script this is a redirect; with it, the script does the navigating."""
    if not _is_save_request():
        return redirect(redirect_to)
    return _save_headers(make_response("", 200), redirect_to, submitted_version)


def _save_refused(redirect_to: str, message: str):
    """The books are closed or read-only: nothing to retry, so the script is told where to look."""
    flash(message)
    if not _is_save_request():
        return redirect(redirect_to)
    return _save_headers(make_response("", 423), redirect_to)


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
        # The key the browser retries on, and the version a second tab is measured against
        # (T7.4/T7.5). A retry with the same key is one entry, not two.
        values={"client_key": uuid4().hex, "workspace_version": g.workspace.version},
        line_range=range(1, 9),
    )


@bp.post("/w/<workspace>/<company_slug>/journals/<key>/entries/new")
@workspace_view
def entry_create(key):
    journal_cfg = _journal_or_404(key)
    journal_url = url_for("student.journal", workspace=g.workspace.public_id,
                          company_slug=g.company.slug, key=key)
    submitted_version = request.form.get("workspace_version")
    if g.read_only:
        return _save_refused(journal_url,
                             g.read_only_message or messages.READ_ONLY_SUBMITTED)
    result = parse_general_entry(request.form, _entry_context(key))
    if not result.ok:
        # What the student was stuck on, for the instructor's Progress screen (I2.5). The message
        # is the one the student saw; their figures are not recorded.
        record_refused_save(
            db.session, g.workspace,
            document_ref=(request.form.get("document_ref") or "").strip() or None,
            reason=result.errors[0][1],
        )
        db.session.commit()
        page = render_template(
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
        )
        return _save_headers(make_response(page, 422), submitted_version=submitted_version)
    command = result.command
    try:
        workspace_write(
            db.session, g.workspace.public_id, current_user,
            activity_kind="save",
            mutate=lambda s, ws: record_entry(s, ws, command),
            detail={"journal": key, "client_key": command.client_key},
        )
    except WriteRefused as refused:
        return _save_refused(journal_url, refused.message)

    flash("Entry recorded.")
    return _saved(journal_url, submitted_version)


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


# ── Checkpoints ──────────────────────────────────────────────────────────────────────────

def _manifest_checkpoints():
    return (g.pack_version.manifest or {}).get("checkpoints", [])


def _checkpoint_or_404(key):
    for c in _manifest_checkpoints():
        if c["key"] == key:
            return c
    abort(404)


@bp.get("/w/<workspace>/<company_slug>/checkpoints")
@workspace_view
def checkpoints():
    rows = []
    for c in _manifest_checkpoints():
        state = checkpoint_state(db.session, g.workspace, c["key"])
        rows.append({"key": c["key"], "ordinal": c.get("ordinal"), "prompt": c.get("prompt", ""),
                     "state": state})
    rows.sort(key=lambda r: r["ordinal"] or 0)
    return render_template("student/checkpoints.html", checkpoints=rows)


@bp.post("/w/<workspace>/<company_slug>/checkpoints/<key>")
@workspace_view
def checkpoint_submit(key):
    _checkpoint_or_404(key)
    redirect_to = redirect(url_for("student.checkpoints", workspace=g.workspace.public_id,
                                   company_slug=g.company.slug))
    if not _guard_writable():
        return redirect_to

    state = checkpoint_state(db.session, g.workspace, key)
    if state.passed:
        flash(messages.CHECKPOINT_PASSED)
        return redirect_to
    if state.locked:
        flash(messages.CHECKPOINT_LOCKED)
        return redirect_to

    try:
        submitted = money.parse_money(request.form.get("value"))
    except money.MoneyError as exc:
        flash(messages.money_error(exc.reason))
        return redirect_to

    # The pass/fail decision reads the key inside grading; only the boolean comes back (A8).
    passed = evaluate_checkpoint(db.session, g.workspace, key, submitted)
    try:
        workspace_write(
            db.session, g.workspace.public_id, current_user,
            activity_kind="checkpoint",
            mutate=lambda s, ws: record_attempt(s, ws, key, submitted, passed),
            detail={"checkpoint": key, "passed": passed},
        )
    except WriteRefused as refused:
        flash(refused.message)
        return redirect_to

    after = checkpoint_state(db.session, g.workspace, key)
    if passed:
        flash(messages.CHECKPOINT_PASSED)
    elif after.locked:
        flash(messages.CHECKPOINT_LOCKED)
    else:
        flash(messages.checkpoint_not_passed(after.remaining))
    return redirect_to


# ── Statements ───────────────────────────────────────────────────────────────────────────
# The app supplies the form, the account list and the student's own figures. What goes where,
# in what order, and every amount, is the student's decision (S5.5).

DEFAULT_BLANK_ROWS = 5
POST_CLOSING_TYPES = ("post_closing_trial_balance",)


def _manifest_statements():
    return (g.pack_version.manifest or {}).get("statements", [])


def _statement_or_404(statement_type):
    for s in _manifest_statements():
        if s["type"] == statement_type:
            return s
    abort(404)


def _statement_stage(statement_type):
    """The post-closing trial balance is built on post-closing figures; the rest on adjusted."""
    return "post_closing" if statement_type in POST_CLOSING_TYPES else "adjusted"


def _statement_context(statement):
    return StatementContext(
        statement_type=statement["type"],
        title=statement.get("title", statement["type"]),
        account_numbers={a.number for a in _accounts(g.pack_version.id)},
        subtotal_types={s["key"]: s["label"] for s in statement.get("subtotal_types", [])},
    )


def _rows_from_form(form, count):
    """Re-render what the student typed after a refusal, so nothing is retyped (S3.10)."""
    rows = []
    for i in range(count):
        rows.append({
            "kind": (form.get(f"row-{i}-kind") or "").strip(),
            "label": (form.get(f"row-{i}-label") or "").strip() or None,
            "account_number": (form.get(f"row-{i}-account") or "").strip() or None,
            "subtotal_type": (form.get(f"row-{i}-subtotal_type") or "").strip() or None,
            "amount": (form.get(f"row-{i}-amount") or "").strip(),
            "indent": int(form.get(f"row-{i}-indent") or 0),
            "amount_column": int(form.get(f"row-{i}-amount_column") or 1),
        })
    return rows


def _submitted_row_count(form):
    highest = -1
    for key in form:
        if key.startswith("row-"):
            try:
                highest = max(highest, int(key.split("-")[1]))
            except (ValueError, IndexError):
                continue
    return highest + 1


@bp.get("/w/<workspace>/<company_slug>/statements")
@workspace_view
def statements():
    counts = statement_counts(db.session, g.workspace)
    rows = [
        {"type": s["type"], "title": s.get("title", s["type"]),
         "row_count": counts.get(s["type"], 0)}
        for s in _manifest_statements()
    ]
    return render_template("student/statements.html", statements=rows)


@bp.get("/w/<workspace>/<company_slug>/statements/<statement_type>")
@workspace_view
def statement(statement_type):
    statement_def = _statement_or_404(statement_type)
    draft = load_draft(db.session, g.workspace, statement_type)
    try:
        blank_rows = max(0, min(50, int(request.args.get("rows", DEFAULT_BLANK_ROWS))))
    except ValueError:
        blank_rows = DEFAULT_BLANK_ROWS
    return render_template(
        "student/statement.html",
        statement=statement_def,
        rows=draft_rows(db.session, g.workspace, draft),
        accounts=_accounts(g.pack_version.id),
        figures=own_figures(db.session, g.workspace, _statement_stage(statement_type)),
        header=(draft.header if draft else {}),
        blank_rows=blank_rows,
        errors={},
    )


@bp.post("/w/<workspace>/<company_slug>/statements/<statement_type>", endpoint="statement_save")
@workspace_view
def statement_save(statement_type):
    statement_def = _statement_or_404(statement_type)
    back = redirect(url_for("student.statement", workspace=g.workspace.public_id,
                            company_slug=g.company.slug, statement_type=statement_type))
    if not _guard_writable():
        return back

    result = parse_statement(request.form, _statement_context(statement_def))
    if not result.ok:
        submitted = _submitted_row_count(request.form)
        return render_template(
            "student/statement.html",
            statement=statement_def,
            rows=_rows_from_form(request.form, submitted),
            accounts=_accounts(g.pack_version.id),
            figures=own_figures(db.session, g.workspace, _statement_stage(statement_type)),
            header={"title": (request.form.get("header-title") or "").strip(),
                    "period": (request.form.get("header-period") or "").strip()},
            blank_rows=0,
            errors=dict(result.errors),
        ), 422

    try:
        workspace_write(db.session, g.workspace.public_id, current_user,
                        activity_kind="statement",
                        mutate=lambda s, ws: save_statement(s, ws, result.command),
                        detail={"statement": statement_type})
    except WriteRefused as refused:
        flash(refused.message)
        return back

    flash(messages.STATEMENT_SAVED)
    if request.form.get("add_rows"):
        return redirect(url_for("student.statement", workspace=g.workspace.public_id,
                                company_slug=g.company.slug, statement_type=statement_type,
                                rows=DEFAULT_BLANK_ROWS))
    return back


# ── Marks ────────────────────────────────────────────────────────────────────────────────

@bp.get("/w/<workspace>/<company_slug>/marks")
@workspace_view
def marks():
    """Nothing is shown until the instructor releases the section's marks (S6.6, I3.6)."""
    assignment = db.session.get(Assignment, g.workspace.assignment_id)
    released = assignment is not None and assignment.marks_released_at is not None
    return render_template(
        "student/marks.html",
        marks=final_marks(db.session, g.workspace) if released else None,
    )


# ── Submission ───────────────────────────────────────────────────────────────────────────

@bp.get("/w/<workspace>/<company_slug>/submit")
@workspace_view
def submit():
    docs = _documents(g.pack_version.id)
    triaged = len(current_dispositions(db.session, g.workspace))
    entry_count = db.session.execute(
        db.select(db.func.count()).select_from(JournalEntry).where(
            JournalEntry.workspace_id == g.workspace.id, JournalEntry.voided_at.is_(None)
        )
    ).scalar_one()
    started = statement_counts(db.session, g.workspace)
    return render_template(
        "student/submit.html",
        triaged=triaged, total=len(docs), entry_count=entry_count,
        statements_started=len([t for t, n in started.items() if n]),
        statements_total=len(_manifest_statements()),
        submitted=(g.workspace.status == "submitted"),
    )


@bp.post("/w/<workspace>/<company_slug>/submit")
@workspace_view
def submit_confirm():
    if g.read_only:
        flash(g.read_only_message or messages.READ_ONLY_SUBMITTED)
        return redirect(url_for("student.overview", workspace=g.workspace.public_id,
                                company_slug=g.company.slug))
    try:
        workspace_write(db.session, g.workspace.public_id, current_user,
                        activity_kind="submit", mutate=lambda s, ws: submit_workspace(s, ws))
        flash("Your work has been submitted. These books are now read-only.")
    except WriteRefused as refused:
        flash(refused.message)
    return redirect(url_for("student.overview", workspace=g.workspace.public_id,
                            company_slug=g.company.slug))
