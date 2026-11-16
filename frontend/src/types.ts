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
