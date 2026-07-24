<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function submit() {
  if (!username.value || !password.value) return
  loading.value = true
  error.value = ''
  try {
    await auth.login(username.value, password.value)
    const redirect = (route.query.redirect as string) || '/analysis'
    router.push(redirect)
  } catch {
    error.value = '用户名或密码错误'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card card no-accent">
      <div class="login-head">
        <div class="sidebar-logo-mark" style="font-size:24px">JCCC</div>
        <div class="sidebar-logo-sub mt-2" style="font-size:13px">竞彩智能顾问 — 请登录以继续</div>
      </div>

      <form @submit.prevent="submit" class="login-form">
        <div class="field">
          <label class="field-label">用户名</label>
          <input v-model="username" class="input" placeholder="admin" autocomplete="username" />
        </div>
        <div class="field">
          <label class="field-label">密码</label>
          <input v-model="password" class="input" type="password" placeholder="••••••••" autocomplete="current-password" />
        </div>
        <p v-if="error" class="text-sm" style="color:var(--primary);margin-bottom:10px">{{ error }}</p>
        <button type="submit" class="btn btn-primary w-full" :disabled="loading">
          {{ loading ? '登录中...' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
  padding: 20px;
}
.login-card {
  width: 100%;
  max-width: 380px;
  padding: 32px;
}
.login-head { margin-bottom: 24px; }
.login-form .field:last-of-type { margin-bottom: 20px; }
</style>
