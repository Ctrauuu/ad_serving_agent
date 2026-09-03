<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Refresh, Search, SwitchButton } from '@element-plus/icons-vue'
import { getCampaigns, getProducts } from '../api/campaign'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const campaigns = ref([])
const total = ref(0)
const productNames = ref({})
const query = reactive({ status: '', keyword: '', page: 1, page_size: 10 })

const statuses = ['草稿', '目标已结构化', '策略生成中', '策略已确认', '任务创建中', '投放中', '已暂停', '已结束']
const canCreate = computed(() => authStore.role === '投放人员')

const formatCurrency = (value) => new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(value)
const formatDate = (value) => value?.replaceAll('-', '.') || '-'
const productName = (row) => productNames.value[row.product_id] || row.structured_goal?.product || `产品 #${row.product_id}`
const ownerName = (row) => row.owner_id === authStore.user?.id ? authStore.user.display_name : `负责人 #${row.owner_id}`
const statusType = (status) => ({ '投放中': 'success', '已结束': 'info', '已暂停': 'warning', '草稿': 'info' }[status] || 'primary')

async function loadProducts() {
  const products = await getProducts()
  productNames.value = Object.fromEntries(products.map((product) => [product.id, product.name]))
}

async function loadCampaigns() {
  loading.value = true
  try {
    const data = await getCampaigns({
      page: query.page,
      page_size: query.page_size,
      status: query.status || undefined,
      keyword: query.keyword.trim() || undefined,
    })
    campaigns.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  loadCampaigns()
}

function reset() {
  Object.assign(query, { status: '', keyword: '', page: 1 })
  loadCampaigns()
}

function changePage(page) {
  query.page = page
  loadCampaigns()
}

function logout() {
  authStore.logout()
  router.replace('/login')
}

onMounted(async () => {
  await Promise.all([loadCampaigns(), loadProducts()])
})
</script>

<template>
  <main class="campaign-page">
    <section class="page-header">
      <div>
        <p class="eyebrow">CAMPAIGN CENTER</p>
        <h1>活动管理</h1>
        <p class="subtitle">统一管理投放目标、进度与预算节奏</p>
      </div>
      <div class="header-actions">
        <el-button v-if="canCreate" type="primary" size="large" :icon="Plus" @click="router.push('/campaigns/create')">新建活动</el-button>
        <el-button size="large" :icon="SwitchButton" @click="logout">退出登录</el-button>
      </div>
    </section>

    <el-card class="filter-card" shadow="never">
      <el-form class="filters" @submit.prevent="search">
        <el-form-item label="活动状态">
          <el-select v-model="query.status" clearable placeholder="全部状态" @change="search">
            <el-option v-for="status in statuses" :key="status" :label="status" :value="status" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键词" class="keyword-filter">
          <el-input v-model="query.keyword" clearable placeholder="搜索活动名称" :prefix-icon="Search" @keyup.enter="search" />
        </el-form-item>
        <div class="filter-actions">
          <el-button type="primary" :icon="Search" @click="search">查询</el-button>
          <el-button :icon="Refresh" @click="reset">重置</el-button>
        </div>
      </el-form>
    </el-card>

    <el-card class="table-card" shadow="never">
      <template #header>
        <div class="table-header">
          <span>活动列表</span>
          <span class="total">共 {{ total }} 个活动</span>
        </div>
      </template>
      <el-table v-loading="loading" :data="campaigns" class="campaign-table" row-key="id">
        <template #empty><el-empty description="暂无符合条件的活动" :image-size="92" /></template>
        <el-table-column label="活动名称" min-width="190">
          <template #default="{ row }"><span class="campaign-name">{{ row.name }}</span></template>
        </el-table-column>
        <el-table-column label="产品" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ productName(row) }}</template>
        </el-table-column>
        <el-table-column label="预算" min-width="130" align="right">
          <template #default="{ row }"><span class="budget">{{ formatCurrency(row.budget) }}</span></template>
        </el-table-column>
        <el-table-column label="周期" min-width="190">
          <template #default="{ row }">{{ formatDate(row.start_date) }} — {{ formatDate(row.end_date) }}</template>
        </el-table-column>
        <el-table-column label="状态" min-width="122">
          <template #default="{ row }"><el-tag :type="statusType(row.status)" effect="light" round>{{ row.status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="负责人" min-width="126">
          <template #default="{ row }">{{ ownerName(row) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }"><el-button link type="primary" @click="router.push(`/campaigns/${row.id}/strategy`)">查看</el-button><el-button link type="primary" @click="router.push(`/campaigns/${row.id}/ad-tasks`)">任务</el-button></template>
        </el-table-column>
      </el-table>
      <div v-if="total" class="pagination">
        <el-pagination :current-page="query.page" :page-size="query.page_size" :total="total" layout="total, prev, pager, next" @current-change="changePage" />
      </div>
    </el-card>
  </main>
</template>

<style scoped>
.campaign-page { min-height: 100vh; padding: 36px clamp(24px, 5vw, 72px) 56px; background: #f5f7fb; }
.page-header { display: flex; max-width: 1440px; margin: 0 auto 30px; align-items: end; justify-content: space-between; gap: 20px; }.header-actions { display: flex; gap: 10px; }
.eyebrow { margin: 0 0 8px; color: #6574d9; font-size: 11px; font-weight: 750; letter-spacing: 1.5px; }.page-header h1 { margin: 0; color: #1e2943; font-size: 30px; letter-spacing: -1px; }.subtitle { margin: 9px 0 0; color: #8a94a8; font-size: 14px; }
.filter-card, .table-card { max-width: 1440px; margin: 0 auto; border: 1px solid #e8ebf2; border-radius: 12px; }.filter-card { margin-bottom: 20px; }
.filters { display: flex; align-items: end; gap: 16px; }.filters :deep(.el-form-item) { margin: 0; }.filters :deep(.el-form-item__label) { padding-bottom: 8px; color: #58647a; font-size: 13px; line-height: 1; }.filters :deep(.el-select) { width: 164px; }.keyword-filter :deep(.el-input) { width: 250px; }.filter-actions { display: flex; gap: 8px; }
.table-header { display: flex; align-items: center; justify-content: space-between; color: #303b55; font-weight: 650; }.total { color: #909aad; font-size: 13px; font-weight: 400; }
.campaign-table { --el-table-header-bg-color: #fafbfe; --el-table-header-text-color: #68748a; --el-table-text-color: #4d596e; --el-table-row-hover-bg-color: #f8f9ff; }.campaign-table :deep(th.el-table__cell) { font-size: 12px; font-weight: 650; }.campaign-table :deep(.el-table__cell) { height: 66px; }.campaign-name { color: #27324c; font-weight: 650; }.budget { color: #263351; font-weight: 650; font-variant-numeric: tabular-nums; }.pagination { display: flex; padding-top: 22px; justify-content: end; }
@media (max-width: 760px) { .campaign-page { padding: 26px 16px; }.page-header { align-items: start; flex-direction: column; }.filters { align-items: stretch; flex-direction: column; }.filters :deep(.el-select), .keyword-filter :deep(.el-input) { width: 100%; }.filter-actions, .header-actions { display: grid; grid-template-columns: 1fr 1fr; }.pagination { justify-content: center; }.pagination :deep(.el-pagination__total) { display: none; } }
</style>
