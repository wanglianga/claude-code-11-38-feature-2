<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { auth } from '../store'
import { L, tagType, fmtDt, labels } from '../labels'
import type { EvidenceDoc, Project } from '../types'

const projects = ref<Project[]>([])
const docs = ref<EvidenceDoc[]>([])
const filter = reactive({ project_id: undefined as number | undefined, doc_type: '' })
const loading = ref(false)

const docTypes = Object.keys(labels.doc_type)

async function load() {
  loading.value = true
  const q = new URLSearchParams()
  if (filter.project_id) q.set('project_id', String(filter.project_id))
  if (filter.doc_type) q.set('doc_type', filter.doc_type)
  docs.value = await api.get<EvidenceDoc[]>(`/api/evidence?${q}`)
  loading.value = false
}

onMounted(async () => {
  projects.value = await api.get<Project[]>('/api/projects')
  await load()
})

// ---------- 新证据受理 ----------
const intakeVisible = ref(false)
const intake = reactive({
  project_id: undefined as number | undefined,
  doc_type: 'contract_item',
  title: '',
  event_time: '',
  payloadText: '{\n  \n}',
  supersedes_id: undefined as number | undefined,
})

function openIntake(supersede?: EvidenceDoc) {
  intake.project_id = supersede?.project_id ?? filter.project_id
  intake.doc_type = supersede?.doc_type ?? 'contract_item'
  intake.title = supersede ? `${supersede.title}（修订）` : ''
  intake.event_time = new Date().toISOString().slice(0, 10) + 'T00:00:00Z'
  intake.payloadText = supersede ? JSON.stringify(supersede.payload, null, 2) : '{\n  \n}'
  intake.supersedes_id = supersede?.id
  intakeVisible.value = true
}

async function submitIntake() {
  let payload: Record<string, any>
  try {
    payload = JSON.parse(intake.payloadText)
  } catch {
    ElMessage.error('payload 不是合法 JSON')
    return
  }
  try {
    const r = await api.post<EvidenceDoc>('/api/evidence', {
      project_id: intake.project_id,
      doc_type: intake.doc_type,
      title: intake.title,
      event_time: intake.event_time,
      payload,
      supersedes_id: intake.supersedes_id ?? null,
    })
    if (r.affected_fact_ids?.length) {
      ElMessage.warning(`验收附件哈希变化，${r.affected_fact_ids.length} 条当前事实已转入复审中并暂停新引用`)
    } else {
      ElMessage.success('证据已受理')
    }
    intakeVisible.value = false
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}

// ---------- 修订链 ----------
const chainVisible = ref(false)
const chain = ref<EvidenceDoc[]>([])
async function showChain(row: EvidenceDoc) {
  chain.value = await api.get<EvidenceDoc[]>(`/api/evidence/${row.id}/chain`)
  chainVisible.value = true
}

const payloadPreview = computed(() => (row: EvidenceDoc) => JSON.stringify(row.payload))
</script>

<template>
  <el-card>
    <template #header>
      <div class="head">
        <b>证据受理库</b>
        <span class="hint">来源哈希 · 事件时间 · 接收时间 · 签发版本 · 修订链</span>
        <el-button v-if="auth.canWrite" type="primary" size="small" @click="openIntake()">受理新证据</el-button>
      </div>
    </template>

    <el-form inline>
      <el-form-item label="项目">
        <el-select v-model="filter.project_id" clearable placeholder="全部" style="width: 260px" @change="load">
          <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="类型">
        <el-select v-model="filter.doc_type" clearable placeholder="全部" style="width: 160px" @change="load">
          <el-option v-for="t in docTypes" :key="t" :label="L('doc_type', t)" :value="t" />
        </el-select>
      </el-form-item>
    </el-form>

    <el-table :data="docs" v-loading="loading" size="small">
      <el-table-column prop="id" label="ID" width="60" />
      <el-table-column label="类型" width="120">
        <template #default="{ row }">{{ L('doc_type', row.doc_type) }}</template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="220" />
      <el-table-column label="来源哈希" width="130">
        <template #default="{ row }">
          <el-tooltip :content="row.source_hash"><code>{{ row.source_hash.slice(0, 10) }}…</code></el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="事件时间" width="105">
        <template #default="{ row }">{{ fmtDt(row.event_time) }}</template>
      </el-table-column>
      <el-table-column label="接收时间" width="105">
        <template #default="{ row }">{{ fmtDt(row.received_at) }}</template>
      </el-table-column>
      <el-table-column label="版本" width="60">
        <template #default="{ row }">v{{ row.version }}</template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
            {{ L('evidence_status', row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link size="small" @click="showChain(row)">修订链</el-button>
          <el-button link size="small" type="primary"
                     @click="ElMessageBox.alert(payloadPreview(row), row.title, { confirmButtonText: '关闭' })">
            原文
          </el-button>
          <el-button v-if="auth.canWrite && row.status === 'active'" link size="small" type="warning"
                     @click="openIntake(row)">修订</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="intakeVisible" :title="intake.supersedes_id ? '修订证据（替换附件/更新内容）' : '受理新证据'" width="640px">
      <el-form label-width="90px">
        <el-form-item label="项目">
          <el-select v-model="intake.project_id" style="width: 100%" :disabled="!!intake.supersedes_id">
            <el-option v-for="p in projects" :key="p.id" :label="`${p.code} ${p.name}`" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="intake.doc_type" style="width: 100%" :disabled="!!intake.supersedes_id">
            <el-option v-for="t in docTypes" :key="t" :label="L('doc_type', t)" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题"><el-input v-model="intake.title" /></el-form-item>
        <el-form-item label="事件时间"><el-input v-model="intake.event_time" placeholder="2025-01-01T00:00:00Z" /></el-form-item>
        <el-form-item label="内容原文">
          <el-input v-model="intake.payloadText" type="textarea" :rows="10" spellcheck="false" />
        </el-form-item>
        <el-alert v-if="intake.supersedes_id" type="warning" :closable="false"
                  title="修订将生成新版本并加入修订链；若为验收报告且哈希变化，引用旧附件的当前事实将转入复审中" />
      </el-form>
      <template #footer>
        <el-button @click="intakeVisible = false">取消</el-button>
        <el-button type="primary" @click="submitIntake">提交</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="chainVisible" title="修订链" size="480px">
      <el-timeline>
        <el-timeline-item v-for="c in chain" :key="c.id"
                          :type="c.status === 'active' ? 'primary' : 'info'">
          <div><b>v{{ c.version }}</b> · {{ c.title }}</div>
          <div class="chain-meta">
            哈希 <code>{{ c.source_hash.slice(0, 16) }}…</code><br />
            事件 {{ fmtDt(c.event_time) }} · 接收 {{ fmtDt(c.received_at) }} ·
            <el-tag size="small" :type="c.status === 'active' ? 'success' : 'info'">
              {{ L('evidence_status', c.status) }}
            </el-tag>
          </div>
        </el-timeline-item>
      </el-timeline>
    </el-drawer>
  </el-card>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 12px; }
.head .hint { color: #999; font-size: 12px; flex: 1; }
.chain-meta { font-size: 12px; color: #888; margin-top: 4px; }
</style>
