<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { auth } from '../store'
import { L, tagType, fmtDt } from '../labels'
import type {
  ComparisonCohort, ComparisonEdge, ComparisonPublication, ComparisonRule,
  ComparisonWorkspace, EdgeTrace, Project,
} from '../types'

const projects = ref<Project[]>([])
const rules = ref<ComparisonRule[]>([])
const workspaces = ref<ComparisonWorkspace[]>([])
const selectedId = ref<number | null>(null)
const detail = ref<ComparisonWorkspace | null>(null)
const loading = ref(true)

const codeOf = (id: number) => projects.value.find(p => p.id === id)?.code ?? String(id)
const pName = (id: number) => projects.value.find(p => p.id === id)?.name ?? String(id)

const activeRules = computed(() => rules.value.filter(r => r.status === 'active'))

async function loadAll() {
  loading.value = true
  projects.value = await api.get<Project[]>('/api/projects')
  rules.value = await api.get<ComparisonRule[]>('/api/comparisons/rules')
  workspaces.value = await api.get<ComparisonWorkspace[]>('/api/comparisons/workspaces')
  if (!selectedId.value && workspaces.value.length) selectedId.value = workspaces.value[0].id
  if (selectedId.value) await loadDetail(selectedId.value)
  loading.value = false
}

async function loadDetail(id: number) {
  detail.value = await api.get<ComparisonWorkspace>(`/api/comparisons/workspaces/${id}`)
}

async function select(id: number) {
  selectedId.value = id
  await loadDetail(id)
}

onMounted(loadAll)

// ---------- 规则登记 / 发布 ----------
const ruleVisible = ref(false)
const ruleForm = reactive({
  code: 'CMP-SCHOOL', building_use: 'school', climate_zone: 'hot_summer_cold_winter',
  occupancy_profile: 'term_time', min_baseline_days: 300, max_baseline_days: 430,
  date_tolerance_days: 7, occupancy_cover_min: 0.85, baseline_length_tolerance_days: 30,
  min_common_window_days: 180, max_area_ratio: 1.5, notes: '',
})

async function registerRule() {
  try {
    await api.post('/api/comparisons/rules', { ...ruleForm })
    ElMessage.success('规则草稿已登记（草稿不参与发布）')
    ruleVisible.value = false
    await loadAll()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function publishStricter(rule: ComparisonRule) {
  try {
    const { value } = await ElMessageBox.prompt(
      `将发布 ${rule.code} 的更新版本（当前 v${rule.version}）。可修改占用覆盖下限等阈值。`,
      '发布更严格规则', { inputValue: String(Math.min(0.99, rule.occupancy_cover_min + 0.1)) })
    const cover = Number(value)
    if (Number.isNaN(cover) || cover < 0 || cover > 1) throw new Error('占用覆盖需在 0~1 之间')
    const res = await api.post(`/api/comparisons/rules/${rule.id}/publish`, {
      code: rule.code, occupancy_cover_min: cover,
      notes: `占用覆盖不低于 ${(cover * 100).toFixed(0)}%`,
    }) as ComparisonRule
    ElMessage.success(`已发布 v${res.version}；${res.stale_workspaces?.length ?? 0} 个工作区按原规则完成并标记过期`)
    await loadAll()
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}

// ---------- 工作区操作 ----------
const wsVisible = ref(false)
const wsForm = reactive({
  code: '', title: '', rule_id: undefined as number | undefined,
  project_ids: [] as number[], material_cutoff: '2026-06-30',
})
const editVisible = ref(false)
const editForm = reactive({
  title: '', rule_id: undefined as number | undefined,
  project_ids: [] as number[], material_cutoff: '', reason: '',
})

function openCreate() {
  wsForm.code = ''
  wsForm.title = ''
  wsForm.rule_id = activeRules.value[0]?.id
  wsForm.project_ids = []
  wsForm.material_cutoff = '2026-06-30'
  wsVisible.value = true
}

async function createWorkspace() {
  try {
    const ws = await api.post<ComparisonWorkspace>('/api/comparisons/workspaces', {
      code: wsForm.code, title: wsForm.title, rule_id: wsForm.rule_id,
      project_ids: wsForm.project_ids,
      material_cutoff: `${wsForm.material_cutoff}T00:00:00Z`,
      compute: true,
    })
    ElMessage.success(`工作区已建立并按规则核验：${ws.edges?.length ?? 0} 条比较边`)
    wsVisible.value = false
    await loadAll()
    await select(ws.id)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

function openEdit() {
  if (!detail.value) return
  editForm.title = detail.value.title
  editForm.rule_id = detail.value.rule_id
  editForm.project_ids = [...detail.value.project_ids]
  editForm.material_cutoff = fmtDt(detail.value.material_cutoff)
  editForm.reason = ''
  editVisible.value = true
}

async function saveEdit() {
  if (!detail.value) return
  try {
    const ws = await api.patch<ComparisonWorkspace>(`/api/comparisons/workspaces/${detail.value.id}`, {
      title: editForm.title, rule_id: editForm.rule_id,
      project_ids: editForm.project_ids,
      material_cutoff: `${editForm.material_cutoff}T00:00:00Z`,
      reason: editForm.reason || '条件变更',
    })
    ElMessage.warning(`条件已更新，旧资格已作废（状态：${L('workspace_status', ws.status)}），请重新核验`)
    editVisible.value = false
    await loadAll()
    await select(ws.id)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function compute() {
  if (!detail.value) return
  try {
    const ws = await api.post<ComparisonWorkspace>(`/api/comparisons/workspaces/${detail.value.id}/compute`)
    ElMessage.success(`已重新核验：${ws.edges?.length ?? 0} 条比较边`)
    await loadAll()
    await select(ws.id)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function buildCohort() {
  if (!detail.value) return
  try {
    await api.post<ComparisonCohort>(`/api/comparisons/workspaces/${detail.value.id}/cohort`)
    ElMessage.success('已求出全组共同交集并建立统一队列')
    await select(detail.value.id)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function publish() {
  if (!detail.value) return
  try {
    const pub = await api.post<ComparisonPublication>(
      `/api/comparisons/workspaces/${detail.value.id}/publish`)
    ElMessage.success(`已发布比较清单 v${pub.version}`)
    await loadAll()
    await select(detail.value.id)
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function withdraw() {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm('撤回后工作区不再可用，已发布清单保留原分母。确认撤回？', '撤回工作区')
    await api.post(`/api/comparisons/workspaces/${detail.value.id}/withdraw`)
    ElMessage.success('已撤回')
    await loadAll()
    await select(detail.value.id)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}

async function removeProject(pid: number) {
  if (!detail.value) return
  try {
    await ElMessageBox.confirm(`移除项目 ${codeOf(pid)}？移除后需重新核验，未受影响的比较仍可使用。`, '项目退出')
    await api.delete(`/api/comparisons/workspaces/${detail.value.id}/projects/${pid}`)
    ElMessage.warning('项目已退出，旧资格作废，请重新核验')
    await loadAll()
    await select(detail.value.id)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}

async function reportCorrection() {
  if (!detail.value) return
  try {
    const { value } = await ElMessageBox.prompt(
      '输入资料更正说明（将按来源定位比较边，再重新检查涉及队列）', '登记资料目录更正',
      { inputValue: '材料目录更正：读数/边界资料修订' })
    const pid = detail.value.project_ids[0]
    await api.post('/api/comparisons/corrections', {
      project_ids: [pid], source_ref: value || 'manual-correction',
    })
    ElMessage.warning('已登记更正：涉及项目的比较边失效，未受影响的项目对保留')
    await loadAll()
    await select(detail.value.id)
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}

// ---------- 比较边详情 ----------
const traceVisible = ref(false)
const trace = ref<EdgeTrace | null>(null)
const traceLoading = ref(false)

async function openTrace(edge: ComparisonEdge) {
  traceLoading.value = true
  traceVisible.value = true
  try {
    trace.value = await api.get<EdgeTrace>(`/api/comparisons/edges/${edge.id}/trace`)
  } catch (e: any) {
    ElMessage.error(e.message)
  } finally {
    traceLoading.value = false
  }
}

const ivText = (iv: { start: string | null; end: string | null }) =>
  iv?.start ? `${fmtDt(iv.start)} ~ ${fmtDt(iv.end)}` : '-'
const ivList = (list: { start: string | null; end: string | null }[] | undefined) =>
  list && list.length ? list.map(ivText).join('；') : '-'

const levelCount = computed(() => {
  const c = { comparable: 0, restricted: 0, blocked: 0 }
  for (const e of detail.value?.edges ?? []) c[e.level as keyof typeof c]++
  return c
})
</script>

<template>
  <div v-loading="loading">
    <el-alert type="info" :closable="false" show-icon style="margin-bottom: 14px"
              title="跨项目比较只判断比较范围与证据覆盖，不据此排名节能效果。可比关系不传递：只登记逐对核验的项目边，不推导未计算的项目对。"/>

    <el-row :gutter="14">
      <!-- 左：工作区列表 -->
      <el-col :span="7">
        <el-card>
          <template #header>
            <div class="head">
              <b>比较工作区</b>
              <span style="flex: 1" />
              <el-button v-if="auth.canWrite" size="small" type="primary" @click="openCreate">新建</el-button>
            </div>
          </template>
          <div v-for="w in workspaces" :key="w.id" class="ws-item"
               :class="{ active: w.id === selectedId }" @click="select(w.id)">
            <div class="ws-top">
              <span class="ws-code">{{ w.code }}</span>
              <el-tag size="small" :type="tagType('workspace_status', w.status)">
                {{ L('workspace_status', w.status) }}
              </el-tag>
            </div>
            <div class="ws-title">{{ w.title }}</div>
            <div class="ws-meta">
              规则 {{ w.rule?.code }} v{{ w.rule_version }} · 截止 {{ fmtDt(w.material_cutoff) }}
            </div>
            <div v-if="w.input_changed" class="ws-warn">输入已变化，需重新核验</div>
            <div v-if="w.rule_superseded" class="ws-warn">规则已有新版本，旧资格不可发布</div>
          </div>
          <el-empty v-if="!workspaces.length" description="暂无工作区" :image-size="60" />
        </el-card>

        <el-card style="margin-top: 14px">
          <template #header>
            <div class="head">
              <b>比较规则</b>
              <span style="flex: 1" />
              <el-button v-if="auth.canWrite" size="small" @click="ruleVisible = true">登记草稿</el-button>
            </div>
          </template>
          <div v-for="r in rules" :key="r.id" class="rule-item">
            <div class="ws-top">
              <span class="ws-code">{{ r.code }} · v{{ r.version }}</span>
              <el-tag size="small" :type="tagType('rule_status', r.status)">
                {{ L('rule_status', r.status) }}
              </el-tag>
            </div>
            <div class="rule-cond">
              {{ L('building_use', r.building_use) }} / {{ L('climate_zone', r.climate_zone) }} /
              {{ L('occupancy_profile', r.occupancy_profile) }}
            </div>
            <div class="rule-cond">
              基线 {{ r.min_baseline_days }}~{{ r.max_baseline_days }} 天 · 占用覆盖 ≥ {{ (r.occupancy_cover_min * 100).toFixed(0) }}% ·
              日期偏差 ≤ {{ r.date_tolerance_days }} 天 · 共同窗口 ≥ {{ r.min_common_window_days }} 天
            </div>
            <el-button v-if="auth.isAdmin && r.status === 'active'" link size="small" type="warning"
                       @click="publishStricter(r)">发布更严格版本</el-button>
          </div>
        </el-card>
      </el-col>

      <!-- 右：工作区详情 -->
      <el-col :span="17">
        <template v-if="detail">
          <el-card style="margin-bottom: 14px">
            <template #header>
              <div class="head">
                <b>{{ detail.code }} · {{ detail.title }}</b>
                <el-tag size="small" :type="tagType('workspace_status', detail.status)">
                  {{ L('workspace_status', detail.status) }}
                </el-tag>
                <span class="hint">规则 {{ detail.rule?.code }} v{{ detail.rule_version }}</span>
                <span style="flex: 1" />
                <template v-if="auth.canWrite">
                  <el-button size="small" @click="openEdit">修改条件</el-button>
                  <el-button size="small" type="primary" @click="compute">重新核验</el-button>
                  <el-button size="small" :disabled="detail.status !== 'computed' && detail.status !== 'published'"
                             @click="buildCohort">全组队列</el-button>
                  <el-button size="small" type="success" @click="publish">发布清单</el-button>
                  <el-button size="small" @click="reportCorrection">登记更正</el-button>
                  <el-button size="small" type="danger" plain @click="withdraw">撤回</el-button>
                </template>
              </div>
            </template>
            <el-descriptions :column="4" border size="small">
              <el-descriptions-item label="项目">
                <el-tag v-for="p in detail.project_ids" :key="p" size="small" style="margin-right: 4px">
                  {{ codeOf(p) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="资料截止点">{{ fmtDt(detail.material_cutoff) }}</el-descriptions-item>
              <el-descriptions-item label="比较边">
                {{ detail.edges?.length ?? 0 }} 条
                （可比 {{ levelCount.comparable }} / 受限 {{ levelCount.restricted }} / 不可比 {{ levelCount.blocked }}）
              </el-descriptions-item>
              <el-descriptions-item label="最近核验">{{ fmtDt(detail.computed_at) }}</el-descriptions-item>
            </el-descriptions>
            <el-alert v-if="detail.stale_reasons?.length" type="error" :closable="false"
                      style="margin-top: 10px" title="旧资格已过期（需重新核验）：">
              <div v-for="(r, i) in detail.stale_reasons" :key="i" class="tiny">
                {{ r.note || r.reason || JSON.stringify(r) }}
                <span v-if="r.changed">（变更：{{ r.changed.join('、') }}）</span>
              </div>
            </el-alert>
            <el-alert v-if="detail.input_changed" type="warning" :closable="false" style="margin-top: 10px"
                      title="输入快照已变化：项目属性/覆盖/占用/窗口事实与核验时不一致，请重新核验。"/>
          </el-card>

          <!-- 比较边 -->
          <el-card style="margin-bottom: 14px">
            <template #header><b>项目对比较边</b>
              <span class="hint">每条边展示共同窗口、排除原因与条件签名；不推导未计算的项目对</span>
            </template>
            <el-table :data="detail.edges ?? []" size="small" empty-text="尚未核验">
              <el-table-column label="项目对" width="170">
                <template #default="{ row }">
                  {{ row.project_a_code ?? codeOf(row.project_a_id) }} ~
                  {{ row.project_b_code ?? codeOf(row.project_b_id) }}
                </template>
              </el-table-column>
              <el-table-column label="结论" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="tagType('edge_level', row.level)">
                    {{ L('edge_level', row.level) }}
                  </el-tag>
                  <el-tag v-if="row.stale" size="small" type="danger" style="margin-left: 4px">已失效</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="共同窗口（基线 / 报告）" min-width="220">
                <template #default="{ row }">
                  <div class="tiny">{{ ivText(row.window.baseline) }}</div>
                  <div class="tiny">{{ ivText(row.window.reporting) }}</div>
                </template>
              </el-table-column>
              <el-table-column label="候选区间" width="90" align="center">
                <template #default="{ row }">
                  {{ row.window.candidate_baseline?.length ?? 0 }} / {{ row.window.candidate_reporting?.length ?? 0 }}
                </template>
              </el-table-column>
              <el-table-column label="全组交集" width="90" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.on_global_intersection" size="small" type="success">是</el-tag>
                  <span v-else>-</span>
                </template>
              </el-table-column>
              <el-table-column label="排除 / 限制" min-width="200">
                <template #default="{ row }">
                  <div class="tiny">排除 {{ row.exclusions.length }} 项 · 限制 {{ row.limitations.length }} 项</div>
                  <div class="tiny reason">{{ row.reasons[0] }}</div>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="70" fixed="right">
                <template #default="{ row }">
                  <el-button link size="small" type="primary" @click="openTrace(row)">回查</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-card>

          <!-- 队列 -->
          <el-card style="margin-bottom: 14px">
            <template #header>
              <div class="head">
                <b>全组统一队列</b>
                <span class="hint">仅在另行求出全组共同交集后开放；薄弱项目会压缩整批可用日期</span>
              </div>
            </template>
            <template v-if="detail.cohort">
              <el-alert v-for="(r, i) in detail.cohort.reasons" :key="i" :title="r" type="info"
                        :closable="false" style="margin-bottom: 6px" />
              <el-descriptions :column="2" border size="small" style="margin-bottom: 10px">
                <el-descriptions-item label="共同基线区间">
                  {{ ivList(detail.cohort.intersection.baseline) }}
                </el-descriptions-item>
                <el-descriptions-item label="共同报告区间">
                  {{ ivList(detail.cohort.intersection.reporting) }}
                </el-descriptions-item>
              </el-descriptions>
              <el-table :data="detail.cohort.project_statuses ?? []" size="small">
                <el-table-column label="项目" width="100">
                  <template #default="{ row }">{{ row.project_code ?? codeOf(row.project_id) }}</template>
                </el-table-column>
                <el-table-column label="状态" width="110">
                  <template #default="{ row }">
                    <el-tag size="small" :type="tagType('cohort_status', row.status)">
                      {{ L('cohort_status', row.status) }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="说明" min-width="240">
                  <template #default="{ row }">
                    <div v-for="(r, i) in row.reasons" :key="i" class="tiny">{{ r }}</div>
                    <div v-if="row.effect" class="tiny">{{ row.effect }}</div>
                  </template>
                </el-table-column>
              </el-table>
              <div v-if="detail.cohort.intersection.limiters?.length" class="tiny" style="margin-top: 6px">
                <b>限制交集的项目：</b>
                <span v-for="l in detail.cohort.intersection.limiters" :key="l.project_id" style="margin-right: 10px">
                  {{ codeOf(l.project_id) }}（移除后可增加 {{ l.days_gained_if_removed }} 天）
                </span>
              </div>
              <div v-for="(l, i) in detail.cohort.limitations" :key="i" class="tiny muted">{{ l }}</div>
            </template>
            <el-empty v-else description="尚未求出全组共同交集（项目对比较仍可用）" :image-size="60" />
          </el-card>

          <!-- 发布清单 -->
          <el-card>
            <template #header><b>发布清单</b>
              <span class="hint">保留原分母；新版本说明新增、失效与受限的项目对</span>
            </template>
            <el-collapse v-if="detail.publications?.length">
              <el-collapse-item v-for="pub in detail.publications" :key="pub.id"
                                :name="pub.id">
                <template #title>
                  <b>v{{ pub.version }}</b>
                  <el-tag size="small" style="margin: 0 8px" :type="pub.stale ? 'danger' : 'success'">
                    {{ pub.stale ? '来源/规则已更新（保留原分母）' : '当前' }}
                  </el-tag>
                  <span class="tiny">规则 v{{ pub.rule_version }} · 截止 {{ fmtDt(pub.material_cutoff) }} ·
                    发布人 {{ pub.published_by }} · {{ fmtDt(pub.published_at) }}</span>
                </template>
                <div class="tiny" style="margin-bottom: 6px">
                  项目对 {{ pub.edges_snapshot.length }} 条 ·
                  新增 {{ pub.diff_from_previous.added.length }} ·
                  失效 {{ pub.diff_from_previous.dropped.length }} ·
                  受限 {{ pub.diff_from_previous.restricted.length }}
                  <span v-if="pub.diff_from_previous.base_version">
                    （对比 v{{ pub.diff_from_previous.base_version }}）
                  </span>
                </div>
                <el-table :data="pub.edges_snapshot" size="small">
                  <el-table-column label="项目对" width="150">
                    <template #default="{ row }">
                      {{ codeOf(row.project_a_id) }} ~ {{ codeOf(row.project_b_id) }}
                    </template>
                  </el-table-column>
                  <el-table-column label="结论" width="100">
                    <template #default="{ row }">
                      <el-tag size="small" :type="tagType('edge_level', row.level)">
                        {{ L('edge_level', row.level) }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="基线窗口" width="190">
                    <template #default="{ row }">{{ ivText(row.window.baseline) }}</template>
                  </el-table-column>
                  <el-table-column label="报告窗口" width="190">
                    <template #default="{ row }">{{ ivText(row.window.reporting) }}</template>
                  </el-table-column>
                  <el-table-column label="限制" min-width="200">
                    <template #default="{ row }">
                      <div v-for="(l, i) in row.limitations" :key="i" class="tiny">{{ l }}</div>
                    </template>
                  </el-table-column>
                </el-table>
                <div v-if="pub.stale_reasons.length" class="tiny" style="margin-top: 6px; color: #b45309">
                  <div v-for="(r, i) in pub.stale_reasons" :key="i">
                    {{ r.note }} — 受影响项目对：
                    {{ (r.affected_pairs ?? []).map((p: number[]) => `${codeOf(p[0])}~${codeOf(p[1])}`).join('、') || '-' }}
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
            <el-empty v-else description="尚未发布" :image-size="60" />
          </el-card>
        </template>
        <el-empty v-else description="请选择或新建比较工作区" />
      </el-col>
    </el-row>

    <!-- 新建工作区 -->
    <el-dialog v-model="wsVisible" title="新建比较工作区" width="640px">
      <el-form label-width="110px">
        <el-form-item label="工作区编码"><el-input v-model="wsForm.code" placeholder="如 WS-SCHOOL-2026" /></el-form-item>
        <el-form-item label="标题"><el-input v-model="wsForm.title" /></el-form-item>
        <el-form-item label="比较规则">
          <el-select v-model="wsForm.rule_id" style="width: 100%">
            <el-option v-for="r in activeRules" :key="r.id" :label="`${r.code} v${r.version}`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目">
          <el-select v-model="wsForm.project_ids" multiple filterable style="width: 100%"
                     placeholder="至少两个项目">
            <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="资料截止点">
          <el-date-picker v-model="wsForm.material_cutoff" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-alert type="info" :closable="false"
                  title="创建后立即按所选规则逐对核验。全组队列需另行触发；条件变更后旧资格作废。"/>
      </el-form>
      <template #footer>
        <el-button @click="wsVisible = false">取消</el-button>
        <el-button type="primary" @click="createWorkspace">建立并核验</el-button>
      </template>
    </el-dialog>

    <!-- 修改条件 -->
    <el-dialog v-model="editVisible" title="修改比较条件（旧资格将作废）" width="640px">
      <el-form label-width="110px">
        <el-form-item label="标题"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item label="比较规则">
          <el-select v-model="editForm.rule_id" style="width: 100%">
            <el-option v-for="r in activeRules" :key="r.id" :label="`${r.code} v${r.version}`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目">
          <el-select v-model="editForm.project_ids" multiple filterable style="width: 100%">
            <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="资料截止点">
          <el-date-picker v-model="editForm.material_cutoff" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="变更原因"><el-input v-model="editForm.reason" /></el-form-item>
        <el-alert type="warning" :closable="false"
                  title="切换用途/日期/项目后，已选项目需重新核验，不能保留上一次的绿色资格。"/>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="saveEdit">保存（作废旧资格）</el-button>
      </template>
    </el-dialog>

    <!-- 登记规则草稿 -->
    <el-dialog v-model="ruleVisible" title="登记比较规则草稿" width="680px">
      <el-form label-width="130px">
        <el-form-item label="规则编码"><el-input v-model="ruleForm.code" /></el-form-item>
        <el-form-item label="建筑用途">
          <el-select v-model="ruleForm.building_use" clearable style="width: 100%">
            <el-option v-for="(label, key) in { school: '学校', office: '办公', hospital: '医疗', library: '图书馆', sports: '体育', cultural: '文化' }"
                       :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="气候带">
          <el-select v-model="ruleForm.climate_zone" clearable style="width: 100%">
            <el-option v-for="(label, key) in { severe_cold: '严寒', cold: '寒冷', hot_summer_cold_winter: '夏热冬冷', hot_summer_warm_winter: '夏热冬暖', mild: '温和' }"
                       :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="占用形态">
          <el-select v-model="ruleForm.occupancy_profile" clearable style="width: 100%">
            <el-option v-for="(label, key) in { year_round: '全年开放', term_time: '学期/工作日', seasonal: '季节性' }"
                       :key="key" :label="label" :value="key" />
          </el-select>
        </el-form-item>
        <el-form-item label="占用覆盖下限">
          <el-input-number v-model="ruleForm.occupancy_cover_min" :min="0" :max="1" :step="0.05" />
        </el-form-item>
        <el-form-item label="基线天数范围">
          <el-input-number v-model="ruleForm.min_baseline_days" :min="1" />
          <span style="margin: 0 6px">~</span>
          <el-input-number v-model="ruleForm.max_baseline_days" :min="1" />
        </el-form-item>
        <el-form-item label="日期允许偏差(天)">
          <el-input-number v-model="ruleForm.date_tolerance_days" :min="0" />
        </el-form-item>
        <el-form-item label="基线长度容忍(天)">
          <el-input-number v-model="ruleForm.baseline_length_tolerance_days" :min="0" />
        </el-form-item>
        <el-form-item label="共同窗口下限(天)">
          <el-input-number v-model="ruleForm.min_common_window_days" :min="1" />
        </el-form-item>
        <el-form-item label="面积比上限">
          <el-input-number v-model="ruleForm.max_area_ratio" :min="1" :step="0.1" />
        </el-form-item>
        <el-form-item label="说明"><el-input v-model="ruleForm.notes" type="textarea" :rows="2" /></el-form-item>
        <el-alert type="info" :closable="false"
                  title="草稿不参与发布；在生效规则上发布新版本会把旧版本标记为已被取代。"/>
      </el-form>
      <template #footer>
        <el-button @click="ruleVisible = false">取消</el-button>
        <el-button type="primary" @click="registerRule">登记草稿</el-button>
      </template>
    </el-dialog>

    <!-- 比较边回查 -->
    <el-dialog v-model="traceVisible" title="比较边回查" width="900px" top="5vh">
      <div v-loading="traceLoading">
        <template v-if="trace">
          <el-alert type="info" :closable="false" :title="trace.note" style="margin-bottom: 10px" />
          <el-descriptions :column="3" border size="small" style="margin-bottom: 10px">
            <el-descriptions-item label="项目对">
              {{ trace.project_a.code }} ~ {{ trace.project_b.code }}
            </el-descriptions-item>
            <el-descriptions-item label="结论">
              <el-tag size="small" :type="tagType('edge_level', trace.edge.level)">
                {{ L('edge_level', trace.edge.level) }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="全组交集">
              {{ trace.edge.on_global_intersection ? '是' : '否' }}
            </el-descriptions-item>
            <el-descriptions-item label="规则">
              {{ trace.rule.code }} v{{ trace.rule.version }}
            </el-descriptions-item>
            <el-descriptions-item label="资料截止点">{{ fmtDt(trace.workspace.material_cutoff) }}</el-descriptions-item>
            <el-descriptions-item label="重算一致">
              <el-tag size="small" :type="trace.recomputed_matches ? 'success' : 'danger'">
                {{ trace.recomputed_matches ? '一致' : '不一致' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>

          <el-divider content-position="left">双方条件签名</el-divider>
          <el-row :gutter="10">
            <el-col :span="12">
              <div class="sig-title">{{ trace.project_a.code }}</div>
              <pre class="json">{{ JSON.stringify(trace.inputs.project_a, null, 2) }}</pre>
            </el-col>
            <el-col :span="12">
              <div class="sig-title">{{ trace.project_b.code }}</div>
              <pre class="json">{{ JSON.stringify(trace.inputs.project_b, null, 2) }}</pre>
            </el-col>
          </el-row>

          <el-divider content-position="left">交集如何取得</el-divider>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="A 覆盖">{{ ivList(trace.inputs.coverage_a) }}</el-descriptions-item>
            <el-descriptions-item label="B 覆盖">{{ ivList(trace.inputs.coverage_b) }}</el-descriptions-item>
            <el-descriptions-item label="双方共同交集">{{ ivList(trace.intersection) }}</el-descriptions-item>
            <el-descriptions-item label="剔除共用总表后">{{ ivList(trace.common_independent_intersection) }}</el-descriptions-item>
          </el-descriptions>

          <el-divider content-position="left">排除区间</el-divider>
          <el-table :data="trace.exclusions" size="small" empty-text="无排除区间">
            <el-table-column label="范围" width="130">
              <template #default="{ row }">{{ row.scope }}</template>
            </el-table-column>
            <el-table-column label="区间" width="200">
              <template #default="{ row }">{{ row.start ? `${fmtDt(row.start)} ~ ${fmtDt(row.end)}` : '-' }}</template>
            </el-table-column>
            <el-table-column label="天数" width="70">
              <template #default="{ row }">{{ row.gap_days }}</template>
            </el-table-column>
            <el-table-column label="原因" min-width="260">
              <template #default="{ row }">{{ row.reason }}</template>
            </el-table-column>
          </el-table>

          <el-divider content-position="left">限制与可支持分析</el-divider>
          <div v-for="(l, i) in trace.limitations" :key="i" class="tiny">· {{ l }}</div>
          <div style="margin-top: 6px">
            <el-tag v-for="a in trace.supported_analysis" :key="a" size="small" style="margin-right: 6px">
              {{ L('analysis_type', a) }}
            </el-tag>
          </div>
          <el-alert v-for="(r, i) in trace.reasons" :key="i" :title="r" type="info" :closable="false"
                    style="margin-top: 6px" />
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 10px; }
.head .hint { color: #999; font-size: 12px; }
.ws-item { padding: 8px 10px; border-radius: 4px; cursor: pointer; border: 1px solid transparent; }
.ws-item:hover { background: #f5f7fa; }
.ws-item.active { background: #ecf5ff; border-color: #b3d8ff; }
.ws-top { display: flex; align-items: center; justify-content: space-between; }
.ws-code { font-weight: 600; font-size: 13px; }
.ws-title { font-size: 12px; color: #555; margin: 2px 0; }
.ws-meta { font-size: 11px; color: #999; }
.ws-warn { font-size: 11px; color: #d97706; margin-top: 2px; }
.rule-item { padding: 6px 0; border-bottom: 1px dashed #eee; }
.rule-cond { font-size: 11px; color: #888; line-height: 1.6; }
.tiny { font-size: 12px; color: #666; }
.tiny.muted { color: #999; }
.reason { color: #555; }
.sig-title { font-weight: 600; font-size: 12px; margin-bottom: 4px; }
.json { background: #f6f8fa; padding: 8px; border-radius: 4px; font-size: 11px; max-height: 260px; overflow: auto; }
</style>
