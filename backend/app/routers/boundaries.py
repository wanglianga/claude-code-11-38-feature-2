from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..compiler import register_meter_event
from ..database import get_db
from ..models import (
    EvidenceStrength,
    MeterEvent,
    MeteringBoundary,
    PeriodRole,
    PipelineKind,
    Project,
    User,
)
from ..schemas import BoundaryIn, MeterEventIn
from ..security import get_current_user, require_write
from ..serialize import to_dict

router = APIRouter(prefix="/api/boundaries", tags=["boundaries"])


@router.get("")
def list_boundaries(project_id: int | None = None, db: Session = Depends(get_db),
                    _: User = Depends(get_current_user)):
    q = db.query(MeteringBoundary)
    if project_id:
        q = q.filter(MeteringBoundary.project_id == project_id)
    return [to_dict(b) for b in q.order_by(MeteringBoundary.id).all()]


@router.post("", status_code=201)
def create_boundary(body: BoundaryIn, db: Session = Depends(get_db), _: User = Depends(require_write)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "项目不存在")
    b = MeteringBoundary(
        project_id=body.project_id,
        meter_serial=body.meter_serial,
        branch_name=body.branch_name,
        pipeline_kind=PipelineKind(body.pipeline_kind),
        zone_name=body.zone_name,
        period_role=PeriodRole(body.period_role),
        valid_from=body.valid_from,
        valid_to=body.valid_to,
        multiplier=body.multiplier,
        multiplier_linked=body.multiplier_linked,
        evidence_strength=EvidenceStrength(body.evidence_strength),
        evidence_ids=body.evidence_ids,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return to_dict(b)


@router.get("/meter-events")
def list_meter_events(project_id: int | None = None, db: Session = Depends(get_db),
                      _: User = Depends(get_current_user)):
    q = db.query(MeterEvent)
    if project_id:
        q = q.filter(MeterEvent.project_id == project_id)
    return [to_dict(e) for e in q.order_by(MeterEvent.id).all()]


@router.post("/meter-events", status_code=201)
def create_meter_event(body: MeterEventIn, db: Session = Depends(get_db), _: User = Depends(require_write)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "项目不存在")
    ev = register_meter_event(
        db, body.project_id, body.old_meter_serial, body.new_meter_serial,
        body.replaced_at, body.multiplier_linked, body.calibration_evidence_id,
    )
    db.commit()
    db.refresh(ev)
    return to_dict(ev)
