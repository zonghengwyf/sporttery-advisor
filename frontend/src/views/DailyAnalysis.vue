<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api from '@/api'

const router = useRouter()
const route = useRoute()

interface Match {
  id: number
  sporttery_id: string
  match_no: string | null
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

interface BatchPrediction {
  risk_label: string | null
  confidence: number | null
  consensus: string | null
}

const matches = ref<Match[]>([])
const predictions = ref<Record<number, BatchPrediction>>({})
const loading = ref(true)
const syncing = ref(false)
const selectMode = ref(false)
const selectedIds = ref<number[]>([])

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
    return { label: formatDateLabel(d, offset), value: localDate(offset) }
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

// ── 选场模式 ─────────────────────────────────────────────────────
function toggleSelectMode() {
  selectMode.value = !selectMode.value
  if (!selectMode.value) selectedIds.value = []
}

function handleCardClick(m: Match) {
  if (selectMode.value) {
    toggleSelect(m.id)
  } else {
    router.push(`/matches/${m.id}`)
  }
}

function toggleSelect(id: number) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

function isSelected(id: number) {
  return selectedIds.value.includes(id)
}

function selectAll() {
  selectedIds.value = matches.value.map(m => m.id)
}

function clearAll() {
  selectedIds.value = []
}

function goGenerate() {
  const ids = selectedIds.value.join(',')
  router.push(`/tickets?ids=${ids}`)
  selectMode.value = false
  selectedIds.value = []
}

// ── Data ─────────────────────────────────────────────────────────
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

function handicapStr(m: Match) {
  const h = m.sporttery_odds?.hhad?.handicap
  if (h == null) return '0'
  return (h > 0 ? '+' : '') + h
}

onMounted(() => {
  if (route.query.selectMode === 'true') {
    selectMode.value = true
  }
  load()
})
</script>

<template>
  <div class="view">
    <!-- Date strip -->
    <div class="date-strip">
      <button
        v-for="d in dates"
        :key="d.value"
        class="date-btn"
        :class="{ on: d.value === selectedDate }"
        @click="selectedDate = d.value; load()"
      >{{ d.label }}</button>
      <div class="strip-actions">
        <button class="btn btn-ghost btn-sm" :disabled="syncing" @click="syncMatches" v-if="!selectMode">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 8A6 6 0 0 1 2.5 12M2 8a6 6 0 0 1 11.5-4M2 4v4h4M14 12v-4h-4"/>
          </svg>
          <span v-if="syncing">同步中…</span>
          <span v-else>同步</span>
        </button>
        <button
          class="select-mode-btn"
          :class="{ 'select-mode-btn--active': selectMode }"
          @click="toggleSelectMode"
          v-if="matches.length > 0"
        >
          <svg v-if="!selectMode" width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <rect x="2" y="2" width="5" height="5" rx="1"/>
            <path d="M9 4h5M9 8h5M2 12h12"/>
          </svg>
          <svg v-else width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M3 8l3.5 3.5L13 5" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          {{ selectMode ? '完成' : '选场' }}
        </button>
      </div>
    </div>

    <!-- Inline stats / select mode bar -->
    <Transition name="mode-swap">
      <div v-if="selectMode" class="mode-bar">
        <span class="mode-bar-text">
          已选 <strong class="font-num">{{ selectedIds.length }}</strong> 场
        </span>
        <div class="mode-bar-actions">
          <button class="mode-link" @click="selectAll">全选</button>
          <span class="mode-dot">·</span>
          <button class="mode-link" @click="clearAll">全不选</button>
        </div>
      </div>
      <div v-else class="stats-bar">
        <span class="stats-bar-item">
          <span class="stats-num text-primary font-num">{{ todayStats.total }}</span>
          <span class="stats-unit">场赛事</span>
        </span>
        <span class="stats-sep">·</span>
        <span class="stats-bar-item">
          <span class="stats-num text-green font-num">{{ todayStats.analyzed }}</span>
          <span class="stats-unit">已分析</span>
        </span>
        <span v-if="todayStats.analyzed === 0 && todayStats.total > 0" class="stats-hint">点赛事卡可触发分析</span>
      </div>
    </Transition>

    <!-- Loading -->
    <div v-if="loading" class="fixture-list">
      <div v-for="i in 4" :key="i" class="skeleton" style="height:90px" />
    </div>

    <!-- Empty -->
    <div v-else-if="!matches.length" class="empty-tip">
      <p class="empty-title">暂无赛事</p>
      <p class="text-sm text-muted mt-2">点击同步按钮拉取今日赛单</p>
    </div>

    <!-- Match list — B-style newspaper fixture rows -->
    <div v-else class="fixture-list" :class="{ 'fixture-list--select': selectMode }">
      <div
        v-for="m in matches"
        :key="m.id"
        class="fixture cursor-pointer"
        :class="{
          'fixture--selected': selectMode && isSelected(m.id),
          'fixture--accent': !!predictions[m.id]
        }"
        @click="handleCardClick(m)"
      >
        <!-- Selection zone (absolute) -->
        <Transition name="chk-fade">
          <div v-if="selectMode" class="sel-zone" @click.stop="toggleSelect(m.id)">
            <span class="sel-chk" :class="{ 'sel-chk--on': isSelected(m.id) }">
              <svg v-if="isSelected(m.id)" width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path d="M2 5l2.5 2.5L8 3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </span>
          </div>
        </Transition>

        <!-- Left: info column -->
        <div class="fx-left" :style="selectMode ? 'padding-left:44px' : ''">
          <div class="fx-meta">
            <span v-if="m.match_no" class="fx-no font-num">{{ m.match_no }}</span>
            <span class="fx-lg">{{ m.league }}</span>
            <span v-if="predictions[m.id]" class="badge" :class="confidenceBadge(predictions[m.id].confidence)">
              {{ confidenceLabel(predictions[m.id].confidence) }}
            </span>
          </div>
          <div class="fx-teams">
            <div class="fx-team">
              <span class="fx-dot fx-dot--h"></span>
              <span class="fx-name">{{ m.home_team }}</span>
              <span class="fx-tag">主</span>
            </div>
            <div class="fx-team">
              <span class="fx-dot fx-dot--a"></span>
              <span class="fx-name">{{ m.away_team }}</span>
              <span class="fx-tag">客</span>
            </div>
          </div>
          <div class="fx-footer">
            <span class="fx-time font-num">{{ formatTime(m.kickoff_at) }}</span>
            <span v-if="predictions[m.id]?.consensus" class="fx-consensus">
              AI · {{ predictions[m.id].consensus }}
            </span>
          </div>
        </div>

        <!-- Odds: HAD + HHAD merged into unified rows -->
        <div class="fx-odds-wrap">
          <template v-if="homeOdds(m)">
            <div v-if="m.sporttery_odds?.hhad" class="fx-hhad-pill font-num">让{{ handicapStr(m) }}</div>
            <div class="fx-or">
              <span class="fx-dsq fx-dsq--w"></span>
              <span class="fx-onum fx-onum--w font-num">{{ homeOdds(m)!.toFixed(2) }}</span>
              <template v-if="m.sporttery_odds?.hhad">
                <span class="fx-vsep"></span>
                <span class="fx-onum fx-onum--w font-num">{{ m.sporttery_odds.hhad.home.toFixed(2) }}</span>
              </template>
            </div>
            <div class="fx-or">
              <span class="fx-dsq fx-dsq--d"></span>
              <span class="fx-onum fx-onum--d font-num">{{ drawOdds(m)!.toFixed(2) }}</span>
              <template v-if="m.sporttery_odds?.hhad">
                <span class="fx-vsep"></span>
                <span class="fx-onum fx-onum--d font-num">{{ m.sporttery_odds.hhad.draw.toFixed(2) }}</span>
              </template>
            </div>
            <div class="fx-or">
              <span class="fx-dsq fx-dsq--l"></span>
              <span class="fx-onum fx-onum--l font-num">{{ awayOdds(m)!.toFixed(2) }}</span>
              <template v-if="m.sporttery_odds?.hhad">
                <span class="fx-vsep"></span>
                <span class="fx-onum fx-onum--l font-num">{{ m.sporttery_odds.hhad.away.toFixed(2) }}</span>
              </template>
            </div>
          </template>
          <span v-else class="fx-na-text">赔率<br>待更新</span>
        </div>
      </div>
    </div>

    <!-- Floating generate bar -->
    <Transition name="float-bar">
      <div v-if="selectMode && selectedIds.length > 0" class="gen-float-bar">
        <div class="gen-float-info">
          <span class="gen-float-count font-num">{{ selectedIds.length }}</span>
          <span class="gen-float-label">场已选</span>
        </div>
        <button class="gen-float-btn" @click="goGenerate">
          <svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M10 2l1.8 5.2 5.2 1.8-5.2 1.8L10 16.5l-1.8-5.2-5.2-1.8 5.2-1.8Z"/>
          </svg>
          生成方案
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; min-height: 100%; }

/* ── Date strip ────────────────────────────────────────────── */
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
.date-btn.on { background: var(--primary); color: #fff; border-color: var(--primary); }

.strip-actions { display: flex; align-items: center; gap: 6px; margin-left: auto; flex-shrink: 0; }

.select-mode-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
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
.select-mode-btn--active {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}

/* ── Stats / Mode bar ──────────────────────────────────────── */
.stats-bar, .mode-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 16px 8px;
  border-bottom: var(--card-bd);
  flex-shrink: 0;
  min-height: 34px;
}
.stats-bar-item { display: flex; align-items: baseline; gap: 3px; }
.stats-num { font-size: 16px; font-weight: 700; line-height: 1; }
.stats-unit { font-size: 11px; color: var(--text3); }
.stats-sep { font-size: 12px; color: var(--line); }
.stats-hint { font-size: 11px; color: var(--text3); margin-left: 4px; }

.mode-bar { background: color-mix(in srgb, var(--primary) 6%, var(--bg)); }
.mode-bar-text { font-size: 12px; color: var(--text2); }
.mode-bar-text strong { color: var(--primary); font-size: 14px; }
.mode-bar-actions { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.mode-link {
  font-size: 12px;
  color: var(--primary);
  background: transparent;
  cursor: pointer;
  font-family: var(--font);
}
.mode-dot { font-size: 10px; color: var(--line); }

/* ── Fixture list (B-style newspaper rows) ─────────────────── */
.fixture-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding-bottom: 16px;
}
.fixture-list--select { padding-bottom: calc(70px + env(safe-area-inset-bottom, 0px) + 56px); }
@media (min-width: 768px) {
  .fixture-list--select { padding-bottom: calc(70px + env(safe-area-inset-bottom, 0px)); }
}

.empty-tip {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}

/* Fixture card — row: fx-left + fx-odds-wrap side by side */
.fixture {
  position: relative;
  display: flex;
  align-items: stretch;
  min-height: 88px;
  background: var(--card);
  border-bottom: 1px solid var(--line);
  border-left: 3px solid transparent;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
  transition: border-left-color 120ms ease-out, background 120ms ease-out;
}
.fixture--accent { border-left-color: var(--primary); }
.fixture--selected {
  border-left-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 5%, var(--card));
}
.fixture:active { background: color-mix(in srgb, var(--primary) 4%, var(--card)); }

/* Selection zone */
.sel-zone {
  position: absolute;
  top: 0; left: 0; bottom: 0;
  width: 44px;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 14px;
  z-index: 2;
  cursor: pointer;
}
.sel-chk {
  width: 18px; height: 18px;
  border-radius: 50%;
  border: 1.5px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 100ms ease-out;
  color: #fff;
  flex-shrink: 0;
}
.sel-chk--on { background: var(--primary); border-color: var(--primary); }

/* Left info column */
.fx-left {
  flex: 1;
  padding: 10px 12px 10px 14px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-width: 0;
}
.fx-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 5px;
}
.fx-no {
  font-family: var(--font-disp);
  font-size: 18px;
  font-weight: 800;
  color: var(--primary);
  line-height: 1;
  letter-spacing: -.3px;
}
.fx-lg {
  font-family: var(--font-disp);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--text3);
}
.fx-teams { display: flex; flex-direction: column; gap: 3px; }
.fx-team { display: flex; align-items: center; gap: 5px; }
.fx-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}
.fx-dot--h { background: var(--primary); }
.fx-dot--a { background: var(--blue, #1D4ED8); }
.fx-name {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fx-tag { font-size: 9px; color: var(--text3); flex-shrink: 0; }
.fx-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}
.fx-time {
  font-family: var(--font-disp);
  font-size: 11px;
  color: var(--text3);
  letter-spacing: .3px;
}
.fx-consensus {
  font-size: 10px;
  color: var(--text2);
  background: var(--primary-d);
  border-left: 2px solid var(--primary);
  padding: 1px 6px;
  border-radius: 0 3px 3px 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 160px;
}

/* Odds — unified column: HAD + HHAD in same rows */
.fx-odds-wrap {
  border-left: 1px solid var(--line);
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 8px 12px 8px 10px;
  gap: 4px;
}
.fx-hhad-pill {
  font-family: var(--font-disp);
  font-size: 10px;
  font-weight: 700;
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  border-radius: 2px;
  padding: 1px 5px;
  align-self: flex-end;
  margin-bottom: 1px;
}
.fx-or { display: flex; align-items: center; gap: 5px; }
/* Fixed-width HAD num so HHAD column aligns */
.fx-or .fx-onum { width: 40px; text-align: right; }
.fx-vsep {
  width: 1px;
  height: 13px;
  background: var(--line);
  flex-shrink: 0;
  margin: 0 1px;
}
.fx-na-text {
  font-size: 10px;
  color: var(--text3);
  text-align: center;
  line-height: 1.5;
  padding: 0 8px;
}
.fx-dsq {
  width: 7px; height: 7px;
  border-radius: 1px;
  flex-shrink: 0;
}
.fx-dsq--w { background: var(--win-c); }
.fx-dsq--d { background: var(--draw-c); }
.fx-dsq--l { background: var(--lose-c, #555); }
.fx-olabel { font-size: 10px; color: var(--text3); flex-shrink: 0; width: 22px; }
.fx-onum {
  font-family: var(--font-disp);
  font-size: 19px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -.3px;
}
.fx-onum--w { color: var(--win-c); }
.fx-onum--d { color: var(--draw-c); }
.fx-onum--l { color: var(--lose-c, #555); }


/* ── Floating generate bar ─────────────────────────────────── */
.gen-float-bar {
  position: fixed;
  bottom: calc(56px + env(safe-area-inset-bottom, 0px));
  left: 0; right: 0;
  background: var(--card);
  border-top: 1.5px solid var(--primary);
  padding: 10px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  z-index: 200;
  gap: 12px;
  will-change: transform;
  box-shadow: 0 -4px 20px rgba(0,0,0,.08);
}
@media (min-width: 768px) {
  .gen-float-bar { bottom: 0; }
}

.gen-float-info { display: flex; align-items: baseline; gap: 4px; }
.gen-float-count { font-size: 20px; font-weight: 700; color: var(--primary); line-height: 1; font-variant-numeric: tabular-nums; }
.gen-float-label { font-size: 12px; color: var(--text2); }

.gen-float-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 22px;
  background: var(--primary);
  color: #fff;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 700;
  font-family: var(--font-disp);
  cursor: pointer;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
  transition: opacity .1s, transform .08s;
  box-shadow: var(--fab-sh);
  letter-spacing: .3px;
}
.gen-float-btn:active { opacity: .85; transform: scale(0.96); }

/* ── Transitions ────────────────────────────────────────────── */
.mode-swap-enter-active, .mode-swap-leave-active { transition: opacity .15s ease; }
.mode-swap-enter-from, .mode-swap-leave-to { opacity: 0; }

.chk-fade-enter-active, .chk-fade-leave-active { transition: opacity .1s ease, transform .1s ease; }
.chk-fade-enter-from, .chk-fade-leave-to { opacity: 0; transform: scale(0.7); }

.float-bar-enter-active, .float-bar-leave-active { transition: transform .12s ease-out, opacity .12s ease-out; }
.float-bar-enter-from, .float-bar-leave-to { transform: translateY(100%); opacity: 0; }
</style>
