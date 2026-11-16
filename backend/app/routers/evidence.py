import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..compiler import apply_evidence_revision
from ..comparison import mark_source_corrections
from ..database import get_db
from ..models import DocType, EvidenceDocument, EvidenceStatus, Project, User
from ..schemas import EvidenceIn
from ..security import get_current_user, require_write
from ..serialize import to_dict

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


def source_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@router.get("")
def list_evidence(project_id: int | None = None, doc_type: str | None = None,
                  db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    q = db.query(EvidenceDocument)
    if project_id:
        q = q.filter(EvidenceDocument.project_id == project_id)
    if doc_type:
        q = q.filter(EvidenceDocument.doc_type == DocType(doc_type))
    rows = q.order_by(EvidenceDocument.id.desc()).all()
    return [to_dict(r) for r in rows]


@router.post("", status_code=201)
def intake_evidence(body: EvidenceIn, db: Session = Depends(get_db), user: User = Depends(require_write)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "项目不存在")
    try:
        doc_type = DocType(body.doc_type)
    except ValueError:
        raise HTTPException(400, f"未知证据类型: {body.doc_type}")

    doc = EvidenceDocument(
        project_id=body.project_id,
        doc_type=doc_type,
        title=body.title,
        source_hash=source_hash(body.payload),
        event_time=body.event_time,
        payload=body.payload,
    )

    affected_facts: list[int] = []
    comparison_impact: dict = {"stale_workspaces": [], "stale_publications": [], "affected_edges": []}
    if body.supersedes_id is not None:
        old = db.get(EvidenceDocument, body.supersedes_id)
        if old is None:
            raise HTTPException(404, "被修订的证据不存在")
        if old.project_id != body.project_id or old.doc_type != doc_type:
            raise HTTPException(400, "修订证据须与原证据同项目同类型")
        affected_facts = apply_evidence_revision(db, old, doc)
        # 资料目录更正：先按来源（证据 id 血缘）定位比较边，再重新检查涉及的比较队列
        comparison_impact = mark_source_corrections(
            db, project_ids=[body.project_id],
            source_ref=f"evidence#{old.id}->{old.doc_type.value}",
            source_types=["evidence"], source_ids=[old.id],
        )

    db.add(doc)
    db.commit()
    db.refresh(doc)
    out = to_dict(doc)
    out["affected_fact_ids"] = affected_facts  # 因附件替换转入复审中的事实
    out["comparison_impact"] = comparison_impact
    return out


@router.get("/{evidence_id}/chain")
def revision_chain(evidence_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """修订链：从任一版本出发，给出整条签发版本链。"""
    doc = db.get(EvidenceDocument, evidence_id)
    if doc is None:
        raise HTTPException(404, "证据不存在")
    # 回溯到链首
    root = doc
    while root.supersedes_id is not None:
        root = db.get(EvidenceDocument, root.supersedes_id)
    chain = []
    cur = root
    while cur is not None:
        chain.append(to_dict(cur))
        nxt = (db.query(EvidenceDocument)
               .filter(EvidenceDocument.supersedes_id == cur.id)
               .order_by(EvidenceDocument.version).first())
        cur = nxt
    return chain


@router.get("/{evidence_id}")
def get_evidence(evidence_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    doc = db.get(EvidenceDocument, evidence_id)
    if doc is None:
        raise HTTPException(404, "证据不存在")
    return to_dict(doc)
