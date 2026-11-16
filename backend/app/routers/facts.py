from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..compiler import compile_fact
from ..database import get_db
from ..models import (
    Citation,
    EvidenceDocument,
    FactStatus,
    MeterEvent,
    MeteringBoundary,
    PerformanceFact,
    Project,
    ScopeRelation,
    Strategy,
    User,
)
from ..schemas import CompileIn
from ..security import get_current_user, require_write
from ..serialize import to_dict

router = APIRouter(prefix="/api/facts", tags=["facts"])


@router.get("")
def list_facts(project_id: int | None = None, status: str | None = None,
               comparability: str | None = None, result_kind: str | None = None,
               db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = db.query(PerformanceFact)
    if project_id:
        q = q.filter(PerformanceFact.project_id == project_id)
    if status:
        q = q.filter(PerformanceFact.status == FactStatus(status))
    if comparability:
        from ..models import Comparability
        q = q.filter(PerformanceFact.comparability == Comparability(comparability))
    if result_kind:
        from ..models import ResultKind
        q = q.filter(PerformanceFact.result_kind == ResultKind(result_kind))
    return [to_dict(f) for f in q.order_by(PerformanceFact.id.desc()).all()]


@router.post("/compile", status_code=201)
def compile_new_fact(body: CompileIn, db: Session = Depends(get_db), user: User = Depends(require_write)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "项目不存在")
    try:
        strategy = Strategy(body.strategy)
    except ValueError:
        raise HTTPException(400, f"未知核验策略: {body.strategy}")
    try:
        fact = compile_fact(
            db, body.project_id, body.scope_relation_id, strategy,
            body.baseline_start, body.baseline_end,
            body.reporting_start, body.reporting_end,
            actor=user.username,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    db.refresh(fact)
    return to_dict(fact)


@router.get("/{fact_id}")
def get_fact(fact_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    fact = db.get(PerformanceFact, fact_id)
    if fact is None:
        raise HTTPException(404, "事实不存在")
    return to_dict(fact)


@router.get("/{fact_id}/trace")
def trace_fact(fact_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """溯源：范围证据、计量边界、所选策略、假设、版本链与下游引用。"""
    fact = db.get(PerformanceFact, fact_id)
    if fact is None:
        raise HTTPException(404, "事实不存在")

    scope = db.get(ScopeRelation, fact.scope_relation_id)
    scope_evidence = []
    if scope:
        for eid in scope.evidence_ids or []:
            doc = db.get(EvidenceDocument, eid)
            if doc:
                scope_evidence.append(to_dict(doc))

    boundary = db.get(MeteringBoundary, fact.boundary_id) if fact.boundary_id else None
    boundary_evidence = []
    if boundary:
        for eid in boundary.evidence_ids or []:
            doc = db.get(EvidenceDocument, eid)
            if doc:
                boundary_evidence.append(to_dict(doc))

    # 版本链：同一谱系全部版本
    lineage = (
        db.query(PerformanceFact)
        .filter(PerformanceFact.project_id == fact.project_id,
                PerformanceFact.scope_relation_id == fact.scope_relation_id,
                PerformanceFact.strategy == fact.strategy)
        .order_by(PerformanceFact.version)
        .all()
    )
    citations = db.query(Citation).filter(Citation.fact_id == fact_id).order_by(Citation.id).all()
    meter_events = (
        db.query(MeterEvent).filter(MeterEvent.project_id == fact.project_id)
        .order_by(MeterEvent.replaced_at).all()
    )
    decl_id = (fact.assumptions or {}).get("declaration_evidence_id")
    decl = db.get(EvidenceDocument, decl_id) if decl_id else None

    return {
        "fact": to_dict(fact),
        "scope_relation": to_dict(scope) if scope else None,
        "scope_evidence": scope_evidence,
        "boundary": to_dict(boundary) if boundary else None,
        "boundary_evidence": boundary_evidence,
        "allocation_declaration": to_dict(decl) if decl else None,
        "strategy": fact.strategy.value,
        "assumptions": fact.assumptions,
        "version_chain": [to_dict(f) for f in lineage],
        "citations": [to_dict(c) for c in citations],
        "meter_events": [to_dict(e) for e in meter_events],
    }
