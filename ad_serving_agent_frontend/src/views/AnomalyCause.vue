<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Loading, Search, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { analyzeAnomalyCause, getAnomalies, getAnomalyCause, getCampaign, scanAnomalies } from '../api/campaign'

const route = useRoute()
const router = useRouter()
const campaignId = Number(route.params.id)
const campaign = ref(null)
const anomalies = ref([])
const selected = ref(null)
const causeResult = ref(null)
const loading = ref(true)
const scanning = ref(false)
const causeLoading = ref(false)
const causeLoadingState = ref(false)

const causes = computed(() => [...(causeResult.value?.causes || [])].sort((a, b) => Number(b.confidence) - Number(a.confidence)))
const severityType = (severity) => ({ '高': 'danger', '中': 'warning', '低': 'info' }[severity] || 'info')
const statusType = (status) => ({ '已归因': 'success', '已处理': 'info', '待归因': 'warning' }[status] || 'info')
const formatValue = (value) => value === null || value === undefined ? '—' : Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 4 })
const formatTime = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const targetLabel = (item) => `${item.target_type === 'ad_group' ? '广告组' : item.target_type} #${item.target_id}`

async function loadAnomalies(preserveId = selected.value?.id) {
  anomalies.value = await getAnomalies(campaignId)
  const next = anomalies.value.find((item) => item.id === preserveId) || anomalies.value[0] || null
  if (next?.id !== selected.value?.id) await selectAnomaly(next)
  else if (!next) {
    selected.value = null
    causeResult.value = null
  }
}

async function selectAnomaly(item) {
  selected.value = item
  causeResult.value = null
  if (!item) return
  causeLoadingState.value = true
  try {
    causeResult.value = await getAnomalyCause(item.id, { silent: true })
  } catch {
    causeResult.value = null
  } finally {
    causeLoadingState.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    const result = await scanAnomalies(campaignId)
    await loadAnomalies(result.created_ids?.[0])
    ElMessage.success(`扫描完成：发现 ${result.created_count} 条新异常`)
  } finally {
    scanning.value = false
  }
}

async function analyze() {
  if (!selected.value) return
  causeLoading.value = true
  try {
    causeResult.value = await analyzeAnomalyCause(selected.value.id)
    await loadAnomalies(selected.value.id)
    ElMessage.success('归因分析完成')
  } finally {
    causeLoading.value = false
  }
}

function goSuggestions() {
  router.push({ path: `/campaigns/${campaignId}/suggestions`, query: { anomaly_id: selected.value.id } })
}

onMounted(async () => {
  try {
    campaign.value = await getCampaign(campaignId)
    await loadAnomalies()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main v-loading="loading" class="anomaly-page">
    <header class="page-header">
      <div>
        <el-button link :icon="ArrowLeft" @click="router.push('/campaigns')">返回活动列表</el-button>
        <p class="eyebrow">ANOMALY INTELLIGENCE</p>
        <h1>异动识别与归因 <span v-if="campaign">· {{ campaign.name }}</span></h1>
        <p>从实时投放数据中定位风险，并追溯可验证的原因假设。</p>
      </div>
      <el-button type="primary" size="large" :icon="Search" :loading="scanning" @click="scan">触发扫描</el-button>
    </header>

    <section class="workspace">
      <section class="list-panel">
        <header><div><b>异常列表</b><span>{{ anomalies.length }} 条记录</span></div><el-button link @click="loadAnomalies()">刷新</el-button></header>
        <el-table :data="anomalies" :row-class-name="({ row }) => row.id === selected?.id ? 'is-selected' : ''" class="anomaly-table" @row-click="selectAnomaly">
          <template #empty><el-empty description="暂无异常，可手动触发扫描" :image-size="82" /></template>
          <el-table-column prop="anomaly_type" label="类型" min-width="150" show-overflow-tooltip />
          <el-table-column label="对象" min-width="120"><template #default="{ row }">{{ targetLabel(row) }}</template></el-table-column>
          <el-table-column label="指标值" min-width="104" align="right"><template #default="{ row }">{{ formatValue(row.metric_value) }}</template></el-table-column>
          <el-table-column label="基线值" min-width="104" align="right"><template #default="{ row }">{{ formatValue(row.baseline_value) }}</template></el-table-column>
          <el-table-column label="严重程度" min-width="105"><template #default="{ row }"><el-tag :type="severityType(row.severity)" size="small" round>{{ row.severity }}</el-tag></template></el-table-column>
          <el-table-column label="状态" min-width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)" size="small" effect="plain" round>{{ row.status }}</el-tag></template></el-table-column>
        </el-table>
      </section>

      <aside class="cause-panel">
        <template v-if="selected">
          <header><div><p>选中异常</p><h2>{{ selected.anomaly_type }}</h2></div><el-tag :type="severityType(selected.severity)" effect="dark" round>{{ selected.severity }}风险</el-tag></header>
          <div class="selected-meta"><span>{{ targetLabel(selected) }}</span><span>{{ selected.metric }}：{{ formatValue(selected.metric_value) }}</span><span>{{ formatTime(selected.detected_at) }}</span></div>

          <div v-if="causeLoadingState" class="empty-state"><el-icon class="is-loading"><Loading /></el-icon>正在读取归因结果…</div>
          <template v-else-if="causeResult">
            <div :class="['sufficiency', { insufficient: !causeResult.data_sufficient }]">
              <el-icon><WarningFilled /></el-icon><span>数据充分性：<b>{{ causeResult.data_sufficient ? '充分' : '不足' }}</b></span>
              <small>{{ causeResult.has_historical_cases ? '已参考历史案例' : '暂无可用历史案例' }}</small>
            </div>
            <div class="cause-list">
              <article v-for="(cause, index) in causes" :key="cause.id" class="cause-card">
                <div class="cause-title"><span>原因假设 {{ index + 1 }}</span><el-tag type="primary" effect="plain" round>置信度 {{ (Number(cause.confidence) * 100).toFixed(0) }}%</el-tag></div>
                <h3>{{ cause.cause_type }}</h3><p>{{ cause.hypothesis }}</p>
                <div class="evidence"><span>证据来源</span><div><el-tag v-for="evidence in cause.evidence_sources || []" :key="`${evidence.type}-${evidence.ref}`" size="small" effect="plain">{{ evidence.type }} · {{ evidence.ref }}{{ evidence.description ? `：${evidence.description}` : '' }}</el-tag></div></div>
              </article>
            </div>
            <el-button class="suggestion-button" type="primary" size="large" :disabled="!causes.length" @click="goSuggestions">生成干预建议</el-button>
          </template>
          <div v-else class="empty-cause"><el-icon><WarningFilled /></el-icon><b>尚未生成归因</b><span>将结合指标、素材、人群与历史数据分析异常原因。</span><el-button type="primary" :loading="causeLoading" @click="analyze">分析原因</el-button></div>
        </template>
        <div v-else class="empty-cause"><el-icon><WarningFilled /></el-icon><b>请选择一条异常</b><span>点击左侧异常记录查看归因结果。</span></div>
      </aside>
    </section>
  </main>
</template>

<style scoped>
.anomaly-page { min-height: 100vh; padding: 30px clamp(18px, 4vw, 64px) 54px; color: #dce5f3; background: #111827; }.page-header, .workspace { max-width: 1420px; margin: 0 auto; }.page-header { display: flex; margin-bottom: 24px; align-items: end; justify-content: space-between; gap: 20px; }.page-header :deep(.el-button.is-link) { margin: 0 0 16px -5px; color: #8fa5cf; }.eyebrow { margin: 0 0 7px; color: #e9a34e; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; }.page-header h1 { margin: 0; color: #f0f5ff; font-size: 29px; letter-spacing: -1px; }.page-header h1 span { color: #9cabca; font-size: 19px; font-weight: 500; }.page-header p:last-child { margin: 9px 0 0; color: #8391a8; font-size: 13px; }.workspace { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(360px, .85fr); gap: 14px; align-items: start; }.list-panel, .cause-panel { overflow: hidden; border: 1px solid #26354c; border-radius: 9px; background: #182235; }.list-panel > header { display: flex; padding: 17px 19px; align-items: center; justify-content: space-between; border-bottom: 1px solid #26354c; }.list-panel header b { color: #e5ecf8; font-size: 14px; }.list-panel header span { margin-left: 10px; color: #8090a9; font-size: 12px; }.anomaly-table { cursor: pointer; --el-table-bg-color: #182235; --el-table-tr-bg-color: #182235; --el-table-header-bg-color: #1d2a40; --el-table-row-hover-bg-color: #243650; --el-table-border-color: #26354c; --el-table-text-color: #d3ddec; --el-table-header-text-color: #98a9c1; }.anomaly-table :deep(.el-table__inner-wrapper:before) { display: none; }.anomaly-table :deep(.el-table__cell) { height: 61px; }.anomaly-table :deep(.is-selected > td.el-table__cell) { background: #243a5a !important; }.cause-panel { min-height: 495px; padding: 20px; }.cause-panel > header { display: flex; align-items: start; justify-content: space-between; gap: 12px; }.cause-panel header p { margin: 0 0 5px; color: #8191aa; font-size: 12px; }.cause-panel h2 { margin: 0; color: #eef4ff; font-size: 18px; }.selected-meta { display: flex; margin: 17px 0; padding: 10px 0; flex-wrap: wrap; gap: 8px 14px; border-top: 1px solid #26354c; border-bottom: 1px solid #26354c; color: #9aa9bd; font-size: 12px; }.sufficiency { display: flex; margin-bottom: 16px; padding: 11px 12px; align-items: center; flex-wrap: wrap; gap: 7px; border: 1px solid rgba(71, 215, 166, .35); border-radius: 6px; background: rgba(71, 215, 166, .08); color: #8ce7c5; font-size: 12px; }.sufficiency.insufficient { border-color: rgba(243, 173, 87, .4); background: rgba(243, 173, 87, .09); color: #f3bd71; }.sufficiency small { color: #91a0b5; }.cause-list { display: grid; gap: 10px; }.cause-card { padding: 13px; border: 1px solid #2a3951; border-radius: 7px; background: #1c283b; }.cause-title { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #91a0b6; font-size: 12px; }.cause-card h3 { margin: 10px 0 5px; color: #e6edf9; font-size: 14px; }.cause-card p { margin: 0; color: #b5c0d2; font-size: 13px; line-height: 1.55; }.evidence { display: grid; margin-top: 12px; gap: 6px; color: #7e8ea6; font-size: 11px; }.evidence > div { display: flex; flex-wrap: wrap; gap: 5px; }.evidence :deep(.el-tag) { max-width: 100%; overflow: hidden; color: #a8b8cf; border-color: #3b4b65; background: #202e43; text-overflow: ellipsis; }.suggestion-button { width: 100%; margin-top: 16px; }.empty-cause, .empty-state { display: flex; min-height: 315px; align-items: center; justify-content: center; flex-direction: column; gap: 10px; color: #8e9db3; text-align: center; font-size: 13px; }.empty-cause :deep(.el-icon) { color: #f3ad57; font-size: 28px; }.empty-cause b { color: #dce5f3; font-size: 15px; }.empty-cause span { max-width: 250px; line-height: 1.55; }.empty-cause .el-button { margin-top: 8px; }.empty-state { min-height: 260px; }.empty-state :deep(.el-icon) { color: #65d4ee; font-size: 22px; }
@media (max-width: 980px) { .workspace { grid-template-columns: 1fr; }.cause-panel { min-height: 0; }.empty-cause { min-height: 220px; } } @media (max-width: 620px) { .anomaly-page { padding: 22px 12px 36px; }.page-header { align-items: start; flex-direction: column; }.page-header .el-button { width: 100%; }.anomaly-table :deep(.el-table__body-wrapper) { overflow-x: auto; }.cause-panel { padding: 16px; } }
</style>
