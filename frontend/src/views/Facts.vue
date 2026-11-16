<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { auth } from '../store'
import { L, tagType, fmtDt, fmtNum, fmtPct } from '../labels'
import type { Fact, Project, ScopeRelation } from '../types'

const router = useRouter()
const projects = ref<Project[]>([])
const benchmark = ref<Fact[]>([])
const facts = ref<Fact[]>([])
const includeAllocated = ref(false)
const filter = reactive({ project_id: undefined as number | undefined })

async function loadBenchmark() {
  benchmark.value = await api.get<Fact[]>(`/api/analysis/benchmark?include_allocated=${includeAllocated.value}`)
}

async function loadFacts() {
  const q = filter.project_id ? `?project_id=${filter.project_id}` : ''
  facts.value = await api.get<Fact[]>(`/api/facts${q}`)
}

onMounted(async () => {
  projects.value = await api.get<Project[]>('/api/projects')
  await Promise.all([loadBenchmark(), loadFacts()])
})

// ---------- 编译新事实 ----------
const compileVisible = ref(false)
const scopeOptions = ref<ScopeRelation[]>([])
const cForm = reactive({
  project_id: undefined as number | undefined,
  scope_relation_id: undefined as number | undefined,
  strategy: 'strict_direct',
  baseline_start: '2024-01-01',
  baseline_end: '2025-01-01',
  reporting_start: '2025-01-01',
  reporting_end: '2026-01-01',
})

async function onCompileProject() {
  cForm.scope_relation_id = undefined
  if (cForm.project_id) {
    scopeOptions.value = await api.get<ScopeRelation[]>(`/api/scope/relations?project_id=${cForm.project_id}`)
  }
}

async function submitCompile() {
  try {
    const f = await api.post<Fact>('/api/facts/compile', {
      project_id: cForm.project_id,
      scope_relation_id: cForm.scope_relation_id,
      strategy: cForm.strategy,
      baseline_start: `${cForm.baseline_start}T00:00:00Z`,
      baseline_end: `${cForm.baseline_end}T00:00:00Z`,
      reporting_start: `${cForm.reporting_start}T00:00:00Z`,
      reporting_end: `${cForm.reporting_end}T00:00:00Z`,
    })
    ElMessage({
      type: f.comparability === 'comparable' ? 'success' : 'warning',
      message: `已签发 v${f.version} · ${L('comparability', f.comparability)}：${f.reasons[0] ?? ''}`,
      duration: 5000,
    })
    compileVisible.value = false
    await Promise.all([loadBenchmark(), loadFacts()])
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

const projCode = (id: number) => projects.value.find(p => p.id === id)?.code ?? String(id)
</script>

<template>
  <el-card style="margin-bottom: 14px">
    <template #header>
      <div class="head">
        <b>节能对标（当前可发布事实）</b>
        <el-checkbox v-model="includeAllocated" @change="loadBenchmark"
                     label="覆盖分析模式：纳入受控分摊值（含假设差异，需承担复核成本）" />
      </div>
    </template>
    <el-alert v-if="!includeAllocated" type="success" :closable="false"
              title="默认节能对标只读直接计量结果，避免把估算量说成实测节能" style="margin-bottom: 10px" />
    <el-alert v-else type="warning" :closable="false"
              title="已纳入受控分摊值：分摊结果基于运行时长/面积假设，使用者需承担假设差异带来的复核成本" style="margin-bottom: 10px" />
    <el-table :data="benchmark" size="small">
      <el-table-column prop="project_code" label="项目" width="90" />
      <el-table-column prop="project_name" label="项目名称" min-width="180" show-overflow-tooltip />
      <el-table-column label="结果类型" width="110">
        <template #default="{ row }">
          <el-tag :type="tagType('result_kind', row.result_kind)" size="small">
            {{ L('result_kind', row.result_kind) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="比较级别" width="110">
        <template #default="{ row }">
          <el-tag :type="tagType('comparability', row.comparability)" size="small">
            {{ L('comparability', row.comparability) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="基线能耗" width="110" align="right">
        <template #default="{ row }">{{ fmtNum(row.baseline_kwh) }}</template>
      </el-table-column>
      <el-table-column label="报告期能耗" width="110" align="right">
        <template #default="{ row }">{{ fmtNum(row.reporting_kwh) }}</template>
      </el-table-column>
      <el-table-column label="节能量(kWh)" width="120" align="right">
        <template #default="{ row }"><b>{{ fmtNum(row.savings_kwh) }}</b></template>
      </el-table-column>
      <el-table-column label="节能率" width="90" align="right">
        <template #default="{ row }">{{ fmtPct(row.savings_rate) }}</template>
      </el-table-column>
      <el-table-column label="版本" width="60">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column label="操作" width="80">
        <template #default="{ row }">
          <el-button link size="small" type="primary" @click="router.push(`/facts/${row.id}`)">溯源</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-card>
    <template #header>
      <div class="head">
        <b>绩效事实库</b>
        <span class="hint">编译器签发 · 版本链 · 复审状态</span>
        <el-button v-if="auth.canWrite" type="primary" size="small" @click="compileVisible = true">编译新事实</el-button>
      </div>
    </template>
    <el-form inline>
      <el-form-item label="项目">
        <el-select v-model="filter.project_id" clearable placeholder="全部" style="width: 260px" @change="loadFacts">
          <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <el-table :data="facts" size="small">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column label="项目" width="90">
        <template #default="{ row }">{{ projCode(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="策略" width="150">
        <template #default="{ row }">{{ L('strategy', row.strategy) }}</template>
      </el-table-column>
      <el-table-column label="结果类型" width="105">
        <template #default="{ row }">
          <el-tag :type="tagType('result_kind', row.result_kind)" size="small">
            {{ L('result_kind', row.result_kind) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="比较级别" width="105">
        <template #default="{ row }">
          <el-tag :type="tagType('comparability', row.comparability)" size="small">
            {{ L('comparability', row.comparability) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="tagType('fact_status', row.status)" size="small">{{ L('fact_status', row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="版本" width="60">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column label="基线期" width="190">
        <template #default="{ row }">{{ fmtDt(row.baseline_start) }} ~ {{ fmtDt(row.baseline_end) }}</template>
      </el-table-column>
      <el-table-column label="节能率" width="80" align="right">
        <template #default="{ row }">{{ fmtPct(row.savings_rate) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button link size="small" type="primary" @click="router.push(`/facts/${row.id}`)">溯源</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="compileVisible" title="编译绩效事实" width="600px">
    <el-form label-width="110px">
      <el-form-item label="项目">
        <el-select v-model="cForm.project_id" style="width: 100%" @change="onCompileProject">
          <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="范围关系">
        <el-select v-model="cForm.scope_relation_id" style="width: 100%">
          <el-option v-for="r in scopeOptions" :key="r.id"
                     :label="`#${r.id} ${L('relation_kind', r.relation_kind)} · ${r.subject_ref}（${L('scope_status', r.status)}）`"
                     :value="r.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="核验策略">
        <el-radio-group v-model="cForm.strategy">
          <el-radio-button value="strict_direct">严格直接计量</el-radio-button>
          <el-radio-button value="allocation_runtime">分摊·运行时长</el-radio-button>
          <el-radio-button value="allocation_area">分摊·面积</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="基线期">
        <el-date-picker v-model="cForm.baseline_start" type="date" value-format="YYYY-MM-DD" style="width: 45%" />
        <span style="margin: 0 6px">~</span>
        <el-date-picker v-model="cForm.baseline_end" type="date" value-format="YYYY-MM-DD" style="width: 45%" />
      </el-form-item>
      <el-form-item label="报告期">
        <el-date-picker v-model="cForm.reporting_start" type="date" value-format="YYYY-MM-DD" style="width: 45%" />
        <span style="margin: 0 6px">~</span>
        <el-date-picker v-model="cForm.reporting_end" type="date" value-format="YYYY-MM-DD" style="width: 45%" />
      </el-form-item>
      <el-alert type="info" :closable="false"
                title="编译器仅在范围关系与计量边界满足所选策略时签发事实；同一谱系重复编译将签发新版本，旧版本转为历史" />
    </el-form>
    <template #footer>
      <el-button @click="compileVisible = false">取消</el-button>
      <el-button type="primary" @click="submitCompile">编译签发</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 16px; }
.head .hint { color: #999; font-size: 12px; flex: 1; }
</style>
