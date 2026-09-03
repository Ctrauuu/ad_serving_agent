<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { getAdTasks, getCampaign, syncAdTaskStatus } from '../api/campaign'

const route = useRoute()
const router = useRouter()
const campaignId = Number(route.params.id)
const taskId = Number(route.params.taskId)
const campaign = ref(null)
const plans = ref([])
const loading = ref(true)
const refreshing = ref(false)
const plan = computed(() => plans.value.find((item) => item.id === taskId))
const statusType = (status) => ({ '已上线': 'success', '创建失败': 'danger', '待创建': 'info' }[status] || 'warning')

async function load() {
  const result = await getAdTasks(campaignId)
  plans.value = result.plans
}

async function refresh() {
  refreshing.value = true
  try {
    await syncAdTaskStatus(taskId)
    await load()
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  try {
    const [campaignResult] = await Promise.all([getCampaign(campaignId), load()])
    campaign.value = campaignResult
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main v-loading="loading" class="detail-page">
    <header class="page-header">
      <div><el-button link :icon="ArrowLeft" @click="router.push(`/campaigns/${campaignId}/ad-tasks`)">返回任务列表</el-button><p class="eyebrow">AD TASK / DETAIL</p><h1>投流任务详情 <span v-if="campaign">· {{ campaign.name }}</span></h1></div>
      <el-button :icon="Refresh" :loading="refreshing" @click="refresh">刷新状态</el-button>
    </header>

    <el-empty v-if="!plan && !loading" description="广告任务不存在或无权访问" />
    <template v-else-if="plan">
      <section class="summary"><div><span>广告计划</span><b>{{ plan.name }}</b></div><div><span>任务状态</span><el-tag :type="statusType(plan.status)" round>{{ plan.status }}</el-tag></div><div><span>计划预算</span><b>¥{{ plan.budget_total }}</b></div><div><span>日预算</span><b>¥{{ plan.budget_daily }}</b></div></section>
      <el-alert v-if="plan.error_message" :title="plan.error_message" type="error" :closable="false" show-icon class="error-alert" />
      <el-card class="detail-card" shadow="never"><template #header><b>投放配置</b></template><el-descriptions :column="2" border><el-descriptions-item label="计划 ID">{{ plan.id }}</el-descriptions-item><el-descriptions-item label="平台任务 ID">{{ plan.ad_platform_task_id || '待创建' }}</el-descriptions-item><el-descriptions-item label="策略 ID">{{ plan.strategy_id }}</el-descriptions-item><el-descriptions-item label="出价策略">{{ plan.bid_strategy || '—' }}</el-descriptions-item></el-descriptions></el-card>
      <el-card class="detail-card" shadow="never"><template #header><b>广告组</b></template><el-table :data="plan.groups" class="group-table"><el-table-column prop="name" label="广告组" min-width="180" /><el-table-column prop="audience_id" label="人群 ID" min-width="110" /><el-table-column prop="creative_id" label="素材 ID" min-width="110" /><el-table-column label="出价" min-width="100"><template #default="{ row }">¥{{ row.bid }}</template></el-table-column><el-table-column label="状态" min-width="110"><template #default="{ row }"><el-tag :type="statusType(row.status)" round>{{ row.status }}</el-tag></template></el-table-column><el-table-column label="关键词" min-width="190"><template #default="{ row }">{{ row.keywords.map((item) => item.word).join('、') || '—' }}</template></el-table-column></el-table></el-card>
    </template>
  </main>
</template>

<style scoped>
.detail-page { min-height: 100vh; padding: 32px clamp(20px, 5vw, 72px) 60px; background: #f5f7fb; }.page-header, .summary, .detail-card, .error-alert { max-width: 1120px; margin-right: auto; margin-left: auto; }.page-header { display: flex; margin-bottom: 26px; align-items: end; justify-content: space-between; gap: 20px; }.page-header :deep(.el-button.is-link) { margin: 0 0 19px -5px; }.eyebrow { margin: 0 0 8px; color: #6475d9; font-size: 11px; font-weight: 750; letter-spacing: 1.4px; }.page-header h1 { margin: 0; color: #202b45; font-size: 30px; letter-spacing: -1px; }.page-header h1 span { color: #69758b; font-size: 20px; font-weight: 500; }.summary { display: grid; margin-bottom: 20px; grid-template-columns: repeat(4, 1fr); border: 1px solid #e7eaf1; border-radius: 12px; background: #fff; }.summary > div { display: grid; min-height: 85px; padding: 18px 22px; align-content: center; border-right: 1px solid #edf0f5; }.summary > div:last-child { border: 0; }.summary span { margin-bottom: 6px; color: #959eaf; font-size: 12px; }.summary b { color: #38445e; font-size: 15px; }.error-alert { margin-bottom: 20px; }.detail-card { margin-top: 20px; border: 1px solid #e7eaf1; border-radius: 12px; }.group-table { --el-table-header-bg-color: #fafbfe; }
@media (max-width: 700px) { .detail-page { padding: 24px 14px 44px; }.page-header { align-items: start; flex-direction: column; }.summary { grid-template-columns: 1fr 1fr; }.summary > div:nth-child(2) { border-right: 0; }.summary > div:nth-child(-n+2) { border-bottom: 1px solid #edf0f5; } }
</style>
