// 枚举 → 中文标签与标签颜色
export const labels: Record<string, Record<string, string>> = {
  doc_type: {
    approval_material: '审批资料', contract_item: '合同条目', equipment_space_list: '设备/空间清单',
    acceptance_report: '验收报告', meter_serial_record: '仪表序列', meter_reading: '读数原文',
    building_master: '建筑主数据', relocation_material: '移装材料', calibration_record: '校验记录',
    allocation_declaration: '分摊声明',
  },
  relation_kind: {
    contract_commitment: '合同承诺', installed_evidence: '实装证据', acceptance_conclusion: '验收结论',
  },
  subject_type: { space: '空间', equipment: '设备' },
  scope_status: {
    candidate: '候选', confirmed: '已确认', conflicted: '冲突', transfer_pending: '转移待核',
  },
  pipeline_kind: { dedicated: '专属', shared: '公共管路' },
  period_role: { baseline: '基线期', reporting: '报告期' },
  evidence_strength: { strong: '强', moderate: '中', weak: '弱' },
  strategy: {
    strict_direct: '严格直接计量', allocation_runtime: '受控分摊·运行时长', allocation_area: '受控分摊·面积',
  },
  result_kind: { direct_metering: '直接计量', controlled_allocation: '受控分摊' },
  comparability: {
    comparable: '可比较', restricted_comparable: '受限可比较',
    pending_review: '待复核', incomparable: '不可比较',
  },
  fact_status: { current: '当前', superseded: '历史版本', under_review: '复审中' },
  evidence_status: { active: '有效', superseded: '已被取代' },
  conflict_type: { duplicate_coverage: '重复覆盖冲突', transfer_pending: '转移待核' },
  conflict_status: { open: '未处理', resolved: '已解决' },
  building_use: {
    school: '学校', office: '办公', hospital: '医疗', library: '图书馆',
    sports: '体育', cultural: '文化',
  },
  climate_zone: {
    severe_cold: '严寒', cold: '寒冷', hot_summer_cold_winter: '夏热冬冷',
    hot_summer_warm_winter: '夏热冬暖', mild: '温和',
  },
  occupancy_profile: { year_round: '全年开放', term_time: '学期/工作日', seasonal: '季节性' },
  rule_status: { draft: '草稿', active: '生效', superseded: '已被取代' },
  workspace_status: {
    draft: '草稿', computed: '已核验', stale: '已过期', published: '已发布', withdrawn: '已撤回',
  },
  edge_level: { comparable: '可比', restricted: '受限可比', blocked: '不可比' },
  cohort_status: { member: '入选', excluded: '已排除', limiter: '限制交集' },
  analysis_type: {
    pairwise_scope_check: '项目对范围核验',
    evidence_coverage_check: '证据覆盖核验',
    local_scope_compare: '局部范围对照',
    conditional_local_compare: '附条件局部对照',
    scope_gap_analysis: '范围缺口分析',
  },
}

export function L(group: string, key: string | null | undefined): string {
  if (!key) return '-'
  return labels[group]?.[key] ?? key
}

export function tagType(group: string, key: string | null | undefined): string {
  const map: Record<string, Record<string, string>> = {
    comparability: {
      comparable: 'success', restricted_comparable: 'warning',
      pending_review: 'info', incomparable: 'danger',
    },
    fact_status: { current: 'success', superseded: 'info', under_review: 'danger' },
    scope_status: {
      candidate: 'info', confirmed: 'success', conflicted: 'danger', transfer_pending: 'warning',
    },
    conflict_type: { duplicate_coverage: 'danger', transfer_pending: 'warning' },
    result_kind: { direct_metering: 'primary', controlled_allocation: 'warning' },
    pipeline_kind: { dedicated: 'success', shared: 'warning' },
    evidence_strength: { strong: 'success', moderate: 'primary', weak: 'danger' },
    edge_level: { comparable: 'success', restricted: 'warning', blocked: 'danger' },
    workspace_status: {
      draft: 'info', computed: 'primary', stale: 'danger', published: 'success', withdrawn: 'info',
    },
    rule_status: { draft: 'info', active: 'success', superseded: 'info' },
    cohort_status: { member: 'success', excluded: 'danger', limiter: 'warning' },
  }
  return map[group]?.[key ?? ''] ?? 'info'
}

export function fmtDt(s: string | null | undefined): string {
  if (!s) return '-'
  return s.slice(0, 10)
}

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return '-'
  return n.toLocaleString('zh-CN')
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined) return '-'
  return (n * 100).toFixed(1) + '%'
}
