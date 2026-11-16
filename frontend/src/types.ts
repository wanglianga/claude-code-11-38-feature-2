export interface Project {
  id: number
  code: string
  name: string
  building_name: string
  owner_org: string
  created_at: string
}

export interface EvidenceDoc {
  id: number
  project_id: number
  doc_type: string
  title: string
  source_hash: string
  event_time: string
  received_at: string
  version: number
  supersedes_id: number | null
  status: string
  payload: Record<string, any>
  affected_fact_ids?: number[]
}

export interface ScopeRelation {
  id: number
  project_id: number
  relation_kind: string
  subject_type: string
  subject_ref: string
  serial_no: string | null
  status: string
  coverage_note: string
  valid_from: string | null
  valid_to: string | null
  physically_exclusive: boolean
  evidence_ids: number[]
  new_conflicts?: Conflict[]
}

export interface Boundary {
  id: number
  project_id: number
  meter_serial: string
  branch_name: string
  pipeline_kind: string
  zone_name: string
  period_role: string
  valid_from: string
  valid_to: string | null
  multiplier: number
  multiplier_linked: boolean
  evidence_strength: string
  segment_of_id: number | null
  evidence_ids: number[]
}

export interface MeterEvent {
  id: number
  project_id: number
  old_meter_serial: string
  new_meter_serial: string
  replaced_at: string
  multiplier_linked: boolean
}

export interface Fact {
  id: number
  project_id: number
  scope_relation_id: number
  boundary_id: number | null
  strategy: string
  result_kind: string
  comparability: string
  status: string
  version: number
  supersedes_id: number | null
  baseline_start: string
  baseline_end: string
  reporting_start: string
  reporting_end: string
  baseline_kwh: number | null
  reporting_kwh: number | null
  savings_kwh: number | null
  savings_rate: number | null
  assumptions: Record<string, any>
  reasons: string[]
  block_new_citations: boolean
  issued_at: string
  project_code?: string
  project_name?: string
}

export interface Conflict {
  id: number
  conflict_type: string
  serial_no: string
  project_ids: number[]
  scope_relation_ids: number[]
  detail: Record<string, any>
  status: string
  created_at: string
}

export interface Citation {
  id: number
  fact_id: number
  fact_version: number
  consumer_type: string
  consumer_name: string
  purpose: string
  created_by: string
  created_at: string
}

export interface FactTrace {
  fact: Fact
  scope_relation: ScopeRelation | null
  scope_evidence: EvidenceDoc[]
  boundary: Boundary | null
  boundary_evidence: EvidenceDoc[]
  allocation_declaration: EvidenceDoc | null
  strategy: string
  assumptions: Record<string, any>
  version_chain: Fact[]
  citations: Citation[]
  meter_events: MeterEvent[]
}

// ---------- 跨项目比较 ----------

export interface ComparisonRule {
  id: number
  code: string
  version: number
  status: string
  building_use: string | null
  climate_zone: string | null
  occupancy_profile: string | null
  min_baseline_days: number
  max_baseline_days: number
  date_tolerance_days: number
  occupancy_cover_min: number
  baseline_length_tolerance_days: number
  min_common_window_days: number
  max_area_ratio: number
  notes: string
  created_by: string
  created_at: string
  stale_workspaces?: { workspace_id: number; code: string; status: string }[]
}

export interface IntervalDto {
  start: string | null
  end: string | null
}

export interface ComparisonEdge {
  id: number
  workspace_id: number
  project_a_id: number
  project_b_id: number
  project_a_code?: string
  project_b_code?: string
  level: string
  eligible: boolean
  on_global_intersection: boolean
  stale: boolean
  stale_reasons: any[]
  signatures: Record<string, any>
  window: {
    baseline: IntervalDto
    reporting: IntervalDto
    candidate_baseline: IntervalDto[]
    candidate_reporting: IntervalDto[]
    considered_windows: any[]
  }
  exclusions: any[]
  limitations: string[]
  reasons: string[]
  inputs: Record<string, any>
  supported_analysis: string[]
  rule_version: number
  computed_at: string
}

export interface CohortProjectStatus {
  project_id: number
  project_code?: string
  in_cohort: boolean
  status: string
  reasons: string[]
  effect: string
}

export interface ComparisonCohort {
  id: number
  workspace_id: number
  intersection: {
    baseline: IntervalDto[]
    reporting: IntervalDto[]
    raw_baseline?: IntervalDto[]
    raw_reporting?: IntervalDto[]
    limiters?: { project_id: number; days_gained_if_removed: number; reason: string }[]
    shared_notes?: any[]
  }
  members: { project_id: number; signature: Record<string, any> }[]
  excluded_projects: any[]
  limitations: string[]
  reasons: string[]
  rule_version: number
  computed_at: string
  project_statuses?: CohortProjectStatus[]
}

export interface ComparisonPublication {
  id: number
  workspace_id: number
  version: number
  rule_id: number
  rule_version: number
  project_ids: number[]
  material_cutoff: string
  edges_snapshot: any[]
  cohort_snapshot: any
  diff_from_previous: {
    added: any[]
    dropped: any[]
    restricted: any[]
    base_version: number | null
  }
  stale: boolean
  stale_reasons: any[]
  published_by: string
  published_at: string
}

export interface ComparisonWorkspace {
  id: number
  code: string
  title: string
  rule_id: number
  rule_version: number
  rule_current_version: number | null
  project_ids: number[]
  project_codes?: string[]
  material_cutoff: string
  status: string
  input_digest: string | null
  input_changed: boolean
  rule_superseded: boolean
  stale_reasons: any[]
  created_by: string
  created_at: string
  computed_at: string | null
  rule?: ComparisonRule
  edges?: ComparisonEdge[]
  cohort?: ComparisonCohort | null
  publications?: ComparisonPublication[]
}

export interface EdgeTrace {
  edge: ComparisonEdge
  workspace: ComparisonWorkspace
  rule: ComparisonRule
  cohort: ComparisonCohort | null
  project_a: { id: number; code: string }
  project_b: { id: number; code: string }
  inputs: Record<string, any>
  intersection: IntervalDto[]
  common_independent_intersection: IntervalDto[]
  exclusions: any[]
  limitations: string[]
  reasons: string[]
  supported_analysis: string[]
  recomputed_matches: boolean | null
  note: string
}
