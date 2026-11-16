from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import (
    AuditLog,
    Comparability,
    FactStatus,
    PerformanceFact,
    Project,
    ResultKind,
    User,
)
from ..security import get_current_user
from ..serialize import to_dict

router = APIRouter(prefix="/api/analysis", tags=["analysis"])

_PUBLISHABLE = (Comparability.comparable, Comparability.restricted_comparable)


@router.get("/benchmark")
def benchmark(include_allocated: bool = False, db: Session = Depends(get_db),
              _: User = Depends(get_current_user)):
    """节能对标：默认只读直接计量的当前事实；覆盖分析可选纳入受控分摊值。"""
    q = (db.query(PerformanceFact)
         .filter(PerformanceFact.status == FactStatus.current,
                 PerformanceFact.comparability.in_(_PUBLISHABLE)))
    if not include_allocated:
        q = q.filter(PerformanceFact.result_kind == ResultKind.direct_metering)
    rows = q.order_by(PerformanceFact.project_id).all()
    projects = {p.id: p for p in db.query(Project).all()}
    return [
        {**to_dict(f),
         "project_code": projects[f.project_id].code if f.project_id in projects else None,
         "project_name": projects[f.project_id].name if f.project_id in projects else None}
        for f in rows
    ]


@router.get("/uncompared")
def uncompared(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """未比较清单：当前仍处于待复核或不可比较的事实（如共用管路项目未走分摊）。"""
    rows = (db.query(PerformanceFact)
            .filter(PerformanceFact.status == FactStatus.current,
                    PerformanceFact.comparability.in_(
                        (Comparability.pending_review, Comparability.incomparable)))
            .order_by(PerformanceFact.project_id).all())
    projects = {p.id: p for p in db.query(Project).all()}
    return [
        {**to_dict(f),
         "project_code": projects[f.project_id].code if f.project_id in projects else None,
         "project_name": projects[f.project_id].name if f.project_id in projects else None}
        for f in rows
    ]


@router.get("/audit-logs")
def audit_logs(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(AuditLog).order_by(AuditLog.id.desc()).limit(200).all()
    return [to_dict(r) for r in rows]
