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

export default router
