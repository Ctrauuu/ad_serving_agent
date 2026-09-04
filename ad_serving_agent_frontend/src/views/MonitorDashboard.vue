<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAdTasks, getCampaign, getCampaignBudget, getMetricTrend, getRealtimeMetrics, syncCampaignMetrics } from '../api/campaign'

const route = useRoute()
const router = useRouter()
const campaignId = Number(route.params.id)
const campaign = ref(null)
const budget = ref({ items: [], is_stale: true, data_time: null })
const realtime = ref({ items: [], is_stale: true, data_time: null })
const groupMetrics = ref({ items: [], is_stale: true, data_time: null })
const trend = ref({ series: [], is_stale: true, data_time: null })
const tasks = ref([])
const dimension = ref('ad_group')
const windowType = ref('hour')
const loading = ref(true)
const syncing = ref(false)
const costChartRef = ref()
const leadsChartRef = ref()
const cpaChartRef = ref()
let charts = []

const dimensionOptions = [{ label: '活动', value: 'campaign' }, { label: '渠道', value: 'channel' }, { label: '广告组', value: 'ad_group' }, { label: '素材', value: 'creative' }]
const windowOptions = [{ label: '分钟', value: 'minute' }, { label: '小时', value: 'hour' }, { label: '天', value: 'day' }]
const groupNames = computed(() => Object.fromEntries(tasks.value.flatMap((plan) => plan.groups.map((group) => [group.id, group.name]))))
const campaignBudget = computed(() => budget.value.items.find((item) => item.target_type === 'campaign') || { budget_total: campaign.value?.budget || 0, cost_total: 0, remaining: campaign.value?.budget || 0, alert_status: '未同步' })
const budgetPercent = computed(() => campaignBudget.value.budget_total ? Math.min(100, Number(campaignBudget.value.cost_total) / Number(campaignBudget.value.budget_total) * 100) : 0)
const isBudgetAlert = computed(() => !['正常', '未同步'].includes(campaignBudget.value.alert_status))
const latestTime = computed(() => trend.value.data_time || realtime.value.data_time || groupMetrics.value.data_time || budget.value.data_time)
const metricRows = computed(() => groupMetrics.value.items.map((item) => ({ ...item, name: groupNames.value[item.dim_id] || `广告组 #${item.dim_id}` })))

const money = (value) => `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
const number = (value) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })
const rate = (value) => `${(Number(value || 0) * 100).toFixed(1)}%`
const time = (value) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '暂无数据'
const groupStatus = (id) => tasks.value.flatMap((plan) => plan.groups).find((group) => group.id === id)?.status || '—'
const statusType = (status) => ({ '已上线': 'success', '创建失败': 'danger' }[status] || 'info')

function trendData(field, transform = (value) => value) {
  const points = {}
  trend.value.series.forEach((series) => series.points.forEach((point) => {
    const label = new Date(point.window_start).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
    points[label] = (points[label] || 0) + Number(point[field] || 0)
  }))
  const entries = Object.entries(points)
  return { labels: entries.map(([label]) => label), values: entries.map(([, value]) => transform(value)) }
}

function renderChart(element, title, series, colors) {
  if (!element) return
  const chart = echarts.getInstanceByDom(element) || echarts.init(element)
  const longest = series.reduce((result, item) => item.data.labels.length > result.labels.length ? item.data : result, { labels: [] })
  chart.setOption({ backgroundColor: 'transparent', color: colors, grid: { top: 38, right: 18, bottom: 28, left: 52 }, tooltip: { trigger: 'axis', backgroundColor: '#202b3d', borderWidth: 0, textStyle: { color: '#eef4ff' } }, legend: { top: 0, textStyle: { color: '#9eaabd' } }, xAxis: { type: 'category', data: longest.labels, boundaryGap: false, axisLine: { lineStyle: { color: '#344158' } }, axisLabel: { color: '#8190a7', fontSize: 10 } }, yAxis: { type: 'value', splitLine: { lineStyle: { color: '#263247' } }, axisLabel: { color: '#8190a7', fontSize: 10 } }, series: series.map((item) => ({ name: item.name, type: 'line', smooth: true, symbol: 'none', lineStyle: { width: 2 }, areaStyle: item.area ? { opacity: .13 } : undefined, data: item.data.values })), title: { text: title, left: 0, top: 0, textStyle: { color: '#e7edf8', fontSize: 13, fontWeight: 600 } } })
  if (!charts.includes(chart)) charts.push(chart)
}

function renderCharts() {
  const cost = trendData('cost')
  const leads = trendData('lead')
  const validLeads = trendData('valid_lead')
  const cpa = trendData('cost')
  const cpaValues = cpa.values.map((costValue, index) => leads.values[index] ? costValue / leads.values[index] : 0)
  renderChart(costChartRef.value, '消耗趋势', [{ name: '消耗', data: cost, area: true }], ['#35c7e8'])
  renderChart(leadsChartRef.value, '线索趋势', [{ name: '线索', data: leads, area: true }, { name: '有效线索', data: validLeads }], ['#8a78ff', '#47d7a6'])
  renderChart(cpaChartRef.value, 'CPA 趋势', [{ name: 'CPA', data: { labels: cpa.labels, values: cpaValues }, area: true }], ['#f3ad57'])
}

async function loadDashboard() {
  const groupRequest = dimension.value === 'ad_group' ? null : getRealtimeMetrics(campaignId, 'ad_group')
  const [realtimeResult, trendResult, budgetResult, tasksResult, groupResult] = await Promise.all([getRealtimeMetrics(campaignId, dimension.value), getMetricTrend(campaignId, dimension.value, windowType.value), getCampaignBudget(campaignId), getAdTasks(campaignId), groupRequest])
  realtime.value = realtimeResult
  trend.value = trendResult
  budget.value = budgetResult
  tasks.value = tasksResult.plans
  groupMetrics.value = groupResult || realtimeResult
  await nextTick()
  renderCharts()
}

async function sync() {
  syncing.value = true
  try {
    const result = await syncCampaignMetrics(campaignId)
    await loadDashboard()
    ElMessage.success(`同步完成：${result.synced_groups} 个广告组`)
  } finally {
    syncing.value = false
  }
}

function resizeCharts() { charts.forEach((chart) => chart.resize()) }

watch([dimension, windowType], () => loadDashboard())
onMounted(async () => {
  try {
    campaign.value = await getCampaign(campaignId)
    await loadDashboard()
  } finally {
    loading.value = false
  }
  window.addEventListener('resize', resizeCharts)
})
onBeforeUnmount(() => { window.removeEventListener('resize', resizeCharts); charts.forEach((chart) => chart.dispose()) })
</script>

<template>
  <main v-loading="loading" class="monitor-page">
    <header class="page-header"><div><el-button link :icon="ArrowLeft" @click="router.push('/campaigns')">返回活动列表</el-button><p class="eyebrow">LIVE MONITORING</p><h1>实时监控 <span v-if="campaign">· {{ campaign.name }}</span></h1></div><div class="sync-actions"><span :class="['data-time', { stale: !latestTime || realtime.is_stale || budget.is_stale }]">● 数据时间：{{ time(latestTime) }}</span><el-button type="primary" :icon="Refresh" :loading="syncing" @click="sync">手动同步</el-button></div></header>

    <section :class="['budget-panel', { alert: isBudgetAlert }]"><div class="budget-main"><span>活动预算</span><b>{{ money(campaignBudget.budget_total) }}</b><small :class="{ danger: isBudgetAlert }">{{ campaignBudget.alert_status }}</small></div><div class="budget-values"><div><span>已消耗</span><b>{{ money(campaignBudget.cost_total) }}</b></div><div><span>剩余预算</span><b>{{ money(campaignBudget.remaining) }}</b></div></div><div class="budget-progress"><div><span>预算消耗进度</span><b>{{ budgetPercent.toFixed(1) }}%</b></div><el-progress :percentage="budgetPercent" :show-text="false" :stroke-width="8" :color="isBudgetAlert ? '#ff647c' : '#3ab7d6'" /></div></section>

    <section class="toolbar"><div><span>监控维度</span><el-segmented v-model="dimension" :options="dimensionOptions" /></div><div><span>时间窗</span><el-segmented v-model="windowType" :options="windowOptions" /></div></section>

    <section class="charts"><div ref="costChartRef" class="chart" /><div ref="leadsChartRef" class="chart" /><div ref="cpaChartRef" class="chart" /></section>

    <section class="table-panel"><header><div><b>广告组实时明细</b><span>按最新采集数据展示</span></div><el-tag :type="groupMetrics.is_stale ? 'warning' : 'success'" effect="plain" round>{{ groupMetrics.is_stale ? '数据延迟' : '实时数据' }}</el-tag></header><el-table :data="metricRows" class="metrics-table"><template #empty><el-empty description="暂无实时指标，请先手动同步" :image-size="78" /></template><el-table-column prop="name" label="广告组" min-width="190" /><el-table-column label="消耗" min-width="120" align="right"><template #default="{ row }">{{ money(row.cost) }}</template></el-table-column><el-table-column label="线索" min-width="92" align="right"><template #default="{ row }">{{ number(row.lead) }}</template></el-table-column><el-table-column label="有效线索" min-width="108" align="right"><template #default="{ row }">{{ number(row.valid_lead) }}</template></el-table-column><el-table-column label="CPA" min-width="105" align="right"><template #default="{ row }">{{ money(row.cpa) }}</template></el-table-column><el-table-column label="CTR" min-width="92" align="right"><template #default="{ row }">{{ rate(row.ctr) }}</template></el-table-column><el-table-column label="状态" min-width="100"><template #default="{ row }"><el-tag :type="statusType(groupStatus(row.dim_id))" size="small" round>{{ groupStatus(row.dim_id) }}</el-tag></template></el-table-column></el-table></section>
  </main>
</template>

<style scoped>
.monitor-page { min-height: 100vh; padding: 28px clamp(18px, 4vw, 64px) 54px; color: #dce5f3; background: #111827; }.page-header, .budget-panel, .toolbar, .charts, .table-panel { max-width: 1420px; margin-right: auto; margin-left: auto; }.page-header { display: flex; margin-bottom: 24px; align-items: end; justify-content: space-between; gap: 20px; }.page-header :deep(.el-button.is-link) { margin: 0 0 16px -5px; color: #8ca2cb; }.eyebrow { margin: 0 0 7px; color: #39c6e5; font-size: 11px; font-weight: 700; letter-spacing: 1.5px; }.page-header h1 { margin: 0; color: #f0f5ff; font-size: 29px; letter-spacing: -1px; }.page-header h1 span { color: #9babca; font-size: 19px; font-weight: 500; }.sync-actions { display: flex; align-items: center; gap: 14px; }.data-time { color: #47d7a6; font-size: 12px; }.data-time.stale { color: #f3ad57; }.budget-panel { display: grid; margin-bottom: 14px; grid-template-columns: 1.1fr 1.2fr 1.3fr; border: 1px solid #26354c; border-radius: 9px; background: #182235; }.budget-panel.alert { border-color: rgba(255, 100, 124, .6); }.budget-panel > div { min-height: 100px; padding: 19px 24px; border-right: 1px solid #26354c; }.budget-panel > div:last-child { border: 0; }.budget-main span, .budget-values span, .budget-progress span { display: block; color: #8797b1; font-size: 12px; }.budget-main b { display: inline-block; margin-top: 8px; color: #f1f5fc; font-size: 25px; }.budget-main small { margin-left: 10px; color: #47d7a6; }.budget-main small.danger { color: #ff647c; }.budget-values { display: grid; grid-template-columns: 1fr 1fr; gap: 22px; }.budget-values b { display: block; margin-top: 10px; color: #dbe4f3; font-size: 17px; }.budget-progress > div { display: flex; margin-bottom: 13px; justify-content: space-between; }.budget-progress b { color: #b9c5dc; font-size: 13px; }.toolbar { display: flex; margin-bottom: 14px; padding: 14px 17px; align-items: center; justify-content: space-between; border: 1px solid #26354c; border-radius: 9px; background: #182235; }.toolbar > div { display: flex; align-items: center; gap: 13px; }.toolbar span { color: #91a0b6; font-size: 12px; }.toolbar :deep(.el-segmented) { --el-segmented-bg-color: #101827; --el-segmented-item-selected-bg-color: #2c4160; --el-segmented-item-selected-color: #67d5ee; --el-text-color-regular: #97a7bf; }.charts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }.chart { height: 265px; border: 1px solid #26354c; border-radius: 9px; background: #182235; }.table-panel { margin-top: 14px; overflow: hidden; border: 1px solid #26354c; border-radius: 9px; background: #182235; }.table-panel > header { display: flex; padding: 17px 19px; align-items: center; justify-content: space-between; border-bottom: 1px solid #26354c; }.table-panel header b { color: #e4ebf7; font-size: 14px; }.table-panel header span { margin-left: 10px; color: #8191aa; font-size: 12px; }.metrics-table { --el-table-bg-color: #182235; --el-table-tr-bg-color: #182235; --el-table-header-bg-color: #1d2a40; --el-table-row-hover-bg-color: #202f48; --el-table-border-color: #26354c; --el-table-text-color: #d4ddec; --el-table-header-text-color: #98a9c1; }.metrics-table :deep(.el-table__inner-wrapper:before) { display: none; }.metrics-table :deep(.el-table__cell) { height: 58px; }.metrics-table :deep(.el-table__empty-block) { background: #182235; }
@media (max-width: 960px) { .budget-panel { grid-template-columns: 1fr 1fr; }.budget-progress { grid-column: span 2; border-top: 1px solid #26354c; }.charts { grid-template-columns: 1fr; }.chart { height: 240px; } } @media (max-width: 620px) { .monitor-page { padding: 22px 12px 38px; }.page-header { align-items: start; flex-direction: column; }.sync-actions { width: 100%; justify-content: space-between; }.budget-panel { grid-template-columns: 1fr; }.budget-panel > div { border-right: 0; border-bottom: 1px solid #26354c; }.budget-progress { grid-column: auto; }.toolbar { align-items: start; flex-direction: column; }.toolbar > div { width: 100%; justify-content: space-between; }.toolbar :deep(.el-segmented) { max-width: 250px; overflow-x: auto; }.budget-values { grid-template-columns: 1fr 1fr; } }
</style>
