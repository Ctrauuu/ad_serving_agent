<script setup>
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Lock, Monitor, UserFilled } from '@element-plus/icons-vue'
import { login } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const authStore = useAuthStore()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const canLogin = computed(() => Boolean(form.username.trim() && form.password))

async function submit() {
  if (!canLogin.value || loading.value) return
  loading.value = true
  try {
    authStore.setLogin(await login({ username: form.username.trim(), password: form.password }))
    router.push('/campaigns')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <div class="ambient ambient-one" />
    <div class="ambient ambient-two" />

    <section class="brand-panel">
      <div class="brand">
        <div class="brand-mark"><Monitor /></div>
        <span>AD•PULSE</span>
      </div>
      <div class="brand-copy">
        <p class="eyebrow">INTELLIGENT MEDIA OPERATIONS</p>
        <h1>把每一笔预算<br><em>投向增长。</em></h1>
        <p class="intro">从策略生成、实时监控到风险审批，让投放决策更快、更有据可依。</p>
      </div>
      <div class="capabilities">
        <div><span class="capability-dot cyan" />实时感知投放异动</div>
        <div><span class="capability-dot violet" />AI 辅助策略决策</div>
        <div><span class="capability-dot pink" />关键动作人工审批</div>
      </div>
      <p class="copyright">© 2026 AD•PULSE / Growth Intelligence</p>
    </section>

    <section class="form-panel">
      <div class="form-wrap">
        <div class="welcome-mark"><Monitor /></div>
        <header>
          <p class="eyebrow">WELCOME BACK</p>
          <h2>登录工作台</h2>
          <p>使用您的系统账号继续</p>
        </header>

        <el-form :model="form" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input v-model="form.username" size="large" autocomplete="username" placeholder="请输入用户名">
              <template #prefix><el-icon><UserFilled /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" size="large" type="password" show-password autocomplete="current-password" placeholder="请输入密码">
              <template #prefix><el-icon><Lock /></el-icon></template>
            </el-input>
          </el-form-item>
          <el-button class="login-button" type="primary" size="large" native-type="submit" :disabled="!canLogin" :loading="loading">
            {{ loading ? '正在验证身份' : '安全登录' }}
            <span v-if="!loading" class="arrow">→</span>
          </el-button>
        </el-form>

        <p class="security-note"><el-icon><Lock /></el-icon> 受保护的内部投放管理系统</p>
      </div>
    </section>
  </main>
</template>

<style scoped>
.login-page {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.08fr) minmax(460px, 0.92fr);
  min-height: 100vh;
  overflow: hidden;
  background: #0a1024;
}

.brand-panel {
  position: relative;
  z-index: 1;
  display: flex;
  min-height: 100vh;
  padding: clamp(38px, 6vw, 86px) clamp(48px, 9vw, 150px);
  flex-direction: column;
  color: #eef3ff;
}

.brand { display: flex; align-items: center; gap: 12px; font-weight: 800; letter-spacing: 1.8px; }
.brand-mark, .welcome-mark { display: grid; place-items: center; border-radius: 12px; }
.brand-mark { width: 38px; height: 38px; color: #071023; background: linear-gradient(135deg, #80f1ff, #8f8cff); font-size: 21px; }
.brand-copy { margin: auto 0 52px; }
.eyebrow { margin: 0 0 16px; color: #8e9bbd; font-size: 11px; font-weight: 700; letter-spacing: 1.6px; }
h1 { margin: 0; color: #f7f9ff; font-size: clamp(42px, 4.5vw, 68px); line-height: 1.12; letter-spacing: -3px; }
h1 em { color: #8cecff; font-style: normal; }
.intro { max-width: 450px; margin: 27px 0 0; color: #aab5d2; font-size: 16px; line-height: 1.8; }
.capabilities { display: grid; gap: 16px; color: #c5cee4; font-size: 14px; }
.capabilities > div { display: flex; align-items: center; gap: 11px; }
.capability-dot { width: 8px; height: 8px; border-radius: 50%; box-shadow: 0 0 13px currentColor; }
.cyan { color: #79ebff; background: #79ebff; }.violet { color: #aa9dff; background: #aa9dff; }.pink { color: #f19ac9; background: #f19ac9; }
.copyright { margin: 52px 0 0; color: #687493; font-size: 11px; letter-spacing: .4px; }

.form-panel { position: relative; z-index: 1; display: grid; padding: 32px; place-items: center; background: #fff; }
.form-wrap { width: min(100%, 390px); }
.welcome-mark { width: 46px; height: 46px; margin-bottom: 35px; color: #fff; background: linear-gradient(135deg, #5767ed, #8b55ce); font-size: 25px; box-shadow: 0 10px 24px rgba(86, 103, 237, .25); }
header { margin-bottom: 33px; }
header .eyebrow { margin-bottom: 10px; color: #6b75be; }
h2 { margin: 0 0 9px; color: #17213b; font-size: 31px; letter-spacing: -1.2px; }
header > p:last-child { margin: 0; color: #9098aa; font-size: 14px; }

:deep(.el-form-item) { margin-bottom: 22px; }
:deep(.el-form-item__label) { padding-bottom: 8px; color: #43506a; font-size: 13px; font-weight: 650; line-height: 1; }
:deep(.el-input__wrapper) { min-height: 46px; padding: 1px 14px; border: 1px solid #e4e8f1; border-radius: 9px; box-shadow: none; transition: border-color .2s, box-shadow .2s; }
:deep(.el-input__wrapper:hover), :deep(.el-input__wrapper.is-focus) { border-color: #7a85e8; box-shadow: 0 0 0 3px rgba(94, 107, 228, .1); }
:deep(.el-input__prefix) { color: #8994ad; font-size: 17px; }
.login-button { width: 100%; height: 48px; margin-top: 7px; border: 0; border-radius: 9px; font-weight: 650; letter-spacing: .2px; background: linear-gradient(100deg, #5968ec, #7a55d1); box-shadow: 0 12px 22px rgba(84, 92, 210, .22); transition: transform .2s, box-shadow .2s; }
.login-button:not(.is-disabled):hover { transform: translateY(-1px); box-shadow: 0 15px 27px rgba(84, 92, 210, .32); }
.arrow { margin-left: 11px; font-size: 20px; line-height: 0; }
.security-note { display: flex; margin: 25px 0 0; justify-content: center; align-items: center; gap: 6px; color: #9ca5b8; font-size: 12px; }

.ambient { position: absolute; border-radius: 50%; filter: blur(2px); opacity: .65; }
.ambient-one { width: 380px; height: 380px; top: -130px; left: 24%; background: radial-gradient(circle, rgba(91, 110, 238, .4), transparent 68%); }
.ambient-two { width: 500px; height: 500px; right: 38%; bottom: -300px; background: radial-gradient(circle, rgba(27, 202, 233, .22), transparent 68%); }

@media (max-width: 820px) {
  .login-page { display: block; background: #fff; }
  .brand-panel { display: none; }
  .form-panel { min-height: 100vh; padding: 28px; }
}

</style>
