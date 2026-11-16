"""数据模型：证据受理库 / 改造范围册 / 计量边界册 / 绩效事实 / 引用簿 / 冲突与换表事件。"""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------- 枚举 ----------


class DocType(str, enum.Enum):
    approval_material = "approval_material"          # 审批资料
    contract_item = "contract_item"                  # 合同条目
    equipment_space_list = "equipment_space_list"    # 设备/空间清单
    acceptance_report = "acceptance_report"          # 验收报告
    meter_serial_record = "meter_serial_record"      # 仪表序列
    meter_reading = "meter_reading"                  # 读数原文
    building_master = "building_master"              # 建筑主数据
    relocation_material = "relocation_material"      # 移装材料
    calibration_record = "calibration_record"        # 校验记录
    allocation_declaration = "allocation_declaration"  # 分摊声明


class EvidenceStatus(str, enum.Enum):
    active = "active"
    superseded = "superseded"   # 被修订链上的新版本取代


class RelationKind(str, enum.Enum):
    contract_commitment = "contract_commitment"      # 合同承诺
    installed_evidence = "installed_evidence"        # 实装证据
    acceptance_conclusion = "acceptance_conclusion"  # 验收结论


class SubjectType(str, enum.Enum):
    space = "space"
    equipment = "equipment"


class ScopeStatus(str, enum.Enum):
    candidate = "candidate"                # 候选
    confirmed = "confirmed"                # 已确认
    conflicted = "conflicted"              # 冲突（重复覆盖）
    transfer_pending = "transfer_pending"  # 转移待核


class PipelineKind(str, enum.Enum):
    dedicated = "dedicated"  # 专属电表/支路
    shared = "shared"        # 公共管路


class PeriodRole(str, enum.Enum):
    baseline = "baseline"
    reporting = "reporting"


class EvidenceStrength(str, enum.Enum):
    strong = "strong"
    moderate = "moderate"
    weak = "weak"


class Strategy(str, enum.Enum):
    strict_direct = "strict_direct"          # 严格直接计量
    allocation_runtime = "allocation_runtime"  # 按运行时长受控分摊
    allocation_area = "allocation_area"        # 按面积受控分摊


class ResultKind(str, enum.Enum):
    direct_metering = "direct_metering"
    controlled_allocation = "controlled_allocation"


class Comparability(str, enum.Enum):
    comparable = "comparable"                      # 可比较
    restricted_comparable = "restricted_comparable"  # 受限可比较
    pending_review = "pending_review"              # 待复核
    incomparable = "incomparable"                  # 不可比较


class FactStatus(str, enum.Enum):
    current = "current"          # 当前签发版本
    superseded = "superseded"    # 历史版本（被新签发取代）
    under_review = "under_review"  # 复审中（验收附件被替换等）


class ConflictType(str, enum.Enum):
    duplicate_coverage = "duplicate_coverage"  # 重复覆盖冲突
    transfer_pending = "transfer_pending"      # 转移待核


class ConflictStatus(str, enum.Enum):
    open = "open"
    resolved = "resolved"


# ---------- 用户与项目 ----------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32), default="analyst")  # admin/auditor/analyst
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    building_name: Mapped[str] = mapped_column(String(200))
    owner_org: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------- 证据受理库 ----------


class EvidenceDocument(Base):
    """证据受理库：保留来源哈希、事件时间、接收时间、签发版本与修订链。"""

    __tablename__ = "evidence_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    doc_type: Mapped[DocType] = mapped_column(Enum(DocType), index=True)
    title: Mapped[str] = mapped_column(String(300))
    source_hash: Mapped[str] = mapped_column(String(64), index=True)  # sha256(canonical payload)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))      # 事件时间
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)  # 接收时间
    version: Mapped[int] = mapped_column(Integer, default=1)                   # 签发版本
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_documents.id"))
    status: Mapped[EvidenceStatus] = mapped_column(Enum(EvidenceStatus), default=EvidenceStatus.active)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")


# ---------- 改造范围册 ----------


class ScopeRelation(Base):
    """改造范围册：合同承诺 / 实装证据 / 验收结论 三类来源分别登记的空间/设备覆盖关系。"""

    __tablename__ = "scope_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    relation_kind: Mapped[RelationKind] = mapped_column(Enum(RelationKind), index=True)
    subject_type: Mapped[SubjectType] = mapped_column(Enum(SubjectType))
    subject_ref: Mapped[str] = mapped_column(String(200), index=True)  # 空间编码或设备位号
    serial_no: Mapped[str | None] = mapped_column(String(120), index=True)  # 设备序列号
    status: Mapped[ScopeStatus] = mapped_column(Enum(ScopeStatus), default=ScopeStatus.candidate, index=True)
    coverage_note: Mapped[str] = mapped_column(Text, default="")
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 服务区间起
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))    # 服务区间止（None=至今）
    physically_exclusive: Mapped[bool] = mapped_column(Boolean, default=True)     # 物理上不可同时安装两处
    evidence_ids: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project = relationship("Project")


# ---------- 计量边界册 ----------


class MeteringBoundary(Base):
    """计量边界册：电表/支路/公共管路/建筑区域在基线期与报告期的有效区间及证据强度。"""

    __tablename__ = "metering_boundaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    meter_serial: Mapped[str] = mapped_column(String(120), index=True)
    branch_name: Mapped[str] = mapped_column(String(200), default="")
    pipeline_kind: Mapped[PipelineKind] = mapped_column(Enum(PipelineKind), index=True)
    zone_name: Mapped[str] = mapped_column(String(200), default="")
    period_role: Mapped[PeriodRole] = mapped_column(Enum(PeriodRole))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    multiplier_linked: Mapped[bool] = mapped_column(Boolean, default=True)  # 倍率是否经校验记录衔接
    evidence_strength: Mapped[EvidenceStrength] = mapped_column(Enum(EvidenceStrength), default=EvidenceStrength.moderate)
    evidence_ids: Mapped[list] = mapped_column(JSONB, default=list)
    segment_of_id: Mapped[int | None] = mapped_column(ForeignKey("metering_boundaries.id"))  # 换表拆分来源
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")


class MeterEvent(Base):
    """换表事件：倍率无法衔接时形成断点，禁止生成跨越断点的可比较事实。"""

    __tablename__ = "meter_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    old_meter_serial: Mapped[str] = mapped_column(String(120))
    new_meter_serial: Mapped[str] = mapped_column(String(120))
    replaced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    multiplier_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    calibration_evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_documents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---------- 绩效事实 ----------


class PerformanceFact(Base):
    """绩效事实：编译器签发，带比较级别、策略、假设、版本链与状态。"""

    __tablename__ = "performance_facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    scope_relation_id: Mapped[int] = mapped_column(ForeignKey("scope_relations.id"))
    boundary_id: Mapped[int | None] = mapped_column(ForeignKey("metering_boundaries.id"))
    strategy: Mapped[Strategy] = mapped_column(Enum(Strategy))
    result_kind: Mapped[ResultKind] = mapped_column(Enum(ResultKind), index=True)
    comparability: Mapped[Comparability] = mapped_column(Enum(Comparability), index=True)
    status: Mapped[FactStatus] = mapped_column(Enum(FactStatus), default=FactStatus.current, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("performance_facts.id"))
    baseline_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    baseline_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reporting_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reporting_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    baseline_kwh: Mapped[float | None] = mapped_column(Float)
    reporting_kwh: Mapped[float | None] = mapped_column(Float)
    savings_kwh: Mapped[float | None] = mapped_column(Float)
    savings_rate: Mapped[float | None] = mapped_column(Float)
    assumptions: Mapped[dict] = mapped_column(JSONB, default=dict)  # 分摊方法/时长/面积等
    reasons: Mapped[list] = mapped_column(JSONB, default=list)      # 比较级别判定理由
    block_new_citations: Mapped[bool] = mapped_column(Boolean, default=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project = relationship("Project")
    scope_relation = relationship("ScopeRelation")
    boundary = relationship("MeteringBoundary")


class Citation(Base):
    """引用簿：记录哪些分析/审计视图使用了哪个版本的事实。"""

    __tablename__ = "citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("performance_facts.id"), index=True)
    fact_version: Mapped[int] = mapped_column(Integer)
    consumer_type: Mapped[str] = mapped_column(String(32))  # analysis / audit_view
    consumer_name: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    fact = relationship("PerformanceFact")


class Conflict(Base):
    """范围冲突/待核清单。"""

    __tablename__ = "conflicts"

    id: Mapped[int] = mapped_column(primary_key=True)
    conflict_type: Mapped[ConflictType] = mapped_column(Enum(ConflictType), index=True)
    serial_no: Mapped[str] = mapped_column(String(120), index=True)
    project_ids: Mapped[list] = mapped_column(JSONB, default=list)
    scope_relation_ids: Mapped[list] = mapped_column(JSONB, default=list)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[ConflictStatus] = mapped_column(Enum(ConflictStatus), default=ConflictStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """关键状态变更审计（附件替换触发复审等）。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(120))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
