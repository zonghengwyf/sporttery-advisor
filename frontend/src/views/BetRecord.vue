<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api, { betsApi, type BetRecord, type BetSummary } from '@/api'

// ── 页面级 tab ─────────────────────────────────────────────────
const pageTab = ref<'records' | 'auto'>('records')

// ── 投注记录 ────────────────────────────────────────────────────
const summary = ref<BetSummary | null>(null)
const records = ref<BetRecord[]>([])
const filter = ref<'all' | 'pending' | 'won' | 'lost'>('all')
const loading = ref(false)
const deleting = ref<number | null>(null)

const filtered = computed(() => {
  if (filter.value === 'all') return records.value
  return records.value.filter(r => r.status === filter.value)
})

async function load() {
  loading.value = true
  try {
    const [sumRes, listRes] = await Promise.all([
      betsApi.summary(),
      betsApi.list({ limit: 100 }),
    ])
    summary.value = sumRes.data
    records.value = listRes.data
  } catch { /* silent */ } finally {
    loading.value = false
  }
}

async function deleteRecord(id: number) {
  if (deleting.value === id) return
  deleting.value = id
  try {
    await betsApi.remove(id)
    records.value = records.value.filter(r => r.id !== id)
    const sumRes = await betsApi.summary()
    summary.value = sumRes.data
  } catch { /* silent */ } finally {
    deleting.value = null
  }
}

onMounted(load)

// ── 自动出票 ────────────────────────────────────────────────────
interface TrackSummary {
  total_runs: number
  synced_runs: number
  total_schemes: number
  won_schemes: number
  hit_rate: number
  roi: number
  profit: number
}
interface AutoLeg {
  match_id?: number
  home_team?: string
  away_team?: string
  league?: string
  pick: string
  market?: string
  odds?: number
  won?: boolean
  actual_result?: string
}
interface AutoScheme {
  plan_id: string
  legs: AutoLeg[]
  status?: string
  profit?: number
}
interface AutoRun {
  id: number
  run_date: string
  trigger: string
  model_info: { llms: string[]; type: string } | null
  match_ids: number[]
  stake: number
  schemes: AutoScheme[]
  sync_status: string
  sync_error: string | null
  created_at: string
  synced_at: string | null
}

const autoSummary = ref<TrackSummary | null>(null)
const autoRuns = ref<AutoRun[]>([])
const autoLoading = ref(false)
const loadError = ref<string | null>(null)
const syncing = ref<number | null>(null)
const skippedExpanded = ref(new Set<number>())

async function loadAuto() {
  autoLoading.value = true
  loadError.value = null
  try {
    const [sumRes, runsRes] = await Promise.all([
      api.get('/track/summary'),
      api.get('/track/runs', { params: { limit: 30 } }),
    ])
    autoSummary.value = sumRes.data
    autoRuns.value = runsRes.data
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail ?? '加载失败'
  } finally {
    autoLoading.value = false
  }
}

async function syncRun(runId: number) {
  syncing.value = runId
  loadError.value = null
  try {
    const { data } = await api.post(`/track/runs/${runId}/sync`)
    const idx = autoRuns.value.findIndex(r => r.id === runId)
    if (idx >= 0) autoRuns.value[idx] = data
    await loadAuto()
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail ?? '同步失败'
  } finally {
    syncing.value = null
  }
}

function switchToAuto() {
  pageTab.value = 'auto'
  if (!autoRuns.value.length && !autoLoading.value) loadAuto()
}

// ── 通用工具函数 ─────────────────────────────────────────────────
function planLabel(planId: string) {
  const isCover = planId.endsWith('_cover')
  const base = isCover ? planId.slice(0, -6) : planId
  const label = { conservative: '稳健', balanced: '均衡', high_odds: '博高赔', scoreline: '比分', manual: '手动' }[base] ?? planId
  return isCover ? label + '·容错' : label
}

function statusLabel(s: string) {
  return { pending: '待结算', won: '已中奖', lost: '未中', void: '无效' }[s] ?? s
}

function pickLabel(pick: string) {
  if (/主胜/.test(pick)) return '主胜'
  if (/^平/.test(pick))  return '平'
  if (/客胜/.test(pick)) return '客胜'
  return pick
}

function pickClass(pick: string) {
  if (/主胜/.test(pick)) return 'tag-win'
  if (/^平/.test(pick))  return 'tag-draw'
  if (/客胜/.test(pick)) return 'tag-lose'
  return 'tag-neutral'
}

function resultClass(r: BetRecord) {
  return { won: 'status-won', lost: 'status-lost', pending: 'status-pending', void: 'status-void' }[r.status] ?? ''
}

function formatDate(iso: string) {
  const d = new Date(iso)
  const mo = String(d.getMonth() + 1).padStart(2, '0')
  const da = String(d.getDate()).padStart(2, '0')
  const hr = String(d.getHours()).padStart(2, '0')
  const mn = String(d.getMinutes()).padStart(2, '0')
  return `${mo}/${da} ${hr}:${mn}`
}

function profitSign(p: number | null | undefined) {
  if (p == null) return ''
  return p >= 0 ? '+' : ''
}

function isHit(pick: string, actualResult: string | null | undefined): boolean {
  if (!actualResult) return false
  const map: Record<string, string[]> = { H: ['主胜'], D: ['平局', '平'], A: ['客胜'] }
  return map[actualResult]?.includes(pick) ?? false
}

function syncStatusLabel(s: string) {
  return { pending: '待同步', synced: '已同步', partial: '部分同步', failed: '同步失败' }[s] ?? s
}
function syncStatusClass(s: string) {
  return { pending: 'chip-pending', synced: 'chip-ok', partial: 'chip-warn', failed: 'chip-err' }[s] ?? ''
}
function triggerLabel(t: string) {
  return t === 'manual' ? '手动' : '定时'
}
function schemeStatus(scheme: any): string {
  return scheme.status ?? 'pending'
}
function calcSchemeOdds(scheme: AutoScheme): number {
  return scheme.legs.reduce((acc, l) => acc * (l.odds ?? 1), 1)
}

const router = useRouter()

function hitRateClass(rate: number): string {
  if (rate >= 60) return 'text-green'
  if (rate >= 40) return 'text-warning'
  return 'text-red'
}

function formatModelLabel(model_info: { llms: string[]; type: string } | null): string {
  if (!model_info?.llms?.length) return '未知模型'
  return model_info.llms.map(m => m.split('/').pop() ?? m).join(' + ')
}

async function tryNavigateToMatch(matchId: number) {
  try {
    await api.get(`/matches/${matchId}`)
    router.push(`/matches/${matchId}`)
  } catch { /* match not found — silently skip */ }
}

// ── 手动比分录入 ──────────────────────────────────────────────────────────────

const scoreEditing = ref<Record<number, boolean>>({})   // match_id → editing open
const scoreInput = ref<Record<number, string>>({})       // match_id → raw input "2-1"
const scoreSubmitting = ref<Record<number, boolean>>({}) // match_id → in-flight

function scoreMissingIds(run: AutoRun): Set<number> {
  const ids = new Set<number>()
  if (!run.sync_error) return ids
  for (const part of run.sync_error.split(';')) {
    const m = part.match(/match#(\d+):\s*score_missing/)
    if (m) ids.add(parseInt(m[1]))
  }
  return ids
}

function openScoreEntry(matchId: number, e: Event) {
  e.stopPropagation()
  scoreEditing.value = { ...scoreEditing.value, [matchId]: true }
  if (!scoreInput.value[matchId]) scoreInput.value = { ...scoreInput.value, [matchId]: '' }
}

function closeScoreEntry(matchId: number, e: Event) {
  e.stopPropagation()
  const ed = { ...scoreEditing.value }
  delete ed[matchId]
  scoreEditing.value = ed
}

async function submitScore(matchId: number, runId: number, e: Event) {
  e.stopPropagation()
  const raw = (scoreInput.value[matchId] ?? '').trim()
  const parts = raw.split(/[-:]/)
  if (parts.length !== 2) return
  const h = parseInt(parts[0].trim()), a = parseInt(parts[1].trim())
  if (isNaN(h) || isNaN(a) || h < 0 || a < 0) return

  const actual_result = h > a ? 'H' : h < a ? 'A' : 'D'
  scoreSubmitting.value = { ...scoreSubmitting.value, [matchId]: true }
  try {
    await api.patch(`/matches/${matchId}/result`, { actual_result, actual_score: `${h}-${a}` })
    closeScoreEntry(matchId, e)
    await syncRun(runId)
  } catch (e: any) {
    loadError.value = e?.response?.data?.detail ?? '录入失败，请重试'
  } finally {
    const sb = { ...scoreSubmitting.value }
    delete sb[matchId]
    scoreSubmitting.value = sb
  }
}

function toggleSkipped(id: number) {
  const s = new Set(skippedExpanded.value)
  s.has(id) ? s.delete(id) : s.add(id)
  skippedExpanded.value = s
}

const expandedSchemes = ref(new Set<string>())
function toggleSchemeExpand(runId: number, si: number) {
  const key = `${runId}-${si}`
  const s = new Set(expandedSchemes.value)
  s.has(key) ? s.delete(key) : s.add(key)
  expandedSchemes.value = s
}
function schemeStatusShort(s: string | undefined): string {
  return ({ pending: '待结算', won: '已中', lost: '未中', void: '无效' } as Record<string, string>)[s ?? 'pending'] ?? '—'
}

const syncedCount = computed(() => autoRuns.value.filter(r => r.sync_status === 'synced').length)
const skippedCount = computed(() => autoRuns.value.filter(r => r.sync_status === 'skipped').length)
const hasAnyModelRuns = computed(() => autoRuns.value.some(r => r.model_info?.llms?.length))

// ── 筛选状态 ─────────────────────────────────────────────────────
const typeFilter   = ref<string | null>(null)
const modelFilter  = ref<string | null>(null)
const parlayFilter = ref<number | null>(null)

// ── 方案详情弹窗 ───────────────────────────────────────────────────
const detailInfo = ref<{ run: AutoRun; scheme: AutoScheme } | null>(null)
function openDetail(run: AutoRun, scheme: AutoScheme) { detailInfo.value = { run, scheme } }
function closeDetail() { detailInfo.value = null }

// ── 筛选后历史列表 ─────────────────────────────────────────────────
const filteredRuns = computed(() => {
  let runs = autoRuns.value
  if (typeFilter.value)        runs = runs.filter(r => r.schemes?.some(s => s.plan_id === typeFilter.value))
  if (modelFilter.value)       runs = runs.filter(r => r.model_info?.llms?.join('+') === modelFilter.value)
  if (parlayFilter.value != null) runs = runs.filter(r => r.schemes?.some(s => s.legs?.length === parlayFilter.value))
  return runs
})
const activeFilterCount = computed(() =>
  [typeFilter.value, modelFilter.value, parlayFilter.value].filter(v => v !== null).length
)
function clearFilters() { typeFilter.value = null; modelFilter.value = null; parlayFilter.value = null }
function toggleTypeFilter(pid: string)  { typeFilter.value   = typeFilter.value   === pid  ? null : pid }
function toggleModelFilter(key: string) { modelFilter.value  = modelFilter.value  === key  ? null : key }
function toggleParlayFilter(n: number)  { parlayFilter.value = parlayFilter.value === n    ? null : n   }

// ── 最佳命中率 key helper ──────────────────────────────────────────
function bestKey(groups: Record<string, {total: number; won: number}>): string | null {
  let best: string | null = null; let bestRate = -1
  for (const [k, v] of Object.entries(groups)) {
    if (v.total < 5) continue
    const rate = v.won / v.total
    if (rate > bestRate) { bestRate = rate; best = k }
  }
  return best
}

interface SchemeAcc { total: number; won: number; label: string }
interface ModelAcc  { total: number; won: number; label: string; type: string }

const schemeAccuracy = computed<Record<string, SchemeAcc>>(() => {
  const groups: Record<string, SchemeAcc> = {
    conservative: { total: 0, won: 0, label: '稳健' },
    balanced:     { total: 0, won: 0, label: '均衡' },
    high_odds:    { total: 0, won: 0, label: '博高赔' },
    scoreline:    { total: 0, won: 0, label: '比分' },
  }
  for (const run of autoRuns.value) {
    if (run.sync_status === 'pending' || run.sync_status === 'skipped') continue
    for (const scheme of run.schemes ?? []) {
      const pid = scheme.plan_id.replace(/_cover$/, '')  // 容错方案归入基础策略统计
      if (!groups[pid]) continue
      if (scheme.status === 'won' || scheme.status === 'lost') {
        groups[pid].total++
        if (scheme.status === 'won') groups[pid].won++
      }
    }
  }
  return groups
})

const modelAccuracy = computed<Record<string, ModelAcc>>(() => {
  const groups: Record<string, ModelAcc> = {}
  for (const run of autoRuns.value) {
    if (!run.model_info?.llms?.length) continue
    const key = run.model_info.llms.join('+')
    if (!groups[key]) groups[key] = { total: 0, won: 0, label: formatModelLabel(run.model_info), type: run.model_info.type ?? 'single' }
  }
  for (const run of autoRuns.value) {
    if (!run.model_info?.llms?.length) continue
    if (run.sync_status === 'pending' || run.sync_status === 'skipped') continue
    const key = run.model_info.llms.join('+')
    for (const scheme of run.schemes ?? []) {
      if (scheme.status === 'won' || scheme.status === 'lost') {
        groups[key].total++
        if (scheme.status === 'won') groups[key].won++
      }
    }
  }
  return groups
})

// ── 串数准确率 ────────────────────────────────────────────────────
const parlayAccuracy = computed<Record<string, {total: number; won: number}>>(() => {
  const groups: Record<string, {total: number; won: number}> = {}
  for (const run of autoRuns.value) {
    if (run.sync_status === 'pending' || run.sync_status === 'skipped') continue
    for (const scheme of run.schemes ?? []) {
      const n = scheme.legs?.length ?? 0
      if (!n) continue
      const key = String(n)
      if (!groups[key]) groups[key] = { total: 0, won: 0 }
      if (scheme.status === 'won' || scheme.status === 'lost') {
        groups[key].total++
        if (scheme.status === 'won') groups[key].won++
      }
    }
  }
  return Object.fromEntries(Object.entries(groups).sort((a, b) => Number(a[0]) - Number(b[0])))
})
const hasParlayData = computed(() => Object.keys(parlayAccuracy.value).length > 0)

// ── 联赛准确率（腿层级）──────────────────────────────────────────
const leagueAccuracy = computed<Record<string, {total: number; won: number}>>(() => {
  const groups: Record<string, {total: number; won: number}> = {}
  for (const run of autoRuns.value) {
    if (run.sync_status === 'pending' || run.sync_status === 'skipped') continue
    for (const scheme of run.schemes ?? []) {
      if (scheme.status === 'pending') continue
      for (const leg of scheme.legs ?? []) {
        const league = leg.league
        if (!league) continue
        if (!groups[league]) groups[league] = { total: 0, won: 0 }
        if (leg.won !== undefined) {
          groups[league].total++
          if (leg.won) groups[league].won++
        }
      }
    }
  }
  return Object.fromEntries(Object.entries(groups).sort((a, b) => b[1].total - a[1].total))
})
const hasLeagueData = computed(() => Object.keys(leagueAccuracy.value).length > 0)

// ── 选项准确率（腿层级，按 pick × market）───────────────────────
interface PickAcc { total: number; won: number; label: string; order: number }
const PICK_KEYS: Record<string, PickAcc> = {
  'HAD_主胜':   { total: 0, won: 0, label: '主胜',   order: 0 },
  'HAD_平局':   { total: 0, won: 0, label: '平局',   order: 1 },
  'HAD_客胜':   { total: 0, won: 0, label: '客胜',   order: 2 },
  'HHAD_主胜':  { total: 0, won: 0, label: '让球胜', order: 3 },
  'HHAD_平局':  { total: 0, won: 0, label: '让球平', order: 4 },
  'HHAD_客胜':  { total: 0, won: 0, label: '让球负', order: 5 },
}
const pickAccuracy = computed<Record<string, PickAcc>>(() => {
  const groups: Record<string, PickAcc> = Object.fromEntries(
    Object.entries(PICK_KEYS).map(([k, v]) => [k, { ...v }])
  )
  for (const run of autoRuns.value) {
    if (run.sync_status === 'pending' || run.sync_status === 'skipped') continue
    for (const scheme of run.schemes ?? []) {
      if (scheme.status === 'pending') continue
      for (const leg of scheme.legs ?? []) {
        if (leg.won === undefined || leg.won === null) continue
        const marketKey = leg.market === '让球胜平负' ? 'HHAD' : 'HAD'
        const key = `${marketKey}_${leg.pick}`
        if (!groups[key]) continue
        groups[key].total++
        if (leg.won) groups[key].won++
      }
    }
  }
  return Object.fromEntries(
    Object.entries(groups).sort((a, b) => a[1].order - b[1].order)
  )
})
const hasPickData = computed(() =>
  Object.values(pickAccuracy.value).some(a => a.total > 0)
)

// ── 赛果实际分布（H/D/A）────────────────────────────────────────
const resultDistribution = computed<Record<string, number>>(() => {
  const dist: Record<string, number> = {}
  const seen = new Set<string>()
  for (const run of autoRuns.value) {
    if (run.sync_status === 'pending' || run.sync_status === 'skipped') continue
    for (const scheme of run.schemes ?? []) {
      if (scheme.status === 'pending') continue
      for (const leg of scheme.legs ?? []) {
        if (!leg.actual_result) continue
        const key = `${run.id}_${leg.match_id}`
        if (seen.has(key)) continue
        seen.add(key)
        dist[leg.actual_result] = (dist[leg.actual_result] ?? 0) + 1
      }
    }
  }
  return dist
})
const resultTotal = computed(() => Object.values(resultDistribution.value).reduce((s, n) => s + n, 0))
const hasResultData = computed(() => resultTotal.value > 0)

// ── 各方案类型 ROI ────────────────────────────────────────────────
interface SchemeRoiAcc { stake: number; profit: number; count: number }
const schemeRoi = computed<Record<string, SchemeRoiAcc>>(() => {
  const groups: Record<string, SchemeRoiAcc> = {}
  for (const run of autoRuns.value) {
    for (const scheme of run.schemes ?? []) {
      if (scheme.status === 'pending' || scheme.profit == null) continue
      const pid = scheme.plan_id.replace(/_cover$/, '')  // 容错方案归入基础策略
      if (!groups[pid]) groups[pid] = { stake: 0, profit: 0, count: 0 }
      groups[pid].stake += run.stake
      groups[pid].profit += scheme.profit
      groups[pid].count++
    }
  }
  return groups
})
const hasRoiData = computed(() => Object.keys(schemeRoi.value).length > 0)
const maxAbsProfit = computed(() =>
  Math.max(1, ...Object.values(schemeRoi.value).map(r => Math.abs(r.profit)))
)
</script>

<template>
  <div class="view">

    <!-- ── 页面级 tab 切换 ───────────────────────────────────────── -->
    <div class="page-tab-bar">
      <button class="ptab" :class="{ 'ptab-on': pageTab === 'records' }" @click="pageTab = 'records'">
        投注记录
        <span v-if="summary?.total_bets" class="ptab-count font-num">{{ summary.total_bets }}</span>
      </button>
      <button class="ptab" :class="{ 'ptab-on': pageTab === 'auto' }" @click="switchToAuto">
        自动出票
        <span v-if="autoSummary?.total_runs" class="ptab-count font-num">{{ autoSummary.total_runs }}</span>
      </button>
    </div>

    <!-- ════════════════════════════════════════════════════════════
         投注记录 tab
    ═══════════════════════════════════════════════════════════════ -->
    <template v-if="pageTab === 'records'">

      <!-- Summary cards -->
      <div class="summary-grid">
        <div class="sum-card">
          <div class="sum-label">累计投入</div>
          <div class="sum-val font-num">¥{{ summary?.total_stake?.toFixed(0) ?? '—' }}</div>
        </div>
        <div class="sum-card" :class="{ 'sum-card--pos': (summary?.profit ?? 0) >= 0, 'sum-card--neg': (summary?.profit ?? 0) < 0 }">
          <div class="sum-label">盈亏</div>
          <div class="sum-val font-num">
            {{ profitSign(summary?.profit) }}{{ summary?.profit?.toFixed(0) ?? '—' }}
          </div>
        </div>
        <div class="sum-card">
          <div class="sum-label">ROI</div>
          <div class="sum-val font-num" :class="(summary?.roi ?? 0) >= 0 ? 'text-green' : 'text-red'">
            {{ profitSign(summary?.roi) }}{{ summary?.roi?.toFixed(1) ?? '—' }}%
          </div>
        </div>
        <div class="sum-card">
          <div class="sum-label">命中率</div>
          <div class="sum-val font-num">{{ summary?.hit_rate?.toFixed(1) ?? '—' }}%</div>
        </div>
      </div>

      <!-- Sub-stats row -->
      <div v-if="summary" class="sub-stats">
        <div class="sub-stat">
          <span class="sub-stat-val font-num">{{ summary.total_bets }}</span>
          <span class="sub-stat-label">总注数</span>
        </div>
        <div class="sub-stat">
          <span class="sub-stat-val font-num">{{ summary.won_bets }}</span>
          <span class="sub-stat-label">已中</span>
        </div>
        <div class="sub-stat">
          <span class="sub-stat-val font-num text-warning">{{ summary.total_bets - summary.settled_bets }}</span>
          <span class="sub-stat-label">待结算</span>
        </div>
        <div class="sub-stat">
          <span class="sub-stat-val font-num">¥{{ summary.pending_stake.toFixed(0) }}</span>
          <span class="sub-stat-label">待结算金额</span>
        </div>
      </div>

      <!-- Filter tabs -->
      <div class="filter-tabs">
        <button
          v-for="f in (['all', 'pending', 'won', 'lost'] as const)"
          :key="f"
          class="filter-tab"
          :class="{ active: filter === f }"
          @click="filter = f"
        >
          {{ { all: '全部', pending: '待结算', won: '已中', lost: '未中' }[f] }}
          <span class="filter-count font-num">
            {{ f === 'all' ? records.length : records.filter(r => r.status === f).length }}
          </span>
        </button>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="center-msg">
        <div class="spin-ring" />
      </div>

      <!-- Empty -->
      <div v-else-if="!filtered.length" class="center-msg empty-msg">
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.4" class="empty-icon">
          <rect x="8" y="8" width="24" height="24" rx="4"/>
          <path d="M14 20h12M14 15h8M14 25h6"/>
        </svg>
        <p>{{ filter === 'all' ? '还没有投注记录' : `暂无${{ pending:'待结算', won:'已中', lost:'未中' }[filter]}记录` }}</p>
        <p class="empty-hint">在投注方案页标记您购买的方案</p>
      </div>

      <!-- Timeline -->
      <div v-else class="timeline">
        <div v-for="record in filtered" :key="record.id" class="bet-card">

          <!-- Card header -->
          <div class="bet-card-head">
            <div class="bet-head-left">
              <span class="plan-badge" :class="record.plan_id">{{ planLabel(record.plan_id) }}</span>
              <span class="bet-date font-num">{{ formatDate(record.bet_at) }}</span>
              <span class="parlay-label font-num">{{ record.legs.length }}串1</span>
            </div>
            <span class="status-badge" :class="resultClass(record)">{{ statusLabel(record.status) }}</span>
          </div>

          <!-- Legs list -->
          <div class="legs-list">
            <div v-for="(leg, i) in record.legs" :key="i" class="leg-row">
              <div class="leg-teams-col">
                <span class="leg-team">{{ leg.home_team }}</span>
                <span class="leg-vs">vs</span>
                <span class="leg-team">{{ leg.away_team }}</span>
              </div>
              <span class="leg-pick-tag" :class="pickClass(leg.pick)">{{ pickLabel(leg.pick) }}</span>
              <span class="leg-odds font-num">×{{ leg.odds?.toFixed(2) ?? '—' }}</span>
              <span class="leg-result" v-if="leg.actual_result">
                <span :class="isHit(leg.pick, leg.actual_result) ? 'result-hit' : 'result-miss'">
                  {{ ({ H:'主胜', D:'平', A:'客胜' } as Record<string,string>)[leg.actual_result] ?? leg.actual_result }}
                </span>
              </span>
            </div>
          </div>

          <!-- Card footer -->
          <div class="bet-card-foot">
            <div class="foot-cell">
              <span class="foot-label">投注</span>
              <span class="foot-val font-num">¥{{ record.stake }}</span>
            </div>
            <div class="foot-sep" />
            <div class="foot-cell">
              <span class="foot-label">预期</span>
              <span class="foot-val font-num">¥{{ record.expected_payout?.toFixed(0) ?? '—' }}</span>
            </div>
            <div class="foot-sep" />
            <div v-if="record.status !== 'pending'" class="foot-cell">
              <span class="foot-label">盈亏</span>
              <span class="foot-val font-num" :class="(record.profit ?? 0) >= 0 ? 'text-green' : 'text-red'">
                {{ profitSign(record.profit) }}{{ record.profit?.toFixed(0) ?? '—' }}
              </span>
            </div>
            <div v-else class="foot-cell">
              <span class="foot-label">待结算</span>
              <span class="foot-val font-num text-warning">¥{{ record.stake }}</span>
            </div>

            <!-- Delete (pending only) -->
            <button
              v-if="record.status === 'pending'"
              class="del-btn"
              :disabled="deleting === record.id"
              @click="deleteRecord(record.id)"
              aria-label="删除"
            >
              <svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round">
                <path d="M1 3h12M5 3V2h4v1M3 3l1 9h6l1-9"/>
              </svg>
            </button>
          </div>

          <div v-if="record.note" class="bet-note">{{ record.note }}</div>
        </div>
      </div>

    </template>

    <!-- ════════════════════════════════════════════════════════════
         自动出票 tab — 预测质量看板
    ═══════════════════════════════════════════════════════════════ -->
    <template v-else>

      <!-- loadError banner -->
      <div v-if="loadError" class="load-error-bar" role="alert">
        加载失败：{{ loadError }}
        <button class="retry-link" @click="loadAuto">重试</button>
      </div>

      <!-- Loading skeleton -->
      <template v-if="autoLoading">
        <div class="summary-grid">
          <div v-for="i in 4" :key="i" class="sum-card skel-card" style="min-height:64px" />
        </div>
        <div class="timeline">
          <div v-for="i in 3" :key="i" class="auto-card skel-card" style="min-height:120px; border-bottom: var(--card-bd)" />
        </div>
      </template>

      <!-- Empty state -->
      <div v-else-if="!autoRuns.length && !loadError" class="center-msg empty-msg">
        <svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.4" class="empty-icon" aria-hidden="true">
          <circle cx="20" cy="20" r="14"/>
          <path d="M20 12v9l5 3"/>
        </svg>
        <p>等待首次自动分析</p>
        <button class="empty-link" @click="router.push('/settings')">前往设置配置定时出票</button>
      </div>

      <!-- Content zones -->
      <template v-else>

        <!-- ZONE 1: 英雄总览 -->
        <div class="az1-hero-wrap" aria-label="自动出票总览">
          <div class="az1-left">
            <div class="az1-hero-label">总命中率</div>
            <div
              class="az1-hero-val font-num"
              :class="syncedCount > 0 && autoSummary ? hitRateClass(autoSummary.hit_rate) : ''"
            >
              <template v-if="syncedCount > 0 && autoSummary">{{ autoSummary.hit_rate.toFixed(1) }}%</template>
              <span v-else class="az1-no-data">暂无数据</span>
            </div>
            <div class="az1-hero-sub">{{ syncedCount > 0 ? `${autoSummary?.won_schemes ?? 0} 中 / ${autoSummary?.total_schemes ?? 0} 次` : '等待赛果结算' }}</div>
          </div>
          <div class="az1-right">
            <div class="az1-stat">
              <span class="az1-stat-val font-num">{{ autoSummary?.total_runs ?? autoRuns.length }}</span>
              <span class="az1-stat-label">运行</span>
            </div>
            <div class="az1-divider" />
            <div class="az1-stat">
              <span class="az1-stat-val font-num">{{ syncedCount }}</span>
              <span class="az1-stat-label">已同步</span>
            </div>
            <div class="az1-divider" />
            <div class="az1-stat">
              <span class="az1-stat-val font-num" style="color:var(--text3)">{{ skippedCount }}</span>
              <span class="az1-stat-label">跳过</span>
            </div>
          </div>
        </div>

        <!-- ZONE 2: 分方案类型准确率 — 4列固定网格（点击筛选历史） -->
        <div class="scheme-acc-grid" role="list" aria-label="分方案准确率">
          <button
            v-for="(acc, planId) in schemeAccuracy"
            :key="planId"
            type="button"
            class="scheme-acc-cell"
            :class="{ 'sac-active': typeFilter === String(planId), 'sac-best': bestKey(schemeAccuracy) === String(planId) && acc.total >= 5 }"
            role="listitem"
            :aria-label="`${acc.label}方案命中率${acc.total >= 5 ? (acc.won / acc.total * 100).toFixed(0) + '%' : acc.total > 0 ? '数据不足' : '暂无数据'}，${acc.total}个样本`"
            @click="toggleTypeFilter(String(planId))"
          >
            <div class="scheme-acc-label">
              {{ acc.label }}
              <span v-if="bestKey(schemeAccuracy) === String(planId) && acc.total >= 5" class="best-badge">最佳</span>
            </div>
            <div v-if="acc.total === 0" class="scheme-acc-val scheme-acc-insufficient">待结算</div>
            <div v-else-if="acc.total < 5" class="scheme-acc-val scheme-acc-insufficient">数据不足</div>
            <div v-else class="scheme-acc-val font-num" :class="hitRateClass(acc.won / acc.total * 100)">
              {{ (acc.won / acc.total * 100).toFixed(0) }}%
            </div>
            <div class="scheme-acc-n font-num">n={{ acc.total }}</div>
          </button>
        </div>

        <!-- ZONE 3: 分模型准确率（点击筛选） -->
        <div v-if="hasAnyModelRuns" class="zone-section">
          <div class="zone-header">按模型准确率</div>
          <div class="accuracy-scroll" role="list">
            <button
              v-for="(acc, modelKey) in modelAccuracy"
              :key="modelKey"
              type="button"
              class="acc-pill acc-pill--wide"
              :class="{ 'acc-pill-active': modelFilter === String(modelKey), 'acc-pill-best': bestKey(modelAccuracy) === String(modelKey) && acc.total >= 5 }"
              role="listitem"
              :aria-label="`${acc.label} 命中率${acc.total >= 5 ? (acc.won / acc.total * 100).toFixed(0) + '%' : acc.total > 0 ? '数据不足' : '暂无数据'}，${acc.total}个样本`"
              @click="toggleModelFilter(String(modelKey))"
            >
              <div class="acc-pill-label">
                {{ acc.label }}
                <span v-if="bestKey(modelAccuracy) === String(modelKey) && acc.total >= 5" class="best-badge">最佳</span>
              </div>
              <div class="acc-pill-type">{{ acc.type === 'ensemble' ? '混合' : '单模型' }}</div>
              <div v-if="acc.total === 0" class="acc-pill-val acc-pill-insufficient">待结算</div>
              <div v-else-if="acc.total < 5" class="acc-pill-val acc-pill-insufficient">数据不足</div>
              <div v-else class="acc-pill-val font-num" :class="hitRateClass(acc.won / acc.total * 100)">
                {{ (acc.won / acc.total * 100).toFixed(0) }}%
              </div>
              <div class="acc-pill-n font-num">n={{ acc.total }}</div>
            </button>
          </div>
        </div>

        <!-- ZONE 4: 按串数准确率（点击筛选） -->
        <div v-if="hasParlayData" class="zone-section">
          <div class="zone-header">按串数准确率</div>
          <div class="accuracy-scroll" role="list">
            <button
              v-for="(acc, n) in parlayAccuracy"
              :key="n"
              type="button"
              class="parlay-chip"
              :class="{ 'parlay-chip-active': parlayFilter === Number(n), 'parlay-chip-best': bestKey(parlayAccuracy) === String(n) && acc.total >= 5 }"
              @click="toggleParlayFilter(Number(n))"
              :aria-label="`${n}串1命中率${acc.total >= 5 ? (acc.won / acc.total * 100).toFixed(0) + '%' : '数据不足'}，${acc.total}个样本`"
            >
              <div class="pc-label">
                {{ n }}串1
                <span v-if="bestKey(parlayAccuracy) === String(n) && acc.total >= 5" class="best-badge">最佳</span>
              </div>
              <div v-if="acc.total === 0" class="pc-val pc-insufficient">待结算</div>
              <div v-else-if="acc.total < 5" class="pc-val pc-insufficient">数据不足</div>
              <div v-else class="pc-val font-num" :class="hitRateClass(acc.won / acc.total * 100)">
                {{ (acc.won / acc.total * 100).toFixed(0) }}%
              </div>
              <div class="pc-n font-num">n={{ acc.total }}</div>
            </button>
          </div>
        </div>

        <!-- ZONE 5: 按联赛准确率（条件显示） -->
        <div v-if="hasLeagueData" class="zone-section">
          <div class="zone-header">按联赛准确率（腿级）</div>
          <div class="accuracy-scroll" role="list">
            <div
              v-for="(acc, league) in leagueAccuracy"
              :key="league"
              class="acc-pill"
              :class="{ 'acc-pill-best': bestKey(leagueAccuracy) === String(league) && acc.total >= 5 }"
              :aria-label="`${league}命中率${acc.total >= 5 ? (acc.won / acc.total * 100).toFixed(0) + '%' : '数据不足'}，${acc.total}个样本`"
            >
              <div class="acc-pill-label">
                {{ league }}
                <span v-if="bestKey(leagueAccuracy) === String(league) && acc.total >= 5" class="best-badge">最佳</span>
              </div>
              <div v-if="acc.total === 0" class="acc-pill-val acc-pill-insufficient">待结算</div>
              <div v-else-if="acc.total < 5" class="acc-pill-val acc-pill-insufficient">数据不足</div>
              <div v-else class="acc-pill-val font-num" :class="hitRateClass(acc.won / acc.total * 100)">
                {{ (acc.won / acc.total * 100).toFixed(0) }}%
              </div>
              <div class="acc-pill-n font-num">n={{ acc.total }}</div>
            </div>
          </div>
        </div>

        <!-- ZONE 6: 按选项准确率（腿级，横向条形） -->
        <div v-if="hasPickData" class="zone-section">
          <div class="zone-header">选项命中率（单场）</div>
          <div class="par-list" role="list">
            <div
              v-for="(acc, key) in pickAccuracy"
              :key="key"
              class="par-row"
              role="listitem"
              :aria-label="`${acc.label}命中率${acc.total >= 3 ? (acc.won / acc.total * 100).toFixed(0) + '%' : '数据不足'}，${acc.total}个样本`"
            >
              <span class="par-label">
                {{ acc.label }}
                <span v-if="bestKey(pickAccuracy) === String(key) && acc.total >= 5" class="best-badge">最佳</span>
              </span>
              <div class="par-bar-track">
                <div
                  class="par-bar-fill"
                  :class="acc.total >= 3 ? hitRateClass(acc.won / acc.total * 100) + '-bar' : 'muted-bar'"
                  :style="`width:${acc.total > 0 ? (acc.won / acc.total * 100).toFixed(0) : 0}%`"
                />
              </div>
              <span class="par-pct font-num" :class="acc.total >= 3 ? hitRateClass(acc.won / acc.total * 100) : ''">
                {{ acc.total >= 3 ? (acc.won / acc.total * 100).toFixed(0) + '%' : acc.total > 0 ? '少' : '—' }}
              </span>
              <span class="par-detail font-num">{{ acc.won }}/{{ acc.total }}</span>
            </div>
          </div>
        </div>

        <!-- ZONE 7: 赛果实际分布 -->
        <div v-if="hasResultData" class="zone-section">
          <div class="zone-header">赛果分布（{{ resultTotal }} 场已结算）</div>
          <div class="rdr-strip">
            <div
              v-for="(count, result) in resultDistribution"
              :key="result"
              class="rdr-cell"
            >
              <div class="rdr-label">{{ { H:'主胜', D:'平局', A:'客胜' }[result] ?? result }}</div>
              <div class="rdr-pct font-num" :class="`rdr-${result}`">
                {{ resultTotal > 0 ? (count / resultTotal * 100).toFixed(0) : 0 }}%
              </div>
              <div class="rdr-bar-track">
                <div class="rdr-bar" :class="`rdr-bar-${result}`" :style="`width:${resultTotal > 0 ? (count / resultTotal * 100).toFixed(0) : 0}%`" />
              </div>
              <div class="rdr-n font-num">{{ count }} 场</div>
            </div>
          </div>
        </div>

        <!-- ZONE 8: 方案收益分析 -->
        <div v-if="hasRoiData" class="zone-section">
          <div class="zone-header">方案收益分析</div>
          <div class="roi-rows">
            <div v-for="(roi, pid) in schemeRoi" :key="pid" class="roi-row">
              <span class="roi-name">{{ planLabel(pid) }}</span>
              <div class="roi-bar-track">
                <div
                  class="roi-bar-fill"
                  :class="roi.profit >= 0 ? 'roi-pos' : 'roi-neg'"
                  :style="`width:${(Math.abs(roi.profit) / maxAbsProfit * 100).toFixed(0)}%`"
                />
              </div>
              <div class="roi-right">
                <span class="roi-profit font-num" :class="roi.profit >= 0 ? 'text-green' : 'text-red'">
                  {{ roi.profit >= 0 ? '+' : '' }}¥{{ roi.profit.toFixed(0) }}
                </span>
                <span class="roi-meta font-num">{{ roi.count }}次 · {{ roi.stake > 0 ? (roi.profit / roi.stake * 100).toFixed(0) : 0 }}% ROI</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 筛选状态栏 -->
        <div class="filter-active-bar" v-if="activeFilterCount > 0">
          <span class="fab-info">
            已筛选：
            <span v-if="typeFilter" class="fab-chip">{{ { conservative:'稳健', balanced:'均衡', high_odds:'博高赔', scoreline:'比分' }[typeFilter] ?? typeFilter }}</span>
            <span v-if="modelFilter" class="fab-chip">{{ modelFilter.split('+').map(m => m.split('/').pop()).join('+') }}</span>
            <span v-if="parlayFilter != null" class="fab-chip">{{ parlayFilter }}串1</span>
            · {{ filteredRuns.length }} 条
          </span>
          <button class="fab-clear" @click="clearFilters">清除</button>
        </div>

        <!-- ZONE 6: 运行历史 -->
        <div class="timeline" aria-label="运行历史">
          <template v-for="run in filteredRuns" :key="run.id">

            <!-- Skipped run (collapsed by default) -->
            <div v-if="run.sync_status === 'skipped'" class="run-skipped">
              <div class="skipped-main" @click="toggleSkipped(run.id)">
                <span class="auto-date font-num">{{ run.run_date }}</span>
                <span class="skipped-label">跳过</span>
              </div>
              <button
                class="skipped-toggle"
                :aria-expanded="skippedExpanded.has(run.id)"
                aria-label="展开跳过详情"
                @click="toggleSkipped(run.id)"
              >
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" :style="skippedExpanded.has(run.id) ? 'transform:rotate(180deg);transition:.15s' : 'transition:.15s'" aria-hidden="true">
                  <path d="M2 4l4 4 4-4"/>
                </svg>
              </button>
              <div v-if="skippedExpanded.has(run.id)" class="skipped-detail">
                {{ run.sync_error ?? '无预测数据' }}
              </div>
            </div>

            <!-- Normal run card -->
            <article v-else class="auto-card" role="article" :aria-label="`${run.run_date} 运行记录`">

              <!-- Card header — 两行分层 -->
              <div class="auto-card-head">
                <div class="auto-head-row1">
                  <span class="auto-date font-num">{{ run.run_date }}</span>
                  <span class="trigger-badge" :class="run.trigger === 'manual' ? 'trigger-manual' : 'trigger-auto'">
                    {{ triggerLabel(run.trigger) }}
                  </span>
                  <span class="sync-chip" :class="syncStatusClass(run.sync_status)">{{ syncStatusLabel(run.sync_status) }}</span>
                  <button
                    v-if="run.sync_status !== 'synced'"
                    class="sync-btn"
                    :disabled="syncing === run.id"
                    @click="syncRun(run.id)"
                  >
                    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true">
                      <path d="M14 8A6 6 0 0 1 2.5 12M2 8a6 6 0 0 1 11.5-4M2 4v4h4M14 12v-4h-4"/>
                    </svg>
                    {{ syncing === run.id ? '…' : '同步' }}
                  </button>
                </div>
                <div v-if="run.model_info" class="auto-head-row2">
                  <span class="model-info-text">{{ formatModelLabel(run.model_info) }} · {{ run.model_info.type === 'ensemble' ? '混合' : '单模型' }}</span>
                  <span class="match-count font-num">{{ run.match_ids?.length ?? 0 }} 场</span>
                </div>
              </div>

              <!-- 方案芯片横排（点击查看详情） -->
              <div v-if="run.schemes?.length" class="scheme-chips-row">
                <button
                  v-for="(scheme, si) in run.schemes"
                  :key="si"
                  type="button"
                  class="scheme-chip"
                  :class="`chip-st-${schemeStatus(scheme)}`"
                  @click="openDetail(run, scheme)"
                  :aria-label="`${planLabel(scheme.plan_id)}方案，${schemeStatusShort(scheme.status)}，点击查看详情`"
                >
                  <div class="sc-row1">
                    <span class="sc-type">{{ planLabel(scheme.plan_id) }}</span>
                    <svg width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true">
                      <path d="M2 3.5l3 3 3-3"/>
                    </svg>
                  </div>
                  <div class="sc-row2">
                    <span class="sc-odds font-num">×{{ calcSchemeOdds(scheme).toFixed(2) }}</span>
                    <span class="sc-status">{{ schemeStatusShort(scheme.status) }}</span>
                  </div>
                </button>
              </div>

              <!-- (inline legs panel removed — use detail sheet) -->
              <template v-if="false">
                <template v-for="(scheme, si) in run.schemes" :key="`elp-${run.id}-${si}`">
                  <div class="scheme-legs-panel">
                    <div class="auto-legs">
                      <div
                        v-for="(leg, li) in scheme.legs ?? []"
                        :key="li"
                        class="leg-row-auto"
                      >
                        <div class="leg-line1"></div>
                        <div class="leg-line2">
                          <span class="leg-pick-tag" :class="pickClass(leg.pick)">{{ pickLabel(leg.pick) }}</span>
                          <span class="leg-arrow">→</span>
                          <span v-if="leg.won !== undefined" :class="leg.won ? 'result-hit' : 'result-miss'">
                            {{ leg.won ? '命中' : '未中' }}
                          </span>
                          <span v-else class="leg-pending">待结算</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </template>
              </template>

              <!-- Card footer -->
              <div class="auto-card-foot">
                <span class="foot-label">每注</span>
                <span class="foot-val font-num">¥{{ run.stake }}</span>
                <span class="foot-sep-inline" />
                <span class="foot-label">{{ run.schemes?.length ?? 0 }} 个方案</span>
              </div>

            </article>
          </template>
        </div>

      </template>

      <!-- 方案详情底部弹窗 -->
      <Teleport to="body">
        <Transition name="sd-slide">
          <div v-if="detailInfo" class="sd-overlay" @click.self="closeDetail" role="dialog" aria-modal="true" :aria-label="`${planLabel(detailInfo.scheme.plan_id)}方案详情`">
            <div class="sd-sheet">
              <div class="sd-drag-bar" @click="closeDetail" role="button" aria-label="关闭" />

              <!-- 弹窗头部 -->
              <div class="sd-head">
                <div class="sd-head-left">
                  <span class="plan-badge" :class="detailInfo.scheme.plan_id">{{ planLabel(detailInfo.scheme.plan_id) }}</span>
                  <span class="status-badge" :class="`status-${schemeStatus(detailInfo.scheme)}`">{{ statusLabel(schemeStatus(detailInfo.scheme)) }}</span>
                </div>
                <div class="sd-odds-block">
                  <div class="sd-odds-val font-num">×{{ calcSchemeOdds(detailInfo.scheme).toFixed(2) }}</div>
                  <div class="sd-odds-label">{{ detailInfo.scheme.legs?.length ?? 0 }}串1</div>
                </div>
              </div>

              <!-- 运行元信息 -->
              <div class="sd-meta-row">
                <span class="sd-meta-date font-num">{{ detailInfo.run.run_date }}</span>
                <span class="sd-meta-sep">·</span>
                <span class="sd-meta-model">{{ formatModelLabel(detailInfo.run.model_info) }}</span>
                <span class="sd-meta-sep">·</span>
                <span class="sd-meta-trigger">{{ triggerLabel(detailInfo.run.trigger) }}</span>
              </div>

              <!-- 腿行列表 -->
              <div class="sd-legs">
                <div
                  v-for="(leg, li) in detailInfo.scheme.legs ?? []"
                  :key="li"
                  class="sd-leg"
                  :class="{ 'sd-leg--link': !!leg.match_id, 'sd-leg--won': leg.won === true, 'sd-leg--lost': leg.won === false }"
                  @click="leg.match_id && (closeDetail(), tryNavigateToMatch(leg.match_id))"
                  :role="leg.match_id ? 'button' : undefined"
                  :aria-label="leg.match_id ? `查看 ${leg.home_team ?? '主队'} vs ${leg.away_team ?? '客队'} 详情` : undefined"
                >
                  <!-- 结果指示线 -->
                  <div class="sd-leg-bar" :class="{ 'bar-won': leg.won === true, 'bar-lost': leg.won === false, 'bar-pending': leg.won === undefined }" />

                  <div class="sd-leg-content">
                    <div class="sd-leg-line1">
                      <span class="sd-leg-home">{{ leg.home_team ?? `赛事#${leg.match_id}` }}</span>
                      <span class="sd-leg-vs">vs</span>
                      <span class="sd-leg-away">{{ leg.away_team ?? '' }}</span>
                      <span v-if="leg.match_id" class="sd-leg-nav-icon" aria-hidden="true">›</span>
                    </div>
                    <div class="sd-leg-line2">
                      <span v-if="leg.league" class="sd-leg-league">{{ leg.league }}</span>
                      <span class="leg-pick-tag" :class="pickClass(leg.pick)">{{ pickLabel(leg.pick) }}</span>
                      <span class="sd-leg-odds font-num">×{{ leg.odds?.toFixed(2) ?? '—' }}</span>
                      <span class="sd-leg-arrow">→</span>
                      <span v-if="leg.won !== undefined" :class="leg.won ? 'result-hit sd-result' : 'result-miss sd-result'">
                        {{ leg.won ? '✓ 命中' : '✗ 未中' }}
                      </span>
                      <template v-else-if="leg.match_id && scoreMissingIds(detailInfo.run).has(leg.match_id)">
                        <template v-if="scoreEditing[leg.match_id]">
                          <input
                            class="score-input"
                            v-model="scoreInput[leg.match_id]"
                            placeholder="2-1"
                            maxlength="5"
                            @click.stop
                            @keyup.enter="submitScore(leg.match_id, detailInfo.run.id, $event)"
                          />
                          <button
                            class="score-ok-btn"
                            :disabled="scoreSubmitting[leg.match_id]"
                            @click="submitScore(leg.match_id, detailInfo.run.id, $event)"
                          >{{ scoreSubmitting[leg.match_id] ? '…' : '确认' }}</button>
                          <button class="score-cancel-btn" @click="closeScoreEntry(leg.match_id, $event)">✕</button>
                        </template>
                        <button v-else class="score-entry-btn" @click="openScoreEntry(leg.match_id, $event)">录入比分</button>
                      </template>
                      <span v-else class="sd-leg-pending">待结算</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 底部操作 -->
              <div class="sd-foot">
                <span class="sd-foot-info">每注 ¥{{ detailInfo.run.stake }} · 预期 ¥{{ (detailInfo.run.stake * calcSchemeOdds(detailInfo.scheme)).toFixed(0) }}</span>
                <button class="sd-close-btn" type="button" @click="closeDetail">关闭</button>
              </div>
            </div>
          </div>
        </Transition>
      </Teleport>

    </template>

  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; min-height: 100%; padding-bottom: 32px; }

/* ── 页面级 tab ───────────────────────────────────────────────── */
.page-tab-bar {
  display: flex;
  background: var(--card);
  border-bottom: var(--card-bd);
}
.ptab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 13px 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text3);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  font-family: var(--font);
  transition: color .12s, border-color .12s;
}
.ptab-on { color: var(--primary); border-bottom-color: var(--primary); }
.ptab-count {
  font-size: 10px;
  background: var(--bg);
  padding: 1px 5px;
  border-radius: 10px;
  color: var(--text3);
}
.ptab-on .ptab-count { background: color-mix(in srgb, var(--primary) 12%, transparent); color: var(--primary); }

/* ── Summary ─────────────────────────────────────────────────── */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border-bottom: 1px solid var(--line);
}
.sum-card {
  background: var(--card);
  padding: 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sum-label { font-size: 10px; color: var(--text3); }
.sum-val { font-size: 18px; font-weight: 700; line-height: 1; font-family: var(--font-disp); letter-spacing: -.2px; }
.sum-card--pos .sum-val { color: #22c55e; }
.sum-card--neg .sum-val { color: #ef4444; }
.sum-val-muted { color: var(--text3) !important; font-size: 16px; }

.sub-stats {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  background: var(--bg);
  border-bottom: var(--card-bd);
}
.sub-stat {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.sub-stat-val { font-size: 15px; font-weight: 700; }
.sub-stat-label { font-size: 10px; color: var(--text3); }
.text-green { color: #22c55e; }
.text-red   { color: #ef4444; }
.text-warning { color: #f59e0b; }

/* ── Filter tabs ─────────────────────────────────────────────── */
.filter-tabs {
  display: flex;
  border-bottom: var(--card-bd);
  background: var(--card);
  padding: 0 10px;
}
.filter-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 10px 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text3);
  background: transparent;
  cursor: pointer;
  font-family: var(--font);
  border-bottom: 2px solid transparent;
  transition: color .12s, border-color .12s;
}
.filter-tab.active { color: var(--primary); border-bottom-color: var(--primary); }
.filter-count {
  font-size: 10px;
  background: var(--bg);
  padding: 1px 5px;
  border-radius: 10px;
}
.filter-tab.active .filter-count { background: color-mix(in srgb, var(--primary) 12%, transparent); color: var(--primary); }

/* ── Loading / empty ─────────────────────────────────────────── */
.center-msg { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; padding: 60px 20px; }
.spin-ring { width: 26px; height: 26px; border: 2.5px solid var(--line); border-top-color: var(--primary); border-radius: 50%; animation: spin .8s linear infinite; }
.spin-ring--sm { width: 14px; height: 14px; border-width: 2px; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-msg { color: var(--text2); font-size: 13px; text-align: center; }
.empty-icon { color: var(--text3); margin-bottom: 4px; }
.empty-hint { font-size: 11px; color: var(--text3); }

/* ── Bet record timeline ─────────────────────────────────────── */
.timeline { display: flex; flex-direction: column; }
.bet-card {
  background: var(--card);
  border-bottom: var(--card-bd);
}

.bet-card-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 11px 14px 8px;
  gap: 8px;
}
.bet-head-left { display: flex; align-items: center; gap: 8px; min-width: 0; }
.plan-badge {
  font-size: 10px; font-weight: 700;
  padding: 2px 7px; border-radius: 4px;
  white-space: nowrap; flex-shrink: 0;
}
.plan-badge.conservative { background: color-mix(in srgb, #22c55e 12%, transparent); color: #16a34a; }
.plan-badge.balanced     { background: color-mix(in srgb, #3b82f6 12%, transparent); color: #2563eb; }
.plan-badge.high_odds    { background: color-mix(in srgb, #f59e0b 12%, transparent); color: #d97706; }
.plan-badge.scoreline    { background: color-mix(in srgb, #ef4444 12%, transparent); color: #dc2626; }
.plan-badge.manual       { background: var(--bg); color: var(--text3); }
.bet-date { font-size: 11px; color: var(--text3); white-space: nowrap; }
.parlay-label { font-size: 10px; color: var(--text3); }

.status-badge { font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px; white-space: nowrap; flex-shrink: 0; }
.status-won     { background: color-mix(in srgb, #22c55e 12%, transparent); color: #16a34a; }
.status-lost    { background: color-mix(in srgb, #ef4444 8%, transparent); color: #dc2626; }
.status-pending { background: color-mix(in srgb, #f59e0b 10%, transparent); color: #d97706; }
.status-void    { background: var(--bg); color: var(--text3); }

.legs-list {
  display: flex; flex-direction: column;
  padding: 0 14px;
  border-top: var(--card-bd);
  border-bottom: var(--card-bd);
}
.leg-row {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 0;
  border-bottom: var(--card-bd);
  font-size: 12px;
}
.leg-row:last-child { border-bottom: none; }
.leg-teams-col { display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0; overflow: hidden; }
.leg-team { color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 70px; }
.leg-vs { color: var(--text3); font-size: 10px; flex-shrink: 0; }
.leg-pick-tag { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 3px; flex-shrink: 0; }
.tag-win  { background: color-mix(in srgb, var(--primary) 14%, transparent); color: var(--primary); }
.tag-draw { background: color-mix(in srgb, #f59e0b 14%, transparent); color: #d97706; }
.tag-lose { background: color-mix(in srgb, #22c55e 14%, transparent); color: #16a34a; }
.tag-neutral { background: var(--bg); color: var(--text3); }
.leg-odds { font-size: 12px; font-weight: 700; color: var(--text2); flex-shrink: 0; }
.leg-result { flex-shrink: 0; font-size: 10px; font-weight: 600; }
.result-hit  { color: #22c55e; }
.result-miss { color: #ef4444; }

.bet-card-foot {
  display: flex; align-items: center;
  padding: 10px 14px;
}
.foot-cell { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.foot-label { font-size: 10px; color: var(--text3); }
.foot-val { font-size: 14px; font-weight: 700; }
.foot-sep { width: 1px; background: var(--line); align-self: stretch; margin: 0 8px; }
.foot-sep-inline { display: inline-block; width: 1px; height: 12px; background: var(--line); margin: 0 8px; vertical-align: middle; }

.del-btn {
  margin-left: 8px;
  width: 28px; height: 28px;
  border-radius: 6px;
  background: transparent;
  border: var(--card-bd);
  color: var(--text3);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: color .12s, border-color .12s;
}
.del-btn:hover { color: #ef4444; border-color: #ef4444; }
.del-btn:disabled { opacity: .4; }

.bet-note {
  font-size: 11px; color: var(--text3);
  padding: 0 14px 10px;
  font-style: italic;
}

/* ── Auto run cards ──────────────────────────────────────────── */
.auto-card {
  background: var(--card);
  border-bottom: var(--card-bd);
}
.auto-card-head {
  padding: 10px 14px 8px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.auto-head-row1 {
  display: flex;
  align-items: center;
  gap: 7px;
  flex-wrap: wrap;
}
.auto-head-row2 {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.auto-date { font-size: 13px; font-weight: 700; color: var(--text); }
.model-info-text { font-size: 10px; color: var(--text3); }
.match-count { font-size: 10px; color: var(--text3); }

.trigger-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
}
.trigger-manual { background: color-mix(in srgb, #3b82f6 12%, transparent); color: #2563eb; }
.trigger-auto   { background: color-mix(in srgb, #8b5cf6 12%, transparent); color: #7c3aed; }

.sync-chip {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
}
.chip-pending { background: color-mix(in srgb, #f59e0b 10%, transparent); color: #d97706; }
.chip-ok      { background: color-mix(in srgb, #22c55e 10%, transparent); color: #16a34a; }
.chip-warn    { background: color-mix(in srgb, #f97316 10%, transparent); color: #ea580c; }
.chip-err     { background: color-mix(in srgb, #ef4444 10%, transparent); color: #dc2626; }

.sync-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 4px;
  border: var(--card-bd);
  background: transparent;
  color: var(--text2);
  cursor: pointer;
  font-family: var(--font);
}
.sync-btn:disabled { opacity: .5; cursor: not-allowed; }

/* ── Scheme chips row ────────────────────────────────────────── */
.scheme-chips-row {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  border-top: 1px solid var(--line);
  scrollbar-width: none;
}
.scheme-chips-row::-webkit-scrollbar { display: none; }
.scheme-chip {
  flex: 1;
  min-width: 90px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 10px 12px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 6px;
  cursor: pointer;
  font-family: var(--font);
  text-align: left;
  transition: background .1s, border-color .1s;
  min-height: 56px;
}
.scheme-chip:active { background: color-mix(in srgb, var(--primary) 8%, var(--bg)); border-color: var(--primary); }
.scheme-chip.chip-open { background: color-mix(in srgb, var(--primary) 6%, var(--bg)); border-color: var(--primary); }

.sc-row1 { display: flex; align-items: center; justify-content: space-between; }
.sc-row2 { display: flex; align-items: center; justify-content: space-between; }
.sc-type { font-size: 11px; font-weight: 700; color: var(--text2); }
.sc-odds { font-size: 15px; font-weight: 800; color: var(--text); }
.sc-status { font-size: 10px; color: var(--text3); }
.sc-chevron { flex-shrink: 0; color: var(--text3); transition: transform .15s; }
.chip-st-won .sc-odds { color: #22c55e; }
.chip-st-won .sc-status { color: #22c55e; }
.chip-st-lost .sc-odds { color: var(--text3); text-decoration: line-through; }

/* ── Expandable legs panel ───────────────────────────────────── */
.scheme-legs-panel {
  border-top: 1px dashed var(--line);
  background: color-mix(in srgb, var(--primary) 2%, var(--bg));
}
.slp-head {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px 6px;
  flex-wrap: wrap;
}
.slp-meta { font-size: 11px; color: var(--text3); }

/* Dual-line leg rows */
.auto-legs { padding: 0 14px; }
.leg-row-auto {
  min-height: 48px;
  padding: 6px 0;
  border-bottom: var(--card-bd);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.leg-row-auto:last-child { border-bottom: none; }
.leg-row-auto--link { cursor: pointer; }
.leg-row-auto--link:active { background: color-mix(in srgb, var(--primary) 4%, transparent); margin: 0 -14px; padding: 6px 14px; }

.leg-line1 {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
}
.leg-line2 {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.leg-home, .leg-away { color: var(--text); max-width: 68px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.leg-vs { color: var(--text3); font-size: 10px; flex-shrink: 0; }
.leg-odds { font-weight: 700; color: var(--text2); flex-shrink: 0; margin-left: auto; }
.leg-arrow { color: var(--text3); font-size: 10px; flex-shrink: 0; }
.leg-pending { color: var(--text3); font-size: 10px; }

.auto-card-foot {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  font-size: 12px;
  color: var(--text3);
  border-top: var(--card-bd);
  gap: 4px;
}
.auto-card-foot .foot-val { font-size: 13px; font-weight: 700; color: var(--text); }

/* ── Load error banner ───────────────────────────────────────── */
.load-error-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  background: color-mix(in srgb, #ef4444 8%, var(--card));
  border-bottom: 1px solid color-mix(in srgb, #ef4444 20%, transparent);
  font-size: 12px;
  color: #dc2626;
}
.retry-link {
  background: transparent;
  border: none;
  color: #dc2626;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  font-family: var(--font);
  padding: 0;
  text-decoration: underline;
}

/* ── Skeleton loading ────────────────────────────────────────── */
.skel-card { animation: skel-pulse 1.4s ease-in-out infinite; }
@keyframes skel-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }

/* ── Empty state ─────────────────────────────────────────────── */
.empty-link {
  background: transparent;
  border: none;
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  font-family: var(--font);
  padding: 4px 0;
  text-decoration: underline;
}

/* ── Zone section wrapper ─────────────────────────────────────── */
.zone-section { background: var(--bg); }

/* ── Zone header ─────────────────────────────────────────────── */
.zone-header {
  font-size: 10px;
  font-weight: 700;
  color: var(--text3);
  letter-spacing: .06em;
  text-transform: uppercase;
  padding: 10px 14px 4px;
  background: var(--bg);
}

/* ── Accuracy scroll (ZONE 2 + 3) ───────────────────────────── */
.accuracy-scroll {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  padding: 8px 14px 12px;
  background: var(--bg);
  border-bottom: var(--card-bd);
  scrollbar-width: none;
}
.accuracy-scroll::-webkit-scrollbar { display: none; }

.acc-pill {
  flex-shrink: 0;
  min-width: 80px;
  min-height: 48px;
  padding: 10px 12px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.acc-pill--wide { min-width: 130px; }
.acc-pill-label { font-size: 10px; color: var(--text3); }
.acc-pill-type { font-size: 9px; color: var(--text3); }
.acc-pill-val { font-size: 16px; font-weight: 700; line-height: 1.1; }
.acc-pill-insufficient { font-size: 10px; color: var(--text3); font-weight: 500; }
.acc-pill-n { font-size: 9px; color: var(--text3); }

/* ── Skipped rows ────────────────────────────────────────────── */
.run-skipped {
  background: var(--card);
  border-bottom: var(--card-bd);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  padding: 10px 14px;
  gap: 6px;
}
.skipped-main {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  cursor: pointer;
}
.skipped-label {
  font-size: 10px;
  font-weight: 600;
  color: var(--text3);
  background: var(--bg);
  padding: 2px 6px;
  border-radius: 3px;
}
.skipped-toggle {
  min-width: 44px;
  min-height: 44px;
  background: transparent;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text3);
  padding: 0;
}
.skipped-detail {
  width: 100%;
  font-size: 11px;
  color: var(--text3);
  padding: 4px 0 2px;
}

/* ── Zone 1 Hero (auto tab) ─────────────────────────────────── */
.az1-hero-wrap {
  display: flex;
  align-items: stretch;
  background: var(--card);
  border-bottom: var(--card-bd);
  padding: 18px 14px;
}
.az1-left {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 16px;
}
.az1-hero-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--text3);
  letter-spacing: .06em;
  text-transform: uppercase;
}
.az1-hero-val {
  font-size: 40px;
  font-weight: 800;
  line-height: 1;
  letter-spacing: -2px;
  font-family: var(--font-disp);
}
.az1-hero-sub {
  font-size: 11px;
  color: var(--text3);
  margin-top: 3px;
}
.az1-muted { color: var(--text3) !important; }
.az1-no-data { font-size: 15px; font-weight: 500; color: var(--text3); letter-spacing: 0; }
.az1-right {
  display: flex;
  align-items: center;
  border-left: 1px solid var(--line);
  padding-left: 16px;
}
.az1-stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 0 10px;
}
.az1-stat-val {
  font-size: 18px;
  font-weight: 700;
  line-height: 1;
  font-family: var(--font-disp);
  color: var(--text);
}
.az1-stat-label {
  font-size: 10px;
  color: var(--text3);
  white-space: nowrap;
}
.az1-divider {
  width: 1px;
  align-self: stretch;
  background: var(--line);
  margin: 4px 0;
}

/* ── Zone 2 Scheme accuracy grid ─────────────────────────────── */
.scheme-acc-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border-bottom: var(--card-bd);
}
.scheme-acc-cell {
  background: var(--card);
  padding: 12px 10px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 72px;
}
.scheme-acc-label {
  font-size: 10px;
  color: var(--text3);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.scheme-acc-val {
  font-size: 22px;
  font-weight: 800;
  line-height: 1;
  font-family: var(--font-disp);
  letter-spacing: -.5px;
}
.scheme-acc-insufficient {
  font-size: 12px !important;
  color: var(--text3) !important;
  font-weight: 400 !important;
  letter-spacing: 0 !important;
}
.scheme-acc-n {
  font-size: 9px;
  color: var(--text3);
}

/* ── Zone 3 model pills (larger) ─────────────────────────────── */
.acc-pill--wide {
  min-width: 148px;
  min-height: 68px;
  padding: 12px 14px;
  cursor: pointer;
  text-align: left;
  background: var(--card);
  border: 1px solid var(--line);
  font-family: var(--font);
  transition: border-color .12s, background .12s;
}
.acc-pill--wide .acc-pill-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text2);
  display: flex;
  align-items: center;
  gap: 5px;
}
.acc-pill--wide .acc-pill-type { font-size: 10px; }
.acc-pill--wide .acc-pill-val { font-size: 20px; }

/* ── Interactive filter states ───────────────────────────────── */
.scheme-acc-cell {
  cursor: pointer;
  border: none;
  font-family: var(--font);
  text-align: left;
  transition: background .12s;
}
.scheme-acc-cell:active { opacity: .85; }
.sac-active {
  background: color-mix(in srgb, var(--primary) 8%, var(--card)) !important;
  outline: 2px solid var(--primary);
  outline-offset: -2px;
}
.sac-best { position: relative; }

.acc-pill-active {
  border-color: var(--primary) !important;
  background: color-mix(in srgb, var(--primary) 8%, var(--card)) !important;
}
.acc-pill-best {
  border-color: color-mix(in srgb, #22c55e 60%, var(--line)) !important;
}

/* ── Zone 6 Pick accuracy bars ────────────────────────────────── */
.par-list { padding: 8px 14px 14px; display: flex; flex-direction: column; gap: 8px; border-bottom: var(--card-bd); }
.par-row { display: flex; align-items: center; gap: 8px; min-height: 28px; }
.par-label {
  width: 52px; font-size: 11px; font-weight: 600; color: var(--text2);
  flex-shrink: 0; display: flex; align-items: center; gap: 4px;
}
.par-bar-track {
  flex: 1; height: 6px; background: var(--line); border-radius: 3px; overflow: hidden;
}
.par-bar-fill { height: 100%; border-radius: 3px; transition: width .3s ease; min-width: 2px; }
.text-green-bar   { background: #22c55e; }
.text-warning-bar { background: #f59e0b; }
.text-red-bar     { background: #ef4444; }
.muted-bar        { background: var(--line); opacity: .5; }
.par-pct   { width: 36px; font-size: 13px; font-weight: 700; text-align: right; flex-shrink: 0; }
.par-detail { width: 36px; font-size: 9px; color: var(--text3); text-align: right; flex-shrink: 0; }

/* ── Best badge ──────────────────────────────────────────────── */
.best-badge {
  font-size: 9px;
  font-weight: 700;
  background: #22c55e;
  color: #fff;
  padding: 1px 4px;
  border-radius: 3px;
  letter-spacing: .02em;
  line-height: 1.4;
  flex-shrink: 0;
}

/* ── Zone 4 Parlay accuracy chips ────────────────────────────── */
.parlay-chip {
  flex-shrink: 0;
  min-width: 90px;
  min-height: 72px;
  padding: 12px 14px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  font-family: var(--font);
  text-align: left;
  transition: border-color .12s, background .12s;
}
.pc-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text2);
  display: flex;
  align-items: center;
  gap: 5px;
}
.pc-val { font-size: 22px; font-weight: 800; line-height: 1; font-family: var(--font-disp); letter-spacing: -.5px; }
.pc-insufficient { font-size: 12px !important; color: var(--text3) !important; font-weight: 400 !important; letter-spacing: 0 !important; }
.pc-n { font-size: 9px; color: var(--text3); }
.parlay-chip-active {
  border-color: var(--primary) !important;
  background: color-mix(in srgb, var(--primary) 8%, var(--card)) !important;
}
.parlay-chip-best {
  border-color: color-mix(in srgb, #22c55e 60%, var(--line)) !important;
}

/* ── Filter active bar ───────────────────────────────────────── */
.filter-active-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: color-mix(in srgb, var(--primary) 6%, var(--bg));
  border-bottom: 1px solid color-mix(in srgb, var(--primary) 20%, transparent);
  font-size: 12px;
  color: var(--text2);
}
.fab-info { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; }
.fab-chip {
  background: color-mix(in srgb, var(--primary) 15%, transparent);
  color: var(--primary);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 10px;
}
.fab-clear {
  background: transparent;
  border: none;
  color: var(--primary);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  font-family: var(--font);
  padding: 4px 8px;
  flex-shrink: 0;
}

/* ── Zone 7 Result distribution ──────────────────────────────── */
.rdr-strip {
  display: flex;
  background: var(--card);
  border-bottom: var(--card-bd);
}
.rdr-cell {
  flex: 1;
  padding: 12px 10px 14px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  border-right: 1px solid var(--line);
}
.rdr-cell:last-child { border-right: none; }
.rdr-label  { font-size: 10px; color: var(--text3); font-weight: 600; letter-spacing: .04em; }
.rdr-pct    { font-size: 24px; font-weight: 800; line-height: 1; font-family: var(--font-disp); letter-spacing: -.5px; }
.rdr-H { color: var(--primary); }
.rdr-D { color: #f59e0b; }
.rdr-A { color: #22c55e; }
.rdr-bar-track { width: 100%; height: 4px; background: var(--line); border-radius: 2px; overflow: hidden; }
.rdr-bar        { height: 100%; border-radius: 2px; transition: width .3s ease; }
.rdr-bar-H { background: var(--primary); }
.rdr-bar-D { background: #f59e0b; }
.rdr-bar-A { background: #22c55e; }
.rdr-n { font-size: 9px; color: var(--text3); }

/* ── Zone 8 ROI analysis rows ─────────────────────────────────── */
.roi-rows { padding: 8px 14px 16px; display: flex; flex-direction: column; gap: 12px; border-bottom: var(--card-bd); }
.roi-row  { display: flex; align-items: center; gap: 10px; }
.roi-name { width: 52px; font-size: 11px; font-weight: 600; color: var(--text2); flex-shrink: 0; }
.roi-bar-track { flex: 1; height: 8px; background: var(--line); border-radius: 4px; overflow: hidden; }
.roi-bar-fill  { height: 100%; border-radius: 4px; transition: width .3s ease; min-width: 2px; }
.roi-pos { background: #22c55e; }
.roi-neg { background: #ef4444; }
.roi-right { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; min-width: 94px; flex-shrink: 0; }
.roi-profit { font-size: 14px; font-weight: 700; line-height: 1; }
.roi-meta   { font-size: 9px; color: var(--text3); }

/* ── Scheme detail bottom sheet (Teleport'd, use :global) ────── */
</style>

<style>
.sd-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.55);
  z-index: 1000;
  display: flex;
  align-items: flex-end;
}
.sd-sheet {
  width: 100%;
  max-height: 82vh;
  background: var(--card, #1a1a1a);
  border-radius: 14px 14px 0 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sd-drag-bar {
  width: 36px;
  height: 4px;
  border-radius: 2px;
  background: var(--line, rgba(255,255,255,.12));
  margin: 10px auto 6px;
  cursor: pointer;
  flex-shrink: 0;
}
.sd-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px 12px;
  border-bottom: 1px solid var(--line, rgba(255,255,255,.08));
  flex-shrink: 0;
}
.sd-head-left { display: flex; align-items: center; gap: 8px; }
.sd-odds-block { text-align: right; }
.sd-odds-val { font-size: 28px; font-weight: 800; line-height: 1; letter-spacing: -1px; font-family: var(--font-disp, inherit); color: var(--text, #fff); }
.sd-odds-label { font-size: 11px; color: var(--text3, rgba(255,255,255,.4)); text-align: right; }
.sd-meta-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  font-size: 12px;
  color: var(--text3, rgba(255,255,255,.4));
  background: var(--bg, #111);
  border-bottom: 1px solid var(--line, rgba(255,255,255,.08));
  flex-shrink: 0;
  flex-wrap: wrap;
}
.sd-meta-date { font-weight: 600; color: var(--text2, rgba(255,255,255,.7)); }
.sd-meta-sep { opacity: .4; }
.sd-meta-model { font-weight: 600; color: var(--text2, rgba(255,255,255,.7)); }
.sd-legs {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
.sd-leg {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid var(--line, rgba(255,255,255,.06));
  min-height: 56px;
}
.sd-leg:last-child { border-bottom: none; }
.sd-leg--link { cursor: pointer; }
.sd-leg--link:active { background: rgba(255,255,255,.03); }
.sd-leg-bar {
  width: 3px;
  flex-shrink: 0;
  border-radius: 0;
}
.bar-won    { background: #22c55e; }
.bar-lost   { background: #ef4444; }
.bar-pending { background: var(--line, rgba(255,255,255,.08)); }
.sd-leg-content {
  flex: 1;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.sd-leg-line1 {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text, #fff);
}
.sd-leg-line2 {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
}
.sd-leg-home, .sd-leg-away {
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sd-leg-vs { color: var(--text3, rgba(255,255,255,.4)); font-size: 10px; flex-shrink: 0; }
.sd-leg-nav-icon { margin-left: auto; color: var(--text3, rgba(255,255,255,.3)); font-size: 16px; flex-shrink: 0; }
.sd-leg-league {
  font-size: 10px;
  color: var(--text3, rgba(255,255,255,.4));
  background: var(--bg, rgba(255,255,255,.04));
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
}
.sd-leg-odds { font-weight: 700; color: var(--text2, rgba(255,255,255,.7)); flex-shrink: 0; }
.sd-leg-arrow { color: var(--text3, rgba(255,255,255,.3)); flex-shrink: 0; }
.sd-result { font-weight: 700; flex-shrink: 0; }
.sd-leg-pending { color: var(--text3, rgba(255,255,255,.4)); font-size: 10px; }

/* 手动比分录入 */
.score-entry-btn {
  font-size: 10px; font-weight: 600;
  padding: 2px 7px; border-radius: 4px;
  border: 1px solid rgba(99,179,237,.5);
  color: #63b3ed; background: rgba(99,179,237,.08);
  cursor: pointer; flex-shrink: 0;
}
.score-entry-btn:active { background: rgba(99,179,237,.18); }
.score-input {
  width: 52px; font-size: 11px; text-align: center;
  background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.15);
  border-radius: 4px; color: var(--text1); padding: 2px 5px;
  outline: none;
}
.score-input:focus { border-color: rgba(99,179,237,.6); }
.score-ok-btn {
  font-size: 10px; font-weight: 600; padding: 2px 7px;
  border-radius: 4px; border: 1px solid rgba(72,187,120,.5);
  color: #48bb78; background: rgba(72,187,120,.1); cursor: pointer;
}
.score-ok-btn:disabled { opacity: .5; cursor: default; }
.score-cancel-btn {
  font-size: 10px; padding: 2px 5px; border-radius: 4px;
  border: 1px solid rgba(255,255,255,.1); color: var(--text3);
  background: transparent; cursor: pointer;
}
.sd-leg--won .sd-leg-line1 { color: var(--text, #fff); }
.sd-leg--lost .sd-leg-line1 { color: var(--text3, rgba(255,255,255,.5)); }
.sd-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px max(16px, env(safe-area-inset-bottom));
  border-top: 1px solid var(--line, rgba(255,255,255,.08));
  background: var(--bg, #111);
  flex-shrink: 0;
}
.sd-foot-info { font-size: 12px; color: var(--text3, rgba(255,255,255,.4)); }
.sd-close-btn {
  background: var(--primary, #e53935);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 10px 24px;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--font, sans-serif);
}

/* ── Sheet slide-up transition ───────────────────────────────── */
.sd-slide-enter-active { transition: opacity .2s, transform .25s cubic-bezier(.32,1,.28,1); }
.sd-slide-leave-active { transition: opacity .15s, transform .2s ease-in; }
.sd-slide-enter-from  { opacity: 0; }
.sd-slide-leave-to    { opacity: 0; }
.sd-slide-enter-from .sd-sheet  { transform: translateY(100%); }
.sd-slide-leave-to   .sd-sheet  { transform: translateY(100%); }
</style>
