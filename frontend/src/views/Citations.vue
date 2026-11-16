<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { fmtDt } from '../labels'
import type { Citation } from '../types'

const citations = ref<Citation[]>([])

onMounted(async () => {
  citations.value = await api.get<Citation[]>('/api/citations')
})
</script>

<template>
  <el-card>
    <template #header>
      <b>引用簿</b>
      <span class="hint">记录哪些分析与审计视图使用了哪个版本的绩效事实</span>
    </template>
    <el-table :data="citations" size="small">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column label="事实" width="100">
        <template #default="{ row }">#{{ row.fact_id }} · v{{ row.fact_version }}</template>
      </el-table-column>
      <el-table-column label="消费类型" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.consumer_type === 'analysis' ? 'primary' : 'warning'">
            {{ row.consumer_type === 'analysis' ? '分析' : '审计视图' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="consumer_name" label="消费方" min-width="200" />
      <el-table-column prop="purpose" label="用途" min-width="180" show-overflow-tooltip />
      <el-table-column prop="created_by" label="登记人" width="100" />
      <el-table-column label="登记时间" width="110">
        <template #default="{ row }">{{ fmtDt(row.created_at) }}</template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<style scoped>
.hint { color: #999; font-size: 12px; margin-left: 12px; }
</style>
