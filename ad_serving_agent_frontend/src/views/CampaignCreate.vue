<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, MagicStick } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { createCampaign, getProducts, parseGoal, updateCampaign } from '../api/campaign'

const router = useRouter()
const formRef = ref()
const products = ref([])
const campaignId = ref(null)
const parsing = ref(false)
const saving = ref(false)
const parsed = ref(false)
const missingFields = ref([])
const form = reactive({ name: '', product_id: '', budget_total: null, start_date: '', end_date: '', conversion_goal: '线索', goal_text: '' })
const structured = reactive({ product: '', audience: '', budget: null, cycle: '', conversion_goal: '线索', channels: [], risk: '' })

const rules = {
  name: [{ required: true, message: '请输入活动名称', trigger: 'blur' }],
  product_id: [{ required: true, message: '请选择推广产品', trigger: 'change' }],
  budget_total: [{ required: true, message: '请输入预算', trigger: 'blur' }],
  start_date: [{ required: true, message: '请选择开始日期', trigger: 'change' }],
  end_date: [{ required: true, message: '请选择结束日期', trigger: 'change' }],
  conversion_goal: [{ required: true, message: '请选择转化目标', trigger: 'change' }],
  goal_text: [{ required: true, message: '请描述投放目标', trigger: 'blur' }],
}
const canSave = computed(() => parsed.value && structured.product && structured.audience && structured.budget && structured.cycle && structured.channels.length && structured.risk)
const payload = () => ({ ...form, product_id: Number(form.product_id), budget_total: Number(form.budget_total) })

watch(() => form.goal_text, () => { if (parsed.value) parsed.value = false })

async function validateForm() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return false
  if (form.end_date < form.start_date) {
    ElMessage.warning('结束日期不能早于开始日期')
    return false
  }
  return true
}

async function ensureDraft() {
  if (campaignId.value) return updateCampaign(campaignId.value, payload())
  const campaign = await createCampaign(payload())
  campaignId.value = campaign.id
  return campaign
}

async function structureGoal() {
  if (!(await validateForm())) return
  parsing.value = true
  missingFields.value = []
  try {
    await ensureDraft()
    const result = await parseGoal(campaignId.value)
    Object.assign(structured, result.structured_goal)
    parsed.value = true
  } catch (error) {
    missingFields.value = error.response?.data?.data?.missing_fields || []
  } finally {
    parsing.value = false
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  try {
    await updateCampaign(campaignId.value, { ...payload(), structured_goal: { ...structured, budget: Number(structured.budget) } })
    ElMessage.success('活动已保存')
    router.push('/campaigns')
  } finally {
    saving.value = false
  }
}

onMounted(async () => { products.value = await getProducts() })
</script>

<template>
  <main class="create-page">
    <div class="page-top">
      <div>
        <el-button link :icon="ArrowLeft" @click="router.push('/campaigns')">返回活动列表</el-button>
        <p class="eyebrow">CAMPAIGN CENTER / NEW</p>
        <h1>新建活动</h1>
        <p>填写投放基础信息，系统将协助结构化您的投放目标。</p>
      </div>
      <div class="steps"><span class="active">1 基础配置</span><i /><span :class="{ active: parsed }">2 目标确认</span></div>
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="form-grid">
      <el-card class="form-card" shadow="never">
        <template #header><div class="card-title"><b>活动基础配置</b><span>标记 <em>*</em> 的为必填项</span></div></template>
        <el-row :gutter="20">
          <el-col :span="24"><el-form-item label="活动名称" prop="name"><el-input v-model="form.name" maxlength="128" show-word-limit placeholder="例如：2026 金秋新品获客推广" /></el-form-item></el-col>
          <el-col :md="12" :xs="24"><el-form-item label="推广产品" prop="product_id"><el-select v-model="form.product_id" filterable placeholder="请选择推广产品"><el-option v-for="product in products" :key="product.id" :label="product.name" :value="product.id" /></el-select></el-form-item></el-col>
          <el-col :md="12" :xs="24"><el-form-item label="投放总预算" prop="budget_total"><el-input v-model.number="form.budget_total" type="number" :min="0" placeholder="请输入金额"><template #prepend>¥</template><template #append>元</template></el-input></el-form-item></el-col>
          <el-col :md="12" :xs="24"><el-form-item label="开始日期" prop="start_date"><el-date-picker v-model="form.start_date" value-format="YYYY-MM-DD" type="date" placeholder="选择日期" /></el-form-item></el-col>
          <el-col :md="12" :xs="24"><el-form-item label="结束日期" prop="end_date"><el-date-picker v-model="form.end_date" value-format="YYYY-MM-DD" type="date" placeholder="选择日期" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="转化目标" prop="conversion_goal"><el-radio-group v-model="form.conversion_goal"><el-radio-button label="线索" /><el-radio-button label="注册" /><el-radio-button label="成交" /><el-radio-button label="新品推广" /></el-radio-group></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="投放目标描述" prop="goal_text"><el-input v-model="form.goal_text" type="textarea" :rows="5" maxlength="1000" show-word-limit placeholder="请描述预算、目标人群、投放周期、渠道偏好和风险限制。例如：预算 8 万，面向中小企业 HR 负责人，投放 30 天，以获取高质量线索为目标。" /></el-form-item></el-col>
        </el-row>
        <div class="parse-bar"><div><b>AI 结构化目标</b><span>系统会将自然语言目标拆解为可确认的投放配置</span></div><el-button type="primary" plain :icon="MagicStick" :loading="parsing" @click="structureGoal">结构化目标</el-button></div>
        <el-alert v-if="missingFields.length" type="warning" :closable="false" show-icon><template #title>目标信息不完整，请补充：{{ missingFields.join('、') }}</template></el-alert>
      </el-card>

      <el-card class="form-card structured-card" shadow="never">
        <template #header><div class="card-title"><b>结构化结果</b><span v-if="parsed" class="confirmed">等待确认保存</span><span v-else>请先生成结构化目标</span></div></template>
        <div v-if="!parsed" class="result-empty"><el-icon><MagicStick /></el-icon><p>AI 解析结果将在这里展示</p><span>请完成基础配置后点击「结构化目标」</span></div>
        <el-form v-else label-position="top" class="structured-form">
          <el-form-item label="推广对象"><el-input v-model="structured.product" /></el-form-item>
          <el-form-item label="目标人群"><el-input v-model="structured.audience" /></el-form-item>
          <el-form-item label="目标预算"><el-input v-model.number="structured.budget" type="number"><template #prepend>¥</template></el-input></el-form-item>
          <el-form-item label="投放周期"><el-input v-model="structured.cycle" /></el-form-item>
          <el-form-item label="转化目标"><el-select v-model="structured.conversion_goal"><el-option v-for="goal in ['线索', '注册', '成交', '新品推广']" :key="goal" :label="goal" :value="goal" /></el-select></el-form-item>
          <el-form-item label="投放渠道"><el-select v-model="structured.channels" multiple filterable allow-create default-first-option placeholder="输入后回车添加"><el-option v-for="channel in ['信息流', '搜索广告', '短视频', '社交媒体']" :key="channel" :label="channel" :value="channel" /></el-select></el-form-item>
          <el-form-item label="风险限制"><el-input v-model="structured.risk" type="textarea" :rows="3" /></el-form-item>
          <el-button class="save-button" type="primary" size="large" :disabled="!canSave" :loading="saving" @click="save">确认并保存活动</el-button>
        </el-form>
      </el-card>
    </el-form>
  </main>
</template>

<style scoped>
.create-page { min-height: 100vh; padding: 32px clamp(20px, 5vw, 72px) 60px; background: #f5f7fb; }.page-top, .form-grid { max-width: 1160px; margin: 0 auto; }.page-top { display: flex; margin-bottom: 28px; align-items: end; justify-content: space-between; gap: 20px; }.page-top :deep(.el-button) { margin: 0 0 20px -5px; }.eyebrow { margin: 0 0 8px; color: #6674d6; font-size: 11px; font-weight: 750; letter-spacing: 1.4px; }.page-top h1 { margin: 0; color: #202b45; font-size: 30px; letter-spacing: -1px; }.page-top p:last-child { margin: 9px 0 0; color: #8c96aa; font-size: 14px; }.steps { display: flex; align-items: center; gap: 10px; color: #abb3c2; font-size: 13px; }.steps span.active { color: #5567dc; font-weight: 650; }.steps i { width: 28px; height: 1px; background: #d9deea; }.form-grid { display: grid; grid-template-columns: minmax(0, 1.45fr) minmax(300px, .9fr); gap: 20px; align-items: start; }.form-card { border: 1px solid #e7eaf1; border-radius: 12px; }.form-card :deep(.el-card__header) { padding: 18px 22px; border-bottom-color: #edf0f5; }.form-card :deep(.el-card__body) { padding: 24px 22px; }.card-title { display: flex; justify-content: space-between; align-items: center; color: #2c3750; }.card-title span { color: #9ba4b5; font-size: 12px; font-weight: 400; }.card-title em { color: #ef5d65; font-style: normal; }.confirmed { color: #4bab83 !important; }.form-card :deep(.el-form-item__label) { padding-bottom: 8px; color: #59657a; font-size: 13px; line-height: 1; }.form-card :deep(.el-select), .form-card :deep(.el-date-editor) { width: 100%; }.parse-bar { display: flex; margin: 4px 0 18px; padding: 16px; align-items: center; justify-content: space-between; gap: 14px; border-radius: 9px; background: linear-gradient(100deg, #f4f4ff, #f7f3fd); }.parse-bar b { display: block; color: #4753a1; font-size: 14px; }.parse-bar span { display: block; margin-top: 4px; color: #8991ad; font-size: 12px; }.structured-card { position: sticky; top: 20px; }.result-empty { display: grid; min-height: 382px; place-content: center; text-align: center; color: #9da6b7; }.result-empty .el-icon { margin: auto; padding: 14px; color: #8996d8; font-size: 32px; border-radius: 14px; background: #f2f4ff; }.result-empty p { margin: 15px 0 6px; color: #69758b; font-size: 14px; }.result-empty span { font-size: 12px; }.structured-form :deep(.el-form-item) { margin-bottom: 17px; }.save-button { width: 100%; margin-top: 3px; }.structured-form :deep(.el-select) { width: 100%; }
@media (max-width: 900px) { .form-grid { grid-template-columns: 1fr; }.structured-card { position: static; }.page-top { align-items: start; flex-direction: column; }.steps { display: none; } }
@media (max-width: 520px) { .create-page { padding: 24px 14px 44px; }.form-card :deep(.el-card__body), .form-card :deep(.el-card__header) { padding-right: 16px; padding-left: 16px; }.parse-bar { align-items: start; flex-direction: column; }.parse-bar :deep(.el-button) { width: 100%; } }
</style>
