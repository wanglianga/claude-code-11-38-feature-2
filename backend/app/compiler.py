"""绩效事实编译器与领域规则。

规则汇总：
1. 范围关系为 冲突 → 不可比较；候选/转移待核 → 待复核。
2. 基线期或报告期中途换表且倍率未衔接 → 断点，禁止跨越断点签发可比较事实。
3. 严格直接计量策略要求专属电表边界完整覆盖；只有公共管路 → 不可比较（建议改用受控分摊）。
4. 受控分摊策略要求有效的分摊声明；缺运行时长/面积 → 待复核；补齐后新签发版本，不改写旧版本。
5. 验收报告附件被替换（哈希变化）→ 引用旧附件的当前事实转入复审中并暂停新引用。
6. 同一设备序列号被两个项目声明：服务区间重叠且物理互斥 → 重复覆盖冲突；
   区间不重叠且缺移装材料 → 转移待核（不得升级为重复主张）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import (
    AuditLog,
    Comparability,
    Conflict,
    ConflictStatus,
    ConflictType,
    DocType,
    EvidenceDocument,
    EvidenceStatus,
    FactStatus,
    MeterEvent,
    MeteringBoundary,
    PerformanceFact,
    PipelineKind,
    RelationKind,
    ResultKind,
    ScopeRelation,
    ScopeStatus,
    Strategy,
    SubjectType,
)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _overlaps(a_from, a_to, b_from, b_to) -> bool:
    a_from, b_from = _aware(a_from), _aware(b_from)
    a_to = _aware(a_to) if a_to else datetime.max.replace(tzinfo=timezone.utc)
    b_to = _aware(b_to) if b_to else datetime.max.replace(tzinfo=timezone.utc)
    return a_from <= b_to and b_from <= a_to


# ---------------------------------------------------------------- 读数汇总


def meter_energy(db: Session, project_id: int, meter_serial: str, start: datetime, end: datetime) -> float:
    """汇总某电表在 [start, end] 内、来自有效读数原文的电量（记录需完整落在区间内）。"""
    docs = (
        db.query(EvidenceDocument)
        .filter(
            EvidenceDocument.project_id == project_id,
            EvidenceDocument.doc_type == DocType.meter_reading,
            EvidenceDocument.status == EvidenceStatus.active,
        )
        .all()
    )
    start, end = _aware(start), _aware(end)
    total = 0.0
    for doc in docs:
        if doc.payload.get("meter_serial") != meter_serial:
            continue
        for rec in doc.payload.get("records", []):
            rs = _aware(datetime.fromisoformat(rec["start"]))
            re = _aware(datetime.fromisoformat(rec["end"]))
            if rs >= start and re <= end:
                total += float(rec["kwh"])
    return total


def _boundary_energy(db: Session, b: MeteringBoundary, start: datetime, end: datetime) -> float:
    return meter_energy(db, b.project_id, b.meter_serial, start, end) * (b.multiplier or 1.0)


def _covering_boundaries(db: Session, project_id: int, period_role, start: datetime, end: datetime):
    start, end = _aware(start), _aware(end)
    rows = (
        db.query(MeteringBoundary)
        .filter(
            MeteringBoundary.project_id == project_id,
            MeteringBoundary.period_role == period_role,
            MeteringBoundary.valid_from <= start,
        )
        .all()
    )
    return [b for b in rows if b.valid_to is None or _aware(b.valid_to) >= end]


# ---------------------------------------------------------------- 主编译入口


def compile_fact(
    db: Session,
    project_id: int,
    scope_relation_id: int,
    strategy: Strategy,
    baseline_start: datetime,
    baseline_end: datetime,
    reporting_start: datetime,
    reporting_end: datetime,
    actor: str = "system",
) -> PerformanceFact:
    scope = db.get(ScopeRelation, scope_relation_id)
    if scope is None or scope.project_id != project_id:
        raise ValueError("范围关系不存在或不属于该项目")

    result_kind = ResultKind.direct_metering if strategy == Strategy.strict_direct else ResultKind.controlled_allocation
    reasons: list[str] = []
    assumptions: dict = {}
    comparability: Comparability | None = None
    boundary_used: MeteringBoundary | None = None
    baseline_kwh = reporting_kwh = savings_kwh = savings_rate = None

    # 1) 范围状态门控
    if scope.status == ScopeStatus.conflicted:
        comparability = Comparability.incomparable
        reasons.append("范围关系存在重复覆盖冲突：同一设备序列号被多个项目声明且服务区间重叠")
    elif scope.status == ScopeStatus.candidate:
        comparability = Comparability.pending_review
        reasons.append("范围关系仍为候选，合同承诺/实装证据/验收结论未达成一致")
    elif scope.status == ScopeStatus.transfer_pending:
        comparability = Comparability.pending_review
        reasons.append("设备序列号跨项目转移待核：服务区间不重叠但缺少移装材料")

    # 2) 换表断点：基线期/报告期中途换表且倍率未衔接 → 禁止跨越断点
    if comparability is None:
        events = (
            db.query(MeterEvent)
            .filter(MeterEvent.project_id == project_id, MeterEvent.multiplier_linked.is_(False))
            .all()
        )
        for ev in events:
            at = _aware(ev.replaced_at)
            in_baseline = _aware(baseline_start) < at < _aware(baseline_end)
            in_reporting = _aware(reporting_start) < at < _aware(reporting_end)
            if in_baseline or in_reporting:
                comparability = Comparability.incomparable
                seg = "基线期" if in_baseline else "报告期"
                reasons.append(
                    f"{seg}中途换表（{ev.old_meter_serial}→{ev.new_meter_serial}）且倍率无法由校验记录衔接，"
                    "受影响区间已拆分，禁止生成跨越该断点的可比较事实"
                )
                break

    # 3) 计量边界与策略匹配
    if comparability is None:
        base_cov = _covering_boundaries(db, project_id, _role_baseline(), baseline_start, baseline_end)
        rep_cov = _covering_boundaries(db, project_id, _role_reporting(), reporting_start, reporting_end)

        if strategy == Strategy.strict_direct:
            comparability, boundary_used, reasons2 = _eval_direct(base_cov, rep_cov)
            reasons.extend(reasons2)
            if comparability in (Comparability.comparable, Comparability.restricted_comparable):
                baseline_kwh = sum(_boundary_energy(db, b, baseline_start, baseline_end) for b in base_cov)
                reporting_kwh = sum(_boundary_energy(db, b, reporting_start, reporting_end) for b in rep_cov)
        else:
            comparability, boundary_used, assumptions, reasons2, energy = _eval_allocation(
                db, project_id, strategy, base_cov, rep_cov,
                baseline_start, baseline_end, reporting_start, reporting_end,
            )
            reasons.extend(reasons2)
            if energy is not None:
                baseline_kwh, reporting_kwh = energy

    # 4) 计算节能量
    if baseline_kwh is not None and reporting_kwh is not None:
        savings_kwh = round(baseline_kwh - reporting_kwh, 2)
        savings_rate = round(savings_kwh / baseline_kwh, 4) if baseline_kwh else None

    # 5) 版本链：同一 (项目, 范围关系, 策略) 为一个谱系，新签发取代旧当前/复审中版本
    lineage = (
        db.query(PerformanceFact)
        .filter(
            PerformanceFact.project_id == project_id,
            PerformanceFact.scope_relation_id == scope_relation_id,
            PerformanceFact.strategy == strategy,
        )
        .all()
    )
    version = max((f.version for f in lineage), default=0) + 1
    supersedes_id = None
    for f in lineage:
        if f.status in (FactStatus.current, FactStatus.under_review):
            f.status = FactStatus.superseded
            supersedes_id = f.id

    fact = PerformanceFact(
        project_id=project_id,
        scope_relation_id=scope_relation_id,
        boundary_id=boundary_used.id if boundary_used else None,
        strategy=strategy,
        result_kind=result_kind,
        comparability=comparability,
        status=FactStatus.current,
        version=version,
        supersedes_id=supersedes_id,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        reporting_start=reporting_start,
        reporting_end=reporting_end,
        baseline_kwh=round(baseline_kwh, 2) if baseline_kwh is not None else None,
        reporting_kwh=round(reporting_kwh, 2) if reporting_kwh is not None else None,
        savings_kwh=savings_kwh,
        savings_rate=savings_rate,
        assumptions=assumptions,
        reasons=reasons,
    )
    db.add(fact)
    db.add(AuditLog(actor=actor, action="compile_fact", entity="performance_fact",
                    detail={"project_id": project_id, "scope_relation_id": scope_relation_id,
                            "strategy": strategy.value, "comparability": comparability.value,
                            "version": version}))
    db.flush()
    return fact


def _role_baseline():
    from .models import PeriodRole
    return PeriodRole.baseline


def _role_reporting():
    from .models import PeriodRole
    return PeriodRole.reporting


def _eval_direct(base_cov, rep_cov):
    """严格直接计量：要求专属电表边界完整覆盖基线期与报告期。"""
    reasons: list[str] = []
    if not base_cov or not rep_cov:
        missing = []
        if not base_cov:
            missing.append("基线期")
        if not rep_cov:
            missing.append("报告期")
        reasons.append(f"计量边界缺失：{'、'.join(missing)}无完整覆盖的计量边界")
        return Comparability.incomparable, None, reasons

    all_cov = base_cov + rep_cov
    if any(b.pipeline_kind == PipelineKind.shared for b in all_cov):
        reasons.append("计量边界包含公共管路，无法将读数直接归属改造范围；请改用受控分摊策略")
        return Comparability.incomparable, None, reasons

    boundary_used = base_cov[0]
    strengths = {b.evidence_strength.value for b in all_cov}
    if "weak" in strengths:
        reasons.append("计量边界证据强度为弱，结论受限可比较")
        return Comparability.restricted_comparable, boundary_used, reasons
    reasons.append("专属电表完整覆盖基线期与报告期，证据链短、结论可直接对标")
    return Comparability.comparable, boundary_used, reasons


def _eval_allocation(db, project_id, strategy, base_cov, rep_cov,
                     baseline_start, baseline_end, reporting_start, reporting_end):
    """受控分摊：需要有效分摊声明；按运行时长或面积分摊公共管路能耗。"""
    reasons: list[str] = []
    assumptions: dict = {}
    if not base_cov or not rep_cov:
        reasons.append("计量边界缺失：公共管路边界未完整覆盖基线期或报告期")
        return Comparability.incomparable, None, assumptions, reasons, None

    decl = (
        db.query(EvidenceDocument)
        .filter(
            EvidenceDocument.project_id == project_id,
            EvidenceDocument.doc_type == DocType.allocation_declaration,
            EvidenceDocument.status == EvidenceStatus.active,
        )
        .order_by(EvidenceDocument.version.desc())
        .first()
    )
    if decl is None:
        reasons.append("缺少公共管路分摊声明，无法签发受控分摊事实")
        return Comparability.pending_review, None, assumptions, reasons, None

    method = "runtime" if strategy == Strategy.allocation_runtime else "area"
    zones = decl.payload.get("zones", [])
    target_zone = base_cov[0].zone_name
    key = "runtime_hours" if method == "runtime" else "area_m2"

    mine = total = None
    for z in zones:
        val = z.get(key)
        if val is None:
            continue
        total = (total or 0) + float(val)
        if z.get("zone") == target_zone:
            mine = float(val)

    if mine is None or not total:
        label = "运行时长" if method == "runtime" else "面积"
        reasons.append(f"分摊声明缺少{label}数据，待补齐后方可签发受控分摊事实")
        return Comparability.pending_review, None, assumptions, reasons, None

    share = mine / total
    base_total = sum(_boundary_energy(db, b, baseline_start, baseline_end) for b in base_cov)
    rep_total = sum(_boundary_energy(db, b, reporting_start, reporting_end) for b in rep_cov)
    assumptions = {
        "method": method,
        "share": round(share, 4),
        "basis": {"zone": target_zone, key: mine, f"total_{key}": total},
        "declaration_evidence_id": decl.id,
        "declaration_version": decl.version,
        "review_note": "分摊值含假设差异，使用者需承担复核成本；默认节能对标不采用",
    }
    reasons.append(
        f"公共管路能耗按{'运行时长' if method == 'runtime' else '面积'}分摊（份额 {share:.2%}），"
        "属受控分摊结果，受限可比较"
    )
    return Comparability.restricted_comparable, base_cov[0], assumptions, reasons, (base_total * share, rep_total * share)


# ---------------------------------------------------------------- 序列号冲突检测


def detect_serial_conflicts(db: Session, relation: ScopeRelation) -> list[Conflict]:
    """同一序列号跨项目声明时的冲突/转移待核判定。返回新产生的冲突记录。"""
    if relation.subject_type != SubjectType.equipment or not relation.serial_no:
        return []
    created: list[Conflict] = []
    others = (
        db.query(ScopeRelation)
        .filter(
            ScopeRelation.serial_no == relation.serial_no,
            ScopeRelation.project_id != relation.project_id,
            ScopeRelation.subject_type == SubjectType.equipment,
            ScopeRelation.status.in_([ScopeStatus.candidate, ScopeStatus.confirmed,
                                      ScopeStatus.transfer_pending, ScopeStatus.conflicted]),
        )
        .all()
    )
    if not others:
        return []

    # 移装材料：任一项目持有覆盖该序列号的有效移装材料 → 不标记
    relocation = (
        db.query(EvidenceDocument)
        .filter(
            EvidenceDocument.doc_type == DocType.relocation_material,
            EvidenceDocument.status == EvidenceStatus.active,
        )
        .all()
    )
    has_relocation = any(d.payload.get("serial_no") == relation.serial_no for d in relocation)

    for other in others:
        pair_projects = sorted({relation.project_id, other.project_id})
        overlap = _overlaps(relation.valid_from or datetime.min.replace(tzinfo=timezone.utc),
                            relation.valid_to,
                            other.valid_from or datetime.min.replace(tzinfo=timezone.utc),
                            other.valid_to)
        exclusive = relation.physically_exclusive or other.physically_exclusive

        if overlap and exclusive:
            ctype = ConflictType.duplicate_coverage
            new_status = ScopeStatus.conflicted
            detail = {"reason": "同一设备序列号被两个项目声明，服务区间重叠且设备物理上不能同时安装于两处"}
        elif not overlap and not has_relocation:
            ctype = ConflictType.transfer_pending
            new_status = ScopeStatus.transfer_pending
            detail = {"reason": "服务区间不重叠但缺少移装材料，列为转移待核（不升级为重复主张）"}
        else:
            continue

        exists = (
            db.query(Conflict)
            .filter(Conflict.serial_no == relation.serial_no,
                    Conflict.conflict_type == ctype,
                    Conflict.status == ConflictStatus.open)
            .all()
        )
        if any(sorted(c.project_ids) == pair_projects for c in exists):
            continue

        relation.status = new_status
        other.status = new_status
        conflict = Conflict(
            conflict_type=ctype,
            serial_no=relation.serial_no,
            project_ids=pair_projects,
            scope_relation_ids=[relation.id, other.id],
            detail=detail,
        )
        db.add(conflict)
        db.add(AuditLog(actor="system", action=f"detect_{ctype.value}", entity="scope_relation",
                        entity_id=relation.id, detail={"serial_no": relation.serial_no, **detail}))
        created.append(conflict)
    return created


# ---------------------------------------------------------------- 换表事件


def register_meter_event(
    db: Session,
    project_id: int,
    old_meter_serial: str,
    new_meter_serial: str,
    replaced_at: datetime,
    multiplier_linked: bool,
    calibration_evidence_id: int | None = None,
) -> MeterEvent:
    """登记换表事件，并把受影响计量边界在断点处拆分为新旧两段。"""
    event = MeterEvent(
        project_id=project_id,
        old_meter_serial=old_meter_serial,
        new_meter_serial=new_meter_serial,
        replaced_at=replaced_at,
        multiplier_linked=multiplier_linked,
        calibration_evidence_id=calibration_evidence_id,
    )
    db.add(event)

    boundaries = (
        db.query(MeteringBoundary)
        .filter(MeteringBoundary.project_id == project_id,
                MeteringBoundary.meter_serial == old_meter_serial,
                MeteringBoundary.valid_from < replaced_at)
        .all()
    )
    for b in boundaries:
        if b.valid_to is not None and _aware(b.valid_to) <= _aware(replaced_at):
            continue
        new_segment = MeteringBoundary(
            project_id=b.project_id,
            meter_serial=new_meter_serial,
            branch_name=b.branch_name,
            pipeline_kind=b.pipeline_kind,
            zone_name=b.zone_name,
            period_role=b.period_role,
            valid_from=replaced_at,
            valid_to=b.valid_to,
            multiplier=b.multiplier,
            multiplier_linked=multiplier_linked,
            evidence_strength=b.evidence_strength,
            evidence_ids=b.evidence_ids,
            segment_of_id=b.id,
        )
        b.valid_to = replaced_at
        db.add(new_segment)

    db.add(AuditLog(actor="system", action="register_meter_event", entity="meter_event",
                    detail={"old": old_meter_serial, "new": new_meter_serial,
                            "multiplier_linked": multiplier_linked}))
    db.flush()
    return event


# ---------------------------------------------------------------- 验收附件替换


def apply_evidence_revision(db: Session, old: EvidenceDocument, new: EvidenceDocument) -> list[int]:
    """登记修订链；验收报告附件哈希变化时，引用旧附件的当前事实转入复审中并暂停新引用。

    返回受影响的事实 id 列表。历史（已被取代的）事实保留原附件与结论，不受影响。
    """
    old.status = EvidenceStatus.superseded
    new.version = old.version + 1
    new.supersedes_id = old.id

    affected: list[int] = []
    if old.doc_type == DocType.acceptance_report and old.source_hash != new.source_hash:
        relations = (
            db.query(ScopeRelation)
            .filter(ScopeRelation.relation_kind == RelationKind.acceptance_conclusion)
            .all()
        )
        for rel in relations:
            if old.id not in (rel.evidence_ids or []):
                continue
            facts = (
                db.query(PerformanceFact)
                .filter(PerformanceFact.scope_relation_id == rel.id,
                        PerformanceFact.status == FactStatus.current)
                .all()
            )
            for fact in facts:
                fact.status = FactStatus.under_review
                fact.block_new_citations = True
                affected.append(fact.id)
                db.add(AuditLog(
                    actor="system", action="fact_under_review", entity="performance_fact",
                    entity_id=fact.id,
                    detail={"trigger": "acceptance_attachment_replaced",
                            "old_evidence_id": old.id, "new_evidence_id": new.id,
                            "old_hash": old.source_hash, "new_hash": new.source_hash},
                ))
    db.flush()
    return affected
