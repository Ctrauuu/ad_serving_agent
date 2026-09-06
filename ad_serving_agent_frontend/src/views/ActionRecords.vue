<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Refresh, RefreshLeft } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { executeApprovalAction, getActionRecord, getActionRecords, getCampaign, rollbackAction } from '../api/campaign'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const campaignId = Number(route.params.id)
const campaign = ref(null)
const records = ref([])
const selected = ref(null)
const detail = ref(null)
const loading = ref(true)
const detailLoading = ref(false)
const working = ref(null)

const isLeader = computed(() => authStore.role === '投放负责人')
const actionLabel = (value) => ({ pause: '暂停投放', adjust_budget: '调整预算', adjust_bid: '调整出价', replace_creative: '更换素材', narrow_audience: '收窄人群', switch_channel: '切换渠道', extend_observation: '延长观察', manual_review: '人工复核' }[value] || value)
const statusType = (value) => ({ '成功': 'success', '失败': 'danger', '执行中': 'warning' }[value] || 'info')
const rollbackType = (value) => ({ '可回滚': 'warning', '已回滚': 'success', '回滚失败': 'danger', '需人工处理': 'danger', '回滚中': 'warning' }[value] || 'info')
const targetLabel = (item) => `${item.target_type === 'ad_group' ? '广告组' : item.target_type} #${item.target_id}`
const executorLabel = (item) => item.executor_id === authStore.user?.id ? authStore.user.display_name || '当前用户' : item.executor_id ? `用户 #${item.executor_id}` : '系统'
const json = (value) => value ? JSON.stringify(value, null, 2) : '—'
const time = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const canRollback = (item) => isLeader.value && item.status === '成功' && item.rollback_status === '可回滚'
const canRetry = (item) => item.status === '失败' && item.approval_id

async function selectRecord(item) {
  selected.value = item
  detail.value = null
  if (!item) return
  detailLoading.value = true
  try {
    detail.value = await getActionRecord(item.id)
  } finally {
    detailLoading.value = false
  }
}

async function loadRecords(keepId = selected.value?.id) {
  records.value = await getActionRecords(campaignId)
  const next = records.value.find((item) => item.id === keepId) || records.value[0] || null
  if (next?.id !== selected.value?.id) await selectRecord(next)
  else if (!next) {
    selected.value = null
    detail.value = null
  }
}

async function rollback(item) {
  working.value = `rollback-${item.id}`
  try {
    await rollbackAction(item.id)
    ElMessage.success('动作已回滚')
    await loadRecords(item.id)
    await selectRecord(records.value.find((record) => record.id === item.id))
  } finally {
    working.value = null
  }
}

async function retry(item) {
  working.value = `retry-${item.id}`
  try {
    const result = await executeApprovalAction(item.approval_id)
    ElMessage.success(result.status === '成功' ? '动作重试成功' : '重试完成，请查看结果')
    await loadRecords(result.id)
    await selectRecord(records.value.find((record) => record.id === result.id))
  } finally {
    working.value = null
  }
}

onMounted(async () => {
  try {
    campaign.value = await getCampaign(campaignId)
    await loadRecords()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main v-loading="loading" class="action-page">
    <header class="page-header">
      <div><div class="back-actions"><el-button link :icon="ArrowLeft" @click="router.push(`/campaigns/${campaignId}/suggestions`)">返回干预建议</el-button><el-button link @click="router.push('/campaigns')">返回活动管理</el-button></div><p class="eyebrow">EXECUTION LEDGER</p><h1>动作执行记录 <span v-if="campaign">· {{ campaign.name }}</span></h1><p>记录平台执行结果与可验证的状态快照，安全回滚仅开放给投放负责人。</p></div>
      <el-button :icon="Refresh" @click="loadRecords()">刷新记录</el-button>
    </header>

    <section class="action-card">
      <header><b>执行记录</b><span>{{ records.length }} 条</span></header>
      <el-table :data="records" :row-class-name="({ row }) => row.id === selected?.id ? 'is-selected' : ''" class="action-table" @row-click="selectRecord"><template #empty><el-empty description="暂无动作执行记录" :image-size="84" /></template>
        <el-table-column label="动作类型" min-width="140"><template #default="{ row }">{{ actionLabel(row.action_type) }}</template></el-table-column>
        <el-table-column label="对象" min-width="120"><template #default="{ row }">{{ targetLabel(row) }}</template></el-table-column>
        <el-table-column label="执行人" min-width="120"><template #default="{ row }">{{ executorLabel(row) }}</template></el-table-column>
        <el-table-column label="状态" min-width="92"><template #default="{ row }"><el-tag :type="statusType(row.status)" size="small" round>{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column label="回滚" min-width="112"><template #default="{ row }"><el-tag :type="rollbackType(row.rollback_status)" size="small" effect="plain" round>{{ row.rollback_status }}</el-tag></template></el-table-column>
        <el-table-column label="执行时间" min-width="170"><template #default="{ row }">{{ time(row.executed_at || row.created_at) }}</template></el-table-column>
        <el-table-column label="操作" width="110" fixed="right"><template #default="{ row }"><el-button v-if="canRollback(row)" link type="danger" :icon="RefreshLeft" :loading="working === `rollback-${row.id}`" @click.stop="rollback(row)">回滚</el-button><el-button v-else-if="canRetry(row)" link type="primary" :icon="Refresh" :loading="working === `retry-${row.id}`" @click.stop="retry(row)">重试</el-button><span v-else class="muted">—</span></template></el-table-column>
      </el-table>
    </section>

    <section class="detail-card">
      <header><div><b>选中记录详情</b><span v-if="detail">#{{ detail.id }} · {{ actionLabel(detail.action_type) }}</span></div><el-tag v-if="detail" :type="statusType(detail.status)" round>{{ detail.status }}</el-tag></header>
      <div v-loading="detailLoading" class="detail-body"><template v-if="detail"><div class="meta"><span>工具：{{ detail.tool_name || '—' }}</span><span>执行时间：{{ time(detail.executed_at) }}</span></div><div class="snapshots"><article><h3>动作前状态</h3><pre>{{ json(detail.before_state) }}</pre></article><article><h3>动作后状态</h3><pre>{{ json(detail.after_state) }}</pre></article></div><article class="tool-result"><h3>工具结果</h3><pre>{{ json(detail.tool_result) }}</pre></article><div :class="['failure', { failed: detail.error_message }]">失败原因：<b>{{ detail.error_message || '—' }}</b></div></template><el-empty v-else description="点击上方记录查看执行详情" :image-size="72" /></div>
    </section>
  </main>
</template>

<style scoped>
.action-page { min-height: 100vh; padding: 32px clamp(18px, 4vw, 64px) 58px; background: #f5f7fb; }.page-header, .action-card, .detail-card { max-width: 1320px; margin-right: auto; margin-left: auto; }.page-header { display: flex; margin-bottom: 24px; align-items: end; justify-content: space-between; gap: 20px; }.back-actions { display: flex; margin: 0 0 16px -5px; gap: 9px; }.page-header :deep(.el-button.is-link) { margin: 0; }.eyebrow { margin: 0 0 8px; color: #4b8a72; font-size: 11px; font-weight: 750; letter-spacing: 1.4px; }.page-header h1 { margin: 0; color: #202b45; font-size: 30px; letter-spacing: -1px; }.page-header h1 span { color: #69758b; font-size: 20px; font-weight: 500; }.page-header p:last-child { margin: 9px 0 0; color: #8c96aa; font-size: 14px; }.action-card, .detail-card { overflow: hidden; border: 1px solid #e4e8f0; border-radius: 11px; background: #fff; }.action-card > header, .detail-card > header { display: flex; padding: 17px 20px; align-items: center; justify-content: space-between; border-bottom: 1px solid #edf0f5; }.action-card header b, .detail-card header b { color: #34405a; font-size: 15px; }.action-card header span, .detail-card header span { margin-left: 10px; color: #929baa; font-size: 12px; }.action-table { cursor: pointer; --el-table-header-bg-color: #fafbfe; --el-table-row-hover-bg-color: #f3f8f5; }.action-table :deep(.el-table__cell) { height: 62px; }.action-table :deep(.is-selected > td.el-table__cell) { background: #eef8f1 !important; }.muted { color: #9ba4b4; font-size: 12px; }.detail-card { margin-top: 20px; }.detail-body { min-height: 235px; padding: 20px; }.meta { display: flex; margin-bottom: 16px; flex-wrap: wrap; gap: 9px 24px; color: #8490a4; font-size: 12px; }.snapshots { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }.snapshots article, .tool-result { overflow: hidden; border: 1px solid #e9edf3; border-radius: 8px; background: #fafbfe; }.tool-result { margin-top: 15px; }.detail-body h3 { margin: 0; padding: 11px 14px; color: #536078; font-size: 13px; border-bottom: 1px solid #e9edf3; background: #f4f6fa; }.detail-body pre { max-height: 220px; margin: 0; padding: 13px 14px; overflow: auto; color: #536078; font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, monospace; white-space: pre-wrap; }.failure { margin-top: 15px; padding: 12px 14px; color: #778398; font-size: 13px; border-radius: 7px; background: #f7f8fb; }.failure.failed { color: #b84e55; background: #fff2f2; }.failure b { font-weight: 500; }
@media (max-width: 760px) { .action-page { padding: 24px 13px 42px; }.page-header { align-items: start; flex-direction: column; }.page-header > .el-button { width: 100%; }.action-table :deep(.el-table__body-wrapper) { overflow-x: auto; }.snapshots { grid-template-columns: 1fr; } }
</style>
