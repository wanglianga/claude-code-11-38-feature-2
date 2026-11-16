"""跨项目比较资格与队列构建 API。

只判断比较范围和证据覆盖，不据此排名节能效果。所有写操作由 admin/analyst 执行，
规则发布仅限管理员（规则管理员）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..comparison import (
    build_cohort,
    compare_pair,
    compute_input_digest,
    create_rule,
    mark_source_corrections,
    mark_workspace_stale,
    publish_rule,
    publish_workspace,
    revalidate_workspace,
)
from ..database import get_db
from ..models import (
    BuildingUse,
    ClimateZone,
    ComparisonCohort,
    ComparisonEdge,
    ComparisonPublication,
    ComparisonProjectStatus,
    ComparisonRule,
    ComparisonSourceAncestry,
    ComparisonWorkspace,
    MeterCoverageWindow,
    OccupancyProfile,
    OccupancyWindow,
    Project,
    ProjectComparisonProfile,
    RuleStatus,
    User,
    WorkspaceStatus,
)
from ..schemas import (
    ComparisonProfileIn,
    ComparisonRuleIn,
    MeterCoverageWindowIn,
    OccupancyWindowIn,
    SourceCorrectionIn,
    WorkspaceIn,
    WorkspaceUpdateIn,
)
from ..security import get_current_user, require_write
from ..serialize import to_dict

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])


def _admin(user: User = Depends(require_write)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "仅规则管理员（admin）可发布比较规则")
    return user


# ---------------------------------------------------------------- 规则


@router.get("/rules")
def list_rules(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(ComparisonRule).order_by(ComparisonRule.code, ComparisonRule.version.desc()).all()
    return [to_dict(r) for r in rows]


@router.post("/rules", status_code=201)
def register_rule(body: ComparisonRuleIn, db: Session = Depends(get_db),
                  user: User = Depends(require_write)):
    """登记规则草稿；草稿不参与发布。"""
    try:
        rule = create_rule(db, body.model_dump(), actor=user.username)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    db.refresh(rule)
    return to_dict(rule)


@router.post("/rules/{rule_id}/publish", status_code=201)
def activate_rule(rule_id: int, body: ComparisonRuleIn, db: Session = Depends(get_db),
                  user: User = Depends(_admin)):
    """发布更严格版本：旧版本 superseded；运行中草稿标记过期，旧资格不得当作新规则结果。"""
    old = db.get(ComparisonRule, rule_id)
    if old is None:
        raise HTTPException(404, "规则不存在")
    if body.code != old.code:
        raise HTTPException(400, "新版本必须与原规则同 code")
    try:
        rule, stale = publish_rule(db, old, body.model_dump(), actor=user.username)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    db.refresh(rule)
    out = to_dict(rule)
    out["stale_workspaces"] = stale
    return out


# ---------------------------------------------------------------- 项目属性 / 覆盖 / 占用


@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(ProjectComparisonProfile).order_by(ProjectComparisonProfile.project_id).all()
    return [to_dict(r) for r in rows]


@router.put("/profiles/{project_id}")
def upsert_profile(project_id: int, body: ComparisonProfileIn, db: Session = Depends(get_db),
                   user: User = Depends(require_write)):
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "项目不存在")
    prof = (db.query(ProjectComparisonProfile)
            .filter(ProjectComparisonProfile.project_id == project_id).first())
    try:
        values = {
            "building_use": BuildingUse(body.building_use),
            "climate_zone": ClimateZone(body.climate_zone),
            "occupancy_profile": OccupancyProfile(body.occupancy_profile),
            "area_m2": body.area_m2,
            "includes_dining": body.includes_dining,
            "includes_public_load": body.includes_public_load,
            "shared_load_keys": body.shared_load_keys,
            "description": body.description,
        }
    except ValueError as exc:
        raise HTTPException(400, f"未知枚举值: {exc}")
    if prof is None:
        prof = ProjectComparisonProfile(project_id=project_id, **values)
        db.add(prof)
    else:
        for k, v in values.items():
            setattr(prof, k, v)
    db.commit()
    db.refresh(prof)
    return to_dict(prof)


@router.get("/occupancy")
def list_occupancy(project_id: int | None = None, db: Session = Depends(get_db),
                   _: User = Depends(get_current_user)):
    q = db.query(OccupancyWindow)
    if project_id:
        q = q.filter(OccupancyWindow.project_id == project_id)
    return [to_dict(r) for r in q.order_by(OccupancyWindow.id).all()]


@router.post("/occupancy", status_code=201)
def add_occupancy(body: OccupancyWindowIn, db: Session = Depends(get_db),
                  _: User = Depends(require_write)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "项目不存在")
    if body.valid_to <= body.valid_from:
        raise HTTPException(400, "占用区间起止无效")
    row = OccupancyWindow(project_id=body.project_id, valid_from=body.valid_from,
                          valid_to=body.valid_to, label=body.label)
    db.add(row)
    db.commit()
    db.refresh(row)
    return to_dict(row)


@router.get("/coverage")
def list_coverage(project_id: int | None = None, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    q = db.query(MeterCoverageWindow)
    if project_id:
        q = q.filter(MeterCoverageWindow.project_id == project_id)
    return [to_dict(r) for r in q.order_by(MeterCoverageWindow.id).all()]


@router.post("/coverage", status_code=201)
def add_coverage(body: MeterCoverageWindowIn, db: Session = Depends(get_db),
                 _: User = Depends(require_write)):
    if db.get(Project, body.project_id) is None:
        raise HTTPException(404, "项目不存在")
    if body.valid_to <= body.valid_from:
        raise HTTPException(400, "计量覆盖区间起止无效")
    row = MeterCoverageWindow(
        project_id=body.project_id, meter_serial=body.meter_serial,
        valid_from=body.valid_from, valid_to=body.valid_to,
        independent=body.independent, has_allocation_basis=body.has_allocation_basis,
        verified=body.verified,
        shared_with_project_id=body.shared_with_project_id,
        evidence_ids=body.evidence_ids, note=body.note,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return to_dict(row)


# ---------------------------------------------------------------- 工作区


def _workspace_payload(db: Session, ws: ComparisonWorkspace, *, include_edges: bool = True) -> dict:
    rule = db.get(ComparisonRule, ws.rule_id)
    out = to_dict(ws)
    out["rule"] = to_dict(rule) if rule else None
    out["rule_current_version"] = None
    if rule is not None:
        active = (db.query(ComparisonRule)
                  .filter(ComparisonRule.code == rule.code,
                          ComparisonRule.status == RuleStatus.active)
                  .order_by(ComparisonRule.version.desc()).first())
        out["rule_current_version"] = active.version if active else None
    # 隐式过期检测：输入指纹变化或规则版本变化时提示（不自动改写结论）
    if rule is not None and ws.status in (WorkspaceStatus.computed, WorkspaceStatus.published):
        digest = compute_input_digest(db, ws, rule)
        out["input_changed"] = bool(ws.input_digest and digest != ws.input_digest)
        out["rule_superseded"] = bool(out["rule_current_version"] and
                                      out["rule_current_version"] != ws.rule_version)
    else:
        out["input_changed"] = False
        out["rule_superseded"] = False
    if include_edges:
        edges = (db.query(ComparisonEdge)
                 .filter(ComparisonEdge.workspace_id == ws.id)
                 .order_by(ComparisonEdge.project_a_id, ComparisonEdge.project_b_id).all())
        cohort = (db.query(ComparisonCohort)
                  .filter(ComparisonCohort.workspace_id == ws.id).first())
        statuses = (db.query(ComparisonProjectStatus)
                    .filter(ComparisonProjectStatus.workspace_id == ws.id)
                    .order_by(ComparisonProjectStatus.project_id).all())
        code_map = {p.id: p.code for p in db.query(Project).all()}
        out["edges"] = [
            {**to_dict(e),
             "project_a_code": code_map.get(e.project_a_id),
             "project_b_code": code_map.get(e.project_b_id)}
            for e in edges
        ]
        out["cohort"] = (
            {**to_dict(cohort),
             "project_statuses": [
                 {**to_dict(s), "project_code": code_map.get(s.project_id)} for s in statuses]}
            if cohort else None
        )
        out["project_codes"] = [code_map.get(int(p)) for p in (ws.project_ids or [])]
        pubs = (db.query(ComparisonPublication)
                .filter(ComparisonPublication.workspace_id == ws.id)
                .order_by(ComparisonPublication.version.desc()).all())
        out["publications"] = [to_dict(p) for p in pubs]
    return out


@router.get("/workspaces")
def list_workspaces(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    rows = db.query(ComparisonWorkspace).order_by(ComparisonWorkspace.id.desc()).all()
    return [_workspace_payload(db, w, include_edges=False) for w in rows]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, db: Session = Depends(get_db),
                     user: User = Depends(require_write)):
    if db.query(ComparisonWorkspace).filter(ComparisonWorkspace.code == body.code).first():
        raise HTTPException(409, "工作区编码已存在")
    rule = db.get(ComparisonRule, body.rule_id)
    if rule is None:
        raise HTTPException(404, "比较规则不存在")
    if rule.status != RuleStatus.active:
        raise HTTPException(400, "只能使用已激活的规则建立工作区")
    pids = sorted(set(int(p) for p in body.project_ids))
    if len(pids) < 2:
        raise HTTPException(400, "比较工作区至少需要两个项目")
    missing = [p for p in pids if db.get(Project, p) is None]
    if missing:
        raise HTTPException(404, f"项目不存在: {missing}")

    ws = ComparisonWorkspace(
        code=body.code, title=body.title, rule_id=rule.id, rule_version=rule.version,
        project_ids=pids, material_cutoff=body.material_cutoff,
        status=WorkspaceStatus.draft, created_by=user.username,
    )
    db.add(ws)
    db.flush()
    if body.compute:
        revalidate_workspace(db, ws, actor=user.username)
    db.commit()
    db.refresh(ws)
    return _workspace_payload(db, ws)


@router.get("/workspaces/{workspace_id}")
def get_workspace(workspace_id: int, db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    ws = db.get(ComparisonWorkspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在")
    return _workspace_payload(db, ws)


@router.patch("/workspaces/{workspace_id}")
def update_workspace(workspace_id: int, body: WorkspaceUpdateIn, db: Session = Depends(get_db),
                     user: User = Depends(require_write)):
    """切换用途/日期/项目或规则后，已选项目作废重验，不能沿用上一次的绿色资格。"""
    ws = db.get(ComparisonWorkspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在")
    if ws.status == WorkspaceStatus.withdrawn:
        raise HTTPException(409, "工作区已撤回，不能修改")

    changed: list[str] = []
    if body.title is not None and body.title != ws.title:
        ws.title = body.title
        changed.append("title")
    if body.rule_id is not None and body.rule_id != ws.rule_id:
        rule = db.get(ComparisonRule, body.rule_id)
        if rule is None or rule.status != RuleStatus.active:
            raise HTTPException(400, "只能切换到已激活的规则")
        ws.rule_id = rule.id
        ws.rule_version = rule.version
        changed.append("rule")
    if body.project_ids is not None:
        pids = sorted(set(int(p) for p in body.project_ids))
        if len(pids) < 2:
            raise HTTPException(400, "比较工作区至少需要两个项目")
        missing = [p for p in pids if db.get(Project, p) is None]
        if missing:
            raise HTTPException(404, f"项目不存在: {missing}")
        if pids != sorted(int(p) for p in (ws.project_ids or [])):
            ws.project_ids = pids
            changed.append("projects")
    if body.material_cutoff is not None and body.material_cutoff != ws.material_cutoff:
        ws.material_cutoff = body.material_cutoff
        changed.append("cutoff")

    if changed and any(c in changed for c in ("rule", "projects", "cutoff")):
        # 条件变更后旧资格一律作废：删除旧边与队列，必须重新核验
        mark_workspace_stale(db, ws, {
            "reason": body.reason or "工作区比较条件已变更",
            "changed": changed,
            "note": "条件变更后旧资格作废，需重新核验后才能发布",
        }, actor=user.username)
    db.commit()
    db.refresh(ws)
    return _workspace_payload(db, ws)


@router.post("/workspaces/{workspace_id}/compute")
def compute_workspace(workspace_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_write)):
    """按冻结的规则版本重新核验全部项目对（清空旧边与旧队列）。"""
    ws = db.get(ComparisonWorkspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在")
    try:
        revalidate_workspace(db, ws, actor=user.username)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    db.refresh(ws)
    return _workspace_payload(db, ws)


@router.post("/workspaces/{workspace_id}/cohort")
def compute_cohort(workspace_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_write)):
    """仅在另行求出全组共同交集后开放全组汇总；不能用局部比较多的项目代替整体更好。"""
    ws = db.get(ComparisonWorkspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在")
    if ws.status in (WorkspaceStatus.stale, WorkspaceStatus.draft, WorkspaceStatus.withdrawn):
        raise HTTPException(409, "工作区未核验、已过期或已撤回：请先重新核验")
    try:
        cohort = build_cohort(db, ws, actor=user.username)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    db.refresh(cohort)
    statuses = (db.query(ComparisonProjectStatus)
                .filter(ComparisonProjectStatus.workspace_id == ws.id)
                .order_by(ComparisonProjectStatus.project_id).all())
    code_map = {p.id: p.code for p in db.query(Project).all()}
    return {**to_dict(cohort),
            "project_statuses": [
                {**to_dict(s), "project_code": code_map.get(s.project_id)} for s in statuses]}


@router.post("/workspaces/{workspace_id}/publish", status_code=201)
def publish(workspace_id: int, db: Session = Depends(get_db),
            user: User = Depends(require_write)):
    ws = db.get(ComparisonWorkspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在")
    try:
        pub = publish_workspace(db, ws, actor=user.username)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    db.refresh(pub)
    return to_dict(pub)


@router.post("/workspaces/{workspace_id}/withdraw")
def withdraw(workspace_id: int, db: Session = Depends(get_db),
             user: User = Depends(require_write)):
    """撤回工作区：已发布清单保留（历史冻结），工作区不再可用。"""
    ws = db.get(ComparisonWorkspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在")
    ws.status = WorkspaceStatus.withdrawn
    db.query(ComparisonSourceAncestry).filter(
        ComparisonSourceAncestry.workspace_id == ws.id).delete()
    db.query(ComparisonEdge).filter(ComparisonEdge.workspace_id == ws.id).delete()
    db.query(ComparisonCohort).filter(ComparisonCohort.workspace_id == ws.id).delete()
    db.commit()
    db.refresh(ws)
    return _workspace_payload(db, ws)


@router.delete("/workspaces/{workspace_id}/projects/{project_id}")
def remove_project(workspace_id: int, project_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_write)):
    """项目退出工作区：移除该项目；重新核验后未受影响的比较仍可使用。"""
    ws = db.get(ComparisonWorkspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在")
    pids = [int(p) for p in (ws.project_ids or [])]
    if project_id not in pids:
        raise HTTPException(404, "该项目不在工作区中")
    remaining = [p for p in pids if p != project_id]
    if len(remaining) < 2:
        raise HTTPException(400, "移除后不足两个项目，无法继续比较；请直接撤回工作区")
    ws.project_ids = remaining
    mark_workspace_stale(db, ws, {
        "reason": "项目退出工作区",
        "removed_project_id": project_id,
        "note": "已移除项目相关的比较边失效，其余项目对需重新核验后继续使用",
    }, actor=user.username)
    db.commit()
    db.refresh(ws)
    return _workspace_payload(db, ws)


# ---------------------------------------------------------------- 比较边与溯源


@router.get("/workspaces/{workspace_id}/edges")
def list_edges(workspace_id: int, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    ws = db.get(ComparisonWorkspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "工作区不存在")
    rows = (db.query(ComparisonEdge)
            .filter(ComparisonEdge.workspace_id == workspace_id)
            .order_by(ComparisonEdge.project_a_id, ComparisonEdge.project_b_id).all())
    return [to_dict(e) for e in rows]


@router.get("/edges/{edge_id}/trace")
def trace_edge(edge_id: int, db: Session = Depends(get_db),
               _: User = Depends(get_current_user)):
    """从任一比较回查双方输入、交集如何取得、排除了哪些区间，以及该结果支持哪种分析。"""
    edge = db.get(ComparisonEdge, edge_id)
    if edge is None:
        raise HTTPException(404, "比较边不存在")
    ws = db.get(ComparisonWorkspace, edge.workspace_id)
    rule = db.get(ComparisonRule, ws.rule_id) if ws else None
    code_map = {p.id: p.code for p in db.query(Project).all()}
    cohort = (db.query(ComparisonCohort)
              .filter(ComparisonCohort.workspace_id == edge.workspace_id).first())

    # 重新计算同一对，得到与存储一致的输入与交集过程（只读，不落库）
    recomputed = None
    if ws is not None and rule is not None:
        recomputed = compare_pair(db, rule, ws, edge.project_a_id, edge.project_b_id)

    return {
        "edge": to_dict(edge),
        "workspace": to_dict(ws) if ws else None,
        "rule": to_dict(rule) if rule else None,
        "cohort": to_dict(cohort) if cohort else None,
        "project_a": {"id": edge.project_a_id, "code": code_map.get(edge.project_a_id)},
        "project_b": {"id": edge.project_b_id, "code": code_map.get(edge.project_b_id)},
        "inputs": edge.inputs,
        "intersection": edge.inputs.get("common_intersection"),
        "common_independent_intersection": edge.inputs.get("common_independent_intersection"),
        "exclusions": edge.exclusions,
        "limitations": edge.limitations,
        "reasons": edge.reasons,
        "supported_analysis": edge.supported_analysis,
        "recomputed_matches": (
            None if recomputed is None else
            (recomputed["eligible"] == edge.eligible
             and recomputed["window"] == edge.window
             and recomputed["exclusions"] == edge.exclusions)
        ),
        "note": "比较边只说明该对在给定条件下的比较范围与证据覆盖，不构成节能效果排名",
    }


# ---------------------------------------------------------------- 发布清单 / 来源更正


@router.get("/publications")
def list_publications(workspace_id: int | None = None, db: Session = Depends(get_db),
                      _: User = Depends(get_current_user)):
    q = db.query(ComparisonPublication)
    if workspace_id:
        q = q.filter(ComparisonPublication.workspace_id == workspace_id)
    rows = q.order_by(ComparisonPublication.workspace_id, ComparisonPublication.version.desc()).all()
    return [to_dict(p) for p in rows]


@router.post("/corrections")
def source_correction(body: SourceCorrectionIn, db: Session = Depends(get_db),
                      user: User = Depends(require_write)):
    """资料目录更正：先按来源定位比较边，再重新检查涉及的队列；未受影响的比较仍可使用。"""
    if not body.project_ids:
        raise HTTPException(400, "需指定受影响的项目")
    source_types = list(body.source_types)
    source_ids = list(body.source_ids)
    if body.evidence_id is not None:
        source_types = ["evidence"]
        source_ids = [body.evidence_id]
    result = mark_source_corrections(db, project_ids=body.project_ids,
                                     source_ref=body.source_ref,
                                     source_types=source_types,
                                     source_ids=source_ids,
                                     actor=user.username)
    db.commit()
    return result
