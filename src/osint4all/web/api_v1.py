"""API JSON do dossiê — o que o painel faz, o agente também pode fazer."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from osint4all.db.models import Entity, Evidence, Investigation, User
from osint4all.db.repository import graph_payload
from osint4all.engines.discovery import capability_registry, recent_queries
from osint4all.engines.intelligence import anomalies, communities, cross_case_hits, global_lookup, semantic_search, shortest_path, smart_alerts
from osint4all.engines.investigation import gap_analysis, hypothesis_board
from osint4all.engines.playbooks import TEMPLATES, list_items, progress
from osint4all.engines.verification import quality_score
from osint4all.quality.timeline import list_events
from osint4all.web.deps import current_user, db_session

api_router = APIRouter(prefix="/api/v1")


def _case(session: Session, case_id: str) -> Investigation | None:
    return session.get(Investigation, case_id)


@api_router.get("/cases")
def api_cases(user: User = Depends(current_user), session: Session = Depends(db_session)):
    rows = [
        inv
        for inv in session.scalars(select(Investigation).order_by(Investigation.created_at.desc()).limit(80)).all()
        if inv.status != "DELETED"
    ]
    return [
        {
            "id": inv.id,
            "title": inv.title,
            "status": inv.status,
            "workflow": inv.workflow,
            "playbook": inv.playbook_key,
            "assignee": inv.assignee,
        }
        for inv in rows
    ]


@api_router.get("/cases/{case_id}")
def api_case(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    inv = _case(session, case_id)
    if not inv or inv.status == "DELETED":
        return JSONResponse({"detail": "caso não encontrado"}, status_code=404)
    return {
        "id": inv.id,
        "title": inv.title,
        "hypothesis": inv.hypothesis,
        "purpose": inv.purpose,
        "workflow": inv.workflow,
        "playbook": inv.playbook_key,
        "quality": quality_score(session, inv),
        "gaps": gap_analysis(session, inv),
    }


@api_router.get("/cases/{case_id}/entities")
def api_entities(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    rows = session.scalars(select(Entity).where(Entity.investigation_id == case_id)).all()
    return [{"id": e.id, "name": e.display_name, "type": e.entity_type, "key": e.canonical_key} for e in rows]


@api_router.get("/cases/{case_id}/evidence")
def api_evidence(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    rows = session.scalars(select(Evidence).where(Evidence.investigation_id == case_id)).all()
    return [
        {"id": ev.id, "source": ev.source_label, "url": ev.url, "connector": ev.connector, "hash": ev.content_sha256}
        for ev in rows
    ]


@api_router.get("/cases/{case_id}/graph")
def api_graph(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    return graph_payload(session, case_id)


@api_router.get("/cases/{case_id}/timeline")
def api_timeline(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    return [
        {"type": ev.event_type, "title": ev.title, "when": ev.occurred_at.isoformat() if ev.occurred_at else None}
        for ev in list_events(session, case_id, limit=80)
    ]


@api_router.get("/cases/{case_id}/sources")
def api_case_sources(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    return [
        {"connector": q.connector, "empty": q.empty, "n": q.result_count, "version": q.connector_version}
        for q in recent_queries(session, case_id)
    ]


@api_router.get("/cases/{case_id}/quality")
def api_quality(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    inv = _case(session, case_id)
    if not inv:
        return JSONResponse({"detail": "caso não encontrado"}, status_code=404)
    return quality_score(session, inv)


@api_router.get("/cases/{case_id}/gaps")
def api_gaps(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    inv = _case(session, case_id)
    if not inv:
        return JSONResponse({"detail": "caso não encontrado"}, status_code=404)
    return gap_analysis(session, inv)


@api_router.get("/cases/{case_id}/hypotheses")
def api_hyps(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    return hypothesis_board(session, case_id)


@api_router.get("/cases/{case_id}/playbook")
def api_playbook(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    inv = _case(session, case_id)
    if not inv:
        return JSONResponse({"detail": "caso não encontrado"}, status_code=404)
    items = list_items(session, case_id, inv.playbook_key)
    return {"progress": progress(items), "items": [{"id": i.id, "title": i.title, "status": i.status} for i in items]}


@api_router.get("/cases/{case_id}/path")
def api_path(
    case_id: str,
    src: str = Query(""),
    dst: str = Query(""),
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    if not src or not dst:
        return JSONResponse({"detail": "informe src e dst"}, status_code=400)
    return shortest_path(session, case_id, src, dst)


@api_router.get("/cases/{case_id}/anomalies")
def api_anomalies(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    return anomalies(session, case_id)


@api_router.get("/cases/{case_id}/communities")
def api_communities(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    return communities(session, case_id)


@api_router.get("/cases/{case_id}/search")
def api_search(
    case_id: str,
    q: str = Query(""),
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    return semantic_search(session, case_id, q)


@api_router.get("/cases/{case_id}/cross")
def api_cross(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    return cross_case_hits(session, case_id)


@api_router.get("/cases/{case_id}/alerts")
def api_alerts(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    return smart_alerts(session, case_id)


@api_router.get("/cases/{case_id}/claims")
def api_claims_alias(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    from osint4all.db.models import Claim

    rows = session.scalars(select(Claim).where(Claim.investigation_id == case_id)).all()
    return [{"id": c.id, "text": c.text, "impact": c.impact, "status": c.status} for c in rows]


@api_router.get("/lookup")
def api_lookup(
    q: str = Query(""),
    user: User = Depends(current_user),
    session: Session = Depends(db_session),
):
    return global_lookup(session, q, user_id=user.id)


@api_router.get("/sources")
def api_sources(user: User = Depends(current_user)):
    return capability_registry()


@api_router.get("/playbooks")
def api_playbooks(user: User = Depends(current_user)):
    return {key: [{"key": k, "title": t} for k, t in steps] for key, steps in TEMPLATES.items()}


@api_router.get("/reports/{case_id}")
def api_report_meta(case_id: str, user: User = Depends(current_user), session: Session = Depends(db_session)):
    inv = _case(session, case_id)
    if not inv:
        return JSONResponse({"detail": "caso não encontrado"}, status_code=404)
    return {"html": f"/app/casos/{case_id}/relatorio", "pdf": f"/app/casos/{case_id}/relatorio.pdf", "quality": quality_score(session, inv)}
