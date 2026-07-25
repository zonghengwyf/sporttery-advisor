<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const nav = [
  { path: '/analysis', label: '赛事' },
  { path: '/tickets',  label: '方案' },
  { path: '/chat',     label: 'AI 分析' },
  { path: '/backtest', label: '回测' },
  { path: '/settings', label: '设置' },
]

function isActive(path: string) {
  return route.path === path || route.path.startsWith(path + '/')
}
</script>

<template>
  <header class="masthead">
    <div class="mh-inner">
      <div class="mh-logo" @click="router.push('/analysis')">
        <span class="mh-mark">JCCC</span>
        <span class="mh-sep">·</span>
        <span class="mh-name">竞彩顾问</span>
      </div>

      <!-- PC inline pill nav (hidden on mobile) -->
      <nav class="mh-nav" aria-label="桌面端导航">
        <button
          v-for="item in nav"
          :key="item.path"
          type="button"
          class="mh-link"
          :class="{ active: isActive(item.path) }"
          @click="router.push(item.path)"
        >{{ item.label }}</button>
      </nav>

      <div class="mh-actions">
        <span v-if="auth.isLoggedIn" class="mh-user">{{ auth.user?.username }}</span>
        <button v-if="auth.isLoggedIn" class="mh-btn" @click="auth.logout(); router.push('/login')">退出</button>
        <button v-else class="mh-btn mh-btn--login" @click="router.push('/login')">登录</button>
      </div>
    </div>
  </header>

  <!-- Content -->
  <main class="main-area">
    <RouterView />
  </main>

  <!-- Mobile bottom nav (hidden on PC) -->
  <nav class="bottom-nav" aria-label="移动端导航">
    <button
      v-for="item in nav"
      :key="item.path"
      type="button"
      class="bn-item"
      :class="{ active: isActive(item.path), 'bn-item--center': item.path === '/chat' }"
      @click="router.push(item.path)"
    >
      <span v-if="item.path === '/chat'" class="bn-fab" :class="{ active: isActive(item.path) }">
        <svg width="24" height="24" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M10 2l1.8 5.2 5.2 1.8-5.2 1.8L10 16.5l-1.8-5.2-5.2-1.8 5.2-1.8Z"/>
        </svg>
      </span>
      <svg v-else-if="item.path === '/analysis'" width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="2" y="2" width="7" height="7" rx="1.5"/><rect x="11" y="2" width="7" height="7" rx="1.5"/>
        <rect x="2" y="11" width="7" height="7" rx="1.5"/><rect x="11" y="11" width="7" height="7" rx="1.5"/>
      </svg>
      <svg v-else-if="item.path === '/tickets'" width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <rect x="3" y="3" width="14" height="14" rx="2"/><path d="M7 10h6M7 7h6M7 13h4"/>
      </svg>
      <svg v-else-if="item.path === '/backtest'" width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M3 15l4-8 3.5 7 3-5 3.5 6"/>
      </svg>
      <svg v-else-if="item.path === '/settings'" width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <circle cx="10" cy="10" r="2.5"/>
        <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42"/>
      </svg>
      <span v-if="item.path !== '/chat'">{{ item.label }}</span>
      <span v-else class="bn-fab-label">{{ item.label }}</span>
    </button>
  </nav>
</template>
