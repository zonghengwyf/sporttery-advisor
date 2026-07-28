<script setup lang="ts">
import { ref, computed, nextTick, watch, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { useChatStore } from '@/stores/chat'

const route = useRoute()
const chatStore = useChatStore()

const open = ref(false)
const minimized = ref(false)
const input = ref('')
const messages = ref<Array<{ role: 'user' | 'assistant'; content: string }>>([])
const streaming = ref(false)
const msgEnd = ref<HTMLElement | null>(null)
const forcedMatchId = ref<number | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const panelStyle = ref<Record<string, string>>({})
let _isDragging = false
let _dragStartX = 0, _dragStartY = 0
let _panelStartRight = 0, _panelStartBottom = 0

// React to external open requests (e.g. from MatchDetail)
watch(() => chatStore.open, (val) => {
  if (val) {
    forcedMatchId.value = chatStore.requestMatchId
    chatStore.requestMatchId = null
    open.value = true
    minimized.value = false
  }
})

// Derive context from forced matchId or current route
const matchId = computed<number | null>(() => {
  if (forcedMatchId.value) return forcedMatchId.value
  if (route.params.id) {
    const id = Number(route.params.id)
    return isNaN(id) ? null : id
  }
  return null
})

const contextLabel = computed(() => {
  if (matchId.value) return `场次 #${matchId.value}`
  const labels: Record<string, string> = {
    '/analysis': '今日赛事',
    '/tickets': '投注方案',
    '/records': '历史战绩',
  }
  return labels[route.path] ?? '竞彩顾问'
})

function toggle() {
  if (open.value && minimized.value) {
    minimized.value = false
    return
  }
  open.value = !open.value
  if (!open.value) {
    chatStore.close()
    forcedMatchId.value = null
  }
}

function close() {
  open.value = false
  chatStore.close()
  forcedMatchId.value = null
  minimized.value = false
  panelStyle.value = {}
}

function onHeaderPointerDown(e: PointerEvent) {
  if ((e.target as HTMLElement).closest('button, textarea, input')) return
  _isDragging = true
  _dragStartX = e.clientX
  _dragStartY = e.clientY
  ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  if (panelRef.value) {
    const rect = panelRef.value.getBoundingClientRect()
    _panelStartRight = window.innerWidth - rect.right
    _panelStartBottom = window.innerHeight - rect.bottom
  }
  document.addEventListener('pointermove', _onPanelMove)
  document.addEventListener('pointerup', _onPanelUp, { once: true })
  document.addEventListener('pointercancel', _onPanelUp, { once: true })
}

function _onPanelMove(e: PointerEvent) {
  if (!_isDragging) return
  const dx = e.clientX - _dragStartX
  const dy = e.clientY - _dragStartY
  panelStyle.value = {
    right: `${Math.max(8, _panelStartRight - dx)}px`,
    bottom: `${Math.max(8, _panelStartBottom - dy)}px`,
  }
}

function _onPanelUp() {
  _isDragging = false
  document.removeEventListener('pointermove', _onPanelMove)
}

onUnmounted(() => {
  document.removeEventListener('pointermove', _onPanelMove)
})

function newSession() {
  messages.value = []
  input.value = ''
}

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: text })
  streaming.value = true
  const idx = messages.value.length
  messages.value.push({ role: 'assistant', content: '' })
  await nextTick()
  scrollToEnd()

  try {
    const token = localStorage.getItem('token') ?? ''
    const body: Record<string, unknown> = {
      message: text,
      history: messages.value.slice(0, -2).map(m => ({ role: m.role, content: m.content })),
    }
    if (matchId.value) body.match_id = matchId.value

    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(120_000),
    })
    if (!res.ok) {
      if (res.status === 401) {
        messages.value[idx].content = '请先登录才能使用 AI 对话'
        setTimeout(() => {
          window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`
        }, 1500)
      } else {
        messages.value[idx].content = '请求失败，请检查 LLM 配置后重试'
      }
      return
    }

    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const ev = JSON.parse(line.slice(6))
          if (ev.event === 'token' || ev.delta) {
            messages.value[idx].content += ev.delta ?? ev.token ?? ''
            await nextTick()
            scrollToEnd()
          }
        } catch { /* skip */ }
      }
    }
  } catch {
    messages.value[idx].content = messages.value[idx].content || '连接失败，请稍后重试'
  } finally {
    streaming.value = false
    await nextTick()
    scrollToEnd()
  }
}

function scrollToEnd() {
  msgEnd.value?.scrollIntoView({ behavior: 'smooth', block: 'end' })
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}
</script>

<template>
  <!-- FAB trigger button -->
  <button
    v-show="!chatStore.fabHidden"
    class="chat-fab-btn"
    :class="{ open: open && !minimized }"
    aria-label="打开 AI 对话"
    @click="toggle"
  >
    <svg v-if="!open || minimized" width="22" height="22" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10 2l1.8 5.2 5.2 1.8-5.2 1.8L10 16.5l-1.8-5.2-5.2-1.8 5.2-1.8Z"/>
    </svg>
    <svg v-else width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
      <path d="M4 4l12 12M16 4L4 16"/>
    </svg>
    <span v-if="open && minimized && messages.length" class="fab-min-dot" />
  </button>

  <!-- Chat panel -->
  <Transition name="fab-panel">
    <div v-if="open && !chatStore.fabHidden" ref="panelRef" class="fab-panel" :class="{ 'fab-panel--min': minimized }" :style="panelStyle">
      <!-- Panel header (drag handle) -->
      <div class="fab-header" @pointerdown="onHeaderPointerDown">
        <div class="fab-header-left">
          <span class="fab-avatar">AI</span>
          <div>
            <div class="fab-title">竞彩 AI 顾问</div>
            <div class="fab-context">{{ contextLabel }}</div>
          </div>
        </div>
        <div class="fab-header-actions">
          <!-- Minimize toggle -->
          <button class="fab-action-btn" :title="minimized ? '展开' : '最小化'" @click.stop="minimized = !minimized">
            <svg v-if="minimized" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M2 12l6-8 6 8"/>
            </svg>
            <svg v-else width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
              <path d="M2 6l6 6 6-6"/>
            </svg>
          </button>
          <button v-if="messages.length && !minimized" class="fab-new-btn" :disabled="streaming" @click.stop="newSession" title="新对话">
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              <path d="M8 3H4a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V9"/>
              <path d="M12 1l3 3-6 6H6V7l6-6z"/>
            </svg>
          </button>
          <button class="fab-close" @click.stop="close" aria-label="关闭">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path d="M1 1l12 12M13 1L1 13"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- Messages (hidden when minimized) -->
      <div v-show="!minimized" class="fab-messages">
        <div v-if="!messages.length" class="fab-empty">
          <p class="fab-empty-title">有什么需要分析的？</p>
          <div class="fab-suggestions">
            <button class="fab-sugg" @click="input = '这场比赛的赔率是否有价值？'; send()">赔率有价值吗？</button>
            <button class="fab-sugg" @click="input = '今日有哪些冷门机会？'; send()">冷门机会？</button>
            <button class="fab-sugg" @click="input = '稳健方案的选场逻辑是什么？'; send()">稳健选场逻辑？</button>
          </div>
        </div>
        <div
          v-for="(m, i) in messages"
          :key="i"
          class="fab-msg"
          :class="m.role"
        >
          <span v-if="m.role === 'assistant'" class="fab-msg-avatar">AI</span>
          <div class="fab-msg-body" :class="{ 'streaming': m.role === 'assistant' && streaming && i === messages.length - 1 }">
            {{ m.content }}<span v-if="m.role === 'assistant' && streaming && i === messages.length - 1 && !m.content" class="typing-dot" />
          </div>
        </div>
        <div ref="msgEnd" style="height:1px" />
      </div>

      <!-- Input bar (hidden when minimized) -->
      <div v-show="!minimized" class="fab-input-bar">
        <textarea
          v-model="input"
          class="fab-input"
          placeholder="输入问题，Enter 发送…"
          rows="1"
          :disabled="streaming"
          @keydown="onKeydown"
        />
        <button class="fab-send" :disabled="!input.trim() || streaming" @click="send">
          <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor">
            <path d="M2 10l16-8-8 16-2-6-6-2z"/>
          </svg>
        </button>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
/* ── FAB button ────────────────────────────────────────────────── */
.chat-fab-btn {
  position: fixed;
  bottom: calc(56px + 16px + env(safe-area-inset-bottom, 0px));
  right: 16px;
  left: auto;
  z-index: 201;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px rgba(0,0,0,.35);
  cursor: pointer;
  transition: transform .15s, background .15s, box-shadow .15s;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}
.chat-fab-btn:hover { transform: scale(1.07); }
.chat-fab-btn:active { transform: scale(0.93); }
.chat-fab-btn.open { background: var(--card); color: var(--text2); box-shadow: 0 2px 8px rgba(0,0,0,.2); }

@media (min-width: 768px) {
  .chat-fab-btn {
    bottom: 24px;
    right: 24px;
  }
}

/* ── Panel ─────────────────────────────────────────────────────── */
.fab-panel {
  position: fixed;
  bottom: calc(56px + 20px + env(safe-area-inset-bottom, 0px));
  right: 14px;
  left: auto;
  z-index: 201;
  width: min(340px, calc(100vw - 28px));
  max-height: 70vh;
  background: var(--card);
  border: var(--card-bd);
  border-radius: 14px;
  box-shadow: 0 8px 32px rgba(0,0,0,.35);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

@media (min-width: 768px) {
  .fab-panel {
    bottom: 88px;
    right: 24px;
  }
}

/* Transition */
.fab-panel-enter-active { transition: opacity .18s ease, transform .18s ease; }
.fab-panel-leave-active { transition: opacity .14s ease, transform .14s ease; }
.fab-panel-enter-from { opacity: 0; transform: translateY(12px) scale(.96); }
.fab-panel-leave-to   { opacity: 0; transform: translateY(8px) scale(.97); }

/* Minimized panel */
.fab-panel--min { max-height: fit-content; min-height: auto; }

/* Minimized badge on FAB */
.fab-min-dot {
  position: absolute;
  top: 5px; right: 5px;
  width: 8px; height: 8px;
  border-radius: 50%;
  background: var(--green, #22c55e);
  border: 1.5px solid #fff;
  pointer-events: none;
}

/* Header */
.fab-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: var(--card-bd);
  flex-shrink: 0;
  cursor: grab;
  user-select: none;
}
.fab-header:active { cursor: grabbing; }

/* Minimize/action button */
.fab-action-btn {
  background: transparent;
  color: var(--text3);
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  display: flex;
  transition: color .12s, background .12s;
}
.fab-action-btn:hover { color: var(--text); background: var(--line); }
.fab-header-left { display: flex; align-items: center; gap: 10px; }
.fab-avatar {
  width: 30px; height: 30px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  font-family: var(--font-disp);
}
.fab-title { font-size: 13px; font-weight: 700; line-height: 1.2; }
.fab-context { font-size: 10px; color: var(--text3); }
.fab-header-actions { display: flex; align-items: center; gap: 2px; }
.fab-new-btn { background: transparent; color: var(--text3); cursor: pointer; padding: 4px; border-radius: 4px; display: flex; transition: color .12s; }
.fab-new-btn:hover { color: var(--primary); }
.fab-new-btn:disabled { opacity: .35; cursor: not-allowed; }
.fab-close { background: transparent; color: var(--text3); cursor: pointer; padding: 4px; border-radius: 4px; display: flex; }
.fab-close:hover { color: var(--text); }

/* Messages */
.fab-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
}

.fab-empty { text-align: center; padding: 20px 0 8px; }
.fab-empty-title { font-size: 12px; color: var(--text2); margin-bottom: 12px; }
.fab-suggestions { display: flex; flex-direction: column; gap: 6px; }
.fab-sugg {
  font-size: 11px;
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary) 20%, transparent);
  border-radius: 6px;
  padding: 7px 10px;
  cursor: pointer;
  text-align: left;
  font-family: var(--font);
  transition: background .12s;
}
.fab-sugg:hover { background: color-mix(in srgb, var(--primary) 14%, transparent); }

.fab-msg {
  display: flex;
  align-items: flex-start;
  gap: 7px;
}
.fab-msg.user { flex-direction: row-reverse; }
.fab-msg-avatar {
  width: 22px; height: 22px;
  border-radius: 50%;
  background: var(--primary);
  color: #fff;
  font-size: 8px;
  font-weight: 800;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  font-family: var(--font-disp);
  margin-top: 1px;
}
.fab-msg-body {
  max-width: 85%;
  font-size: 12px;
  line-height: 1.6;
  padding: 7px 10px;
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
}
.fab-msg.user .fab-msg-body {
  background: var(--primary);
  color: #fff;
  border-radius: 8px 8px 2px 8px;
}
.fab-msg.assistant .fab-msg-body {
  background: var(--bg);
  color: var(--text);
  border-radius: 8px 8px 8px 2px;
}
.typing-dot {
  display: inline-block;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--text3);
  animation: tdot .8s ease-in-out infinite;
  vertical-align: middle;
}
@keyframes tdot { 0%, 100% { opacity: .3; } 50% { opacity: 1; } }

/* Input */
.fab-input-bar {
  display: flex;
  align-items: flex-end;
  gap: 8px;
  padding: 10px 12px;
  border-top: var(--card-bd);
  flex-shrink: 0;
}
.fab-input {
  flex: 1;
  background: var(--bg);
  border: var(--card-bd);
  border-radius: 8px;
  color: var(--text);
  font-size: 13px;
  font-family: var(--font);
  padding: 8px 10px;
  resize: none;
  min-height: 36px;
  max-height: 80px;
  line-height: 1.5;
  outline: none;
}
.fab-input:focus { border-color: var(--primary); }
.fab-input:disabled { opacity: .5; }
.fab-send {
  width: 34px; height: 34px;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity .12s;
}
.fab-send:disabled { opacity: .35; cursor: not-allowed; }
</style>
