<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { auth } from '../store'
import { L, tagType, fmtDt, fmtNum, fmtPct } from '../labels'
import type { FactTrace } from '../types'

const route = useRoute()
const trace = ref<FactTrace | null>(null)

async function load() {
  trace.value = await api.get<FactTrace>(`/api/facts/${route.params.id}/trace`)
}

onMounted(load)

// ---------- 登记引用 ----------
const citeVisible = ref(false)
const citeForm = ref({ consumer_type: 'analysis', consumer_name: '', purpose: '' })

async function submitCitation() {
  try {
    await api.post('/api/citations', {
      fact_id: trace.value!.fact.id,
      ...citeForm.value,
    })
    ElMessage.success('引用已登记到引用簿')
    citeVisible.value = false
    citeForm.value = { consumer_type: 'analysis', consumer_name: '', purpose: '' }
    await load()
  } catch (e: any) {
    ElMessage.error(e.message)
  }
}
</script>

<template>
  <div v-if="trace">
    <el-card style="margin-bottom: 14px">
      <template #header>
        <div class="head">
          <b>绩效事实 #{{ trace.fact.id }} · v{{ trace.fact.version }}</b>
          <el-tag :type="tagType('comparability', trace.fact.comparability)">
            {{ L('comparability', trace.fact.comparability) }}
          </el-tag>
          <el-tag :type="tagType('fact_status', trace.fact.status)">{{ L('fact_status', trace.fact.status) }}</el-tag>
          <el-tag :type="tagType('result_kind', trace.fact.result_kind)">{{ L('result_kind', trace.fact.result_kind) }}</el-tag>
          <span style="flex: 1" />
          <el-button v-if="trace.fact.status === 'current'" type="primary" size="small"
                     @click="citeVisible = true">登记引用</el-button>
          <el-tooltip v-else content="复审中/历史版本不可新增引用">
            <el-button type="primary" size="small" disabled>登记引用</el-button>
          </el-tooltip>
        </div>
      </template>
      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="核验策略">{{ L('strategy', trace.strategy) }}</el-descriptions-item>
        <el-descriptions-item label="基线期">{{ fmtDt(trace.fact.baseline_start) }} ~ {{ fmtDt(trace.fact.baseline_end) }}</el-descriptions-item>
        <el-descriptions-item label="报告期">{{ fmtDt(trace.fact.reporting_start) }} ~ {{ fmtDt(trace.fact.reporting_end) }}</el-descriptions-item>
        <el-descriptions-item label="基线能耗">{{ fmtNum(trace.fact.baseline_kwh) }} kWh</el-descriptions-item>
        <el-descriptions-item label="报告期能耗">{{ fmtNum(trace.fact.reporting_kwh) }} kWh</el-descriptions-item>
        <el-descriptions-item label="节能量 / 节能率">
          <b>{{ fmtNum(trace.fact.savings_kwh) }} kWh</b> / {{ fmtPct(trace.fact.savings_rate) }}
        </el-descriptions-item>
        <el-descriptions-item label="签发时间">{{ fmtDt(trace.fact.issued_at) }}</el-descriptions-item>
        <el-descriptions-item label="暂停新引用">
          <el-tag :type="trace.fact.block_new_citations ? 'danger' : 'success'" size="small">
            {{ trace.fact.block_new_citations ? '是' : '否' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
      <el-alert v-for="(r, i) in trace.fact.reasons" :key="i" :title="r" type="info" :closable="false"
                style="margin-top: 8px" />
      <template v-if="trace.assumptions && Object.keys(trace.assumptions).length">
        <el-divider content-position="left">分摊假设（使用者需承担假设差异带来的复核成本）</el-divider>
        <pre class="json">{{ JSON.stringify(trace.assumptions, null, 2) }}</pre>
      </template>
    </el-card>

    <el-row :gutter="14">
      <el-col :span="12">
        <el-card style="margin-bottom: 14px">
          <template #header><b>范围证据链</b></template>
          <template v-if="trace.scope_relation">
            <el-descriptions :column="1" border size="small" style="margin-bottom: 10px">
              <el-descriptions-item label="来源">{{ L('relation_kind', trace.scope_relation.relation_kind) }}</el-descriptions-item>
              <el-descriptions-item label="对象">
                {{ L('subject_type', trace.scope_relation.subject_type) }} · {{ trace.scope_relation.subject_ref }}
                <span v-if="trace.scope_relation.serial_no">（序列号 {{ trace.scope_relation.serial_no }}）</span>
              </el-descriptions-item>
              <el-descriptions-item label="状态">
                <el-tag :type="tagType('scope_status', trace.scope_relation.status)" size="small">
                  {{ L('scope_status', trace.scope_relation.status) }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </template>
          <el-table :data="trace.scope_evidence" size="small">
            <el-table-column label="证据" min-width="180">
              <template #default="{ row }">{{ row.title }}</template>
            </el-table-column>
            <el-table-column label="类型" width="110">
              <template #default="{ row }">{{ L('doc_type', row.doc_type) }}</template>
            </el-table-column>
            <el-table-column label="版本" width="60">
              <template #default="{ row }">v{{ row.version }}</template>
            </el-table-column>
            <el-table-column label="哈希" width="110">
              <template #default="{ row }"><code>{{ row.source_hash.slice(0, 8) }}…</code></template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-card style="margin-bottom: 14px">
          <template #header><b>计量边界</b></template>
          <template v-if="trace.boundary">
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="电表序列">{{ trace.boundary.meter_serial }}</el-descriptions-item>
              <el-descriptions-item label="类型">
                <el-tag :type="tagType('pipeline_kind', trace.boundary.pipeline_kind)" size="small">
                  {{ L('pipeline_kind', trace.boundary.pipeline_kind) }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="支路/管路">{{ trace.boundary.branch_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="建筑区域">{{ trace.boundary.zone_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="有效区间">
                {{ fmtDt(trace.boundary.valid_from) }} ~ {{ trace.boundary.valid_to ? fmtDt(trace.boundary.valid_to) : '至今' }}
              </el-descriptions-item>
              <el-descriptions-item label="证据强度">{{ L('evidence_strength', trace.boundary.evidence_strength) }}</el-descriptions-item>
            </el-descriptions>
          </template>
          <el-empty v-else description="无关联边界（范围门控未通过）" :image-size="60" />
          <template v-if="trace.meter_events.length">
            <el-divider content-position="left">换表事件</el-divider>
            <el-table :data="trace.meter_events" size="small">
              <el-table-column label="旧表 → 新表">
                <template #default="{ row }">{{ row.old_meter_serial }} → {{ row.new_meter_serial }}</template>
              </el-table-column>
              <el-table-column label="时间" width="110">
                <template #default="{ row }">{{ fmtDt(row.replaced_at) }}</template>
              </el-table-column>
              <el-table-column label="倍率衔接" width="110">
                <template #default="{ row }">
                  <el-tag :type="row.multiplier_linked ? 'success' : 'danger'" size="small">
                    {{ row.multiplier_linked ? '已衔接' : '断点' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </el-card>

        <el-card v-if="trace.allocation_declaration">
          <template #header><b>分摊声明证据</b></template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="标题">{{ trace.allocation_declaration.title }}</el-descriptions-item>
            <el-descriptions-item label="版本">v{{ trace.allocation_declaration.version }}</el-descriptions-item>
            <el-descriptions-item label="内容">
              <pre class="json">{{ JSON.stringify(trace.allocation_declaration.payload, null, 2) }}</pre>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card style="margin-bottom: 14px">
          <template #header><b>版本链</b>（同一谱系的签发历史，历史版本保留原结论）</template>
          <el-timeline>
            <el-timeline-item v-for="v in [...trace.version_chain].reverse()" :key="v.id"
                              :type="v.status === 'current' ? 'primary' : v.status === 'under_review' ? 'danger' : 'info'"
                              :timestamp="fmtDt(v.issued_at)">
              <div>
                <b>v{{ v.version }}</b>
                <el-tag size="small" :type="tagType('comparability', v.comparability)" style="margin: 0 6px">
                  {{ L('comparability', v.comparability) }}
                </el-tag>
                <el-tag size="small" :type="tagType('fact_status', v.status)">{{ L('fact_status', v.status) }}</el-tag>
              </div>
              <div class="vmeta">节能率 {{ fmtPct(v.savings_rate) }} · {{ L('result_kind', v.result_kind) }}</div>
            </el-timeline-item>
          </el-timeline>
        </el-card>

        <el-card>
          <template #header><b>下游引用（引用簿）</b></template>
          <el-table :data="trace.citations" size="small">
            <el-table-column label="消费方" min-width="160">
              <template #default="{ row }">{{ row.consumer_name }}</template>
            </el-table-column>
            <el-table-column label="类型" width="90">
              <template #default="{ row }">{{ row.consumer_type === 'analysis' ? '分析' : '审计视图' }}</template>
            </el-table-column>
            <el-table-column label="版本" width="60">
              <template #default="{ row }">v{{ row.fact_version }}</template>
            </el-table-column>
            <el-table-column label="登记人" width="90">
              <template #default="{ row }">{{ row.created_by }}</template>
            </el-table-column>
            <el-table-column label="时间" width="105">
              <template #default="{ row }">{{ fmtDt(row.created_at) }}</template>
            </el-table-column>
          </el-table>
          <el-empty v-if="!trace.citations.length" description="暂无引用" :image-size="60" />
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="citeVisible" title="登记引用（写入引用簿）" width="480px">
      <el-form label-width="90px">
        <el-form-item label="消费类型">
          <el-radio-group v-model="citeForm.consumer_type">
            <el-radio-button value="analysis">分析</el-radio-button>
            <el-radio-button value="audit_view">审计视图</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="消费方名称"><el-input v-model="citeForm.consumer_name" placeholder="如：2026年度节能对标分析" /></el-form-item>
        <el-form-item label="用途"><el-input v-model="citeForm.purpose" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="citeVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCitation">登记</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 10px; }
.json { background: #f6f8fa; padding: 10px; border-radius: 4px; font-size: 12px; overflow: auto; }
.vmeta { font-size: 12px; color: #888; margin-top: 2px; }
</style>
