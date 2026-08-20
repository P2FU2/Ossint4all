"""Investigation engine: hipóteses, gaps, planner, claims, comentários, snapshots."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from osint4all.db.models import (
    CaseComment,
    CaseSnapshot,
    Claim,
    ClaimApproval,
    Edge,
    Entity,
    Evidence,
    Hypothesis,
    HypothesisStance,
    Investigation,
    ResearchPlan,
)
from osint4all.graph.identity import entity_status, has_expandable_anchor
from osint4all.quality.verification import verdict_label


def add_hypothesis(
    session: Session,
    investigation: Investigation,
    *,
    title: str,
    body: str = "",
    kind: str = "primary",
    created_by: str | None = None,
) -> Hypothesis:
    row = Hypothesis(
        investigation_id=investigation.id,
        title=(title or "Hipótese").strip()[:255],
        body=(body or "").strip()[:4000],
        kind="alternative" if kind == "alternative" else "primary",
        created_by=created_by,
    )
    session.add(row)
    session.flush()
    return row


def ensure_primary_hypothesis(session: Session, investigation: Investigation) -> Hypothesis | None:
    existing = session.scalar(
        select(Hypothesis).where(Hypothesis.investigation_id == investigation.id, Hypothesis.kind == "primary")
    )
    if existing:
        return existing
    text = (investigation.hypothesis or "").strip()
    if not text:
        return None
    return add_hypothesis(session, investigation, title=text[:255], body=text, kind="primary")


def list_hypotheses(session: Session, investigation_id: str) -> list[Hypothesis]:
    return list(session.scalars(select(Hypothesis).where(Hypothesis.investigation_id == investigation_id)).all())


def set_stance(
    session: Session,
    hypothesis: Hypothesis,
    evidence: Evidence,
    *,
    stance: str,
    note: str = "",
) -> HypothesisStance:
    label = stance if stance in {"for", "against", "inconclusive"} else "inconclusive"
    row = session.scalar(
        select(HypothesisStance).where(
            HypothesisStance.hypothesis_id == hypothesis.id, HypothesisStance.evidence_id == evidence.id
        )
    )
    if row:
        row.stance = label
        row.note = (note or "")[:400]
        return row
    row = HypothesisStance(hypothesis_id=hypothesis.id, evidence_id=evidence.id, stance=label, note=(note or "")[:400])
    session.add(row)
    return row


def hypothesis_board(session: Session, investigation_id: str) -> list[dict[str, Any]]:
    hyps = list_hypotheses(session, investigation_id)
    ev_ids = {st.evidence_id for hyp in hyps for st in hyp.stances}
    evidence = {
        ev.id: ev
        for ev in session.scalars(select(Evidence).where(Evidence.id.in_(ev_ids))).all()
    } if ev_ids else {}
    out = []
    for hyp in hyps:
        buckets: dict[str, list[dict[str, str]]] = {"for": [], "against": [], "inconclusive": []}
        for st in hyp.stances:
            ev = evidence.get(st.evidence_id)
            buckets.setdefault(st.stance, []).append(
                {
                    "evidence_id": st.evidence_id,
                    "label": ev.source_label if ev else st.evidence_id[:8],
                    "snippet": (ev.snippet if ev else "") or "",
                    "note": st.note,
                }
            )
        out.append(
            {
                "id": hyp.id,
                "title": hyp.title,
                "body": hyp.body,
                "kind": hyp.kind,
                "status": hyp.status,
                "for": buckets["for"],
                "against": buckets["against"],
                "inconclusive": buckets["inconclusive"],
            }
        )
    return out


def suggest_alternatives(title: str) -> list[str]:
    text = (title or "esta relação").strip()
    return [
        f"A relação em «{text}» é coincidência de nome (homônimo).",
        f"A ligação existe, mas por motivo lícito e público diferente do suspeito.",
        f"As menções copiam a mesma matéria original e não são fontes independentes.",
    ]


def gap_analysis(session: Session, investigation: Investigation) -> list[dict[str, str]]:
    entities = list(session.scalars(select(Entity).where(Entity.investigation_id == investigation.id)).all())
    edges = list(session.scalars(select(Edge).where(Edge.investigation_id == investigation.id)).all())
    evidence = list(session.scalars(select(Evidence).where(Evidence.investigation_id == investigation.id)).all())
    gaps: list[dict[str, str]] = []
    orgs = [e for e in entities if e.entity_type == "ORG"]
    people = [e for e in entities if e.entity_type == "PERSON"]
    qsa = [edge for edge in edges if edge.rel_type in {"SOCIO", "ADMIN"}]
    if people and not any(has_expandable_anchor(p) for p in people):
        gaps.append(
            {
                "code": "identity",
                "title": "Falta identificador forte de pessoa",
                "detail": "Há pessoa no grafo só com nome. Sem CPF/e-mail/telefone público a identidade continua candidata.",
            }
        )
    if orgs and not qsa:
        gaps.append(
            {
                "code": "qsa",
                "title": "Há empresa, mas falta quadro societário primário",
                "detail": "Vínculo empresarial provável sem sócio/administrador ligado. Falta QSA da Receita.",
            }
        )
    probable_people = [p for p in people if entity_status(p) == "probable"]
    if probable_people and not qsa:
        gaps.append(
            {
                "code": "probable_link",
                "title": "Há vínculo empresarial provável, mas falta documento societário primário",
                "detail": f"{probable_people[0].display_name} está como provável sem aresta SOCIO/ADMIN.",
            }
        )
    if orgs and not any((o.attrs or {}).get("endereco") for o in orgs):
        gaps.append(
            {
                "code": "address",
                "title": "Falta endereço publicado",
                "detail": "Empresa sem endereço no QSA — o mapa e a coincidência geográfica ficam cegos.",
            }
        )
    if not any(ev.connector in {"transparencia", "diario_oficial"} for ev in evidence) and orgs:
        gaps.append(
            {
                "code": "contracts",
                "title": "Sem contratos ou diário oficial",
                "detail": "Ainda não há evidência de pagamento público ou publicação oficial.",
            }
        )
    if not any(ev.connector in {"datajud", "djen"} for ev in evidence):
        gaps.append(
            {
                "code": "cases",
                "title": "Sem processos públicos",
                "detail": "DataJud/DJEN ainda não devolveram capa. «Não encontrado» não é «não existe».",
            }
        )
    hyps = list_hypotheses(session, investigation.id)
    if investigation.hypothesis and (not hyps or not any(hyp.stances for hyp in hyps)):
        gaps.append(
            {
                "code": "hypothesis",
                "title": "Hipótese do caso ainda não foi operacionalizada",
                "detail": "Existe texto de hipótese, mas nenhuma evidência foi marcada a favor ou contra.",
            }
        )
    return gaps


def build_plan(question: str) -> list[dict[str, str]]:
    q = (question or "").strip() or "Qual a relação entre as entidades do caso?"
    return [
        {"key": "question", "title": "Questão central", "body": q},
        {"key": "hypotheses", "title": "Hipóteses", "body": " ; ".join(suggest_alternatives(q))},
        {"key": "need", "title": "Informações necessárias", "body": "Identidade, QSA, endereços, contratos, processos, menções públicas."},
        {"key": "sources", "title": "Fontes apropriadas", "body": "Receita/QSA, Transparência, DataJud, diário oficial, Wikidata, menção web."},
        {"key": "collect", "title": "Coleta", "body": "Explodir QSA → Processar fila → anexar documentos → registrar negativos."},
        {"key": "verify", "title": "Verificação", "body": "Marcar veredito, independência de fonte e decay. Claims de alto impacto pedem dois pareceres."},
        {"key": "conclude", "title": "Conclusão", "body": "Só o que as evidências numeradas sustentam. Lacunas ficam explícitas."},
    ]


def save_plan(session: Session, investigation: Investigation, question: str, created_by: str | None) -> ResearchPlan:
    row = ResearchPlan(
        investigation_id=investigation.id,
        question=question.strip()[:2000],
        steps=build_plan(question),
        created_by=created_by,
    )
    session.add(row)
    return row


def add_claim(
    session: Session,
    investigation: Investigation,
    *,
    text: str,
    impact: str = "medium",
    created_by: str | None = None,
    entity_id: str | None = None,
) -> Claim:
    row = Claim(
        investigation_id=investigation.id,
        text=(text or "").strip()[:2000],
        impact=impact if impact in {"low", "medium", "high"} else "medium",
        created_by=created_by,
        entity_id=entity_id,
        status="draft",
    )
    session.add(row)
    return row


def approve_claim(session: Session, claim: Claim, *, username: str, role: str) -> Claim:
    if any(a.username == username for a in claim.approvals):
        return claim
    session.add(ClaimApproval(claim_id=claim.id, username=username, role=role or "analyst"))
    session.flush()
    session.refresh(claim)
    roles = {a.role for a in claim.approvals}
    if claim.impact == "high":
        claim.status = "verified" if len(claim.approvals) >= 2 and roles & {"reviewer", "admin"} else "review"
    else:
        claim.status = "verified"
    return claim


def add_comment(session: Session, investigation: Investigation, body: str, created_by: str | None, entity_id: str | None = None) -> CaseComment:
    row = CaseComment(
        investigation_id=investigation.id,
        body=(body or "").strip()[:4000],
        created_by=created_by,
        entity_id=entity_id,
    )
    session.add(row)
    return row


def take_snapshot(session: Session, investigation: Investigation, label: str = "") -> CaseSnapshot:
    digest = {
        "entities": session.scalar(select(func.count()).select_from(Entity).where(Entity.investigation_id == investigation.id)) or 0,
        "edges": session.scalar(select(func.count()).select_from(Edge).where(Edge.investigation_id == investigation.id)) or 0,
        "evidence": session.scalar(select(func.count()).select_from(Evidence).where(Evidence.investigation_id == investigation.id)) or 0,
        "status": {entity_status(e): 0 for e in []},
    }
    rows = session.scalars(select(Entity).where(Entity.investigation_id == investigation.id)).all()
    counts: dict[str, int] = defaultdict(int)
    for entity in rows:
        counts[entity_status(entity)] += 1
        counts[entity.entity_type] += 1
    digest["status"] = dict(counts)
    row = CaseSnapshot(investigation_id=investigation.id, label=(label or "agora")[:80], digest=dict(digest))
    session.add(row)
    return row


def diff_snapshots(older: CaseSnapshot, newer: CaseSnapshot) -> list[str]:
    a, b = older.digest or {}, newer.digest or {}
    lines = []
    for key in ("entities", "edges", "evidence"):
        delta = int(b.get(key) or 0) - int(a.get(key) or 0)
        if delta:
            lines.append(f"{'+' if delta > 0 else ''}{delta} {key}")
    return lines or ["Sem mudança de contagem."]


def claim_ready_for_report(claim: Claim) -> bool:
    if claim.status != "verified":
        return False
    if claim.impact != "high":
        return True
    roles = {a.role for a in claim.approvals}
    return len(claim.approvals) >= 2 and bool(roles & {"reviewer", "admin"})


def verdict_summary(entities: list[Entity]) -> str:
    return ", ".join(f"{e.display_name}: {verdict_label(entity_status(e))}" for e in entities[:8])
