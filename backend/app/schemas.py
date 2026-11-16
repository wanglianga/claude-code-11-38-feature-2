"""API 入参/出参模式。"""

from datetime import datetime

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    token: str
    username: str
    display_name: str
    role: str


class ProjectIn(BaseModel):
    code: str
    name: str
    building_name: str
    owner_org: str


class EvidenceIn(BaseModel):
    project_id: int
    doc_type: str
    title: str
    event_time: datetime
    payload: dict = Field(default_factory=dict)
    supersedes_id: int | None = None  # 修订：指向被取代的证据


class ScopeRelationIn(BaseModel):
    project_id: int
    relation_kind: str
    subject_type: str
    subject_ref: str
    serial_no: str | None = None
    status: str = "candidate"
    coverage_note: str = ""
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    physically_exclusive: bool = True
    evidence_ids: list[int] = Field(default_factory=list)


class BoundaryIn(BaseModel):
    project_id: int
    meter_serial: str
    branch_name: str = ""
    pipeline_kind: str = "dedicated"
    zone_name: str = ""
    period_role: str = "baseline"
    valid_from: datetime
    valid_to: datetime | None = None
    multiplier: float = 1.0
    multiplier_linked: bool = True
    evidence_strength: str = "moderate"
    evidence_ids: list[int] = Field(default_factory=list)


class MeterEventIn(BaseModel):
    project_id: int
    old_meter_serial: str
    new_meter_serial: str
    replaced_at: datetime
    multiplier_linked: bool = False
    calibration_evidence_id: int | None = None


class CompileIn(BaseModel):
    project_id: int
    scope_relation_id: int
    strategy: str
    baseline_start: datetime
    baseline_end: datetime
    reporting_start: datetime
    reporting_end: datetime


class CitationIn(BaseModel):
    fact_id: int
    consumer_type: str = "analysis"  # analysis / audit_view
    consumer_name: str
    purpose: str = ""


# ---------- 跨项目比较 ----------


class ComparisonRuleIn(BaseModel):
    code: str
    building_use: str | None = None
    climate_zone: str | None = None
    occupancy_profile: str | None = None
    min_baseline_days: int = 300
    max_baseline_days: int = 430
    date_tolerance_days: int = 7
    occupancy_cover_min: float = 1.0
    baseline_length_tolerance_days: int = 30
    min_common_window_days: int = 150
    max_area_ratio: float = 2.0
    notes: str = ""


class ComparisonProfileIn(BaseModel):
    building_use: str
    climate_zone: str
    occupancy_profile: str
    area_m2: float = 0.0
    includes_dining: bool = False
    includes_public_load: bool = False
    shared_load_keys: list[str] = Field(default_factory=list)
    description: str = ""


class OccupancyWindowIn(BaseModel):
    project_id: int
    valid_from: datetime
    valid_to: datetime
    label: str = ""


class MeterCoverageWindowIn(BaseModel):
    project_id: int
    meter_serial: str
    valid_from: datetime
    valid_to: datetime
    independent: bool = True
    has_allocation_basis: bool = False
    verified: bool = True
    shared_with_project_id: int | None = None
    evidence_ids: list[int] = Field(default_factory=list)
    note: str = ""


class WorkspaceIn(BaseModel):
    code: str
    title: str
    rule_id: int
    project_ids: list[int]
    material_cutoff: datetime
    compute: bool = True  # 创建后立即核验


class WorkspaceUpdateIn(BaseModel):
    title: str | None = None
    rule_id: int | None = None
    project_ids: list[int] | None = None
    material_cutoff: datetime | None = None
    reason: str = ""


class SourceCorrectionIn(BaseModel):
    project_ids: list[int]
    source_ref: str
    evidence_id: int | None = None
    source_types: list[str] = Field(default_factory=list)
    source_ids: list[int] = Field(default_factory=list)
