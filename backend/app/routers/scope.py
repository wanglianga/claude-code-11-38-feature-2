from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..compiler import detect_serial_conflicts
from ..database import get_db
from ..models import (
    Conflict,
    ConflictStatus,
    Project,
    RelationKind,
    ScopeRelation,
    ScopeStatus,
    SubjectType,
    User,
)
from ..schemas import ScopeRelationIn
from ..security import get_current_user, require_write
from ..serialize import to_dict

router = APIRouter(prefix="/api/scope", tags=["scope"])


@router.get("/relations")
def list_relations(project_id: int | None = None, status: str | None = None,
                   db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = db.query(ScopeRelation)
    if project_id:
        q = q.filter(ScopeRelation.project_id == project_id)
    if status:
        q = q.filter(ScopeRelation.status == ScopeStatus(status))
    rows = q.order_by(ScopeRelation.id).all()
    return [to_dict(r) for r in rows]


@router.post("/relations", status_code=201)
def create_relation(body: ScopeRelationIn, db: Session = Depends(get_db), _: User = Depends(require_write)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "项目不存在")
    rel = ScopeRelation(
        project_id=body.project_id,
        relation_kind=RelationKind(body.relation_kind),
        subject_type=SubjectType(body.subject_type),
        subject_ref=body.subject_ref,
        serial_no=body.serial_no,
        status=ScopeStatus(body.status),
        coverage_note=body.coverage_note,
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        physically_exclusive=body.physically_exclusive,
        evidence_ids=body.evidence_ids,
    )
    db.add(rel)
    db.flush()
    conflicts = detect_serial_conflicts(db, rel)
    db.commit()
    db.refresh(rel)
    out = to_dict(rel)
    out["new_conflicts"] = [to_dict(c) for c in conflicts]
    return out


@router.patch("/relations/{relation_id}")
def update_relation(relation_id: int, body: dict, db: Session = Depends(get_db),
                    _: User = Depends(require_write)):
    rel = db.get(ScopeRelation, relation_id)
    if rel is None:
        raise HTTPException(404, "范围关系不存在")
    for field in ("status", "coverage_note", "valid_from", "valid_to", "evidence_ids"):
        if field in body:
            val = body[field]
            if field == "status":
                val = ScopeStatus(val)
            setattr(rel, field, val)
    conflicts = detect_serial_conflicts(db, rel)
    db.commit()
    db.refresh(rel)
    out = to_dict(rel)
    out["new_conflicts"] = [to_dict(c) for c in conflicts]
    return out


@router.get("/conflicts")
def list_conflicts(status: str | None = None, db: Session = Depends(get_db),
                   _: User = Depends(get_current_user)):
    q = db.query(Conflict)
    if status:
        q = q.filter(Conflict.status == ConflictStatus(status))
    return [to_dict(c) for c in q.order_by(Conflict.id.desc()).all()]


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(conflict_id: int, db: Session = Depends(get_db), _: User = Depends(require_write)):
    c = db.get(Conflict, conflict_id)
    if c is None:
        raise HTTPException(404, "冲突记录不存在")
    c.status = ConflictStatus.resolved
    db.commit()
    return to_dict(c)
