<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ArrowLeft, MagicStick, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { generateReview, getCampaign, getCases, getReview } from '../api/campaign'

const route = useRoute()
const router = useRouter()
const campaignId = Number(route.params.id)
const campaign = ref(null)
const report = ref(null)
const cases = ref([])
const loading = ref(true)
const generating = ref(false)
const chartRef = ref()
let chart

const canGenerate = computed(() => campaign.value?.status === '已结束')
const metrics = computed(() => report.value?.overall_metrics || {})
const comparisons = computed(() => Object.entries(report.value?.strategy_evaluation?.metrics || {}).map(([name, value]) => ({ name, ...value })).filter((item) => item.actual !== null && item.actual !== undefined && Number.isFinite(Number(item.expected))))
const interventions = computed(() => Object.values(report.value?.intervention_evaluation || {}))
const reviewCases = computed(() => cases.value.filter((item) => item.campaign_id === campaignId))
const metricName = (key) => ({ cost: '消耗', lead: '线索', valid_lead: '有效线索', cpa: 'CPA', valid_lead_rate: '有效线索率', cpc: 'CPC', ctr: 'CTR', roi: 'ROI', click_to_lead_rate: '点击转线索率', cost_rate_daily: '日均消耗' }[key] || key)
const actionName = (key) => ({ pause: '暂停投放', adjust_budget: '调整预算', adjust_bid: '调整出价', replace_creative: '更换素材', narrow_audience: '收窄人群', switch_channel: '切换渠道', extend_observation: '延长观察', manual_review: '人工复核' }[key] || key)
const money = (value) => `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
const number = (value) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
const rate = (value) => value === null || value === undefined ? '—' : `${(Number(value) * 100).toFixed(1)}%`
const metricValue = (key, value) => ['cost', 'cpa', 'cpc', 'cost_rate_daily'].includes(key) ? money(value) : ['ctr', 'valid_lead_rate', 'click_to_lead_rate'].includes(key) ? rate(value) : value === null || value === undefined ? '—' : number(value)
const verdictType = (value) => ({ '达标': 'success', '部分达标': 'warning', '未达标': 'danger', '改善': 'success', '恶化': 'danger', '无明显变化': 'info' }[value] || 'info')

function renderChart() {
  if (!chartRef.value || !comparisons.value.length) return
  chart ||= echarts.init(chartRef.value)
  chart.setOption({ color: ['#7a88e8', '#eaa35b'], tooltip: { trigger: 'axis' }, legend: { top: 3 }, grid: { top: 45, right: 20, bottom: 45, left: 55 }, xAxis: { type: 'category', data: comparisons.value.map((item) => metricName(item.name)), axisLabel: { color: '#7e899e' } }, yAxis: { type: 'value', splitLine: { lineStyle: { color: '#edf0f5' } }, axisLabel: { color: '#7e899e' } }, series: [{ name: '预期', type: 'bar', barMaxWidth: 34, data: comparisons.value.map((item) => item.expected) }, { name: '实际', type: 'bar', barMaxWidth: 34, data: comparisons.value.map((item) => item.actual) }] })
}

async function loadReport() {
  try {
    report.value = await getReview(campaignId, { silent: true })
    await nextTick()
    renderChart()
  } catch {
    report.value = null
  }
}

async function generate() {
  if (!canGenerate.value) return ElMessage.warning('活动结束后才能生成复盘')
  generating.value = true
  try {
    report.value = await generateReview(campaignId)
    cases.value = await getCases()
    await nextTick()
    renderChart()
    ElMessage.success(`复盘已生成，当前为 V${report.value.version}`)
  } finally {
    generating.value = false
  }
}

async function refreshCases() { cases.value = await getCases() }

function resize() { chart?.resize() }

onMounted(async () => {
  try {
    const [campaignResult, casesResult] = await Promise.all([getCampaign(campaignId), getCases()])
    campaign.value = campaignResult
    cases.value = casesResult
    await loadReport()
  } finally {
    loading.value = false
  }
  window.addEventListener('resize', resize)
})
onBeforeUnmount(() => { window.removeEventListener('resize', resize); chart?.dispose() })
</script>

<template>
  <main v-loading="loading" class="review-page">
    <div v-if="generating" class="generation-overlay"><el-icon class="is-loading"><MagicStick /></el-icon><b>AI 正在生成投放复盘</b><span>正在汇总指标、策略偏差、干预效果与可复用案例</span></div>
    <header class="page-header"><div><el-button link :icon="ArrowLeft" @click="router.push('/campaigns')">返回活动列表</el-button><p class="eyebrow">POST-CAMPAIGN REVIEW</p><h1>投放复盘 <span v-if="campaign">· {{ campaign.name }}</span></h1><p>从真实执行数据中沉淀可复用的投放经验。</p></div><div><el-tooltip :disabled="canGenerate" content="活动结束后才能生成复盘"><el-button type="primary" size="large" :icon="MagicStick" :disabled="!canGenerate" :loading="generating" @click="generate">{{ report ? '重新生成复盘' : '生成复盘' }}</el-button></el-tooltip></div></header>

    <section v-if="!report && !loading" class="empty-report"><el-icon><MagicStick /></el-icon><h2>尚未生成复盘报告</h2><p>{{ canGenerate ? '活动已结束，可以生成指标总结、策略评价和案例沉淀。' : `当前活动状态为“${campaign?.status || '—'}”，结束后即可生成复盘。` }}</p><el-button v-if="canGenerate" type="primary" :loading="generating" @click="generate">生成复盘</el-button></section>

    <template v-else-if="report">
      <section class="metric-grid"><div><span>总消耗</span><b>{{ money(metrics.cost) }}</b></div><div><span>线索</span><b>{{ number(metrics.lead) }}</b></div><div><span>有效线索</span><b>{{ number(metrics.valid_lead) }}</b></div><div><span>CPA</span><b>{{ money(metrics.cpa) }}</b></div><div><span>有效线索率</span><b>{{ rate(metrics.valid_lead_rate) }}</b></div></section>

      <section class="content-grid"><article class="panel strategy-panel"><header><div><b>策略评价</b><span>V{{ report.version }} · {{ report.strategy_evaluation?.verdict || '数据不足' }}</span></div><el-tag :type="verdictType(report.strategy_evaluation?.verdict)" round>{{ report.strategy_evaluation?.verdict || '数据不足' }}</el-tag></header><div v-if="comparisons.length" ref="chartRef" class="comparison-chart" /><el-empty v-else description="暂无可对比的预期指标" :image-size="76" /></article>
        <article class="panel intervention-panel"><header><div><b>干预效果</b><span>成功执行动作的前后窗口对比</span></div></header><el-empty v-if="!interventions.length" description="暂无可评估的干预动作" :image-size="70" /><div v-else class="interventions"><div v-for="item in interventions" :key="item.action_id" class="intervention"><div><b>{{ actionName(item.action_type) }} · 广告组 #{{ item.target_id }}</b><span>CPA {{ money(item.before?.cpa) }} → {{ money(item.after?.cpa) }}</span></div><el-tag :type="verdictType(item.verdict)" round>{{ item.verdict }}</el-tag></div></div></article>
      </section>

      <section class="conclusion-grid"><article><span>可复用结论</span><p>{{ report.reusable_conclusion || '—' }}</p></article><article><span>失败教训</span><p>{{ report.lessons || '—' }}</p></article><article><span>改进建议</span><p>{{ report.improvement || '—' }}</p></article></section>

      <section class="panel cases-panel"><header><div><b>沉淀案例</b><span>已写入案例库的当前活动案例</span></div><el-button text :icon="Refresh" @click="refreshCases">刷新案例</el-button></header><el-empty v-if="!reviewCases.length" description="当前复盘尚未沉淀案例" :image-size="72" /><el-table v-else :data="reviewCases" class="case-table"><el-table-column prop="case_type" label="类型" width="110" /><el-table-column prop="scene_desc" label="场景" min-width="250" show-overflow-tooltip /><el-table-column prop="cause" label="原因" min-width="130" show-overflow-tooltip /><el-table-column prop="action" label="动作" min-width="135"><template #default="{ row }">{{ row.action ? actionName(row.action) : '—' }}</template></el-table-column><el-table-column label="效果" width="100"><template #default="{ row }"><el-tag :type="row.effectiveness === '有效' ? 'success' : 'danger'" size="small" round>{{ row.effectiveness }}</el-tag></template></el-table-column><el-table-column prop="conclusion" label="结论" min-width="260" show-overflow-tooltip /></el-table></section>
    </template>
  </main>
</template>

<style scoped>
.review-page { min-height: 100vh; padding: 32px clamp(18px, 4vw, 64px) 58px; background: #f5f7fb; }.page-header, .metric-grid, .content-grid, .conclusion-grid, .cases-panel, .empty-report { max-width: 1320px; margin-right: auto; margin-left: auto; }.page-header { display: flex; margin-bottom: 24px; align-items: end; justify-content: space-between; gap: 20px; }.page-header :deep(.el-button.is-link) { margin: 0 0 16px -5px; }.eyebrow { margin: 0 0 8px; color: #876acb; font-size: 11px; font-weight: 750; letter-spacing: 1.4px; }.page-header h1 { margin: 0; color: #202b45; font-size: 30px; letter-spacing: -1px; }.page-header h1 span { color: #69758b; font-size: 20px; font-weight: 500; }.page-header p:last-child { margin: 9px 0 0; color: #8c96aa; font-size: 14px; }.generation-overlay { position: fixed; z-index: 100; inset: 0; display: grid; gap: 13px; place-content: center; color: #fff; text-align: center; background: rgba(32, 39, 65, .76); backdrop-filter: blur(4px); }.generation-overlay .el-icon { margin: auto; color: #bf9aff; font-size: 38px; }.generation-overlay span { color: #d9deea; font-size: 13px; }.empty-report { display: grid; min-height: 370px; padding: 40px; place-content: center; text-align: center; border: 1px solid #e4e8f0; border-radius: 11px; background: #fff; }.empty-report .el-icon { margin: auto; padding: 17px; color: #8c73ce; font-size: 34px; border-radius: 14px; background: #f3f0ff; }.empty-report h2 { margin: 18px 0 8px; color: #34405a; font-size: 20px; }.empty-report p { max-width: 430px; margin: 0 0 20px; color: #8d98aa; font-size: 14px; }.metric-grid { display: grid; margin-bottom: 20px; grid-template-columns: repeat(5, 1fr); border: 1px solid #e4e8f0; border-radius: 11px; background: #fff; }.metric-grid > div { padding: 20px 23px; border-right: 1px solid #edf0f5; }.metric-grid > div:last-child { border: 0; }.metric-grid span { display: block; color: #929bab; font-size: 12px; }.metric-grid b { display: block; margin-top: 8px; color: #3d4961; font-size: 19px; }.content-grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: 20px; align-items: stretch; }.panel { overflow: hidden; border: 1px solid #e4e8f0; border-radius: 11px; background: #fff; }.panel > header { display: flex; padding: 17px 20px; align-items: center; justify-content: space-between; border-bottom: 1px solid #edf0f5; }.panel header b { color: #34405a; font-size: 15px; }.panel header span { margin-left: 10px; color: #929baa; font-size: 12px; }.comparison-chart { height: 300px; }.strategy-panel :deep(.el-empty), .intervention-panel :deep(.el-empty) { height: 300px; }.interventions { display: grid; padding: 8px 20px; }.intervention { display: flex; padding: 14px 0; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid #edf0f5; }.intervention:last-child { border: 0; }.intervention b { display: block; color: #4d5970; font-size: 13px; }.intervention span { display: block; margin-top: 6px; color: #8793a7; font-size: 12px; }.conclusion-grid { display: grid; margin-top: 20px; grid-template-columns: repeat(3, 1fr); gap: 20px; }.conclusion-grid article { min-height: 142px; padding: 20px; border: 1px solid #e4e8f0; border-radius: 11px; background: #fff; }.conclusion-grid article:nth-child(1) { border-top: 3px solid #6f82df; }.conclusion-grid article:nth-child(2) { border-top: 3px solid #df8a74; }.conclusion-grid article:nth-child(3) { border-top: 3px solid #75ad8b; }.conclusion-grid span { color: #657188; font-size: 13px; font-weight: 650; }.conclusion-grid p { margin: 12px 0 0; color: #6c778d; font-size: 13px; line-height: 1.7; }.cases-panel { margin-top: 20px; }.case-table { --el-table-header-bg-color: #fafbfe; }.case-table :deep(.el-table__cell) { height: 59px; }
@media (max-width: 900px) { .metric-grid { grid-template-columns: repeat(3, 1fr); }.metric-grid > div:nth-child(3) { border-right: 0; }.metric-grid > div:nth-child(-n+3) { border-bottom: 1px solid #edf0f5; }.content-grid, .conclusion-grid { grid-template-columns: 1fr; } } @media (max-width: 620px) { .review-page { padding: 24px 13px 42px; }.page-header { align-items: start; flex-direction: column; }.page-header > div:last-child, .page-header :deep(.el-button) { width: 100%; }.metric-grid { grid-template-columns: 1fr 1fr; }.metric-grid > div { border-right: 0; border-bottom: 1px solid #edf0f5; }.metric-grid > div:last-child { border-bottom: 0; }.cases-panel :deep(.el-table__body-wrapper) { overflow-x: auto; } }
</style>
