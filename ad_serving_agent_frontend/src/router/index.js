import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'
import CampaignList from '../views/CampaignList.vue'
import CampaignCreate from '../views/CampaignCreate.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/campaigns' },
    { path: '/login', name: 'login', component: Login },
    { path: '/campaigns', name: 'campaigns', component: CampaignList, meta: { requiresAuth: true } },
    { path: '/campaigns/create', component: CampaignCreate, meta: { requiresAuth: true } },
    { path: '/campaigns/:id/strategy', component: { template: '<main />' }, meta: { requiresAuth: true } },
  ],
})

router.beforeEach((to) => {
  if (to.meta.requiresAuth && !localStorage.getItem('token')) return { name: 'login' }
  if (to.name === 'login' && localStorage.getItem('token')) return { name: 'campaigns' }
})

export default router
