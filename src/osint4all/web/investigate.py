"""Rotas HTML da segunda geração: playbook, hipóteses, planner, caminho."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from osint4all.db.models import CaseComment, CaseSnapshot, Claim, Entity, Evidence, Hypothesis, Investigation, ResearchPlan, User
from osint4all.engines.discovery import recent_queries
from osint4all.engines.intelligence import (
    anomalies,
    communities,
    cross_case_hits,
    semantic_search,
    shortest_path,
    smart_alerts,
)
from osint4all.engines.investigation import (
    add_claim,
    add_comment,
    add_hypothesis,
    approve_claim,
    build_plan,
    diff_snapshots,
    ensure_primary_hypothesis,
    gap_analysis,
    hypothesis_board,
    save_plan,
    set_stance,
    suggest_alternatives,
    take_snapshot,
)
from osint4all.engines.knowledge import extract_events
from osint4all.engines.playbooks import TEMPLATES, add_custom_step, attach_playbook, list_items, progress, set_item_status
from osint4all.engines.verification import cluster_sources, quality_score
from osint4all.paths import project_root
from osint4all.web.auth import write_audit
from osint4all.web.deps import current_user, db_session, require_csrf, template_context

templates = Jinja2Templates(directory=str(project_root() / "templates"))
investigate_router = APIRouter()


def _flash(request: Request, level: str, message: str) -> None:
    request.session["flash"] = {"level": level, "message": message}


def _ctx(request: Request, user: User, session: Session, inv: Investigation) -> dict:
    entities = list(session.scalars(select(Entity).where(Entity.investigation_id == inv.id).order_by(Entity.display_name)).all())
    evidence = list(session.scalars(select(Evidence).where(Evidence.investigation_id == inv.id)).all())
    items = list_items(session, inv.id, inv.playbook_key)
    ensure_primary_hypothesis(session, inv)
    snapshots = list(session.scalars(select(CaseSnapshot).where(CaseSnapshot.investigation_id == inv.id)).all())
    claims = list(session.scalars(select(Claim).where(Claim.investigation_id == inv.id).options(selectinload(Claim.approvals))).all())
    hyps = list(session.scalars(select(Hypothesis).where(Hypothesis.investigation_id == inv.id).options(selectinload(Hypothesis.stances))).all())
    comments = list(session.scalars(select(CaseComment).where(CaseComment.investigation_id == inv.id).order_by(CaseComment.created_at.desc())).all())
    latest_plan = session.scalars(select(ResearchPlan).where(ResearchPlan.investigation_id == inv.id).order_by(ResearchPlan.created_at.desc())).first()
    ctx = template_context(request, user)
    ctx.update(
        {
            "nav": "casos",
            "inv": inv,
            "entities": entities,
            "evidence": evidence,
            "playbook_items": items,
            "playbook_progress": progress(items),
            "playbooks": TEMPLATES,
            "hypotheses": hypothesis_board(session, inv.id),
            "gaps": gap_analysis(session, inv),
            "quality": quality_score(session, inv),
            "clusters": cluster_sources(evidence),
            "anomalies": anomalies(session, inv.id),
            "communities": communities(session, inv.id),
            "cross_hits": cross_case_hits(session, inv.id),
            "alerts": smart_alerts(session, inv.id),
            "queries": recent_queries(session, inv.id),
            "events": extract_events(entities, evidence),
            "alternatives": suggest_alternatives(inv.hypothesis or inv.title),
            "snapshots": snapshots,
            "claims": claims,
            "hyp_rows": hyps,
            "comments": comments,
            "plan_steps": (latest_plan.steps if latest_plan and latest_plan.steps else build_plan(inv.hypothesis or inv.title)),
            "plan_question": latest_plan.question if latest_plan else (inv.hypothesis or inv.title),
        }
    )
    return ctx


@investigate_router.get("/app/casos/{investigation_id}/investigar", response_class=HTMLResponse)
def investigate_page(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    inv = session.get(Investigation, investigation_id)
    if not inv:
        _flash(request, "error", "Investigação não encontrada.")
        return RedirectResponse("/app/casos", status_code=303)
    if not list_items(session, inv.id, inv.playbook_key):
        attach_playbook(session, inv)
        session.flush()
    return templates.TemplateResponse(request, "app/investigate.html", _ctx(request, user, session, inv))


@investigate_router.post("/app/casos/{investigation_id}/playbook")
def set_playbook(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    playbook_key: str = Form("PERSON"),
):
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv:
        attach_playbook(session, inv, playbook_key)
        write_audit(session, "playbook.set", username=user.username, investigation_id=inv.id, details={"key": playbook_key})
        session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/playbook/{item_id}")
def playbook_item(
    investigation_id: str,
    item_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    status: str = Form("done"),
    note: str = Form(""),
):
    require_csrf(request, csrf_token)
    set_item_status(session, investigation_id, item_id, status, note)
    session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/playbook-passo")
def playbook_custom(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    title: str = Form(""),
):
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv and title.strip():
        add_custom_step(session, inv, title)
        session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/hipoteses")
def new_hypothesis(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    title: str = Form(""),
    kind: str = Form("primary"),
):
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv and title.strip():
        add_hypothesis(session, inv, title=title, kind=kind, created_by=user.username)
        session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/hipoteses/{hyp_id}/evidencia")
def stance_evidence(
    investigation_id: str,
    hyp_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    evidence_id: str = Form(""),
    stance: str = Form("inconclusive"),
):
    require_csrf(request, csrf_token)
    hyp = session.get(Hypothesis, hyp_id)
    ev = session.get(Evidence, evidence_id)
    if hyp and ev and hyp.investigation_id == investigation_id:
        set_stance(session, hyp, ev, stance=stance)
        session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/plano")
def make_plan(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    question: str = Form(""),
):
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv:
        save_plan(session, inv, question or inv.hypothesis or inv.title, user.username)
        _flash(request, "ok", "Plano de pesquisa gravado. Cada etapa fica no histórico do caso.")
        session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/claims")
def new_claim(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    text: str = Form(""),
    impact: str = Form("medium"),
):
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv and text.strip():
        add_claim(session, inv, text=text, impact=impact, created_by=user.username)
        session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/claims/{claim_id}/aprovar")
def claim_approve(
    investigation_id: str,
    claim_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
):
    require_csrf(request, csrf_token)
    claim = session.get(Claim, claim_id)
    if claim and claim.investigation_id == investigation_id:
        role = "reviewer" if user.role == "admin" else "analyst"
        approve_claim(session, claim, username=user.username, role=role)
        session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/comentarios")
def new_comment(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    body: str = Form(""),
):
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv and body.strip():
        add_comment(session, inv, body, user.username)
        session.commit()
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.post("/app/casos/{investigation_id}/snapshot")
def snapshot_now(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
    csrf_token: str = Form(""),
    label: str = Form(""),
):
    require_csrf(request, csrf_token)
    inv = session.get(Investigation, investigation_id)
    if inv:
        take_snapshot(session, inv, label or "agora")
        session.commit()
        _flash(request, "ok", "Snapshot do dossiê gravado.")
    return RedirectResponse(f"/app/casos/{investigation_id}/investigar", status_code=303)


@investigate_router.get("/app/casos/{investigation_id}/diff", response_class=HTMLResponse)
def snapshot_diff(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return RedirectResponse("/app/casos", status_code=303)
    rows = list(session.scalars(select(CaseSnapshot).where(CaseSnapshot.investigation_id == inv.id).order_by(CaseSnapshot.created_at)).all())
    lines = diff_snapshots(rows[-2], rows[-1]) if len(rows) >= 2 else ["Grave dois snapshots para comparar."]
    ctx = _ctx(request, user, session, inv)
    ctx["diff_lines"] = lines
    return templates.TemplateResponse(request, "app/investigate.html", ctx)


@investigate_router.get("/app/casos/{investigation_id}/caminho", response_class=HTMLResponse)
def path_page(
    investigation_id: str,
    request: Request,
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    inv = session.get(Investigation, investigation_id)
    if not inv:
        return RedirectResponse("/app/casos", status_code=303)
    src = request.query_params.get("from") or ""
    dst = request.query_params.get("to") or ""
    ctx = _ctx(request, user, session, inv)
    ctx["path"] = shortest_path(session, inv.id, src, dst) if src and dst else None
    ctx["search_hits"] = semantic_search(session, inv.id, request.query_params.get("q") or "")
    return templates.TemplateResponse(request, "app/investigate.html", ctx)
