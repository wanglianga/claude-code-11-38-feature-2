<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { auth } from '../store'
import { L, tagType, fmtDt } from '../labels'
import type { Boundary, MeterEvent, Project } from '../types'

const projects = ref<Project[]>([])
const boundaries = ref<Boundary[]>([])
const events = ref<MeterEvent[]>([])
const filter = reactive({ project_id: undefined as number | undefined })

async function load() {
  const q = filter.project_id ? `?project_id=${filter.project_id}` : ''
  boundaries.value = await api.get<Boundary[]>(`/api/boundaries${q}`)
  events.value = await api.get<MeterEvent[]>(`/api/boundaries/meter-events${q}`)
}

onMounted(async () => {
  projects.value = await api.get<Project[]>('/api/projects')
  await load()
})

const eventVisible = ref(false)
const evForm = reactive({
  project_id: undefined as number | undefined,
  old_meter_serial: '',
  new_meter_serial: '',
  replaced_at: '',
  multiplier_linked: false,
})

async function submitEvent() {
  try {
    await api.post('/api/boundaries/meter-events', {
      ...evForm,
      replaced_at: `${evForm.replaced_at}T00:00:00Z`,
    })
    ElMessage.success(evForm.multiplier_linked
      ? '换表事件已登记（倍率经校验衔接）'
      : '换表事件已登记：倍率未衔接，受影响边界已在断点处拆分，禁止跨越断点签发可比较事实')
    eventVisible.value = false
    await load()
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
        <b>计量边界册</b>
        <span class="hint">电表 · 支路 · 公共管路 · 建筑区域 · 有效区间 · 证据强度</span>
        <el-button v-if="auth.canWrite" type="warning" size="small" @click="eventVisible = true">登记换表事件</el-button>
      </div>
    </template>
    <el-form inline>
      <el-form-item label="项目">
        <el-select v-model="filter.project_id" clearable placeholder="全部" style="width: 260px" @change="load">
          <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <el-table :data="boundaries" size="small">
      <el-table-column label="项目" width="90">
        <template #default="{ row }">{{ projCode(row.project_id) }}</template>
      </el-table-column>
      <el-table-column prop="meter_serial" label="电表序列" width="110" />
      <el-table-column prop="branch_name" label="支路/管路" width="130" />
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag :type="tagType('pipeline_kind', row.pipeline_kind)" size="small">
            {{ L('pipeline_kind', row.pipeline_kind) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="zone_name" label="建筑区域" width="110" />
      <el-table-column label="期间" width="80">
        <template #default="{ row }">{{ L('period_role', row.period_role) }}</template>
      </el-table-column>
      <el-table-column label="有效区间" width="210">
        <template #default="{ row }">{{ fmtDt(row.valid_from) }} ~ {{ row.valid_to ? fmtDt(row.valid_to) : '至今' }}</template>
      </el-table-column>
      <el-table-column prop="multiplier" label="倍率" width="70" />
      <el-table-column label="倍率衔接" width="90">
        <template #default="{ row }">
          <el-tag :type="row.multiplier_linked ? 'success' : 'danger'" size="small">
            {{ row.multiplier_linked ? '已衔接' : '未衔接' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="证据强度" width="90">
        <template #default="{ row }">
          <el-tag :type="tagType('evidence_strength', row.evidence_strength)" size="small">
            {{ L('evidence_strength', row.evidence_strength) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="拆分来源" width="90">
        <template #default="{ row }">{{ row.segment_of_id ? `#${row.segment_of_id}` : '-' }}</template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-card>
    <template #header><b>换表事件</b>（倍率未衔接的换表形成断点，禁止跨越断点签发可比较事实）</template>
    <el-table :data="events" size="small">
      <el-table-column label="项目" width="90">
        <template #default="{ row }">{{ projCode(row.project_id) }}</template>
      </el-table-column>
      <el-table-column label="旧表 → 新表" width="200">
        <template #default="{ row }">{{ row.old_meter_serial }} → {{ row.new_meter_serial }}</template>
      </el-table-column>
      <el-table-column label="换表时间" width="120">
        <template #default="{ row }">{{ fmtDt(row.replaced_at) }}</template>
      </el-table-column>
      <el-table-column label="倍率衔接" width="100">
        <template #default="{ row }">
          <el-tag :type="row.multiplier_linked ? 'success' : 'danger'" size="small">
            {{ row.multiplier_linked ? '校验记录已衔接' : '无法衔接（断点）' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-dialog v-model="eventVisible" title="登记换表事件" width="520px">
    <el-form label-width="110px">
      <el-form-item label="项目">
        <el-select v-model="evForm.project_id" style="width: 100%">
          <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="旧表序列"><el-input v-model="evForm.old_meter_serial" /></el-form-item>
      <el-form-item label="新表序列"><el-input v-model="evForm.new_meter_serial" /></el-form-item>
      <el-form-item label="换表时间">
        <el-date-picker v-model="evForm.replaced_at" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="倍率衔接">
        <el-switch v-model="evForm.multiplier_linked" active-text="校验记录可衔接新旧表倍率" />
      </el-form-item>
      <el-alert type="warning" :closable="false"
                title="倍率无法衔接时，受影响计量边界将在断点处拆分，编译器禁止生成跨越断点的可比较事实" />
    </el-form>
    <template #footer>
      <el-button @click="eventVisible = false">取消</el-button>
      <el-button type="primary" @click="submitEvent">登记</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; }
.head .hint { color: #999; font-size: 12px; flex: 1; }
</style>
