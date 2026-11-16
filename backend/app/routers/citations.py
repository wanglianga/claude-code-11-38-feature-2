from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Citation, FactStatus, PerformanceFact, User
from ..schemas import CitationIn
from ..security import get_current_user
from ..serialize import to_dict

router = APIRouter(prefix="/api/citations", tags=["citations"])


@router.get("")
def list_citations(fact_id: int | None = None, db: Session = Depends(get_db),
                   _: User = Depends(get_current_user)):
    q = db.query(Citation)
    if fact_id:
        q = q.filter(Citation.fact_id == fact_id)
    return [to_dict(c) for c in q.order_by(Citation.id.desc()).all()]


@router.post("", status_code=201)
def create_citation(body: CitationIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    fact = db.get(PerformanceFact, body.fact_id)
    if fact is None:
        raise HTTPException(404, "事实不存在")
    if fact.status == FactStatus.under_review or fact.block_new_citations:
        raise HTTPException(409, "该事实处于复审中，已暂停新分析引用")
    if fact.status == FactStatus.superseded:
        raise HTTPException(409, "该事实版本已被新签发取代，请引用当前版本")
    c = Citation(
        fact_id=fact.id,
        fact_version=fact.version,
        consumer_type=body.consumer_type,
        consumer_name=body.consumer_name,
        purpose=body.purpose,
        created_by=user.username,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return to_dict(c)
