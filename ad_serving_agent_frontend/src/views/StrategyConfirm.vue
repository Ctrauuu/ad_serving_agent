<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Check, Loading, MagicStick, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { confirmStrategy, generateStrategy, getCampaign, getStrategy } from '../api/campaign'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const campaign = ref(null)
const detail = ref(null)
const loading = ref(true)
const generating = ref(false)
const confirming = ref(false)
const campaignId = Number(route.params.id)
const strategy = computed(() => detail.value?.strategy)
const evidence = computed(() => detail.value?.evidence || [])
const canConfirm = computed(() => authStore.role === '投放负责人' && strategy.value?.status === '待确认')
const canGenerate = computed(() => strategy.value?.status !== '已确认')
const budgetTotal = computed(() => Object.values(strategy.value?.budget_split || {}).reduce((sum, value) => sum + Number(value), 0))
const money = (value) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(value)
const percent = (value) => budgetTotal.value ? `${((Number(value) / budgetTotal.value) * 100).toFixed(1)}%` : '-'
const score = (value) => value == null ? '—' : Number(value).toFixed(2)

async function loadStrategy() {
  try {
    detail.value = await getStrategy(campaignId, { silent: true })
  } catch (error) {
    if (error.response?.status !== 404) ElMessage.error(error.response?.data?.message || '加载策略失败')
  }
}

async function generate() {
  generating.value = true
  try {
    detail.value = await generateStrategy(campaignId)
    await loadStrategy()
    ElMessage.success('策略生成完成')
  } finally {
    generating.value = false
  }
}

async function confirm() {
  confirming.value = true
  try {
    await confirmStrategy(campaignId)
    ElMessage.success('策略已确认')
    router.push(`/campaigns/${campaignId}/ad-tasks`)
  } finally {
    confirming.value = false
  }
}

onMounted(async () => {
  try {
    campaign.value = await getCampaign(campaignId)
    await loadStrategy()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main v-loading="loading" class="strategy-page">
    <div v-if="generating" class="generation-overlay">
      <el-icon class="is-loading"><Loading /></el-icon>
      <b>AI 正在生成投放策略</b>
      <span>正在分析目标、渠道规则与历史策略，通常需要约 30 秒</span>
    </div>
    <header class="page-header">
      <div>
        <el-button link :icon="ArrowLeft" @click="router.push('/campaigns')">返回活动列表</el-button>
        <p class="eyebrow">CAMPAIGN CENTER / STRATEGY</p>
        <h1>策略生成与确认 <span v-if="campaign">· {{ campaign.name }}</span></h1>
        <p>基于结构化目标、渠道规则与历史策略生成可执行投放方案。</p>
      </div>
      <el-button type="primary" size="large" :icon="MagicStick" :loading="generating" :disabled="!canGenerate" @click="generate">{{ strategy ? '重新生成策略' : '生成策略' }}</el-button>
    </header>

    <section v-if="!strategy && !loading" class="empty-strategy">
      <el-icon><MagicStick /></el-icon>
      <h2>还没有生成策略</h2>
      <p>确认活动目标已结构化后，即可生成渠道组合、预算拆分和策略依据。</p>
      <el-button type="primary" :icon="MagicStick" :loading="generating" @click="generate">生成策略</el-button>
    </section>

    <template v-else-if="strategy">
      <section class="summary-card">
        <div><span>策略版本</span><b>V{{ strategy.version }}</b></div>
        <div><span>投放渠道</span><b>{{ strategy.channel_mix.length }} 个</b></div>
        <div><span>总预算</span><b>{{ money(budgetTotal) }}</b></div>
        <div><span>策略状态</span><el-tag :type="strategy.status === '已确认' ? 'success' : 'warning'" round>{{ strategy.status }}</el-tag></div>
      </section>

      <section class="content-grid">
        <div class="main-content">
          <el-card class="content-card" shadow="never">
            <template #header><div class="card-title"><b>渠道组合</b><span>渠道定位与预算优先级</span></div></template>
            <div class="channel-list">
              <div v-for="channel in strategy.channel_mix" :key="channel.channel_id" class="channel-item"><div class="channel-icon">{{ channel.channel_name.slice(0, 1) }}</div><div><b>{{ channel.channel_name }}</b><p>{{ channel.purpose }}</p></div></div>
            </div>
          </el-card>

          <el-card class="content-card" shadow="never">
            <template #header><div class="card-title"><b>预算拆分</b><span>总计 {{ money(budgetTotal) }}</span></div></template>
            <el-table :data="Object.entries(strategy.budget_split).map(([channel, budget]) => ({ channel, budget }))" class="budget-table">
              <el-table-column prop="channel" label="渠道" min-width="140" />
              <el-table-column label="预算" min-width="130" align="right"><template #default="{ row }">{{ money(row.budget) }}</template></el-table-column>
              <el-table-column label="占比" min-width="170"><template #default="{ row }"><div class="ratio"><el-progress :percentage="Number(percent(row.budget).replace('%', ''))" :stroke-width="7" :show-text="false" /><span>{{ percent(row.budget) }}</span></div></template></el-table-column>
            </el-table>
          </el-card>

          <el-card class="content-card" shadow="never">
            <template #header><div class="card-title"><b>广告组结构</b><span>按渠道拆分的测试单元</span></div></template>
            <div class="ad-groups"><div v-for="group in strategy.ad_group_structure" :key="group.channel" class="ad-group"><b>{{ group.channel }}</b><div><el-tag v-for="name in group.groups" :key="name" effect="plain">{{ name }}</el-tag></div></div></div>
          </el-card>

          <el-card class="content-card" shadow="never">
            <template #header><div class="card-title"><b>素材测试方案</b><span>首轮创意验证方向</span></div></template>
            <div class="creative-list"><div v-for="(plan, name) in strategy.creative_test_plan" :key="name"><b>{{ name }}</b><p>{{ plan }}</p></div></div>
          </el-card>
        </div>

        <aside>
          <el-card class="content-card metrics-card" shadow="never"><template #header><div class="card-title"><b>预期指标</b><span>策略目标</span></div></template><div class="metrics"><div v-for="(value, name) in strategy.expected_metrics" :key="name"><span>{{ name }}</span><b>{{ value }}</b></div></div><div class="bid"><span>出价策略</span><b>{{ strategy.bid_strategy }}</b></div></el-card>
          <el-card class="content-card risk-card" shadow="never"><template #header><div class="card-title"><b>风险提示</b></div></template><p>{{ strategy.risk_notes }}</p></el-card>
        </aside>
      </section>

      <el-card class="content-card evidence-card" shadow="never">
        <template #header><div class="card-title"><b>策略依据</b><span>每项建议均可追溯</span></div></template>
        <el-empty v-if="!evidence.length" description="暂无策略依据" :image-size="72" />
        <el-table v-else :data="evidence" class="evidence-table">
          <el-table-column prop="evidence_type" label="依据类型" width="110"><template #default="{ row }"><el-tag size="small" effect="plain">{{ row.evidence_type }}</el-tag></template></el-table-column>
          <el-table-column prop="target_item" label="对应项" min-width="130" />
          <el-table-column prop="explanation" label="说明" min-width="310" show-overflow-tooltip />
          <el-table-column prop="source_ref" label="来源" min-width="130"><template #default="{ row }">{{ row.source_ref || '系统规则' }}</template></el-table-column>
          <el-table-column label="相似度" width="100" align="right"><template #default="{ row }">{{ score(row.vector_score) }}</template></el-table-column>
        </el-table>
      </el-card>

      <footer class="actions"><span v-if="strategy.status === '已确认'" class="confirmed-text"><el-icon><Check /></el-icon> 此策略已由负责人确认</span><template v-else><el-button :icon="Refresh" :loading="generating" @click="generate">重新生成</el-button><el-button v-if="canConfirm" type="primary" :icon="Check" :loading="confirming" @click="confirm">确认策略</el-button><span v-else class="role-note">仅投放负责人可确认策略</span></template></footer>
    </template>
  </main>
</template>

<style scoped>
.strategy-page { min-height: 100vh; padding: 32px clamp(20px, 5vw, 72px) 60px; background: #f5f7fb; }.generation-overlay { position: fixed; z-index: 100; inset: 0; display: grid; gap: 13px; place-content: center; color: #fff; text-align: center; background: rgba(18, 28, 57, .76); backdrop-filter: blur(4px); }.generation-overlay .el-icon { margin: auto; color: #9ba8ff; font-size: 38px; }.generation-overlay b { font-size: 18px; }.generation-overlay span { color: #d1d7ef; font-size: 13px; }.page-header, .summary-card, .content-grid, .evidence-card, .actions, .empty-strategy { max-width: 1240px; margin-right: auto; margin-left: auto; }.page-header { display: flex; margin-bottom: 28px; align-items: end; justify-content: space-between; gap: 20px; }.page-header :deep(.el-button.is-link) { margin: 0 0 19px -5px; }.eyebrow { margin: 0 0 8px; color: #6475d9; font-size: 11px; font-weight: 750; letter-spacing: 1.4px; }.page-header h1 { margin: 0; color: #202b45; font-size: 30px; letter-spacing: -1px; }.page-header h1 span { color: #69758b; font-size: 20px; font-weight: 500; }.page-header p:last-child { margin: 9px 0 0; color: #8c96aa; font-size: 14px; }.empty-strategy { display: grid; min-height: 370px; padding: 40px; place-content: center; text-align: center; border: 1px solid #e7eaf1; border-radius: 12px; background: #fff; }.empty-strategy .el-icon { margin: auto; padding: 17px; color: #6d7ade; font-size: 34px; border-radius: 15px; background: #f0f2ff; }.empty-strategy h2 { margin: 18px 0 8px; color: #34405b; font-size: 20px; }.empty-strategy p { max-width: 370px; margin: 0 0 22px; color: #8993a7; font-size: 14px; }.summary-card { display: grid; margin-bottom: 20px; grid-template-columns: repeat(4, 1fr); border: 1px solid #e7eaf1; border-radius: 12px; background: #fff; }.summary-card > div { display: grid; min-height: 88px; padding: 20px 25px; align-content: center; border-right: 1px solid #edf0f5; }.summary-card > div:last-child { border: 0; }.summary-card span { margin-bottom: 6px; color: #9099aa; font-size: 12px; }.summary-card b { color: #303b55; font-size: 17px; }.content-grid { display: grid; grid-template-columns: minmax(0, 1.8fr) minmax(270px, .8fr); gap: 20px; align-items: start; }.main-content { display: grid; gap: 20px; }.content-card { border: 1px solid #e7eaf1; border-radius: 12px; }.content-card :deep(.el-card__header) { padding: 17px 21px; border-bottom-color: #edf0f5; }.content-card :deep(.el-card__body) { padding: 20px 21px; }.card-title { display: flex; justify-content: space-between; color: #303b55; }.card-title span { color: #9aa3b4; font-size: 12px; font-weight: 400; }.channel-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }.channel-item { display: flex; padding: 13px; gap: 11px; border: 1px solid #edf0f5; border-radius: 9px; }.channel-icon { display: grid; width: 34px; height: 34px; flex: none; place-items: center; color: #5f6fdc; border-radius: 9px; background: #eef0ff; font-weight: 700; }.channel-item b { color: #3a4660; font-size: 14px; }.channel-item p { margin: 5px 0 0; color: #8c96a9; font-size: 12px; line-height: 1.45; }.budget-table { --el-table-header-bg-color: #fafbfe; }.ratio { display: flex; align-items: center; gap: 10px; }.ratio :deep(.el-progress) { width: 82px; }.ratio span { color: #657187; font-size: 12px; }.ad-groups { display: grid; gap: 14px; }.ad-group { display: flex; align-items: start; gap: 20px; }.ad-group > b { width: 82px; padding-top: 5px; color: #556178; font-size: 13px; }.ad-group > div { display: flex; flex: 1; flex-wrap: wrap; gap: 8px; }.creative-list { display: grid; gap: 14px; }.creative-list > div { padding-left: 13px; border-left: 3px solid #7b87e6; }.creative-list b { color: #4b5770; font-size: 13px; }.creative-list p { margin: 5px 0 0; color: #778298; font-size: 13px; line-height: 1.65; }.metrics { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }.metrics > div { padding: 13px; border-radius: 8px; background: #f8f9fd; }.metrics span, .bid span { display: block; color: #939caf; font-size: 12px; }.metrics b { display: block; margin-top: 7px; color: #5364d5; font-size: 17px; }.bid { margin-top: 17px; padding-top: 15px; border-top: 1px solid #edf0f5; }.bid b { display: block; margin-top: 7px; color: #42506a; font-size: 13px; }.risk-card { margin-top: 20px; border-color: #f1dfbd; background: #fffdf8; }.risk-card p { margin: 0; color: #76613d; font-size: 13px; line-height: 1.7; }.evidence-card { margin-top: 20px; }.evidence-table { --el-table-header-bg-color: #fafbfe; }.actions { display: flex; padding-top: 24px; justify-content: end; align-items: center; gap: 10px; }.role-note { margin-left: 4px; color: #96a0b2; font-size: 12px; }.confirmed-text { display: flex; align-items: center; gap: 6px; color: #54a47d; font-size: 13px; }
@media (max-width: 860px) { .page-header { align-items: start; flex-direction: column; }.summary-card { grid-template-columns: 1fr 1fr; }.summary-card > div:nth-child(2) { border-right: 0; }.summary-card > div:nth-child(-n+2) { border-bottom: 1px solid #edf0f5; }.content-grid { grid-template-columns: 1fr; } } @media (max-width: 520px) { .strategy-page { padding: 24px 14px 44px; }.summary-card { grid-template-columns: 1fr; }.summary-card > div { min-height: 72px; border-right: 0; border-bottom: 1px solid #edf0f5; }.summary-card > div:last-child { border-bottom: 0; }.ad-group { gap: 10px; flex-direction: column; }.actions { align-items: stretch; flex-direction: column; }.actions :deep(.el-button) { width: 100%; }.role-note { margin: 0; text-align: center; } }
</style>
