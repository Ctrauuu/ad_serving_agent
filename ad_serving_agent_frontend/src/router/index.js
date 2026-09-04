import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'
import CampaignList from '../views/CampaignList.vue'
import CampaignCreate from '../views/CampaignCreate.vue'
import StrategyConfirm from '../views/StrategyConfirm.vue'
import AdTasks from '../views/AdTasks.vue'
import AdTaskDetail from '../views/AdTaskDetail.vue'
import MonitorDashboard from '../views/MonitorDashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/campaigns' },
    { path: '/login', name: 'login', component: Login },
    { path: '/campaigns', name: 'campaigns', component: CampaignList, meta: { requiresAuth: true } },
    { path: '/campaigns/create', component: CampaignCreate, meta: { requiresAuth: true } },
    { path: '/campaigns/:id/strategy', component: StrategyConfirm, meta: { requiresAuth: true } },
    { path: '/campaigns/:id/ad-tasks', component: AdTasks, meta: { requiresAuth: true } },
    { path: '/campaigns/:id/ad-tasks/:taskId', component: AdTaskDetail, meta: { requiresAuth: true } },
    { path: '/campaigns/:id/monitor', component: MonitorDashboard, meta: { requiresAuth: true } },
  ],
})

router.beforeEach((to) => {
  if (to.meta.requiresAuth && !localStorage.getItem('token')) return { name: 'login' }
  if (to.name === 'login' && localStorage.getItem('token')) return { name: 'campaigns' }
})

export default router
