<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { auth } from '../store'
import { L, tagType, fmtDt } from '../labels'
import type { Conflict, Project, ScopeRelation } from '../types'

const projects = ref<Project[]>([])
const relations = ref<ScopeRelation[]>([])
const conflicts = ref<Conflict[]>([])
const filter = reactive({ project_id: undefined as number | undefined })

async function load() {
  const q = filter.project_id ? `?project_id=${filter.project_id}` : ''
  relations.value = await api.get<ScopeRelation[]>(`/api/scope/relations${q}`)
  conflicts.value = await api.get<Conflict[]>('/api/scope/conflicts')
}

onMounted(async () => {
  projects.value = await api.get<Project[]>('/api/projects')
  await load()
})

const createVisible = ref(false)
const form = reactive({
  project_id: undefined as number | undefined,
  relation_kind: 'installed_evidence',
  subject_type: 'equipment',
  subject_ref: '',
  serial_no: '',
  status: 'confirmed',
  coverage_note: '',
  valid_from: '',
  valid_to: '',
  physically_exclusive: true,
})

async function submit() {
  try {
    const r = await api.post<ScopeRelation>('/api/scope/relations', {
      ...form,
      valid_from: form.valid_from ? `${form.valid_from}T00:00:00Z` : null,
      valid_to: form.valid_to ? `${form.valid_to}T00:00:00Z` : null,
      serial_no: form.serial_no || null,
      evidence_ids: [],
    })
    if (r.new_conflicts?.length) {
      const c = r.new_conflicts[0]
      ElMessage.warning(`触发${L('conflict_type', c.conflict_type)}：序列号 ${c.serial_no}`)
    } else {
      ElMessage.success('范围关系已登记')
    }
    createVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

async function resolveConflict(c: Conflict) {
  await api.post(`/api/scope/conflicts/${c.id}/resolve`)
  ElMessage.success('已标记解决')
  await load()
}

const projCode = (id: number) => projects.value.find(p => p.id === id)?.code ?? String(id)
</script>

<template>
  <el-card style="margin-bottom: 14px">
    <template #header>
      <div class="head">
        <b>改造范围册</b>
        <span class="hint">合同承诺 / 实装证据 / 验收结论 → 候选 · 已确认 · 冲突 · 转移待核</span>
        <el-button v-if="auth.canWrite" type="primary" size="small" @click="createVisible = true">登记范围关系</el-button>
      </div>
    </template>
    <el-form inline>
      <el-form-item label="项目">
        <el-select v-model="filter.project_id" clearable placeholder="全部" style="width: 260px" @change="load">
          <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <el-table :data="relations" size="small">
      <el-table-column label="项目" width="90">
        <template #default="{ row }">{{ projCode(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="来源" width="100">
        <template #default="{ row }">{{ L('relation_kind', row.relation_kind) }}</template>
      </el-table-column>
      <el-table-column label="对象" width="70">
        <template #default="{ row }">{{ L('subject_type', row.subject_type) }}</template>
      </el-table-column>
      <el-table-column prop="subject_ref" label="空间/设备位号" min-width="130" />
      <el-table-column prop="serial_no" label="序列号" width="110">
        <template #default="{ row }">{{ row.serial_no || '-' }}</template>
      </el-table-column>
      <el-table-column label="服务区间" width="200">
        <template #default="{ row }">{{ fmtDt(row.valid_from) }} ~ {{ row.valid_to ? fmtDt(row.valid_to) : '至今' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="tagType('scope_status', row.status)" size="small">{{ L('scope_status', row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="coverage_note" label="覆盖说明" min-width="200" show-overflow-tooltip />
    </el-table>
  </el-card>

  <el-card>
    <template #header><b>冲突与待核清单</b></template>
    <el-table :data="conflicts" size="small">
      <el-table-column label="类型" width="130">
        <template #default="{ row }">
          <el-tag :type="tagType('conflict_type', row.conflict_type)" size="small">
            {{ L('conflict_type', row.conflict_type) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="serial_no" label="序列号" width="120" />
      <el-table-column label="涉及项目" width="120">
        <template #default="{ row }">{{ row.project_ids.map(projCode).join(' / ') }}</template>
      </el-table-column>
      <el-table-column label="说明">
        <template #default="{ row }">{{ row.detail.reason }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'open' ? 'danger' : 'success'" size="small">
            {{ L('conflict_status', row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="90">
        <template #default="{ row }">
          <el-button v-if="row.status === 'open' && auth.canWrite" link size="small" type="primary"
                     @click="resolveConflict(row)">标记解决</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="createVisible" title="登记范围关系" width="560px">
    <el-form label-width="100px">
      <el-form-item label="项目">
        <el-select v-model="form.project_id" style="width: 100%">
          <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="来源">
        <el-radio-group v-model="form.relation_kind">
          <el-radio-button value="contract_commitment">合同承诺</el-radio-button>
          <el-radio-button value="installed_evidence">实装证据</el-radio-button>
          <el-radio-button value="acceptance_conclusion">验收结论</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="对象类型">
        <el-radio-group v-model="form.subject_type">
          <el-radio-button value="space">空间</el-radio-button>
          <el-radio-button value="equipment">设备</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="空间/位号"><el-input v-model="form.subject_ref" /></el-form-item>
      <el-form-item label="设备序列号"><el-input v-model="form.serial_no" placeholder="设备类必填，用于跨项目冲突检测" /></el-form-item>
      <el-form-item label="服务区间">
        <el-date-picker v-model="form.valid_from" type="date" value-format="YYYY-MM-DD" placeholder="起" style="width: 45%" />
        <el-date-picker v-model="form.valid_to" type="date" value-format="YYYY-MM-DD" placeholder="止（空=至今）" style="width: 45%; margin-left: 8px" />
      </el-form-item>
      <el-form-item label="物理互斥">
        <el-switch v-model="form.physically_exclusive" active-text="设备不能同时安装于两处" />
      </el-form-item>
      <el-form-item label="覆盖说明"><el-input v-model="form.coverage_note" type="textarea" :rows="2" /></el-form-item>
      <el-alert type="info" :closable="false"
                title="同一序列号跨项目声明时：服务区间重叠且物理互斥 → 重复覆盖冲突；区间不重叠且缺移装材料 → 转移待核" />
    </el-form>
    <template #footer>
      <el-button @click="createVisible = false">取消</el-button>
      <el-button type="primary" @click="submit">登记</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; }
.head .hint { color: #999; font-size: 12px; flex: 1; }
</style>
