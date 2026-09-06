<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Check, MagicStick, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { approveApproval, generateSuggestions, getAnomalies, getApprovals, getCampaign, getSuggestions, rejectApproval, submitSuggestionApproval } from '../api/campaign'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const campaignId = Number(route.params.id)
const campaign = ref(null)
const anomalies = ref([])
const anomalyId = ref(Number(route.query.anomaly_id) || null)
const suggestionResult = ref(null)
const approvalRows = ref([])
const selectedApproval = ref(null)
const loading = ref(true)
const generating = ref(false)
const submittingId = ref(null)
const deciding = ref(false)
const rejectVisible = ref(false)
const rejectReason = ref('')

const isLeader = computed(() => authStore.role === '投放负责人')
const suggestions = computed(() => suggestionResult.value?.suggestions || [])
const currentAnomaly = computed(() => anomalies.value.find((item) => item.id === anomalyId.value))
const approvals = computed(() => approvalRows.value.filter((item) => item.approval.campaign_id === campaignId))
const pendingApprovals = computed(() => approvals.value.filter((item) => item.approval.status === '待审批'))
const actionLabel = (value) => ({ pause: '暂停投放', adjust_budget: '调整预算', adjust_bid: '调整出价', replace_creative: '更换素材', narrow_audience: '收窄人群', switch_channel: '切换渠道', extend_observation: '延长观察', manual_review: '人工复核' }[value] || value)
const riskType = (value) => ({ '高': 'danger', '中': 'warning', '低': 'success' }[value] || 'info')
const approvalType = (value) => ({ '已通过': 'success', '已驳回': 'danger', '已超时': 'info', '待审批': 'warning' }[value] || 'info')
const targetLabel = (item) => `${item.target_type === 'ad_group' ? '广告组' : item.target_type} #${item.target_id}`
const compact = (value) => value && Object.keys(value).length ? Object.entries(value).map(([key, item]) => `${key}: ${typeof item === 'object' ? JSON.stringify(item) : item}`).join('；') : '—'
const formatTime = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'

async function loadSuggestions() {
  suggestionResult.value = null
  if (!anomalyId.value) return
  try {
    suggestionResult.value = await getSuggestions(anomalyId.value, { silent: true })
  } catch {
    suggestionResult.value = null
  }
}

async function loadApprovals() {
  if (!isLeader.value) return
  approvalRows.value = await getApprovals()
  const next = pendingApprovals.value.find((item) => item.approval.id === selectedApproval.value?.approval.id) || pendingApprovals.value[0] || approvals.value[0] || null
  selectedApproval.value = next
}

async function changeAnomaly() {
  await loadSuggestions()
  router.replace({ query: anomalyId.value ? { anomaly_id: anomalyId.value } : {} })
}

async function generate() {
  if (!anomalyId.value) return
  generating.value = true
  try {
    suggestionResult.value = await generateSuggestions(anomalyId.value)
    ElMessage.success('干预建议已生成')
  } finally {
    generating.value = false
  }
}

async function submit(suggestion) {
  submittingId.value = suggestion.id
  try {
    const result = await submitSuggestionApproval(suggestion.id)
    suggestion.status = result.suggestion.status
    ElMessage.success(result.approval.auto_execute ? '低风险建议已进入待执行' : '建议已提交负责人审批')
    await loadApprovals()
  } finally {
    submittingId.value = null
  }
}

async function approve() {
  if (!selectedApproval.value) return
  deciding.value = true
  try {
    await approveApproval(selectedApproval.value.approval.id)
    ElMessage.success('审批已通过，建议已进入待执行')
    await loadApprovals()
  } finally {
    deciding.value = false
  }
}

function openReject() {
  rejectReason.value = ''
  rejectVisible.value = true
}

async function reject() {
  if (!rejectReason.value.trim()) return ElMessage.warning('请填写驳回原因')
  deciding.value = true
  try {
    await rejectApproval(selectedApproval.value.approval.id, rejectReason.value.trim())
    rejectVisible.value = false
    ElMessage.success('审批已驳回')
    await loadApprovals()
  } finally {
    deciding.value = false
  }
}

watch(anomalyId, changeAnomaly)
onMounted(async () => {
  try {
    const [campaignResult, anomalyResult] = await Promise.all([getCampaign(campaignId), getAnomalies(campaignId)])
    campaign.value = campaignResult
    anomalies.value = anomalyResult
    if (!anomalyId.value || !anomalies.value.some((item) => item.id === anomalyId.value)) anomalyId.value = anomalies.value[0]?.id || null
    else await loadSuggestions()
    await loadApprovals()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main v-loading="loading" class="suggestion-page">
    <div v-if="generating" class="generation-overlay"><el-icon class="is-loading"><MagicStick /></el-icon><b>AI 正在生成干预建议</b><span>正在综合归因证据、风险边界与历史案例</span></div>
    <header class="page-header">
      <div><el-button link :icon="ArrowLeft" @click="router.push(`/campaigns/${campaignId}/anomalies`)">返回异动归因</el-button><p class="eyebrow">INTERVENTION CONTROL</p><h1>干预建议与审批 <span v-if="campaign">· {{ campaign.name }}</span></h1><p>每项动作均附带指标证据、预期影响及风险控制边界。</p></div>
      <el-button type="primary" size="large" :icon="MagicStick" :disabled="!anomalyId" :loading="generating" @click="generate">{{ suggestions.length ? '重新生成建议' : '生成干预建议' }}</el-button>
    </header>

    <section class="selector-card"><span>关联异常</span><el-select v-model="anomalyId" placeholder="请选择异常" :disabled="!anomalies.length"><el-option v-for="item in anomalies" :key="item.id" :label="`${item.anomaly_type} · ${targetLabel(item)}`" :value="item.id" /></el-select><el-tag v-if="currentAnomaly" :type="riskType(currentAnomaly.severity)" effect="plain" round>{{ currentAnomaly.severity }}风险</el-tag><el-button :icon="Refresh" text @click="loadSuggestions">刷新建议</el-button></section>

    <section class="suggestion-card">
      <header><div><b>建议列表</b><span v-if="suggestionResult">数据充分性：{{ suggestionResult.data_sufficient ? '充分' : '不足' }} · {{ suggestionResult.has_historical_cases ? '已参考历史案例' : '暂无历史案例' }}</span></div></header>
      <el-table :data="suggestions" class="suggestion-table"><template #empty><el-empty :description="anomalyId ? '暂未生成建议，可点击右上角生成' : '请先选择一条异常'" :image-size="84" /></template>
        <el-table-column label="动作" min-width="135"><template #default="{ row }"><b>{{ actionLabel(row.action_type) }}</b><small v-if="row.is_primary">主建议</small></template></el-table-column>
        <el-table-column label="对象" min-width="120"><template #default="{ row }">{{ targetLabel(row) }}</template></el-table-column>
        <el-table-column label="风险" min-width="92"><template #default="{ row }"><el-tag :type="riskType(row.risk_level)" size="small" round>{{ row.risk_level }}</el-tag></template></el-table-column>
        <el-table-column label="指标证据" min-width="240" show-overflow-tooltip><template #default="{ row }">{{ compact(row.metric_evidence) }}</template></el-table-column>
        <el-table-column label="预估影响" min-width="190" show-overflow-tooltip><template #default="{ row }">{{ compact(row.expected_impact) }}</template></el-table-column>
        <el-table-column label="状态" min-width="100"><template #default="{ row }"><el-tag size="small" effect="plain">{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="132" fixed="right"><template #default="{ row }"><el-button v-if="row.status === '待提交'" link type="primary" :loading="submittingId === row.id" @click="submit(row)">{{ row.risk_level === '低' ? '自动执行' : '提交审批' }}</el-button><span v-else class="muted">{{ row.status === '待执行' ? '已待执行' : '—' }}</span></template></el-table-column>
      </el-table>
    </section>

    <section v-if="isLeader" class="approval-section">
      <header class="section-title"><div><p>负责人视角</p><h2>待审批建议 <el-badge :value="pendingApprovals.length" :hidden="!pendingApprovals.length" /></h2></div><el-button :icon="Refresh" @click="loadApprovals">刷新审批</el-button></header>
      <div class="approval-layout">
        <section class="approval-list"><el-empty v-if="!approvals.length" description="暂无审批记录" :image-size="72" /><button v-for="item in approvals" :key="item.approval.id" :class="['approval-row', { active: selectedApproval?.approval.id === item.approval.id }]" @click="selectedApproval = item"><span>{{ actionLabel(item.suggestion.action_type) }}</span><small>{{ targetLabel(item.suggestion) }} · {{ formatTime(item.approval.submitted_at) }}</small><el-tag :type="approvalType(item.approval.status)" size="small" round>{{ item.approval.status }}</el-tag></button></section>
        <aside class="approval-detail"><template v-if="selectedApproval"><div class="detail-top"><div><p>审批详情</p><h3>{{ actionLabel(selectedApproval.suggestion.action_type) }} · {{ targetLabel(selectedApproval.suggestion) }}</h3></div><el-tag :type="riskType(selectedApproval.suggestion.risk_level)" effect="dark" round>{{ selectedApproval.suggestion.risk_level }}风险</el-tag></div><dl><dt>指标证据</dt><dd>{{ compact(selectedApproval.suggestion.metric_evidence) }}</dd><dt>预估影响</dt><dd>{{ compact(selectedApproval.suggestion.expected_impact) }}</dd><dt>风险说明</dt><dd>{{ selectedApproval.suggestion.risk_notes || '—' }}</dd><dt v-if="selectedApproval.approval.reject_reason">驳回原因</dt><dd v-if="selectedApproval.approval.reject_reason">{{ selectedApproval.approval.reject_reason }}</dd></dl><div v-if="selectedApproval.approval.status === '待审批'" class="approval-actions"><el-button type="danger" plain @click="openReject">驳回</el-button><el-button type="primary" :icon="Check" :loading="deciding" @click="approve">通过</el-button></div><div v-else-if="selectedApproval.approval.status === '已通过'" class="approved-action"><el-icon><Check /></el-icon> 已通过审批，<el-button link type="primary" @click="router.push(`/campaigns/${campaignId}/actions`)">查看执行记录</el-button></div></template><el-empty v-else description="请选择一条审批记录" :image-size="72" /></aside>
      </div>
    </section>

    <el-dialog v-model="rejectVisible" title="驳回审批" width="420px"><el-form label-position="top"><el-form-item label="驳回原因" required><el-input v-model="rejectReason" type="textarea" :rows="4" maxlength="512" show-word-limit placeholder="请说明驳回原因" /></el-form-item></el-form><template #footer><el-button @click="rejectVisible = false">取消</el-button><el-button type="danger" :loading="deciding" @click="reject">确认驳回</el-button></template></el-dialog>
  </main>
</template>

<style scoped>
.suggestion-page { min-height: 100vh; padding: 32px clamp(18px, 4vw, 64px) 58px; background: #f5f7fb; }.page-header, .selector-card, .suggestion-card, .approval-section { max-width: 1320px; margin-right: auto; margin-left: auto; }.page-header { display: flex; margin-bottom: 24px; align-items: end; justify-content: space-between; gap: 20px; }.page-header :deep(.el-button.is-link) { margin: 0 0 16px -5px; }.eyebrow { margin: 0 0 8px; color: #ba6d20; font-size: 11px; font-weight: 750; letter-spacing: 1.4px; }.page-header h1 { margin: 0; color: #202b45; font-size: 30px; letter-spacing: -1px; }.page-header h1 span { color: #69758b; font-size: 20px; font-weight: 500; }.page-header p:last-child { margin: 9px 0 0; color: #8c96aa; font-size: 14px; }.generation-overlay { position: fixed; z-index: 100; inset: 0; display: grid; gap: 13px; place-content: center; color: #fff; text-align: center; background: rgba(32, 39, 65, .76); backdrop-filter: blur(4px); }.generation-overlay .el-icon { margin: auto; color: #f1ad61; font-size: 38px; }.generation-overlay span { color: #d9deea; font-size: 13px; }.selector-card { display: flex; margin-bottom: 18px; padding: 14px 17px; align-items: center; gap: 12px; border: 1px solid #e4e8f0; border-radius: 11px; background: #fff; }.selector-card > span { color: #647087; font-size: 13px; }.selector-card :deep(.el-select) { width: 320px; }.suggestion-card { overflow: hidden; border: 1px solid #e4e8f0; border-radius: 11px; background: #fff; }.suggestion-card > header { display: flex; padding: 17px 20px; align-items: center; justify-content: space-between; border-bottom: 1px solid #edf0f5; }.suggestion-card header b { color: #34405a; font-size: 15px; }.suggestion-card header span { margin-left: 11px; color: #929baa; font-size: 12px; }.suggestion-table { --el-table-header-bg-color: #fafbfe; --el-table-row-hover-bg-color: #f8f9ff; }.suggestion-table :deep(.el-table__cell) { height: 66px; }.suggestion-table b { color: #3f4b65; font-size: 13px; }.suggestion-table small { display: block; margin-top: 4px; color: #7181dc; font-size: 11px; }.muted { color: #9ba4b4; font-size: 12px; }.approval-section { margin-top: 28px; }.section-title { display: flex; margin-bottom: 13px; align-items: end; justify-content: space-between; }.section-title p { margin: 0 0 5px; color: #a96b32; font-size: 11px; font-weight: 700; letter-spacing: 1.3px; }.section-title h2 { margin: 0; color: #34405a; font-size: 19px; }.section-title :deep(.el-badge) { margin-left: 6px; vertical-align: top; }.approval-layout { display: grid; grid-template-columns: minmax(240px, .7fr) minmax(0, 1.3fr); min-height: 335px; overflow: hidden; border: 1px solid #e4e8f0; border-radius: 11px; background: #fff; }.approval-list { padding: 8px; border-right: 1px solid #edf0f5; }.approval-row { display: grid; width: 100%; margin-bottom: 5px; padding: 12px; grid-template-columns: 1fr auto; gap: 5px 9px; color: #4c5870; text-align: left; cursor: pointer; border: 0; border-radius: 8px; background: transparent; }.approval-row:hover, .approval-row.active { background: #f2f5ff; }.approval-row span { font-size: 13px; font-weight: 650; }.approval-row small { color: #919bad; font-size: 11px; }.approval-row .el-tag { grid-row: span 2; grid-column: 2; align-self: center; }.approval-detail { padding: 21px 24px; }.detail-top { display: flex; align-items: start; justify-content: space-between; gap: 10px; }.detail-top p { margin: 0 0 5px; color: #9099aa; font-size: 12px; }.detail-top h3 { margin: 0; color: #34405a; font-size: 16px; }.approval-detail dl { display: grid; margin: 18px 0; grid-template-columns: 90px 1fr; gap: 13px; font-size: 13px; }.approval-detail dt { color: #8c96a8; }.approval-detail dd { margin: 0; color: #56637b; line-height: 1.55; }.approval-actions { display: flex; justify-content: end; gap: 9px; }.approved-action { display: flex; align-items: center; color: #4f9a72; font-size: 13px; }.approved-action .el-icon { margin-right: 5px; }.approved-action :deep(.el-button) { margin-left: 3px; }.approval-list :deep(.el-empty) { min-height: 280px; }.generation-overlay b { font-size: 18px; }
@media (max-width: 820px) { .page-header { align-items: start; flex-direction: column; }.selector-card { align-items: stretch; flex-wrap: wrap; }.selector-card :deep(.el-select) { width: min(100%, 320px); }.approval-layout { grid-template-columns: 1fr; }.approval-list { border-right: 0; border-bottom: 1px solid #edf0f5; }.suggestion-table :deep(.el-table__body-wrapper) { overflow-x: auto; } } @media (max-width: 520px) { .suggestion-page { padding: 24px 13px 42px; }.page-header > .el-button { width: 100%; }.selector-card { gap: 9px; }.selector-card > .el-button { margin-left: auto; }.approval-detail { padding: 18px; }.approval-detail dl { grid-template-columns: 1fr; gap: 4px; }.approval-detail dd { margin-bottom: 10px; } }
</style>
