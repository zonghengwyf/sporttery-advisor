<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const nav = [
  { path: '/analysis', label: '今日赛事' },
  { path: '/tickets',  label: '投注方案' },
  { path: '/chat',     label: 'AI 分析' },
  { path: '/backtest', label: '回测报告' },
  { path: '/settings', label: '设置' },
]

const mobileNav = [
  { path: '/analysis', label: '赛事',  icon: `<rect x="2" y="2" width="7" height="7" rx="1.5"/><rect x="11" y="2" width="7" height="7" rx="1.5"/><rect x="2" y="11" width="7" height="7" rx="1.5"/><rect x="11" y="11" width="7" height="7" rx="1.5"/>` },
  { path: '/tickets',  label: '方案',  icon: `<rect x="3" y="3" width="14" height="14" rx="2"/><path d="M7 10h6M7 7h6M7 13h4"/>` },
  { path: '/chat',     label: 'AI',    icon: `<circle cx="10" cy="10" r="8"/><path d="M6.5 10h7M10 7v6"/>` },
  { path: '/backtest', label: '回测',  icon: `<path d="M3 16l5-10 4 8 3-5 4 7"/>` },
  { path: '/settings', label: '设置',  icon: `<circle cx="10" cy="7" r="3"/><path d="M3 18c0-4 3.1-7 7-7s7 3 7 7"/>` },
]

function isActive(path: string) {
  return route.path === path || route.path.startsWith(path + '/')
}
</script>

<template>
  <!-- 报纸报头导航 -->
  <header class="masthead">
    <div class="mh-inner">
      <div class="mh-logo" @click="router.push('/analysis')">
        <span class="mh-mark">JCCC</span>
        <span class="mh-sep">·</span>
        <span class="mh-name">竞彩顾问</span>
      </div>

      <nav class="mh-nav">
        <span
          v-for="item in nav"
          :key="item.path"
          class="mh-link"
          :class="{ active: isActive(item.path) }"
          @click="router.push(item.path)"
        >{{ item.label }}</span>
      </nav>

      <div class="mh-actions">
        <span v-if="auth.isLoggedIn" class="mh-user">{{ auth.user?.username }}</span>
        <button v-if="auth.isLoggedIn" class="mh-btn" @click="auth.logout(); router.push('/login')">退出</button>
        <button v-else class="mh-btn mh-btn--login" @click="router.push('/login')">登录</button>
      </div>
    </div>
  </header>

  <!-- 内容 -->
  <main class="main-area">
    <RouterView />
  </main>

  <!-- 移动端底导 -->
  <nav class="bottom-nav">
    <div
      v-for="item in mobileNav"
      :key="item.path"
      class="bn-item"
      :class="{ active: isActive(item.path) }"
      @click="router.push(item.path)"
    >
      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" v-html="item.icon" />
      {{ item.label }}
    </div>
  </nav>
</template>
