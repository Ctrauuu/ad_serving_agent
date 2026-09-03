<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, CircleCheck, MagicStick, Refresh, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { createAdTasks, getAdTasks, getAudiences, getCampaign, getChannels, getCreatives, syncAdTaskStatus } from '../api/campaign'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const campaignId = Number(route.params.id)
const campaign = ref(null)
const taskData = ref({ plans: [], status: '' })
const audiences = ref([])
const creatives = ref([])
const channels = ref([])
const loading = ref(true)
const creating = ref(false)
const refreshing = ref(false)
const retrying = ref(null)
const form = reactive({ audience_id: '', creative_id: '', bid: 5 })
const canCreate = computed(() => authStore.role === '投放人员')
const audienceNames = computed(() => Object.fromEntries(audiences.value.map((item) => [item.id, item.name])))
const channelNames = computed(() => Object.fromEntries(channels.value.map((item) => [item.id, item.name])))
const rows = computed(() => taskData.value.plans.flatMap((plan) => plan.groups.length ? plan.groups.map((group) => ({ ...group, plan })) : [{ id: `plan-${plan.id}`, plan, name: '—', audience_id: null, status: plan.status, error_message: plan.error_message }]))
const allOnline = computed(() => rows.value.length && taskData.value.plans.every((plan) => plan.status === '已上线') && rows.value.every((row) => row.status === '已上线'))

const statusType = (status) => ({ '已上线': 'success', '创建失败': 'danger', '待创建': 'info' }[status] || 'warning')
const audienceName = (id) => audienceNames.value[id] || (id ? `人群 #${id}` : '—')
const channelName = (id) => channelNames.value[id] || `渠道 #${id}`

async function loadTasks() {
  taskData.value = await getAdTasks(campaignId)
}

async function createTasks(payload = form) {
  if (!payload.audience_id || !payload.creative_id || !payload.bid) {
    ElMessage.warning('请选择人群、素材并填写出价')
    return
  }
  creating.value = true
  try {
    taskData.value = await createAdTasks(campaignId, { audience_id: Number(payload.audience_id), creative_id: Number(payload.creative_id), bid: Number(payload.bid) })
    if (allOnline.value) ElMessage.success('全部广告任务已上线，可前往监控看板')
    else ElMessage.warning('部分任务未上线，请查看失败原因后重试')
  } finally {
    creating.value = false
  }
}

async function retry(row) {
  retrying.value = row.id
  try {
    await createTasks({ audience_id: row.audience_id, creative_id: row.creative_id, bid: row.bid })
  } finally {
    retrying.value = null
  }
}

async function refresh() {
  refreshing.value = true
  try {
    await Promise.all(taskData.value.plans.map((plan) => syncAdTaskStatus(plan.id)))
    await loadTasks()
    if (allOnline.value) ElMessage.success('全部广告任务已上线')
  } finally {
    refreshing.value = false
  }
}

onMounted(async () => {
  try {
    const [campaignResult, tasksResult, audienceResult, creativeResult, channelResult] = await Promise.all([getCampaign(campaignId), getAdTasks(campaignId), getAudiences(), getCreatives(), getChannels()])
    campaign.value = campaignResult
    taskData.value = tasksResult
    audiences.value = audienceResult
    creatives.value = creativeResult
    channels.value = channelResult
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main v-loading="loading" class="tasks-page">
    <header class="page-header">
      <div>
        <el-button link :icon="ArrowLeft" @click="router.push(`/campaigns/${campaignId}/strategy`)">返回策略</el-button>
        <p class="eyebrow">CAMPAIGN CENTER / AD TASKS</p>
        <h1>广告任务 <span v-if="campaign">· {{ campaign.name }}</span></h1>
        <p>根据已确认策略创建广告计划和广告组，并同步平台上线状态。</p>
      </div>
      <div class="header-actions"><el-button :icon="Refresh" :loading="refreshing" @click="refresh">刷新状态</el-button><el-button v-if="allOnline" type="success" :icon="VideoPlay" @click="router.push(`/campaigns/${campaignId}/monitor`)">前往监控看板</el-button></div>
    </header>

    <el-card v-if="canCreate" class="create-card" shadow="never">
      <div class="create-copy"><div class="create-icon"><MagicStick /></div><div><b>按策略创建任务</b><p>选择首轮投放人群、素材和出价后，系统将自动拆分并创建各渠道广告任务。</p></div></div>
      <div class="create-form"><el-select v-model="form.audience_id" filterable placeholder="选择投放人群"><el-option v-for="item in audiences" :key="item.id" :label="item.name" :value="item.id" /></el-select><el-select v-model="form.creative_id" filterable placeholder="选择投放素材"><el-option v-for="item in creatives" :key="item.id" :label="item.name" :value="item.id" /></el-select><el-input v-model.number="form.bid" type="number" :min="0.01" placeholder="出价"><template #prepend>¥</template></el-input><el-button type="primary" :loading="creating" @click="createTasks()">按策略创建任务</el-button></div>
    </el-card>

    <el-alert v-else title="仅投放人员可创建或重试广告任务" type="info" :closable="false" show-icon class="role-alert" />
    <el-alert v-if="allOnline" title="全部广告任务已上线，活动已进入投放中" type="success" :closable="false" show-icon class="online-alert" />

    <el-card class="table-card" shadow="never">
      <template #header><div class="card-header"><div><b>任务执行列表</b><span>共 {{ rows.length }} 个广告组</span></div><el-tag :type="allOnline ? 'success' : 'warning'" effect="light" round>{{ taskData.status || '待创建' }}</el-tag></div></template>
      <el-table :data="rows" class="task-table" row-key="id">
        <template #empty><el-empty description="暂未创建广告任务" :image-size="88"><template #description><p>确认策略后，可按策略创建广告计划和广告组</p></template></el-empty></template>
        <el-table-column label="广告计划" min-width="180"><template #default="{ row }"><div class="plan-name">{{ row.plan.name }}</div><small>预算 ¥{{ row.plan.budget_total }}</small><el-button link type="primary" class="detail-link" @click="router.push(`/campaigns/${campaignId}/ad-tasks/${row.plan.id}`)">查看详情 →</el-button></template></el-table-column>
        <el-table-column label="渠道" min-width="125"><template #default="{ row }">{{ channelName(row.plan.channel_id) }}</template></el-table-column>
        <el-table-column prop="name" label="广告组" min-width="180" />
        <el-table-column label="人群" min-width="170"><template #default="{ row }">{{ audienceName(row.audience_id) }}</template></el-table-column>
        <el-table-column label="状态" min-width="120"><template #default="{ row }"><el-tooltip v-if="row.error_message" :content="row.error_message" placement="top"><el-tag :type="statusType(row.status)" effect="light" round>{{ row.status }}</el-tag></el-tooltip><el-tag v-else :type="statusType(row.status)" effect="light" round>{{ row.status }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="140" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="router.push(`/campaigns/${campaignId}/ad-tasks/${row.plan.id}`)">详情</el-button><el-button v-if="canCreate && row.status === '创建失败' && row.audience_id" link type="danger" :loading="retrying === row.id" @click="retry(row)">重试</el-button></template></el-table-column>
      </el-table>
    </el-card>
  </main>
</template>

<style scoped>
.tasks-page { min-height: 100vh; padding: 32px clamp(20px, 5vw, 72px) 60px; background: #f5f7fb; }.page-header, .create-card, .table-card, .role-alert, .online-alert { max-width: 1240px; margin-right: auto; margin-left: auto; }.page-header { display: flex; margin-bottom: 26px; align-items: end; justify-content: space-between; gap: 20px; }.page-header :deep(.el-button.is-link) { margin: 0 0 19px -5px; }.eyebrow { margin: 0 0 8px; color: #6475d9; font-size: 11px; font-weight: 750; letter-spacing: 1.4px; }.page-header h1 { margin: 0; color: #202b45; font-size: 30px; letter-spacing: -1px; }.page-header h1 span { color: #69758b; font-size: 20px; font-weight: 500; }.page-header p:last-child { margin: 9px 0 0; color: #8c96aa; font-size: 14px; }.header-actions { display: flex; gap: 10px; }.create-card, .table-card { border: 1px solid #e7eaf1; border-radius: 12px; }.create-card { margin-bottom: 20px; }.create-card :deep(.el-card__body) { display: flex; padding: 20px 22px; align-items: center; justify-content: space-between; gap: 24px; }.create-copy { display: flex; min-width: 250px; align-items: center; gap: 13px; }.create-icon { display: grid; width: 41px; height: 41px; flex: none; place-items: center; color: #6475d9; border-radius: 11px; background: #eff1ff; font-size: 21px; }.create-copy b { color: #34405a; font-size: 14px; }.create-copy p { max-width: 380px; margin: 5px 0 0; color: #8d97aa; font-size: 12px; line-height: 1.5; }.create-form { display: grid; width: min(100%, 650px); grid-template-columns: 1.2fr 1.2fr .65fr auto; gap: 9px; }.role-alert, .online-alert { margin-bottom: 20px; }.card-header { display: flex; justify-content: space-between; align-items: center; }.card-header b { color: #34405a; }.card-header span { margin-left: 11px; color: #98a1b2; font-size: 12px; }.task-table { --el-table-header-bg-color: #fafbfe; --el-table-row-hover-bg-color: #f8f9ff; }.task-table :deep(.el-table__cell) { height: 82px; }.plan-name { color: #36415b; font-weight: 650; }.task-table small { display: block; margin-top: 5px; color: #9aa3b2; }.detail-link { height: auto; margin-top: 5px; padding: 0; font-size: 12px; }.empty-operation { color: #bbc2cd; }
@media (max-width: 980px) { .create-card :deep(.el-card__body) { align-items: stretch; flex-direction: column; }.create-form { width: 100%; }.page-header { align-items: start; flex-direction: column; } } @media (max-width: 650px) { .tasks-page { padding: 24px 14px 44px; }.create-form { grid-template-columns: 1fr; }.header-actions { width: 100%; }.header-actions :deep(.el-button) { flex: 1; }.create-card :deep(.el-card__body) { padding: 18px; } }
</style>
