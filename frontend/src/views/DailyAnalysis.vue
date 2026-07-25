<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api'

const router = useRouter()

interface Match {
  id: number
  sporttery_id: string
  home_team: string
  away_team: string
  league: string
  kickoff_at: string
  sale_date: string
  sporttery_odds: {
    home: number; draw: number; away: number
    hhad?: { home: number; draw: number; away: number; handicap: number | null }
  } | null
  overseas_odds: Record<string, number> | null
  is_tournament: boolean
}

// /predictions/batch returns a compact shape (no probs)
interface BatchPrediction {
  risk_label: string | null
  confidence: number | null   // float 0-1
  consensus: string | null
}

const matches = ref<Match[]>([])
const predictions = ref<Record<number, BatchPrediction>>({})
const loading = ref(true)
const syncing = ref(false)

function localDate(offset = 0) {
  const d = new Date()
  d.setDate(d.getDate() + offset)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const selectedDate = ref(localDate())

const dates = computed(() => {
  return [-1, 0, 1].map(offset => {
    const d = new Date()
    d.setDate(d.getDate() + offset)
    return {
      label: formatDateLabel(d, offset),
      value: localDate(offset),
    }
  })
})

function formatDateLabel(d: Date, offset: number) {
  const days = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  const prefix = offset === 0 ? '今天' : offset === -1 ? '昨天' : offset === 1 ? '明天' : days[d.getDay()]
  return `${prefix} ${d.getMonth() + 1}/${d.getDate()}`
}

const todayStats = computed(() => {
  const analyzed = Object.keys(predictions.value).length
  return { total: matches.value.length, analyzed }
})

async function load() {
  loading.value = true
  try {
    const { data } = await api.get('/matches/', { params: { sale_date: selectedDate.value } })
    matches.value = data
    await loadPredictions()
  } catch {
    matches.value = []
  } finally {
    loading.value = false
  }
}

async function loadPredictions() {
  if (!matches.value.length) return
  const ids = matches.value.map((m) => m.id).join(',')
  try {
    const { data } = await api.get('/predictions/batch', { params: { match_ids: ids } })
    predictions.value = data
  } catch {
    // predictions optional
  }
}

async function syncMatches() {
  syncing.value = true
  try {
    await api.post('/matches/sync')
    await load()
  } finally {
    syncing.value = false
  }
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

// confidence is a float 0-1 from backend
function confidenceLabel(c: number | null) {
  if (c == null) return '待分析'
  if (c >= 0.7) return '高置信'
  if (c >= 0.4) return '中置信'
  return '低置信'
}

function confidenceBadge(c: number | null) {
  if (c == null) return 'badge-gray'
  if (c >= 0.7) return 'badge-red'
  if (c >= 0.4) return 'badge-blue'
  return 'badge-gray'
}

function homeOdds(m: Match) { return m.sporttery_odds?.home ?? null }
function drawOdds(m: Match) { return m.sporttery_odds?.draw ?? null }
function awayOdds(m: Match) { return m.sporttery_odds?.away ?? null }

onMounted(load)
</script>

<template>
  <div class="view">
    <!-- Date strip with sync -->
    <div class="date-strip">
      <button
        v-for="d in dates"
        :key="d.value"
        class="date-btn"
        :class="{ on: d.value === selectedDate }"
        @click="selectedDate = d.value; load()"
      >
        {{ d.label }}
      </button>
      <button class="btn btn-ghost btn-sm" style="margin-left:auto;flex-shrink:0" :disabled="syncing" @click="syncMatches">
        <svg v-if="!syncing" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M14 8A6 6 0 0 1 2.5 12M2 8a6 6 0 0 1 11.5-4M2 4v4h4M14 12v-4h-4"/>
        </svg>
        <span v-if="syncing">同步中…</span>
        <span v-else>同步</span>
      </button>
    </div>

    <!-- Stats row -->
    <div class="stats-row">
      <div class="stat-item card no-accent p-3">
        <div class="stat-val text-primary">{{ todayStats.total }}</div>
        <div class="stat-label">今日场次</div>
      </div>
      <div class="stat-item card no-accent p-3">
        <div class="stat-val text-green">{{ todayStats.analyzed }}</div>
        <div class="stat-label">已分析</div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="match-list">
      <div v-for="i in 4" :key="i" class="skeleton" style="height:140px;margin-bottom:8px" />
    </div>

    <!-- Empty -->
    <div v-else-if="!matches.length" class="empty-tip">
      <p class="empty-title">暂无赛事</p>
      <p class="text-sm text-muted mt-2">点击同步按钮拉取今日赛单</p>
    </div>

    <!-- Match list -->
    <div v-else class="match-list">
      <div
        v-for="m in matches"
        :key="m.id"
        class="card cursor-pointer"
        @click="router.push(`/matches/${m.id}`)"
      >
        <!-- Card head: league + time + badge -->
        <div class="card-head flex items-center justify-between">
          <div class="flex items-center gap-1">
            <span class="text-xs text-muted font-disp">{{ m.league }}</span>
          </div>
          <div class="flex items-center gap-2">
            <span
              v-if="predictions[m.id]"
              class="badge"
              :class="confidenceBadge(predictions[m.id].confidence)"
            >
              {{ confidenceLabel(predictions[m.id].confidence) }}
            </span>
            <span class="text-xs text-muted">{{ formatTime(m.kickoff_at) }}</span>
          </div>
        </div>

        <!-- Teams -->
        <div class="teams-row">
          <div class="team-col">
            <div class="team-name">{{ m.home_team }}</div>
            <div class="text-xs text-muted">主场</div>
          </div>
          <div class="vs-sep font-disp">VS</div>
          <div class="team-col">
            <div class="team-name">{{ m.away_team }}</div>
            <div class="text-xs text-muted">客场</div>
          </div>
        </div>

        <!-- Prob bar: use confidence as proxy width when no fused_probs in batch -->
        <div v-if="predictions[m.id]?.confidence != null" class="px-4 mb-2">
          <div class="prob-bar">
            <div class="prob-fill" :style="{ width: Math.round((predictions[m.id].confidence ?? 0) * 100) + '%' }" />
          </div>
        </div>

        <!-- Odds: 胜平负 + 让球 -->
        <div v-if="homeOdds(m)" class="odds-section">
          <div class="odds-row">
            <div class="odd-item">
              <span class="odd-label">主胜</span>
              <span class="odd-val win">{{ homeOdds(m)?.toFixed(2) }}</span>
            </div>
            <div class="odd-item">
              <span class="odd-label">平局</span>
              <span class="odd-val draw">{{ drawOdds(m)?.toFixed(2) }}</span>
            </div>
            <div class="odd-item">
              <span class="odd-label">客胜</span>
              <span class="odd-val lose">{{ awayOdds(m)?.toFixed(2) }}</span>
            </div>
          </div>
          <div v-if="m.sporttery_odds?.hhad" class="odds-row hhad-row">
            <div class="odd-item">
              <span class="odd-label">让球</span>
              <span class="odd-label-handicap">
                {{ m.sporttery_odds.hhad.handicap != null ? (m.sporttery_odds.hhad.handicap > 0 ? '+' : '') + m.sporttery_odds.hhad.handicap : '' }}
              </span>
            </div>
            <div class="odd-item">
              <span class="odd-val win">{{ m.sporttery_odds.hhad.home.toFixed(2) }}</span>
            </div>
            <div class="odd-item">
              <span class="odd-val draw">{{ m.sporttery_odds.hhad.draw.toFixed(2) }}</span>
            </div>
            <div class="odd-item">
              <span class="odd-val lose">{{ m.sporttery_odds.hhad.away.toFixed(2) }}</span>
            </div>
          </div>
        </div>
        <div v-else class="odds-row">
          <span class="text-xs text-muted">赔率未更新</span>
        </div>

        <!-- Consensus badge (from batch prediction) -->
        <div v-if="predictions[m.id]?.consensus" class="ai-snippet">
          <div class="chat-avatar chat-avatar--sm">AI</div>
          <div class="ai-snip-text">模型共识：{{ predictions[m.id].consensus }} · 点击查看完整分析</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; min-height: 100%; }

.date-strip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  border-bottom: var(--card-bd);
  overflow-x: auto;
  flex-shrink: 0;
}
.date-btn {
  padding: 4px 12px;
  border-radius: 20px;
  border: var(--card-bd);
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  background: transparent;
  color: var(--text2);
  transition: all .15s;
  font-family: var(--font);
}
.date-btn.on {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

.stats-row {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: var(--card-bd);
}
.stat-item { flex: 1; text-align: center; }

.match-list {
  flex: 1;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.empty-tip {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}

.card-head {
  padding: 10px 14px 0;
}
.teams-row {
  display: flex;
  align-items: center;
  padding: 8px 14px 10px;
  gap: 12px;
}
.team-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.team-col:last-child { align-items: flex-end; }
.team-name {
  font-size: 14px;
  font-weight: 600;
}
.vs-sep {
  font-size: 11px;
  color: var(--text3);
  font-weight: 500;
  letter-spacing: 1px;
  flex-shrink: 0;
}

.odds-section { display: flex; flex-direction: column; }
.hhad-row { border-top: 1px solid var(--line); padding-top: 6px; opacity: .85; }
.odd-label-handicap {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  font-family: var(--font-num);
}

.ai-snippet {  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 0 14px 12px;
}
.ai-snip-text {
  font-size: 12px;
  color: var(--text2);
  line-height: 1.55;
  background: var(--primary-d);
  border-left: 2px solid var(--primary);
  padding: 7px 10px;
  border-radius: 0 4px 4px 0;
  flex: 1;
  /* clamp to 2 lines */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>
