import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('@/views/Login.vue') },
    {
      path: '/',
      component: () => import('@/layouts/MainLayout.vue'),
      children: [
        { path: '', redirect: '/analysis' },
        { path: 'analysis', component: () => import('@/views/DailyAnalysis.vue') },
        { path: 'matches/:id', component: () => import('@/views/MatchDetail.vue') },
        { path: 'tickets', component: () => import('@/views/BettingTickets.vue') },
        { path: 'backtest', component: () => import('@/views/BacktestReport.vue') },
        { path: 'chat', component: () => import('@/views/ChatAnalysis.vue') },
        { path: 'settings', component: () => import('@/views/Settings.vue') },
      ],
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  const protectedPaths = ['/settings', '/chat']
  const needsAuth = protectedPaths.some(p => to.path.startsWith(p))

  if (to.path === '/login' && token) {
    next('/analysis')
  } else if (needsAuth && !token) {
    next(`/login?redirect=${encodeURIComponent(to.fullPath)}`)
  } else {
    next()
  }
})

export default router
