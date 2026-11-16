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


class BuildingUse(str, enum.Enum):
    school = "school"        # 学校
    office = "office"        # 办公
    hospital = "hospital"    # 医疗
    library = "library"      # 图书馆
    sports = "sports"        # 体育
    cultural = "cultural"    # 文化


class ClimateZone(str, enum.Enum):
    severe_cold = "severe_cold"                          # 严寒
    cold = "cold"                                        # 寒冷
    hot_summer_cold_winter = "hot_summer_cold_winter"    # 夏热冬冷
    hot_summer_warm_winter = "hot_summer_warm_winter"    # 夏热冬暖
    mild = "mild"                                        # 温和


class OccupancyProfile(str, enum.Enum):
    year_round = "year_round"    # 全年开放
    term_time = "term_time"      # 学期/工作日开放
    seasonal = "seasonal"        # 季节性开放


class RuleStatus(str, enum.Enum):
    draft = "draft"
    active = "active"
    superseded = "superseded"


class WorkspaceStatus(str, enum.Enum):
    draft = "draft"            # 草稿，尚未核验
    computed = "computed"      # 已按固定规则核验
    stale = "stale"            # 条件/规则/来源变化，已过期，待重新核验
    published = "published"    # 已发布清单
    withdrawn = "withdrawn"    # 已撤回


class EdgeLevel(str, enum.Enum):
    comparable = "comparable"              # 共同条件一致，可作为该工作区的比较边
    restricted = "restricted"              # 只能局部比较（条件/范围/覆盖存在限制）
    blocked = "blocked"                    # 不成立：条件缺口、无共同窗口或共用总表


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
    scope_relation_id: Mapped[int | None] = mapped_column(ForeignKey("scope_relations.id"))  # 关联的已确认范围
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


# ---------- 跨项目比较层 ----------


class ComparisonRule(Base):
    """比较规则：登记建筑用途、气候带、占用覆盖、基线长度与允许偏差。

    规则一经激活即不可修改；发布更严格规则时签发新版本并把旧版本标记为 superseded。
    已按旧规则完成的草稿保留原结论并标记过期，不得以新规则名义发布。
    """

    __tablename__ = "comparison_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[RuleStatus] = mapped_column(Enum(RuleStatus), default=RuleStatus.draft, index=True)
    building_use: Mapped[BuildingUse | None] = mapped_column(Enum(BuildingUse))          # None=不限
    climate_zone: Mapped[ClimateZone | None] = mapped_column(Enum(ClimateZone))          # None=不限
    occupancy_profile: Mapped[OccupancyProfile | None] = mapped_column(Enum(OccupancyProfile))  # None=不限
    min_baseline_days: Mapped[int] = mapped_column(Integer, default=300)
    max_baseline_days: Mapped[int] = mapped_column(Integer, default=430)
    date_tolerance_days: Mapped[int] = mapped_column(Integer, default=7)       # 起止日期允许偏差
    occupancy_cover_min: Mapped[float] = mapped_column(Float, default=1.0)     # 占用覆盖下限（占区间比例）
    baseline_length_tolerance_days: Mapped[int] = mapped_column(Integer, default=30)  # 两项目基线长度差容忍
    min_common_window_days: Mapped[int] = mapped_column(Integer, default=150)  # 共同窗口最短天数
    max_area_ratio: Mapped[float] = mapped_column(Float, default=2.0)          # 面积比上限（仅登记为限制，不据此排名）
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    def constraint_signature(self) -> dict:
        """规则参与比较的约束条件签名。"""
        return {
            "rule_code": self.code,
            "rule_version": self.version,
            "building_use": self.building_use.value if self.building_use else None,
            "climate_zone": self.climate_zone.value if self.climate_zone else None,
            "occupancy_profile": self.occupancy_profile.value if self.occupancy_profile else None,
            "min_baseline_days": self.min_baseline_days,
            "max_baseline_days": self.max_baseline_days,
            "date_tolerance_days": self.date_tolerance_days,
            "occupancy_cover_min": self.occupancy_cover_min,
            "baseline_length_tolerance_days": self.baseline_length_tolerance_days,
            "min_common_window_days": self.min_common_window_days,
            "max_area_ratio": self.max_area_ratio,
        }


class ProjectComparisonProfile(Base):
    """项目比较属性：建筑用途、气候带、占用覆盖、面积、尾气/公共负荷说明。"""

    __tablename__ = "project_comparison_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), unique=True, index=True)
    building_use: Mapped[BuildingUse] = mapped_column(Enum(BuildingUse))
    climate_zone: Mapped[ClimateZone] = mapped_column(Enum(ClimateZone))
    occupancy_profile: Mapped[OccupancyProfile] = mapped_column(Enum(OccupancyProfile))
    area_m2: Mapped[float] = mapped_column(Float, default=0.0)
    includes_dining: Mapped[bool] = mapped_column(Boolean, default=False)   # 是否含食堂等附属负荷
    includes_public_load: Mapped[bool] = mapped_column(Boolean, default=False)  # 含公共负荷（照明/电梯等）
    shared_load_keys: Mapped[list] = mapped_column(JSONB, default=list)     # 公共负荷标识（中央空调/集中热水等）
    description: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    project = relationship("Project")


class OccupancyWindow(Base):
    """占用区间：建筑实际开放/使用的时段，用于计算占用覆盖。"""

    __tablename__ = "occupancy_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    label: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MeterCoverageWindow(Base):
    """计量覆盖区间：某电表在某区间内可由可核验读数/倍率补证覆盖。

    independent=True 表示该项目有独立读数或分配依据；False 表示与其他项目共用同一总表。
    共用总表且 has_allocation_basis=False 时，不得作为两份独立样本参与同一条比较边。
    """

    __tablename__ = "meter_coverage_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    meter_serial: Mapped[str] = mapped_column(String(120), index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    independent: Mapped[bool] = mapped_column(Boolean, default=True)
    has_allocation_basis: Mapped[bool] = mapped_column(Boolean, default=False)
    verified: Mapped[bool] = mapped_column(Boolean, default=True)  # 读数/倍率是否可核验；False 只登记不进入候选
    shared_with_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"))
    evidence_ids: Mapped[list] = mapped_column(JSONB, default=list)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComparisonWorkspace(Base):
    """比较工作区：固定一批项目、资料截止点与所选规则版本。"""

    __tablename__ = "comparison_workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    rule_id: Mapped[int] = mapped_column(ForeignKey("comparison_rules.id"))
    rule_version: Mapped[int] = mapped_column(Integer, default=1)   # 创建时冻结的规则版本
    project_ids: Mapped[list] = mapped_column(JSONB, default=list)
    material_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 资料截止点
    status: Mapped[WorkspaceStatus] = mapped_column(Enum(WorkspaceStatus), default=WorkspaceStatus.draft, index=True)
    input_digest: Mapped[str | None] = mapped_column(String(64))     # 核验时的输入快照指纹
    stale_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rule = relationship("ComparisonRule")


class ComparisonEdge(Base):
    """项目对比较边：记录共同条件、共同窗口、排除区间及结论。

    可比关系不传递：只登记实际计算出的项目对，不推导未计算的对。
    """

    __tablename__ = "comparison_edges"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("comparison_workspaces.id"), index=True)
    project_a_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    project_b_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    level: Mapped[EdgeLevel] = mapped_column(Enum(EdgeLevel), default=EdgeLevel.blocked, index=True)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False)  # comparable/restricted 时为 True
    consecutive: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否由直接相邻计算得出
    on_global_intersection: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否落在全组公共交集
    stale: Mapped[bool] = mapped_column(Boolean, default=False)     # 来源更正后该边失效
    stale_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    signatures: Mapped[dict] = mapped_column(JSONB, default=dict)   # 双方条件签名
    window: Mapped[dict] = mapped_column(JSONB, default=dict)       # 共同窗口={baseline, reporting}
    exclusions: Mapped[list] = mapped_column(JSONB, default=list)   # 排除区间与原因
    limitations: Mapped[list] = mapped_column(JSONB, default=list)  # 限制（非排除）
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    inputs: Mapped[dict] = mapped_column(JSONB, default=dict)       # 可回查的双方输入快照
    supported_analysis: Mapped[list] = mapped_column(JSONB, default=list)  # 该结果能支持的分析类型
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComparisonCohort(Base):
    """全组统一队列：仅在所有项目共同交集上建立，附每项排除/限制说明。"""

    __tablename__ = "comparison_cohorts"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("comparison_workspaces.id"), unique=True, index=True)
    intersection: Mapped[dict] = mapped_column(JSONB, default=dict)
    members: Mapped[list] = mapped_column(JSONB, default=list)
    excluded_projects: Mapped[list] = mapped_column(JSONB, default=list)
    limitations: Mapped[list] = mapped_column(JSONB, default=list)
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComparisonProjectStatus(Base):
    """全组队列中每个项目的状态：入选 / 排除 / 限制交集，并说明压缩的日期范围。"""

    __tablename__ = "comparison_project_statuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("comparison_workspaces.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    in_cohort: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(32), default="excluded")  # member/excluded/limiter
    reasons: Mapped[list] = mapped_column(JSONB, default=list)
    effect: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComparisonSourceAncestry(Base):
    """比较边的来源血缘：记录该边引用的范围/边界/覆盖/占用登记，便于按来源定位比较边。"""

    __tablename__ = "comparison_source_ancestry"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("comparison_workspaces.id"), index=True)
    edge_id: Mapped[int | None] = mapped_column(ForeignKey("comparison_edges.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(32))  # scope_relation/boundary/coverage/occupancy/evidence
    source_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ComparisonPublication(Base):
    """已发布比较清单：冻结分母与被排除项，新版本说明新增、失效与受限的项目对。"""

    __tablename__ = "comparison_publications"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("comparison_workspaces.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    rule_id: Mapped[int] = mapped_column(ForeignKey("comparison_rules.id"))
    rule_version: Mapped[int] = mapped_column(Integer, default=1)
    project_ids: Mapped[list] = mapped_column(JSONB, default=list)
    material_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    edges_snapshot: Mapped[list] = mapped_column(JSONB, default=list)
    cohort_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    diff_from_previous: Mapped[dict] = mapped_column(JSONB, default=dict)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)     # 来源更正后标记过期，但保留原分母
    stale_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    published_by: Mapped[str] = mapped_column(String(64), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

