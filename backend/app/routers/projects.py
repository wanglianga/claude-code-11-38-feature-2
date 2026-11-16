from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    Comparability,
    Conflict,
    ConflictStatus,
    EvidenceDocument,
    FactStatus,
    PerformanceFact,
    Project,
    ScopeRelation,
    User,
)
from ..schemas import ProjectIn
from ..security import get_current_user, require_write
from ..serialize import to_dict

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def list_projects(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(Project).order_by(Project.id).all()
    return [to_dict(p) for p in rows]


@router.post("", status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), _: User = Depends(require_write)):
    if db.query(Project).filter(Project.code == body.code).first():
        raise HTTPException(409, "项目编码已存在")
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return to_dict(p)


@router.get("/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "项目不存在")
    return to_dict(p)


@router.get("/{project_id}/summary")
def project_summary(project_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(404, "项目不存在")
    facts = db.query(PerformanceFact).filter(PerformanceFact.project_id == project_id).all()
    current = [f for f in facts if f.status == FactStatus.current]
    return {
        "project": to_dict(p),
        "evidence_count": db.query(EvidenceDocument).filter(EvidenceDocument.project_id == project_id).count(),
        "scope_count": db.query(ScopeRelation).filter(ScopeRelation.project_id == project_id).count(),
        "facts_current": len(current),
        "facts_total": len(facts),
        "comparable": sum(1 for f in current if f.comparability == Comparability.comparable),
        "restricted": sum(1 for f in current if f.comparability == Comparability.restricted_comparable),
        "pending": sum(1 for f in current if f.comparability == Comparability.pending_review),
        "incomparable": sum(1 for f in current if f.comparability == Comparability.incomparable),
        "under_review": sum(1 for f in facts if f.status == FactStatus.under_review),
        "open_conflicts": len([
            c for c in db.query(Conflict).filter(Conflict.status == ConflictStatus.open).all()
            if project_id in (c.project_ids or [])
        ]),
    }
