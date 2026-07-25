<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import api from '@/api'

const route = useRoute()

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const messages = ref<Message[]>([])
const input = ref('')
const sending = ref(false)
const chatEl = ref<HTMLElement | null>(null)
const selectedMatch = ref<number | null>(null)
const matches = ref<any[]>([])

async function loadMatches() {
  try {
    const { data } = await api.get('/matches/', {
      params: { sale_date: new Date().toISOString().split('T')[0] },
    })
    matches.value = data
    const qid = route.query.match ? Number(route.query.match) : null
    if (qid && data.find((m: any) => m.id === qid)) {
      selectedMatch.value = qid
    } else if (data.length) {
      selectedMatch.value = data[0].id
    }
  } catch {
    matches.value = []
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  sending.value = true

  const assistantMsg: Message = { role: 'assistant', content: '' }
  messages.value.push(assistantMsg)
  await nextTick()
  scrollToBottom()

  try {
    const res = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${localStorage.getItem('token') ?? ''}`,
      },
      body: JSON.stringify({
        message: text,
        match_id: selectedMatch.value,
        history: messages.value.slice(0, -2).map((m) => ({ role: m.role, content: m.content })),
      }),
    })

    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      const chunk = decoder.decode(value)
      const lines = chunk.split('\n')
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6))
            if (data.content) {
              assistantMsg.content += data.content
              await nextTick()
              scrollToBottom()
            }
          } catch { /* skip */ }
        }
      }
    }
  } catch (e) {
    assistantMsg.content = '连接失败，请检查后端服务。'
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

function scrollToBottom() {
  if (chatEl.value) chatEl.value.scrollTop = chatEl.value.scrollHeight
}

function handleKey(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

onMounted(loadMatches)
</script>

<template>
  <div class="view">
    <!-- Match selector -->
    <div class="match-sel-bar">
      <label class="field-label" for="match-sel" style="margin:0;white-space:nowrap">比赛</label>
      <select id="match-sel" v-model="selectedMatch" class="input" style="max-width:280px;font-size:12px;padding:5px 10px">
        <option v-for="m in matches" :key="m.id" :value="m.id">
          {{ m.home_team }} vs {{ m.away_team }}
        </option>
      </select>
    </div>

    <!-- Messages -->
    <div class="messages" ref="chatEl">
      <div v-if="!messages.length" class="chat-empty">
        <div class="chat-avatar chat-avatar--lg mb-3">AI</div>
        <p class="empty-title">开始提问</p>
        <p class="text-sm text-muted mt-2">就本场赛事进行 AI 深度分析</p>
      </div>

      <template v-else>
        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="msg-row"
          :class="msg.role"
        >
          <template v-if="msg.role === 'assistant'">
            <div class="chat-avatar">AI</div>
            <div class="chat-bubble-ai">
              <span v-if="!msg.content && sending" class="typing">
                <span /><span /><span />
              </span>
              <span v-else>{{ msg.content }}</span>
            </div>
          </template>
          <template v-else>
            <div class="chat-bubble-user">{{ msg.content }}</div>
          </template>
        </div>
      </template>
    </div>

    <!-- Input -->
    <div class="chat-bar">
      <textarea
        v-model="input"
        class="chat-input"
        rows="2"
        placeholder="输入问题，Enter 发送…"
        @keydown="handleKey"
      />
      <button class="send-btn btn-primary" :disabled="sending || !input.trim()" @click="send">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <path d="M1 8h14M8 2l7 6-7 6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.view {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.match-sel-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: var(--card-bd);
  flex-shrink: 0;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
}

.msg-row {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.msg-row.user { justify-content: flex-end; }

.typing {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}
.typing span {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--primary);
  animation: bounce .8s infinite;
}
.typing span:nth-child(2) { animation-delay: .15s; }
.typing span:nth-child(3) { animation-delay: .3s; }
@keyframes bounce {
  0%, 80%, 100% { transform: scale(1); opacity: .4; }
  40%            { transform: scale(1.3); opacity: 1; }
}

.chat-bar {
  display: flex;
  gap: 8px;
  align-items: flex-end;
  padding: 12px 16px;
  border-top: var(--card-bd);
  background: var(--card);
  flex-shrink: 0;
}
.chat-input {
  flex: 1;
  resize: none;
  border: var(--card-bd);
  border-radius: var(--radius);
  padding: 9px 12px;
  font: inherit;
  font-size: 13px;
  color: var(--text);
  background: var(--bg);
  outline: none;
  line-height: 1.5;
  transition: border-color .15s;
}
.chat-input:focus { border-color: var(--primary); }
.send-btn {
  width: 38px;
  height: 38px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
  transition: opacity .15s;
}
.send-btn:disabled { opacity: .4; cursor: not-allowed; }
</style>
