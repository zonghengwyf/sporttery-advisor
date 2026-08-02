<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api, { betsApi } from '@/api'
import { useBettingStore } from '@/stores/betting'
import AnalysisModeSheet from '@/components/AnalysisModeSheet.vue'
import { useAnalysisPreference, type AnalysisMode } from '@/composables/useAnalysisPreference'
import { useTicketTask } from '@/composables/useTicketTask'
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetFooter,
} from '@/components/ui/sheet'

const router = useRouter()
const route = useRoute()
const bettingStore = useBettingStore()
const { setPreference } = useAnalysisPreference()
const ticketTask = useTicketTask()

// ── Types ────────────────────────────────────────────────────
interface Leg {
  match_id?: number
  match_no?: string | null
  match_code?: string           // 竞彩场次编号（如 "026001"）
  home_team: string
  away_team: string
  league: string
  kickoff?: string              // "20:00"
  market?: string               // "胜平负" | "让球胜平负"
  handicap?: number             // 让球数，正=主让，负=受让
  handicap_label?: string       // 格式化让球字符串，如 "+0.5" / "-1"
  pick: string
  pick_code?: string            // 投注代码 "3"/"1"/"0"（主选）
  picks?: string[]              // 全部选项，如 ["主胜","平"]（多选时）
  pick_codes?: string[]         // 对应投注代码列表
  picks_odds?: number[]         // 每个选项的赔率
  num_picks?: number            // 本腿选了几个结果
  odds?: number
  odds_estimated?: boolean
  confidence?: number
  model_votes?: { agree: number; total: number; models?: string[] }
  rationale?: string
}
interface Scheme {
  legs: Leg[]
  total_odds?: number
  stake?: number
  num_combos?: number
  risk_label?: string
  rationale?: string
  parlay_type?: string
  win_probability?: number
  theoretical_prize?: number
}
interface Schemes {
  conservative?: Scheme
  balanced?: Scheme
  high_odds?: Scheme
  scoreline?: Scheme
}

// ── State ────────────────────────────────────────────────────
const totalMatchCount = ref(0)
const generating = ref(false)

// Analysis freshness
const analysisLatestAt = ref<string | null>(null)
const modelCount = ref(1)
const sheetVisible = ref(false)
const pendingMatchIds = ref<number[]>([])
const currentMatchName = ref('')

const schemes = ref<Schemes | null>(null)
const activeTab = ref<'conservative' | 'balanced' | 'high_odds' | 'scoreline'>('conservative')
const error = ref<string | null>(null)
const progressIndex = ref(0)
const progressMsg = ref('')
const elapsedSecs = ref(0)
const lastMatchIds = ref<number[]>([])
const completedSteps = ref(0)
const stepLogExpanded = ref(false)
const stepLog = ref<string[]>([])
const localMultiplier = ref(1)
let _elapsedTimer: ReturnType<typeof setInterval> | null = null
let _pollTimer: ReturnType<typeof setInterval> | null = null
let _lastEventIndex = 0

const TABS = [
  { key: 'conservative' as const, label: '稳健', risk: '低风险' },
  { key: 'balanced'     as const, label: '均衡', risk: '中风险' },
  { key: 'high_odds'    as const, label: '博高赔', risk: '高风险' },
  { key: 'scoreline'    as const, label: '比分', risk: '极高' },
]

const STEPS = [
  { key: 'check',  label: '检查已有分析' },
  { key: 'ai',     label: 'AI 情报分析' },
  { key: 'model',  label: '概率建模' },
  { key: 'ticket', label: '票型生成' },
]

// ── Derived ──────────────────────────────────────────────────
const activeScheme  = computed(() => schemes.value?.[activeTab.value] ?? null)
const activeTabInfo = computed(() => TABS.find(t => t.key === activeTab.value) ?? TABS[0])
const hasSchemes    = computed(() => schemes.value && TABS.some(t => schemes.value![t.key]?.legs?.length))
const hasEstimatedOdds = computed(() => {
  if (!schemes.value) return false
  for (const t of TABS) {
    const legs = schemes.value[t.key]?.legs ?? []
    if (legs.some((l: Leg) => l.odds_estimated)) return true
  }
  return false
})

// Sync localMultiplier when active scheme changes
watch(activeScheme, (scheme) => {
  if (scheme?.stake != null) localMultiplier.value = Math.max(1, Math.round(scheme.stake / 2))
}, { immediate: true })

const localStake = computed(() => Math.max(1, Math.round(localMultiplier.value)) * 2)
const dynamicPrize = computed(() =>
  Math.round(localStake.value * (activeScheme.value?.total_odds ?? 1))
)

function pickColorClass(pick: string) {
  if (/主胜/.test(pick) || pick === '3') return 'tag-win'
  if (/^平/.test(pick)  || pick === '1') return 'tag-draw'
  if (/客胜/.test(pick) || pick === '0') return 'tag-lose'
  return 'tag-neutral'
}

function pickLabel(pick: string) {
  if (/主胜/.test(pick) || pick === '3') return '主胜'
  if (/^平/.test(pick)  || pick === '1') return '平'
  if (/客胜/.test(pick) || pick === '0') return '客胜'
  return pick
}

// ── Analysis freshness helpers ────────────────────────────────
async function fetchAnalysisStatus(matchIds?: number[]) {
  try {
    const params: Record<string, string> = {}
    if (matchIds?.length) params.match_ids = matchIds.join(',')
    const { data } = await api.get('/predictions/analysis-status', { params })
    analysisLatestAt.value = data.latest_at ?? null
  } catch {
    // silent — freshness is non-critical
  }
}

async function fetchModelCount() {
  try {
    const { data } = await api.get('/settings/llm')
    modelCount.value = Array.isArray(data) ? Math.max(1, data.length) : 1
  } catch { /* silent */ }
}

// ── Task-based generation with polling ───────────────────────

function _resetProgressState() {
  error.value = null
  schemes.value = null
  progressIndex.value = 0
  progressMsg.value = '准备中…'
  currentMatchName.value = ''
  elapsedSecs.value = 0
  completedSteps.value = 0
  stepLogExpanded.value = false
  stepLog.value = new Array(STEPS.length).fill('')
  _lastEventIndex = 0
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null }
  if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null }
  generating.value = false
  currentMatchName.value = ''
  ticketTask.clear()
  fetchAnalysisStatus(lastMatchIds.value)
}

async function _poll(taskId: string) {
  try {
    const { data } = await api.get(`/tickets/task/${taskId}`)
    const newEvents = (data.events as any[]).slice(_lastEventIndex)
    _lastEventIndex = (data.events as any[]).length

    for (const ev of newEvents) {
      if (ev.event === 'step') {
        const idx = ev.index ?? 0
        progressIndex.value = idx
        progressMsg.value = ev.msg ?? ''
        if (ev.match_name) currentMatchName.value = ev.match_name
        if (ev.msg) stepLog.value[idx] = ev.msg
      } else if (ev.event === 'done') {
        // result is in data.result (written to Redis separately)
        if (data.result) {
          schemes.value = data.result
          for (const t of TABS) {
            if (data.result?.[t.key]?.legs?.length) { activeTab.value = t.key; break }
          }
          completedSteps.value = STEPS.length
          if (ev.summary) stepLog.value[STEPS.length - 1] = ev.summary
          bettingStore.save(data.result, activeTab.value, lastMatchIds.value)
          stopPolling()
          return
        }
        // result not yet written — wait one more tick
      } else if (ev.event === 'error') {
        completedSteps.value = progressIndex.value
        if (ev.msg) stepLog.value[progressIndex.value] = `失败: ${ev.msg}`
        error.value = ev.msg ?? '未知错误'
        stopPolling()
        return
      }
    }

    // Safety: done event was consumed in a previous tick but result arrived late
    if (!schemes.value && data.result) {
      schemes.value = data.result
      for (const t of TABS) {
        if (data.result?.[t.key]?.legs?.length) { activeTab.value = t.key; break }
      }
      completedSteps.value = STEPS.length
      bettingStore.save(data.result, activeTab.value, lastMatchIds.value)
      stopPolling()
      return
    }

    // Safety: status=done but result never arrived (Redis write failure)
    if (data.status === 'done' && !data.result && !schemes.value) {
      error.value = '方案数据写入失败，请重新生成'
      stopPolling()
      return
    }

    // Safety: status error with no error event yet
    if (data.status === 'error' && !error.value && newEvents.length === 0) {
      error.value = '任务执行失败，请稍后重试'
      stopPolling()
    }
  } catch (e: any) {
    if (e.response?.status === 404) {
      error.value = '分析任务已过期（24h），请重新生成'
      stopPolling()
    }
    // transient network errors: continue polling
  }
}

function startPolling(taskId: string) {
  generating.value = true
  if (!_elapsedTimer) {
    _elapsedTimer = setInterval(() => { elapsedSecs.value++ }, 1000)
  }
  // immediate first poll, then every 2s
  _poll(taskId)
  _pollTimer = setInterval(() => _poll(taskId), 2000)
}

async function generate(matchIds: number[], force = false, analyzeAll = false) {
  if (!matchIds.length || generating.value) return
  lastMatchIds.value = matchIds
  generating.value = true
  _resetProgressState()

  try {
    const { data } = await api.post('/tickets/task', {
      match_ids: matchIds,
      force,
      analyze_all: analyzeAll,
      multiplier: localMultiplier.value,
    })
    ticketTask.save(data.task_id, matchIds)
    startPolling(data.task_id)
  } catch (e: any) {
    generating.value = false
    if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null }
    if (e.response?.status === 401) {
      localStorage.removeItem('token')
      window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`
      return
    }
    error.value = e.response?.data?.detail ?? e.message ?? '生成失败，请检查 LLM 配置后重试'
  }
}

async function generateAll() {
  try {
    const { data } = await api.get('/matches/', { params: { sale_date: 'all' } })
    const ids = (data as { id: number }[]).map(m => m.id)
    pendingMatchIds.value = ids
    // Refresh latest_at for these matches before showing sheet
    await fetchAnalysisStatus(ids)
    sheetVisible.value = true
  } catch {
    error.value = '加载赛事失败，请稍后重试'
  }
}

async function onSheetSelect(mode: AnalysisMode) {
  sheetVisible.value = false
  setPreference(mode)
  const ids = pendingMatchIds.value
  if (!ids.length) return
  if (mode === 'cache') {
    await generate(ids, false, true)
  } else {
    await generate(ids, true, true)
  }
}

function retry() {
  if (lastMatchIds.value.length) {
    generate(lastMatchIds.value)
  } else {
    generateAll()
  }
}

function goCustomSelect() {
  router.push('/analysis?selectMode=true')
}

function resetSchemes() {
  schemes.value = null
  error.value = null
  completedSteps.value = 0
  bettingStore.clear()
}

// ── 标记投注 sheet ────────────────────────────────────────────────
interface BetSheet {
  visible: boolean
  planId: string
  stake: number
  submitting: boolean
  done: boolean
  error: string | null
}
const betSheet = ref<BetSheet>({ visible: false, planId: '', stake: 20, submitting: false, done: false, error: null })
let betSheetTimer: ReturnType<typeof setTimeout> | null = null

function openBetSheet(planId: string) {
  if (betSheetTimer) { clearTimeout(betSheetTimer); betSheetTimer = null }
  const scheme = schemes.value?.[planId as keyof typeof schemes.value] as { stake?: number } | undefined
  betSheet.value = {
    visible: true,
    planId,
    stake: scheme?.stake ?? 20,
    submitting: false,
    done: false,
    error: null,
  }
}
function closeBetSheet() {
  if (betSheetTimer) { clearTimeout(betSheetTimer); betSheetTimer = null }
  betSheet.value.visible = false
}

async function confirmBet() {
  const sheet = betSheet.value
  if (sheet.submitting) return
  const scheme = schemes.value?.[sheet.planId as keyof typeof schemes.value] as { legs?: any[]; total_odds?: number } | undefined
  if (!scheme?.legs?.length) return

  const legs = scheme.legs.map((leg: any) => ({
    match_id: leg.match_id ?? 0,
    home_team: leg.home_team,
    away_team: leg.away_team,
    pick: leg.pick,
    pick_code: leg.pick_code ?? '',
    odds: leg.odds ?? 1,
  }))

  sheet.submitting = true
  sheet.error = null
  try {
    await betsApi.create({
      plan_id: sheet.planId,
      legs,
      stake: sheet.stake,
      expected_payout: Math.round(sheet.stake * (scheme.total_odds ?? 1) * 100) / 100,
    })
    sheet.done = true
    betSheetTimer = setTimeout(() => { sheet.visible = false; betSheetTimer = null }, 1400)
  } catch (e: any) {
    sheet.error = e.response?.data?.detail ?? '提交失败，请稍后重试'
  } finally {
    sheet.submitting = false
  }
}

onMounted(async () => {
  try {
    const { data } = await api.get('/matches/', { params: { sale_date: 'all' } })
    totalMatchCount.value = (data as unknown[]).length
  } catch { /* silent */ }

  // Non-critical parallel fetches
  fetchAnalysisStatus()
  fetchModelCount()

  // Recover in-progress task from previous session (navigation away / refresh)
  const saved = ticketTask.getSaved()
  if (saved) {
    lastMatchIds.value = saved.matchIds
    _resetProgressState()
    progressMsg.value = '恢复中…'
    startPolling(saved.taskId)
    return
  }

  const idsQuery = route.query.ids as string | undefined
  if (idsQuery) {
    const ids = idsQuery.split(',').map(Number).filter(Boolean)
    if (ids.length) await generate(ids)
  } else if (bettingStore.schemes) {
    schemes.value = bettingStore.schemes
    activeTab.value = bettingStore.activeTab
    lastMatchIds.value = bettingStore.lastMatchIds
  }
})

onUnmounted(() => {
  // Stop polling loop on navigation — keep localStorage so we can recover on return
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null }
  if (_elapsedTimer) { clearInterval(_elapsedTimer); _elapsedTimer = null }
})
</script>

<template>
  <div class="view">

    <!-- ── Empty state ──────────────────────────────────────── -->
    <div v-if="!hasSchemes && !generating" class="empty-wrap">
      <div class="empty-icon-wrap">
        <div class="te-dot-grid">
          <span class="te-dot"></span>
          <span class="te-dot te-dot--hi"></span>
          <span class="te-dot"></span>
          <span class="te-dot te-dot--hi"></span>
          <span class="te-dot te-dot--hi"></span>
          <span class="te-dot te-dot--hi"></span>
          <span class="te-dot"></span>
          <span class="te-dot te-dot--hi"></span>
          <span class="te-dot"></span>
        </div>
      </div>

      <div class="empty-title">AI 投注方案</div>
      <div class="empty-sub">
        <strong>{{ totalMatchCount > 0 ? `${totalMatchCount} 场赛事` : '全部赛事' }}</strong>
        可选 · AI 三模型筛选
      </div>

      <!-- Scheme type preview pills -->
      <div class="scheme-preview-row">
        <span class="scheme-pill scheme-pill--safe">稳健 <span class="pill-risk">低风险</span></span>
        <span class="scheme-pill scheme-pill--bal">均衡 <span class="pill-risk">中风险</span></span>
        <span class="scheme-pill scheme-pill--hi">博高赔 <span class="pill-risk">高风险</span></span>
        <span class="scheme-pill scheme-pill--sc">比分 <span class="pill-risk">极高</span></span>
      </div>

      <button class="gen-all-btn" @click="generateAll">
        <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10 2l1.8 5.2 5.2 1.8-5.2 1.8L10 16.5l-1.8-5.2-5.2-1.8 5.2-1.8Z"/>
        </svg>
        一键生成方案
      </button>
      <div class="analysis-ts" v-if="analysisLatestAt">
        <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
          <circle cx="8" cy="8" r="6.5"/>
          <path d="M8 4.5V8l2.5 2"/>
        </svg>
        最早分析于 {{ new Date(analysisLatestAt).toLocaleTimeString('zh-CN', { hour:'2-digit', minute:'2-digit' }) }}
      </div>

      <button class="custom-select-btn" @click="goCustomSelect">
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <rect x="2" y="2" width="5" height="5" rx="1"/>
          <path d="M9 4h5M9 8h5M2 12h12"/>
        </svg>
        自定义选场
      </button>

      <!-- Error shown beneath buttons when in empty state -->
      <Transition name="fade">
        <div v-if="error" class="empty-error-block">
          <div class="empty-error-icon">
            <svg width="14" height="14" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M10 3L18 17H2L10 3z"/>
              <path d="M10 9v4M10 14.5h.01" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="empty-error-msg">{{ error }}</div>
          <button class="empty-retry-btn" @click="retry">重试</button>
        </div>
      </Transition>
    </div>

    <!-- ── Generating (SSE real-time) ────────────────────────── -->
    <div v-if="generating" class="gen-loading">
      <div class="gen-loading-inner">
        <div class="spin-ring" />
        <div class="gen-loading-text">
          <div class="gen-loading-title">正在生成方案…</div>
          <div class="gen-loading-sub">
        {{ currentMatchName ? `分析中：${currentMatchName}` : (progressMsg || '统计建模 · 情报融合 · 多模型投票') }}
      </div>
        </div>
        <div class="gen-loading-right">
          <div class="gen-elapsed font-num">{{ elapsedSecs }}s</div>
          <button class="gen-stop-btn" type="button" @click="stopPolling" title="停止生成">
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor" aria-hidden="true">
              <rect x="3" y="3" width="8" height="8" rx="1.5"/>
            </svg>
            停止
          </button>
        </div>
      </div>
      <div class="gen-loading-steps">
        <div
          v-for="(s, i) in STEPS"
          :key="s.key"
          class="step-item"
          :class="{
            'step-done':    i < progressIndex,
            'step-active':  i === progressIndex,
            'step-pending': i > progressIndex,
          }"
        >
          <!-- Done: checkmark -->
          <svg v-if="i < progressIndex" class="step-icon step-icon--done" width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="2,6 5,9 10,3"/>
          </svg>
          <!-- Active: pulsing dot -->
          <span v-else-if="i === progressIndex" class="step-dot step-dot--spin" />
          <!-- Pending: empty dot -->
          <span v-else class="step-dot" />
          <span class="step-label">{{ s.label }}</span>
          <span v-if="i === progressIndex && progressMsg" class="step-detail">{{ progressMsg }}</span>
        </div>
      </div>
    </div>

    <!-- ── Scheme results ──────────────────────────────────────── -->
    <div v-if="hasSchemes && !generating" class="results-wrap">

      <!-- Estimated odds notice -->
      <div v-if="hasEstimatedOdds" class="est-odds-notice">
        <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
          <circle cx="8" cy="8" r="6.5"/>
          <path d="M8 5v3.5M8 10.5h.01"/>
        </svg>
        部分赔率为模型预估（标注"预估"），官方赔率尚未开售，购彩前请在竞彩官网确认
      </div>

      <!-- Results header -->
      <div class="results-head">
        <div class="results-head-left">
          <div class="results-title">AI 投注方案</div>
          <div class="results-sub">调整注额可实时重算彩金</div>
        </div>
        <div class="results-head-right">
          <button
            v-if="completedSteps > 0"
            class="log-icon-btn"
            :class="{ active: stepLogExpanded }"
            :title="`生成日志 ${completedSteps}/${STEPS.length} 步`"
            @click="stepLogExpanded = !stepLogExpanded"
          >
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M2 4h12M2 8h8M2 12h5"/>
            </svg>
            <span>日志</span>
          </button>
          <button class="reselect-btn" @click="generate(lastMatchIds, true)">
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M14 8A6 6 0 0 1 2.5 12M2 8a6 6 0 0 1 11.5-4M2 4v4h4M14 12v-4h-4"/>
            </svg>
            重新生成
          </button>
        </div>
      </div>

      <!-- Step log dropdown -->
      <div v-if="completedSteps > 0 && stepLogExpanded" class="step-log-dropdown">
        <div
          v-for="(s, i) in STEPS"
          :key="s.key"
          class="step-log-item"
          :class="i < completedSteps ? 'step-log-done' : 'step-log-skip'"
        >
          <svg v-if="i < completedSteps" class="step-icon--done" width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="2,6 5,9 10,3"/>
          </svg>
          <span v-else class="step-dot" />
          <span class="step-log-name">{{ s.label }}</span>
          <span v-if="stepLog[i]" class="step-log-detail-text">{{ stepLog[i] }}</span>
        </div>
      </div>

      <!-- Tabs -->
      <div class="scheme-tabs">
        <button
          v-for="t in TABS"
          :key="t.key"
          class="scheme-tab"
          :class="{ 'tab-on': activeTab === t.key, 'tab-disabled': !schemes![t.key]?.legs?.length }"
          :disabled="!schemes![t.key]?.legs?.length"
          @click="activeTab = t.key"
        >
          <span class="tab-label">{{ t.label }}</span>
          <span class="tab-risk">{{ t.risk }}</span>
          <span class="tab-count font-num">
            {{ schemes![t.key]?.legs?.length ? `${schemes![t.key]!.legs.length}串1` : '—' }}
          </span>
        </button>
      </div>

      <!-- Active scheme -->
      <div v-if="activeScheme" class="scheme-card">

        <!-- Card header -->
        <div class="scheme-card-head">
          <div class="scheme-card-head-left">
            <span class="scheme-name">{{ activeTabInfo.label }}方案</span>
            <span class="scheme-parlay font-num">
              {{ activeScheme.parlay_type || `${activeScheme.legs?.length}串1` }}
            </span>
            <span v-if="activeScheme.num_combos && activeScheme.num_combos > 1" class="scheme-combos font-num">
              共{{ activeScheme.num_combos }}注
            </span>
          </div>
          <span class="risk-badge" :class="activeTab">{{ activeScheme.risk_label || activeTabInfo.risk }}</span>
        </div>

        <!-- Legend -->
        <div class="leg-legend">
          <span class="legend-no">编号</span>
          <span class="legend-match">对阵</span>
          <span class="legend-pick">投注</span>
          <span class="legend-odds">赔率</span>
        </div>

        <!-- Legs -->
        <div class="scheme-legs">
          <div v-for="(leg, i) in activeScheme.legs" :key="i" class="scheme-leg">
            <div class="leg-no-col">
              <div class="leg-match-no font-num">{{ leg.match_code ? leg.match_code.slice(-3) : String(i+1).padStart(2,'0') }}</div>
              <div v-if="leg.kickoff" class="leg-kickoff font-num">{{ leg.kickoff }}</div>
            </div>
            <div class="leg-info">
              <div class="leg-teams">
                <div class="leg-team-row">
                  <span class="leg-dot leg-dot--h"></span>
                  <span class="leg-team-name">{{ leg.home_team }}</span>
                </div>
                <div class="leg-team-row">
                  <span class="leg-dot leg-dot--a"></span>
                  <span class="leg-team-name">{{ leg.away_team }}</span>
                </div>
              </div>
              <div class="leg-meta">
                <span class="leg-league">{{ leg.league }}</span>
                <span v-if="leg.model_votes?.total" class="leg-votes font-num">
                  {{ leg.model_votes.agree }}/{{ leg.model_votes.total }}共识
                </span>
                <span v-else-if="leg.confidence" class="leg-conf font-num">{{ leg.confidence }}%</span>
              </div>
              <div v-if="leg.rationale" class="leg-rationale">{{ leg.rationale }}</div>
            </div>
            <div class="leg-pick-col">
              <span v-if="leg.market === '让球胜平负'" class="leg-hhad-badge">让</span>
              <!-- Multi-pick: render each outcome as a separate badge -->
              <template v-if="leg.picks && leg.picks.length > 1">
                <span
                  v-for="(p, pi) in leg.picks"
                  :key="pi"
                  class="leg-pick"
                  :class="pickColorClass(p)"
                >{{ pickLabel(p) }}</span>
                <span class="leg-pick-code font-num">{{ leg.pick_codes?.join('/') }}</span>
              </template>
              <!-- Single pick -->
              <template v-else>
                <span class="leg-pick" :class="pickColorClass(leg.pick)">{{ pickLabel(leg.pick) }}</span>
                <span v-if="leg.pick_code" class="leg-pick-code font-num">{{ leg.pick_code }}</span>
              </template>
              <span v-if="leg.handicap_label" class="leg-handicap font-num">{{ leg.handicap_label }}</span>
            </div>
            <div class="leg-odds-col">
              <span v-if="leg.odds" class="leg-odds font-num" :class="{ 'leg-odds--est': leg.odds_estimated }">
                {{ leg.odds.toFixed(2) }}
              </span>
              <span v-if="leg.odds_estimated" class="leg-odds-est-badge">预估</span>
              <span v-else-if="!leg.odds" class="leg-odds text-muted">—</span>
            </div>
          </div>
        </div>

        <!-- Divider -->
        <div class="scheme-divider" />

        <!-- Stats -->
        <div class="scheme-stats">
          <div class="stat-cell">
            <div class="stat-label">倍数</div>
            <div class="stat-stake-wrap">
              <input
                v-model.number="localMultiplier"
                type="number"
                min="1"
                max="500"
                step="1"
                class="stat-stake-input font-num"
              />
              <span class="stat-currency font-num">倍</span>
            </div>
            <div class="stat-stake-hint font-num">= ¥{{ localStake }}</div>
          </div>
          <div class="stat-sep" />
          <div class="stat-cell">
            <div class="stat-label">综合赔率</div>
            <div class="stat-val font-num text-primary">×{{ activeScheme.total_odds?.toFixed(2) ?? '—' }}</div>
          </div>
          <div class="stat-sep" />
          <div class="stat-cell">
            <div class="stat-label">预期彩金</div>
            <div class="stat-val font-num text-green">¥{{ dynamicPrize }}</div>
          </div>
        </div>

        <!-- Win probability bar -->
        <div v-if="activeScheme.win_probability" class="win-prob-bar-wrap">
          <div class="win-prob-label">
            <span>中奖概率</span>
            <span class="font-num text-primary">{{ (activeScheme.win_probability * 100).toFixed(1) }}%</span>
          </div>
          <div class="win-prob-track">
            <div class="win-prob-fill" :style="{ width: `${Math.min(activeScheme.win_probability * 100, 100)}%` }" />
          </div>
        </div>

        <!-- Mark as bet button -->
        <div class="bet-action-row">
          <button class="bet-mark-btn" @click="openBetSheet(activeTab)">
            <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="8" cy="8" r="6.5"/>
              <path d="M5.5 8l2 2 3-3"/>
            </svg>
            标记我已购买此方案
          </button>
        </div>

        <!-- AI rationale -->
        <div v-if="activeScheme.rationale" class="scheme-rationale">
          <div class="rationale-header">
            <span class="chat-avatar chat-avatar--sm">AI</span>
            <span class="rationale-label">方案说明</span>
          </div>
          <p class="rationale-body">{{ activeScheme.rationale }}</p>
        </div>
      </div>

      <!-- Empty tab state -->
      <div v-else class="empty-tip">
        <p class="empty-title" style="font-size:14px">该类型无推荐</p>
        <p class="text-sm text-muted mt-1">切换其他方案类型查看</p>
      </div>
    </div>

  </div>

  <!-- ── Analysis mode sheet ──────────────────────────────────── -->
  <AnalysisModeSheet
    v-model:open="sheetVisible"
    :latest-at="analysisLatestAt"
    :match-count="pendingMatchIds.length || totalMatchCount"
    :model-count="modelCount"
    @select="onSheetSelect"
  />

  <!-- ── 标记投注 Sheet ────────────────────────────────────────── -->
  <Sheet :open="betSheet.visible" @update:open="(v) => { if (!v) closeBetSheet() }">
    <SheetContent side="bottom" class="rounded-t-2xl px-4 pb-8 pt-3 max-w-xl mx-auto">
      <div class="w-9 h-1 rounded-full mx-auto mb-3" style="background:var(--line-dash)" />

      <!-- Success state -->
      <div v-if="betSheet.done" class="sheet-done">
        <svg width="36" height="36" viewBox="0 0 36 36" fill="none" stroke="#22c55e" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="18" cy="18" r="16"/><polyline points="11,18 16,23 25,13"/>
        </svg>
        <p>投注记录已保存</p>
      </div>

      <template v-else>
        <SheetHeader class="mb-4">
          <SheetTitle class="text-[15px] font-semibold text-left" style="color:var(--text)">
            标记投注 · {{ { conservative:'稳健', balanced:'均衡', high_odds:'博高赔', scoreline:'比分' }[betSheet.planId] || betSheet.planId }}方案
          </SheetTitle>
        </SheetHeader>

        <div class="flex flex-col gap-4">
          <p class="text-sm" style="color:var(--text2)">记录您实际购买的注额，AI 将追踪命中情况</p>
          <div>
            <label class="sheet-label">投注金额（元）</label>
            <div class="sheet-stake-row">
              <button class="stake-adj" @click="betSheet.stake = Math.max(2, betSheet.stake - 2)">−</button>
              <input
                v-model.number="betSheet.stake"
                class="stake-input"
                type="number" min="2" max="10000" step="2"
              />
              <button class="stake-adj" @click="betSheet.stake = Math.min(10000, betSheet.stake + 2)">+</button>
            </div>
          </div>
          <div v-if="betSheet.error" class="sheet-error">{{ betSheet.error }}</div>
        </div>

        <SheetFooter class="mt-6 flex-row gap-3">
          <button class="sheet-cancel flex-1" @click="closeBetSheet">取消</button>
          <button class="sheet-confirm flex-1" :disabled="betSheet.submitting" @click="confirmBet">
            <span v-if="betSheet.submitting" class="btn-spin" />
            {{ betSheet.submitting ? '保存中…' : '确认已购买' }}
          </button>
        </SheetFooter>
      </template>
    </SheetContent>
  </Sheet>
</template>

<style scoped>
.view { display: flex; flex-direction: column; min-height: 100%; position: relative; }

/* ── Empty state ────────────────────────────────────────────── */
.empty-wrap {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding: 48px 24px 80px;
  text-align: center;
  gap: 0;
}
.empty-icon-wrap {
  margin-bottom: 20px;
  width: 72px; height: 72px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
}
.te-dot-grid {
  display: grid;
  grid-template-columns: repeat(3, 9px);
  grid-template-rows: repeat(3, 9px);
  gap: 5px;
}
.te-dot {
  width: 9px; height: 9px;
  border-radius: 50%;
  background: color-mix(in srgb, var(--primary) 22%, transparent);
}
.te-dot--hi { background: var(--primary); }
.empty-title {
  font-family: var(--font-disp);
  font-size: 24px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .3px;
  color: var(--text);
  line-height: 1.1;
  margin-bottom: 8px;
}
.empty-sub {
  font-size: 12px;
  color: var(--text2);
  line-height: 1.65;
  max-width: 260px;
  margin-bottom: 16px;
}
.empty-sub strong { color: var(--primary); font-weight: 700; }

/* Scheme type preview */
.scheme-preview-row {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  justify-content: center;
  margin-bottom: 24px;
}
.scheme-pill {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-disp);
  letter-spacing: .2px;
}
.scheme-pill--safe { background: color-mix(in srgb, var(--green, #22c55e) 10%, transparent); color: var(--green, #22c55e); }
.scheme-pill--bal  { background: color-mix(in srgb, #3b82f6 10%, transparent); color: #3b82f6; }
.scheme-pill--hi   { background: color-mix(in srgb, #f59e0b 10%, transparent); color: #d97706; }
.scheme-pill--sc   { background: color-mix(in srgb, #ef4444 10%, transparent); color: #ef4444; }
.pill-risk { font-size: 9px; font-weight: 400; opacity: .8; font-family: var(--font); }

.gen-all-btn {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 13px 28px;
  background: var(--primary);
  color: #fff;
  border-radius: 6px;
  font-size: 15px;
  font-weight: 700;
  font-family: var(--font-disp);
  cursor: pointer;
  width: 100%;
  max-width: 300px;
  justify-content: center;
  transition: opacity .12s, transform .1s;
  letter-spacing: .3px;
  margin-bottom: 12px;
  box-shadow: var(--fab-sh);
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}
.gen-all-btn:active { opacity: .82; transform: scale(0.96); }

.analysis-ts {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text3);
  margin-top: -4px;
  margin-bottom: 8px;
}

.custom-select-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 16px;
  font-size: 13px;
  color: var(--text2);
  background: transparent;
  cursor: pointer;
  font-family: var(--font);
  border: var(--card-bd);
  border-radius: 6px;
  transition: color .15s, border-color .15s;
  touch-action: manipulation;
  -webkit-tap-highlight-color: transparent;
}
.custom-select-btn:hover { color: var(--primary); border-color: var(--primary); }

/* Error block in empty state */
.empty-error-block {
  margin-top: 20px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 14px;
  background: color-mix(in srgb, #ef4444 8%, var(--card));
  border: 1px solid color-mix(in srgb, #ef4444 30%, transparent);
  border-radius: 8px;
  max-width: 300px;
  width: 100%;
  text-align: left;
}
.empty-error-icon { color: #ef4444; flex-shrink: 0; margin-top: 1px; }
.empty-error-msg { flex: 1; font-size: 12px; color: var(--text2); line-height: 1.5; }
.empty-retry-btn {
  font-size: 12px; color: var(--primary); background: transparent;
  cursor: pointer; font-family: var(--font); white-space: nowrap; flex-shrink: 0;
  padding: 0; font-weight: 600;
}

/* ── Generating state ───────────────────────────────────────── */
.gen-loading {
  margin: 16px;
  background: var(--card);
  border: var(--card-bd);
  border-radius: 10px;
  overflow: hidden;
}
.gen-loading-inner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  border-bottom: var(--card-bd);
}
.spin-ring {
  width: 26px; height: 26px;
  border: 2.5px solid var(--line);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin .8s linear infinite;
  flex-shrink: 0;
}
@keyframes spin { to { transform: rotate(360deg); } }

.gen-loading-title { font-size: 13px; font-weight: 700; }
.gen-loading-sub { font-size: 11px; color: var(--text3); margin-top: 3px; line-height: 1.5; }
.gen-loading-right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; margin-left: auto; flex-shrink: 0; }
.gen-elapsed { font-size: 11px; color: var(--text3); }
.gen-stop-btn {
  display: flex; align-items: center; gap: 4px;
  font-size: 11px; font-weight: 600;
  padding: 4px 10px; border-radius: 6px;
  border: 1px solid rgba(239,68,68,.4);
  color: #f87171; background: rgba(239,68,68,.08);
  cursor: pointer; white-space: nowrap;
}
.gen-stop-btn:active { background: rgba(239,68,68,.18); }

.gen-loading-steps { display: flex; flex-direction: column; padding: 4px 0; }
.step-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 16px;
  font-size: 12px;
  color: var(--text3);
  border-bottom: var(--card-bd);
  transition: background .15s;
}
.step-item:last-child { border-bottom: none; }
.step-active {
  color: var(--text);
  font-weight: 600;
  background: color-mix(in srgb, var(--primary) 4%, transparent);
}
.step-done { color: var(--text3); }

.step-icon { flex-shrink: 0; }
.step-icon--done { color: var(--green, #22c55e); }

.step-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--line); flex-shrink: 0; }
.step-dot--spin { background: var(--primary); animation: pulse 1s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }

.step-label { flex-shrink: 0; }
.step-detail { font-size: 11px; color: var(--primary); margin-left: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* ── Results ────────────────────────────────────────────────── */
.results-wrap { padding: 12px 14px 32px; display: flex; flex-direction: column; gap: 10px; }

.est-odds-notice {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 10px 12px;
  background: color-mix(in srgb, #f59e0b 8%, var(--card));
  border: 1px solid color-mix(in srgb, #f59e0b 30%, transparent);
  border-radius: 7px;
  font-size: 11px;
  color: #92400e;
  line-height: 1.5;
}
:root.dark .est-odds-notice { color: #fcd34d; }
.est-odds-notice svg { flex-shrink: 0; margin-top: 1px; color: #d97706; }

.results-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.results-title { font-size: 14px; font-weight: 700; }
.results-sub { font-size: 11px; color: var(--text3); margin-top: 2px; }

.reselect-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text2);
  background: transparent;
  cursor: pointer;
  font-family: var(--font);
  padding: 10px 10px;
  border: var(--card-bd);
  border-radius: 6px;
  white-space: nowrap;
  flex-shrink: 0;
  min-height: 36px;
  touch-action: manipulation;
}

/* Tabs */
.scheme-tabs { display: flex; gap: 5px; }
.scheme-tab {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 10px 4px;
  min-height: 56px;
  font-family: var(--font);
  background: var(--card);
  border: var(--card-bd);
  border-radius: 7px;
  cursor: pointer;
  transition: all .12s;
}
.tab-label { font-size: 12px; font-weight: 700; color: var(--text2); }
.tab-risk { font-size: 9px; color: var(--text3); }
.tab-count { font-family: var(--font-disp); font-size: 10px; color: var(--text3); }
.scheme-tab.tab-on {
  background: color-mix(in srgb, var(--primary) 10%, var(--card));
  border-color: var(--primary);
  border-bottom: 2px solid var(--primary);
}
.scheme-tab.tab-on .tab-label { color: var(--primary); font-weight: 800; }
.scheme-tab.tab-on .tab-risk  { color: color-mix(in srgb, var(--primary) 80%, var(--text3)); }
.scheme-tab.tab-on .tab-count { color: color-mix(in srgb, var(--primary) 80%, var(--text3)); }
.scheme-tab.tab-disabled { opacity: .35; cursor: not-allowed; }

/* Scheme card */
.scheme-card { background: var(--card); border: var(--card-bd); border-radius: 10px; overflow: hidden; }

.scheme-card-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 11px 14px; border-bottom: var(--card-bd);
  background: color-mix(in srgb, var(--primary) 3%, var(--bg));
}
.scheme-card-head-left { display: flex; align-items: center; gap: 8px; }
.scheme-name { font-size: 13px; font-weight: 700; }
.scheme-parlay { font-size: 11px; color: var(--text3); }
.scheme-combos {
  font-size: 10px; font-weight: 700;
  padding: 1px 6px; border-radius: 3px;
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
}

.risk-badge { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px; }
.risk-badge.conservative { background: color-mix(in srgb, var(--green, #22c55e) 12%, transparent); color: var(--green, #22c55e); }
.risk-badge.balanced { background: color-mix(in srgb, #3b82f6 12%, transparent); color: #3b82f6; }
.risk-badge.high_odds { background: color-mix(in srgb, #f59e0b 12%, transparent); color: #d97706; }
.risk-badge.scoreline { background: color-mix(in srgb, #ef4444 12%, transparent); color: #ef4444; }

.leg-legend {
  display: flex; align-items: center;
  padding: 5px 14px;
  background: var(--bg); border-bottom: var(--card-bd); gap: 8px;
}
.legend-no  { font-size: 10px; color: var(--text3); min-width: 48px; flex-shrink: 0; }
.legend-match { font-size: 10px; color: var(--text3); flex: 1; }
.legend-pick  { font-size: 10px; color: var(--text3); min-width: 32px; text-align: center; flex-shrink: 0; }
.legend-odds  { font-size: 10px; color: var(--text3); min-width: 36px; text-align: right; flex-shrink: 0; }

.scheme-legs { display: flex; flex-direction: column; }
.scheme-leg { display: flex; align-items: flex-start; gap: 8px; padding: 11px 14px; border-bottom: var(--card-bd); }
.scheme-leg:last-child { border-bottom: none; }

.leg-no-col { min-width: 48px; flex-shrink: 0; padding-top: 1px; }
.leg-match-no {
  font-size: 12px; font-weight: 700; color: var(--primary);
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  border-radius: 3px; padding: 2px 5px; display: inline-block;
  letter-spacing: .3px;
}
.leg-kickoff { font-size: 10px; color: var(--text3); margin-top: 3px; padding-left: 5px; }

.leg-info { flex: 1; min-width: 0; }
.leg-teams { display: flex; flex-direction: column; gap: 3px; margin-bottom: 2px; }
.leg-team-row { display: flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 600; line-height: 1.2; }
.leg-dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
.leg-dot--h { background: var(--primary); }
.leg-dot--a { background: var(--draw-c, #1D4ED8); }
.leg-team-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text); }
.leg-meta { display: flex; align-items: center; gap: 8px; margin-top: 1px; }
.leg-league { font-size: 10px; color: var(--text3); }
.leg-conf   { font-size: 10px; color: var(--primary); font-weight: 600; }
.leg-votes  { font-size: 10px; color: var(--primary); font-weight: 600; }
.leg-rationale {
  font-size: 11px; color: var(--text2); margin-top: 4px; line-height: 1.5;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}

.leg-pick-col { min-width: 36px; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; gap: 3px; padding-top: 1px; }
.leg-pick { font-size: 11px; font-weight: 700; padding: 3px 7px; border-radius: 4px; white-space: nowrap; }
.leg-pick-code { font-size: 11px; font-weight: 700; color: var(--text3); }
.leg-hhad-badge { font-size: 9px; font-weight: 700; padding: 1px 4px; border-radius: 3px; background: var(--draw-bg); color: var(--draw-c); letter-spacing: .3px; }
.leg-handicap { font-size: 10px; color: var(--draw-c); font-weight: 600; }

.leg-odds-col { min-width: 40px; flex-shrink: 0; text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.leg-odds { font-family: var(--font-disp); font-size: 17px; font-weight: 700; line-height: 1; letter-spacing: -.2px; color: var(--primary); }
.leg-odds--est { color: var(--text2); }
.leg-odds-est-badge { font-size: 9px; color: var(--text3); background: var(--bg); border: 1px solid var(--line); border-radius: 2px; padding: 1px 3px; line-height: 1; }

.tag-win  { background: color-mix(in srgb, var(--primary) 14%, transparent); color: var(--primary); }
.tag-draw { background: color-mix(in srgb, #f59e0b 14%, transparent); color: #d97706; }
.tag-lose { background: color-mix(in srgb, var(--green, #22c55e) 14%, transparent); color: var(--green, #22c55e); }
.tag-neutral { background: var(--bg); color: var(--text2); }

.scheme-divider { border: none; border-top: 1.5px dashed var(--line); margin: 0; }

.scheme-stats {
  display: flex; align-items: stretch; padding: 13px 14px;
  background: color-mix(in srgb, var(--primary) 2%, var(--bg));
}
.stat-cell { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.stat-cell:not(:first-child) { padding-left: 14px; }
.stat-label { font-size: 11px; color: var(--text3); }
.stat-val { font-size: 19px; font-weight: 700; line-height: 1; font-family: var(--font-disp); letter-spacing: -.2px; }
.stat-sep { width: 1px; background: var(--line); margin: 0 6px; align-self: stretch; }

/* Win probability bar */
.win-prob-bar-wrap { padding: 10px 14px; border-top: var(--card-bd); }
.win-prob-label { display: flex; justify-content: space-between; font-size: 11px; color: var(--text3); margin-bottom: 6px; }
.win-prob-track { height: 4px; background: var(--line); border-radius: 2px; overflow: hidden; }
.win-prob-fill { height: 100%; background: var(--primary); border-radius: 2px; transition: width .4s ease; }

.scheme-rationale { padding: 0 14px 12px; border-top: var(--card-bd); }
.rationale-header { display: flex; align-items: center; gap: 6px; padding: 10px 0 6px; }
.rationale-label { font-size: 11px; color: var(--text3); font-family: var(--font-disp); }
.rationale-body {
  font-size: 12px; color: var(--text2); line-height: 1.65;
  background: var(--primary-d); border-left: 2px solid var(--primary);
  padding: 8px 10px; border-radius: 0 5px 5px 0;
}

/* ── Shared ─────────────────────────────────────────────────── */
.empty-tip { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 60px 20px; text-align: center; }

.fade-enter-active, .fade-leave-active { transition: opacity .2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

/* ── Bet action row ─────────────────────────────────────────── */
.bet-action-row {
  padding: 0 14px 14px;
  border-top: var(--card-bd);
}
.bet-mark-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 11px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font);
  color: var(--primary);
  background: color-mix(in srgb, var(--primary) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary) 25%, transparent);
  cursor: pointer;
  margin-top: 12px;
  transition: background .12s, border-color .12s;
  touch-action: manipulation;
}
.bet-mark-btn:hover { background: color-mix(in srgb, var(--primary) 14%, transparent); border-color: var(--primary); }
.bet-mark-btn:active { opacity: .8; }

/* ── Bet sheet ──────────────────────────────────────────────── */
.sheet-label { font-size: 12px; color: var(--text2); font-weight: 600; }
.sheet-stake-row { display: flex; align-items: center; gap: 10px; }
.stake-adj {
  width: 36px; height: 36px;
  border-radius: 8px;
  background: var(--bg);
  border: var(--card-bd);
  color: var(--text);
  font-size: 18px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: background .1s;
}
.stake-adj:hover { background: color-mix(in srgb, var(--primary) 10%, transparent); }
.stake-input {
  flex: 1;
  background: var(--bg);
  border: var(--card-bd);
  border-radius: 8px;
  color: var(--text);
  font-size: 22px;
  font-family: var(--font-disp);
  font-weight: 700;
  text-align: center;
  padding: 8px;
  outline: none;
  min-width: 0;
}
.stake-input:focus { border-color: var(--primary); }
.sheet-error { font-size: 12px; color: #ef4444; }

.sheet-cancel {
  flex: 1;
  padding: 12px;
  border-radius: 8px;
  border: var(--card-bd);
  background: transparent;
  color: var(--text2);
  font-size: 14px;
  cursor: pointer;
  font-family: var(--font);
}
.sheet-confirm {
  flex: 2;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  padding: 12px;
  border-radius: 8px;
  background: var(--primary);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--font);
  transition: opacity .12s;
}
.sheet-confirm:disabled { opacity: .5; cursor: not-allowed; }

.sheet-done {
  padding: 48px 20px;
  display: flex; flex-direction: column; align-items: center; gap: 14px;
  color: #22c55e;
  font-size: 15px; font-weight: 700;
}

.btn-spin {
  width: 14px; height: 14px;
  border: 2px solid rgba(255,255,255,.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin .7s linear infinite;
  display: inline-block;
}

/* ── Results head ────────────────────────────────────────────── */
.results-head-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }

.log-icon-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 9px;
  font-size: 11px;
  font-family: var(--font);
  color: var(--text2);
  background: transparent;
  border: var(--card-bd);
  border-radius: 5px;
  cursor: pointer;
  min-height: 36px;
  white-space: nowrap;
  transition: color .12s, background .12s, border-color .12s;
}
.log-icon-btn:hover { color: var(--primary); border-color: var(--primary); }
.log-icon-btn.active { color: var(--primary); background: var(--primary-d); border-color: var(--primary); }

/* ── Step log dropdown ───────────────────────────────────────── */
.step-log-dropdown {
  background: var(--card);
  border: var(--card-bd);
  border-radius: 8px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.step-log-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 12px;
  font-size: 11px;
  border-bottom: var(--card-bd);
}
.step-log-item:last-child { border-bottom: none; }
.step-log-name { flex-shrink: 0; }
.step-log-detail-text {
  font-size: 10px;
  color: var(--text3);
  margin-left: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.step-log-done { color: var(--text2); }
.step-log-skip { color: var(--text3); opacity: .4; }

/* ── Dynamic stake ───────────────────────────────────────────── */
.stat-stake-wrap { display: flex; align-items: baseline; gap: 3px; }
.stat-currency { font-family: var(--font-disp); font-size: 13px; font-weight: 600; color: var(--text2); line-height: 1; }
.stat-stake-hint { font-size: 10px; color: var(--text3); margin-top: 2px; }
.stat-stake-input {
  font-size: 19px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -.2px;
  color: var(--text);
  background: transparent;
  border: none;
  border-bottom: 1.5px solid var(--line);
  width: 72px;
  padding: 0 0 1px;
  outline: none;
  transition: border-color .15s;
  font-family: var(--font-disp);
  -moz-appearance: textfield;
}
.stat-stake-input:focus { border-color: var(--primary); }
.stat-stake-input::-webkit-outer-spin-button,
.stat-stake-input::-webkit-inner-spin-button { -webkit-appearance: none; }

</style>
