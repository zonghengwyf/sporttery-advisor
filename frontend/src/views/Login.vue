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
  if (!username.value) { error.value = '请输入用户名'; return }
  if (!password.value) { error.value = '请输入密码'; return }
  loading.value = true
  error.value = ''
  try {
    await auth.login(username.value, password.value)
    const redirect = (route.query.redirect as string) || '/analysis'
    router.push(redirect)
  } catch (e: any) {
    console.error('[login]', e)
    const msg = e?.response?.data?.detail
    error.value = msg ? String(msg) : '用户名或密码错误'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card card no-accent">
      <div class="login-head">
        <div class="login-logo">JCCC</div>
        <div class="text-sm text-muted mt-2">竞彩智能顾问，请登录以继续</div>
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
  min-height: 100dvh;
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
.login-logo {
  font-family: var(--font-disp);
  font-size: 28px;
  font-weight: 800;
  letter-spacing: .5px;
  color: var(--text);
  text-transform: uppercase;
  line-height: 1;
}
.login-form .field:last-of-type { margin-bottom: 20px; }
</style>
