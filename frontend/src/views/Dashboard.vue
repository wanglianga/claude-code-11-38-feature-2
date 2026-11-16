<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { L, tagType, fmtPct } from '../labels'
import type { Conflict, Fact, Project } from '../types'

interface Summary {
  project: Project
  evidence_count: number
  scope_count: number
  facts_current: number
  comparable: number
  restricted: number
  pending: number
  incomparable: number
  under_review: number
  open_conflicts: number
}

const summaries = ref<Summary[]>([])
const conflicts = ref<Conflict[]>([])
const uncompared = ref<Fact[]>([])
const loading = ref(true)

onMounted(async () => {
  const projects = await api.get<Project[]>('/api/projects')
  summaries.value = await Promise.all(projects.map(p => api.get<Summary>(`/api/projects/${p.id}/summary`)))
  conflicts.value = await api.get<Conflict[]>('/api/scope/conflicts?status=open')
  uncompared.value = await api.get<Fact[]>('/api/analysis/uncompared')
  loading.value = false
})
</script>

<template>
  <div v-loading="loading">
    <el-row :gutter="14">
      <el-col v-for="s in summaries" :key="s.project.id" :span="6" style="margin-bottom: 14px">
        <el-card shadow="hover">
          <div class="pcode">{{ s.project.code }}</div>
          <div class="pname">{{ s.project.name }}</div>
          <div class="porg">{{ s.project.owner_org }} · {{ s.project.building_name }}</div>
          <div class="stats">
            <el-tag size="small" type="success">可比较 {{ s.comparable }}</el-tag>
            <el-tag size="small" type="warning">受限 {{ s.restricted }}</el-tag>
            <el-tag size="small" type="info">待复核 {{ s.pending }}</el-tag>
            <el-tag size="small" type="danger">不可比 {{ s.incomparable }}</el-tag>
          </div>
          <div class="meta">
            证据 {{ s.evidence_count }} · 范围 {{ s.scope_count }} · 当前事实 {{ s.facts_current }}
            <el-tooltip v-if="s.under_review" content="有事实因验收附件替换处于复审中">
              <el-tag size="small" type="danger" effect="dark">复审中 {{ s.under_review }}</el-tag>
            </el-tooltip>
            <el-tag v-if="s.open_conflicts" size="small" type="danger">冲突 {{ s.open_conflicts }}</el-tag>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="14">
      <el-col :span="12">
        <el-card>
          <template #header><b>未处理冲突 / 待核</b></template>
          <el-table :data="conflicts" size="small">
            <el-table-column label="类型" width="130">
              <template #default="{ row }">
                <el-tag :type="tagType('conflict_type', row.conflict_type)" size="small">
                  {{ L('conflict_type', row.conflict_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="serial_no" label="序列号" width="120" />
            <el-table-column label="涉及项目" width="110">
              <template #default="{ row }">{{ row.project_ids.join(' / ') }}</template>
            </el-table-column>
            <el-table-column label="说明">
              <template #default="{ row }">{{ row.detail.reason }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header><b>未比较清单</b>（待复核 / 不可比较的当前事实）</template>
          <el-table :data="uncompared" size="small">
            <el-table-column prop="project_code" label="项目" width="90" />
            <el-table-column label="策略" width="140">
              <template #default="{ row }">{{ L('strategy', row.strategy) }}</template>
            </el-table-column>
            <el-table-column label="级别" width="100">
              <template #default="{ row }">
                <el-tag :type="tagType('comparability', row.comparability)" size="small">
                  {{ L('comparability', row.comparability) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="节能率" width="80">
              <template #default="{ row }">{{ fmtPct(row.savings_rate) }}</template>
            </el-table-column>
            <el-table-column label="原因">
              <template #default="{ row }">
                <span class="reason">{{ row.reasons[0] }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped>
.pcode { font-size: 12px; color: #999; }
.pname { font-weight: 600; margin: 2px 0; }
.porg { font-size: 12px; color: #888; margin-bottom: 10px; }
.stats { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.meta { font-size: 12px; color: #888; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.reason { font-size: 12px; color: #666; }
</style>
