<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api, { betsApi, type BetRecord, type BetSummary } from '@/api'
import InfoTip from '@/components/InfoTip.vue'

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
  model_info: { llms: string[]; type: string; tokens?: { prompt: number; completion: number } } | null
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
  if (/主胜/.test(pick)) return 'pick-win'
  if (/^平/.test(pick))  return 'pick-draw'
  if (/客胜/.test(pick)) return 'pick-lose'
  return 'pick-neutral'
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
  if (rate >= 60) return 'text-g'
  if (rate >= 40) return 'text-amber'
  return 'text-r'
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

const scoreEditing = ref<Record<number, boolean>>({})
const scoreInput = ref<Record<number, string>>({})
const scoreSubmitting = ref<Record<number, boolean>>({})

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

// 统计区块折叠控制
const statsExpanded = ref(false)

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
      const pid = scheme.plan_id.replace(/_cover$/, '')
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
  return Object.fromEntries(Object.entries(groups).sort((a, b) => a[1].order - b[1].order))
})
const hasPickData = computed(() =>
  Object.values(pickAccuracy.value).some(a => a.total > 0)
)

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

interface SchemeRoiAcc { stake: number; profit: number; count: number }
const schemeRoi = computed<Record<string, SchemeRoiAcc>>(() => {
  const groups: Record<string, SchemeRoiAcc> = {}
  for (const run of autoRuns.value) {
    for (const scheme of run.schemes ?? []) {
      if (scheme.status === 'pending' || scheme.profit == null) continue
      const pid = scheme.plan_id.replace(/_cover$/, '')
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

    <!-- ── Tab 栏 ───────────────────────────────────────────────── -->
    <div class="tab-rail">
      <button class="tab-btn" :class="{ 'tab-btn--on': pageTab === 'records' }" @click="pageTab = 'records'">
        投注记录
        <span v-if="summary?.total_bets" class="tab-cnt" :class="{ 'tab-cnt--on': pageTab === 'records' }">{{ summary.total_bets }}</span>
      </button>
      <button class="tab-btn" :class="{ 'tab-btn--on': pageTab === 'auto' }" @click="switchToAuto">
        自动出票
        <span v-if="autoSummary?.total_runs" class="tab-cnt" :class="{ 'tab-cnt--on': pageTab === 'auto' }">{{ autoSummary.total_runs }}</span>
      </button>
    </div>

    <!-- ════════════════════════════════════════════════════════════
         投注记录 Tab
    ═══════════════════════════════════════════════════════════════ -->
    <template v-if="pageTab === 'records'">

      <!-- KPI 总览 -->
      <div class="kpi-grid">
        <div class="kpi-cell">
          <div class="kpi-label">累计投入</div>
          <div class="kpi-val">¥{{ summary?.total_stake?.toFixed(0) ?? '—' }}</div>
        </div>
        <div class="kpi-cell" :class="{ 'kpi--pos': (summary?.profit ?? 0) >= 0, 'kpi--neg': (summary?.profit ?? 0) < 0 }">
          <div class="kpi-label">总盈亏 <InfoTip text="实际盈利或亏损金额（元）。= 总奖金 − 总投入。正数为盈利，负数为亏损。" /></div>
          <div class="kpi-val">{{ profitSign(summary?.profit) }}{{ summary?.profit?.toFixed(0) ?? '—' }}</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">ROI <InfoTip text="投资回报率（%）= 盈亏 ÷ 总投入 × 100。>0 表示盈利，常见彩票长期ROI约-25%到-50%，突破0%即跑赢彩票基准线。" /></div>
          <div class="kpi-val" :class="(summary?.roi ?? 0) >= 0 ? 'text-g' : 'text-r'">{{ profitSign(summary?.roi) }}{{ summary?.roi?.toFixed(1) ?? '—' }}%</div>
        </div>
        <div class="kpi-cell">
          <div class="kpi-label">串票命中 <InfoTip text="串关方案全部命中的比例（%）。串关需要所有腿同时中奖，3串1每腿60%胜率时全串中奖率约22%，属正常水平。" /></div>
          <div class="kpi-val" :class="hitRateClass(summary?.hit_rate ?? 0)">{{ summary?.hit_rate?.toFixed(1) ?? '—' }}%</div>
        </div>
      </div>

      <!-- 二级数据 -->
      <div v-if="summary" class="aux-strip">
        <div class="aux-item">
          <div class="aux-val">{{ summary.total_bets }}</div>
          <div class="aux-lbl">总注数</div>
        </div>
        <div class="aux-div" />
        <div class="aux-item">
          <div class="aux-val text-g">{{ summary.won_bets }}</div>
          <div class="aux-lbl">已中奖</div>
        </div>
        <div class="aux-div" />
        <div class="aux-item">
          <div class="aux-val text-amber">{{ summary.total_bets - summary.settled_bets }}</div>
          <div class="aux-lbl">待结算</div>
        </div>
        <div class="aux-div" />
        <div class="aux-item">
          <div class="aux-val">¥{{ summary.pending_stake.toFixed(0) }}</div>
          <div class="aux-lbl">挂单额</div>
        </div>
      </div>

      <!-- 筛选栏 -->
      <div class="filter-rail">
        <button
          v-for="f in (['all','pending','won','lost'] as const)"
          :key="f"
          class="filter-btn"
          :class="{ 'filter-btn--on': filter === f }"
          @click="filter = f"
        >
          {{ { all:'全部', pending:'待结算', won:'已中', lost:'未中' }[f] }}
          <span class="filter-n">{{ f === 'all' ? records.length : records.filter(r => r.status === f).length }}</span>
        </button>
      </div>

      <!-- 加载 -->
      <div v-if="loading" class="center-box">
        <div class="spinner" />
      </div>

      <!-- 空状态 -->
      <div v-else-if="!filtered.length" class="empty-box">
        <svg width="44" height="44" viewBox="0 0 44 44" fill="none" stroke="currentColor" stroke-width="1.3" class="empty-icon">
          <rect x="8" y="10" width="28" height="26" rx="5"/>
          <path d="M15 22h14M15 16h10M15 28h8"/>
        </svg>
        <p class="empty-title">{{ filter === 'all' ? '还没有投注记录' : `暂无${({ pending:'待结算', won:'已中', lost:'未中' } as Record<string,string>)[filter]}记录` }}</p>
        <p class="empty-hint">在投注方案页标记您购买的方案</p>
      </div>

      <!-- 投注记录列表 -->
      <div v-else class="card-list">
        <div v-for="record in filtered" :key="record.id" class="bet-card" :class="`bet-card--${record.status}`">

          <!-- 卡头 -->
          <div class="bet-head">
            <div class="bet-head-l">
              <span class="plan-tag" :class="`plan-${record.plan_id}`">{{ planLabel(record.plan_id) }}</span>
              <span class="meta-txt">{{ formatDate(record.bet_at) }}</span>
              <span class="meta-txt">{{ record.legs.length }}串1</span>
            </div>
            <span class="status-tag" :class="`status-${record.status}`">{{ statusLabel(record.status) }}</span>
          </div>

          <!-- 腿列表 -->
          <div class="legs-wrap">
            <div v-for="(leg, i) in record.legs" :key="i" class="leg-row">
              <div class="leg-teams">
                <span class="leg-team">{{ leg.home_team }}</span>
                <span class="leg-vs">vs</span>
                <span class="leg-team">{{ leg.away_team }}</span>
              </div>
              <span class="pick-tag" :class="pickClass(leg.pick)">{{ pickLabel(leg.pick) }}</span>
              <span class="leg-odds">×{{ leg.odds?.toFixed(2) ?? '—' }}</span>
              <span v-if="leg.actual_result" class="leg-res" :class="isHit(leg.pick, leg.actual_result) ? 'text-g' : 'text-r'">
                {{ ({ H:'主胜', D:'平', A:'客胜' } as Record<string,string>)[leg.actual_result] ?? leg.actual_result }}
              </span>
            </div>
          </div>

          <!-- 卡脚 -->
          <div class="bet-foot">
            <div class="foot-kv">
              <span class="foot-k">投注</span>
              <span class="foot-v">¥{{ record.stake }}</span>
            </div>
            <div class="foot-sep" />
            <div class="foot-kv">
              <span class="foot-k">预期</span>
              <span class="foot-v">¥{{ record.expected_payout?.toFixed(0) ?? '—' }}</span>
            </div>
            <div class="foot-sep" />
            <div v-if="record.status !== 'pending'" class="foot-kv">
              <span class="foot-k">盈亏</span>
              <span class="foot-v" :class="(record.profit ?? 0) >= 0 ? 'text-g' : 'text-r'">{{ profitSign(record.profit) }}{{ record.profit?.toFixed(0) ?? '—' }}</span>
            </div>
            <div v-else class="foot-kv">
              <span class="foot-k">待结算</span>
              <span class="foot-v text-amber">¥{{ record.stake }}</span>
            </div>
            <button v-if="record.status === 'pending'" class="del-btn" :disabled="deleting === record.id" @click="deleteRecord(record.id)" aria-label="删除">
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
         自动出票 Tab — 预测质量看板
    ═══════════════════════════════════════════════════════════════ -->
    <template v-else>

      <!-- Error banner -->
      <div v-if="loadError" role="alert" class="err-bar">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1a7 7 0 1 0 0 14A7 7 0 0 0 8 1zm-.75 3.5h1.5v4.5h-1.5V4.5zm0 6h1.5v1.5h-1.5V10.5z"/></svg>
        {{ loadError }}
        <button class="err-retry" @click="loadAuto">重试</button>
      </div>

      <!-- 骨架屏 -->
      <template v-if="autoLoading">
        <div class="kpi-grid">
          <div v-for="i in 4" :key="i" class="kpi-cell skel" style="min-height:64px" />
        </div>
        <div class="card-list">
          <div v-for="i in 3" :key="i" class="bet-card skel" style="min-height:110px" />
        </div>
      </template>

      <!-- 空状态 -->
      <div v-else-if="!autoRuns.length && !loadError" class="empty-box">
        <svg width="44" height="44" viewBox="0 0 44 44" fill="none" stroke="currentColor" stroke-width="1.3" class="empty-icon">
          <circle cx="22" cy="22" r="15"/>
          <path d="M22 13v10l6 3"/>
        </svg>
        <p class="empty-title">等待首次自动分析</p>
        <button class="empty-link" @click="router.push('/settings')">前往设置配置定时出票 →</button>
      </div>

      <template v-else>

        <!-- ZONE 1 — 英雄总览 -->
        <div class="hero-zone">
          <div class="hero-main">
            <div class="hero-label">总命中率</div>
            <div class="hero-rate" :class="syncedCount > 0 && autoSummary ? hitRateClass(autoSummary.hit_rate) : 'text-muted'">
              <template v-if="syncedCount > 0 && autoSummary">{{ autoSummary.hit_rate.toFixed(1) }}%</template>
              <span v-else>暂无数据</span>
            </div>
            <div class="hero-sub">
              {{ syncedCount > 0 && autoSummary
                ? `${autoSummary.won_schemes} 中 / ${autoSummary.total_schemes} 次 串票`
                : '等待赛果结算' }}
            </div>
          </div>
          <div class="hero-stats">
            <div class="hero-stat-item">
              <div class="hero-stat-val">{{ autoSummary?.total_runs ?? autoRuns.length }}</div>
              <div class="hero-stat-lbl">运行次数</div>
            </div>
            <div class="hero-stat-sep" />
            <div class="hero-stat-item">
              <div class="hero-stat-val text-g">{{ syncedCount }}</div>
              <div class="hero-stat-lbl">已结算</div>
            </div>
            <div class="hero-stat-sep" />
            <div class="hero-stat-item">
              <div class="hero-stat-val" style="color:var(--text3)">{{ skippedCount }}</div>
              <div class="hero-stat-lbl">已跳过</div>
            </div>
            <div v-if="autoSummary && syncedCount > 0" class="hero-stat-sep" />
            <div v-if="autoSummary && syncedCount > 0" class="hero-stat-item">
              <div class="hero-stat-val" :class="autoSummary.profit >= 0 ? 'text-g' : 'text-r'">
                {{ autoSummary.profit >= 0 ? '+' : '' }}¥{{ autoSummary.profit.toFixed(0) }}
              </div>
              <div class="hero-stat-lbl">总盈亏</div>
            </div>
          </div>
        </div>

        <!-- 分析折叠开关 -->
        <button class="stats-toggle-btn" @click="statsExpanded = !statsExpanded" :aria-expanded="statsExpanded">
          <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor" :style="statsExpanded ? 'transform:rotate(180deg);transition:.2s' : 'transition:.2s'">
            <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
          </svg>
          {{ statsExpanded ? '收起命中分析' : '查看命中分析' }}
          <span v-if="activeFilterCount > 0 && !statsExpanded" class="stats-toggle-filter">{{ activeFilterCount }} 个筛选生效</span>
        </button>

        <!-- ZONE 2-8 折叠区 -->
        <div v-show="statsExpanded">

        <!-- ZONE 2 — 方案命中率 (4格) -->
        <div class="zone">
          <div class="zone-hd">方案命中率 <span class="zone-hint">点击筛选历史</span></div>
          <div class="acc4-grid">
            <button
              v-for="(acc, planId) in schemeAccuracy"
              :key="planId"
              type="button"
              class="acc4-cell"
              :class="{ 'acc4-cell--on': typeFilter === String(planId), 'acc4-cell--best': bestKey(schemeAccuracy) === String(planId) && acc.total >= 5 }"
              @click="toggleTypeFilter(String(planId))"
              :aria-label="`${acc.label}方案，${acc.total >= 5 ? (acc.won / acc.total * 100).toFixed(0) + '%' : '数据不足'}`"
            >
              <div class="acc4-name">
                {{ acc.label }}
                <span v-if="bestKey(schemeAccuracy) === String(planId) && acc.total >= 5" class="best-badge">最佳</span>
              </div>
              <div v-if="acc.total === 0" class="acc4-rate acc4-na">—</div>
              <div v-else-if="acc.total < 5" class="acc4-rate acc4-na">数据少</div>
              <div v-else class="acc4-rate" :class="hitRateClass(acc.won / acc.total * 100)">
                {{ (acc.won / acc.total * 100).toFixed(0) }}%
              </div>
              <div class="acc4-bar-track">
                <div
                  class="acc4-bar-fill"
                  :class="acc.total >= 5 ? hitRateClass(acc.won / acc.total * 100) + '-bar' : 'muted-bar'"
                  :style="acc.total > 0 ? `width:${(acc.won / acc.total * 100).toFixed(0)}%` : 'width:0%'"
                />
              </div>
              <div class="acc4-n">{{ acc.won }}/{{ acc.total }}</div>
            </button>
          </div>
        </div>

        <!-- ZONE 3 — 模型命中率 -->
        <div v-if="hasAnyModelRuns" class="zone">
          <div class="zone-hd">模型命中率 <span class="zone-hint">点击筛选</span></div>
          <div class="hscroll">
            <button
              v-for="(acc, modelKey) in modelAccuracy"
              :key="modelKey"
              type="button"
              class="model-card"
              :class="{ 'model-card--on': modelFilter === String(modelKey), 'model-card--best': bestKey(modelAccuracy) === String(modelKey) && acc.total >= 5 }"
              @click="toggleModelFilter(String(modelKey))"
            >
              <div class="mc-header">
                <span class="mc-name">{{ acc.label }}</span>
                <span v-if="bestKey(modelAccuracy) === String(modelKey) && acc.total >= 5" class="best-badge">最佳</span>
              </div>
              <div class="mc-type">{{ acc.type === 'ensemble' ? '混合分析' : '单模型' }}</div>
              <div v-if="acc.total === 0" class="mc-rate mc-na">待结算</div>
              <div v-else-if="acc.total < 5" class="mc-rate mc-na">数据不足</div>
              <div v-else class="mc-rate" :class="hitRateClass(acc.won / acc.total * 100)">
                {{ (acc.won / acc.total * 100).toFixed(0) }}%
              </div>
              <div class="acc4-bar-track" style="margin-top:4px">
                <div class="acc4-bar-fill"
                  :class="acc.total >= 5 ? hitRateClass(acc.won / acc.total * 100) + '-bar' : 'muted-bar'"
                  :style="acc.total > 0 ? `width:${(acc.won / acc.total * 100).toFixed(0)}%` : 'width:0%'" />
              </div>
              <div class="acc4-n">{{ acc.won }}/{{ acc.total }}</div>
            </button>
          </div>
        </div>

        <!-- ZONE 4 — 串数命中率 -->
        <div v-if="hasParlayData" class="zone">
          <div class="zone-hd">串数命中率 <span class="zone-hint">点击筛选</span></div>
          <div class="hscroll">
            <button
              v-for="(acc, n) in parlayAccuracy"
              :key="n"
              type="button"
              class="parlay-card"
              :class="{ 'parlay-card--on': parlayFilter === Number(n), 'parlay-card--best': bestKey(parlayAccuracy) === String(n) && acc.total >= 5 }"
              @click="toggleParlayFilter(Number(n))"
            >
              <div class="pc-name">{{ n }}串1<span v-if="bestKey(parlayAccuracy) === String(n) && acc.total >= 5" class="best-badge">最佳</span></div>
              <div v-if="acc.total === 0" class="mc-rate mc-na">—</div>
              <div v-else-if="acc.total < 5" class="mc-rate mc-na">少</div>
              <div v-else class="mc-rate" :class="hitRateClass(acc.won / acc.total * 100)">{{ (acc.won / acc.total * 100).toFixed(0) }}%</div>
              <div class="acc4-n">n={{ acc.total }}</div>
            </button>
          </div>
        </div>

        <!-- ZONE 5 — 联赛命中率 -->
        <div v-if="hasLeagueData" class="zone">
          <div class="zone-hd">联赛命中率（单腿）</div>
          <div class="hscroll">
            <div
              v-for="(acc, league) in leagueAccuracy"
              :key="league"
              class="league-card"
              :class="{ 'league-card--best': bestKey(leagueAccuracy) === String(league) && acc.total >= 5 }"
            >
              <div class="lc-name">{{ league }}<span v-if="bestKey(leagueAccuracy) === String(league) && acc.total >= 5" class="best-badge">最佳</span></div>
              <div v-if="acc.total >= 5" class="lc-rate" :class="hitRateClass(acc.won / acc.total * 100)">{{ (acc.won / acc.total * 100).toFixed(0) }}%</div>
              <div v-else class="lc-rate mc-na">少</div>
              <div class="acc4-n">{{ acc.total }} 场</div>
            </div>
          </div>
        </div>

        <!-- ZONE 6 — 选项命中率（横向条形图） -->
        <div v-if="hasPickData" class="zone">
          <div class="zone-hd">选项命中率（单场腿级）</div>
          <div class="bar-chart">
            <div
              v-for="(acc, key) in pickAccuracy"
              :key="key"
              class="bar-row"
            >
              <span class="bar-lbl">{{ acc.label }}<span v-if="bestKey(pickAccuracy) === String(key) && acc.total >= 5" class="best-badge">★</span></span>
              <div class="bar-track">
                <div
                  class="bar-fill"
                  :class="acc.total >= 3 ? hitRateClass(acc.won / acc.total * 100) + '-bar' : 'muted-bar'"
                  :style="acc.total > 0 ? `width:${(acc.won / acc.total * 100).toFixed(0)}%` : 'width:0%'"
                />
              </div>
              <span class="bar-pct" :class="acc.total >= 3 ? hitRateClass(acc.won / acc.total * 100) : 'text-muted'">
                {{ acc.total >= 3 ? (acc.won / acc.total * 100).toFixed(0) + '%' : acc.total > 0 ? '少' : '—' }}
              </span>
              <span class="bar-detail">{{ acc.won }}/{{ acc.total }}</span>
            </div>
          </div>
        </div>

        <!-- ZONE 7 — 赛果分布 -->
        <div v-if="hasResultData" class="zone">
          <div class="zone-hd">赛果分布 <span class="zone-hint">{{ resultTotal }} 场已结算</span></div>
          <div class="dist-strip">
            <div v-for="(count, result) in resultDistribution" :key="result" class="dist-cell" :class="`dist-${result}`">
              <div class="dist-name">{{ { H:'主胜', D:'平局', A:'客胜' }[result] ?? result }}</div>
              <div class="dist-pct">{{ resultTotal > 0 ? (count / resultTotal * 100).toFixed(0) : 0 }}%</div>
              <div class="dist-track">
                <div class="dist-fill" :class="`dfill-${result}`" :style="`width:${resultTotal > 0 ? (count / resultTotal * 100).toFixed(0) : 0}%`" />
              </div>
              <div class="dist-n">{{ count }} 场</div>
            </div>
          </div>
        </div>

        <!-- ZONE 8 — 方案收益分析 -->
        <div v-if="hasRoiData" class="zone">
          <div class="zone-hd">方案收益分析</div>
          <div class="roi-list">
            <div v-for="(roi, pid) in schemeRoi" :key="pid" class="roi-row">
              <span class="roi-name">{{ planLabel(pid) }}</span>
              <div class="bar-track roi-track">
                <div class="bar-fill" :class="roi.profit >= 0 ? 'pos-bar' : 'neg-bar'"
                  :style="`width:${(Math.abs(roi.profit) / maxAbsProfit * 100).toFixed(0)}%`" />
              </div>
              <div class="roi-right">
                <span class="roi-profit" :class="roi.profit >= 0 ? 'text-g' : 'text-r'">{{ roi.profit >= 0 ? '+' : '' }}¥{{ roi.profit.toFixed(0) }}</span>
                <span class="roi-meta">{{ roi.count }}次 · {{ roi.stake > 0 ? (roi.profit / roi.stake * 100).toFixed(0) : 0 }}% ROI</span>
              </div>
            </div>
          </div>
        </div>

        </div><!-- /v-show stats -->

        <!-- 筛选状态条 -->
        <div v-if="activeFilterCount > 0" class="filter-bar">
          <span class="fb-info">
            已筛选：
            <span v-if="typeFilter" class="fb-chip">{{ { conservative:'稳健', balanced:'均衡', high_odds:'博高赔', scoreline:'比分' }[typeFilter] ?? typeFilter }}</span>
            <span v-if="modelFilter" class="fb-chip">{{ modelFilter.split('+').map(m => m.split('/').pop()).join('+') }}</span>
            <span v-if="parlayFilter != null" class="fb-chip">{{ parlayFilter }}串1</span>
            · {{ filteredRuns.length }} 条
          </span>
          <button class="fb-clear" @click="clearFilters">清除筛选</button>
        </div>

        <!-- 运行历史列表 -->
        <div class="zone-hd" style="padding-top:16px">运行历史</div>
        <div class="card-list" aria-label="运行历史">
          <template v-for="run in filteredRuns" :key="run.id">

            <!-- 跳过行 -->
            <div v-if="run.sync_status === 'skipped'" class="skipped-row">
              <div class="sk-main" @click="toggleSkipped(run.id)">
                <span class="run-date">{{ run.run_date }}</span>
                <span class="sk-lbl">跳过</span>
              </div>
              <button class="sk-toggle" @click="toggleSkipped(run.id)" :aria-expanded="skippedExpanded.has(run.id)">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"
                  :style="skippedExpanded.has(run.id) ? 'transform:rotate(180deg);transition:.15s' : 'transition:.15s'">
                  <path d="M2 4l4 4 4-4"/>
                </svg>
              </button>
              <div v-if="skippedExpanded.has(run.id)" class="sk-detail">{{ run.sync_error ?? '无预测数据' }}</div>
            </div>

            <!-- 运行卡片 -->
            <article v-else class="run-card" :class="`sync-${run.sync_status}`">

              <!-- 左侧状态线 -->
              <div class="run-status-bar" :class="`sbar-${run.sync_status}`" />

              <div class="run-body">
                <!-- 行1: 日期 + 状态标签 -->
                <div class="run-r1">
                  <span class="run-date">{{ run.run_date }}</span>
                  <span class="tag-chip trigger-chip-{{ run.trigger }}">{{ triggerLabel(run.trigger) }}</span>
                  <span class="tag-chip" :class="`sync-chip-${run.sync_status}`">{{ syncStatusLabel(run.sync_status) }}</span>
                  <button
                    v-if="run.sync_status !== 'synced'"
                    class="sync-action"
                    :disabled="syncing === run.id"
                    @click.stop="syncRun(run.id)"
                  >
                    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" :class="syncing === run.id ? 'spin-anim' : ''">
                      <path d="M14 8A6 6 0 0 1 2.5 12M2 8a6 6 0 0 1 11.5-4M2 4v4h4M14 12v-4h-4"/>
                    </svg>
                    {{ syncing === run.id ? '同步中…' : '同步赛果' }}
                  </button>
                </div>

                <!-- 行2: 模型信息 -->
                <div v-if="run.model_info" class="run-r2">
                  <span class="run-model">{{ formatModelLabel(run.model_info) }}</span>
                  <span class="run-model-type">{{ run.model_info.type === 'ensemble' ? '混合' : '单模型' }}</span>
                  <span class="run-match-n">{{ run.match_ids?.length ?? 0 }} 场</span>
                  <span v-if="run.model_info.tokens" class="run-tokens">
                    {{ ((run.model_info.tokens.prompt + run.model_info.tokens.completion) / 1000).toFixed(1) }}k tokens
                  </span>
                </div>

                <!-- 方案芯片 -->
                <div v-if="run.schemes?.length" class="scheme-row">
                  <button
                    v-for="(scheme, si) in run.schemes"
                    :key="si"
                    type="button"
                    class="s-chip"
                    :class="`s-chip--${schemeStatus(scheme)}`"
                    @click="openDetail(run, scheme)"
                    :aria-label="`${planLabel(scheme.plan_id)}方案详情`"
                  >
                    <span class="sc-type">{{ planLabel(scheme.plan_id) }}</span>
                    <span class="sc-odds">×{{ calcSchemeOdds(scheme).toFixed(2) }}</span>
                    <span class="sc-st">{{ schemeStatusShort(scheme.status) }}</span>
                  </button>
                </div>

                <!-- 卡脚 -->
                <div class="run-foot">
                  <span class="run-foot-txt">每注 ¥{{ run.stake }} · {{ run.schemes?.length ?? 0 }} 方案</span>
                </div>
              </div>

            </article>
          </template>
        </div>

      </template>

      <!-- ── 方案详情底部弹窗 ─────────────────────────────────── -->
      <Teleport to="body">
        <Transition name="sheet">
          <div v-if="detailInfo" class="sheet-overlay" @click.self="closeDetail" role="dialog" aria-modal="true" :aria-label="`${planLabel(detailInfo.scheme.plan_id)}方案详情`">
            <div class="sheet-panel">

              <!-- 拖拽把手 -->
              <div class="sheet-handle" role="button" aria-label="关闭" @click="closeDetail" />

              <!-- 弹窗头 -->
              <div class="sheet-head">
                <div class="sheet-head-l">
                  <span class="plan-tag" :class="`plan-${detailInfo.scheme.plan_id}`">{{ planLabel(detailInfo.scheme.plan_id) }}</span>
                  <span class="status-tag" :class="`status-${schemeStatus(detailInfo.scheme)}`" style="margin-left:8px">{{ statusLabel(schemeStatus(detailInfo.scheme)) }}</span>
                </div>
                <div class="sheet-odds">
                  <div class="sheet-odds-val">×{{ calcSchemeOdds(detailInfo.scheme).toFixed(2) }}</div>
                  <div class="sheet-odds-lbl">{{ detailInfo.scheme.legs?.length ?? 0 }}串1</div>
                </div>
              </div>

              <!-- 元信息行 -->
              <div class="sheet-meta">
                {{ detailInfo.run.run_date }} · {{ formatModelLabel(detailInfo.run.model_info) }} · {{ triggerLabel(detailInfo.run.trigger) }}
              </div>

              <!-- 腿列表 -->
              <div class="sheet-legs">
                <div
                  v-for="(leg, li) in detailInfo.scheme.legs ?? []"
                  :key="li"
                  class="sl-row"
                  :class="{ 'sl-row--link': !!leg.match_id, 'sl-row--won': leg.won === true, 'sl-row--lost': leg.won === false }"
                  @click="leg.match_id && (closeDetail(), tryNavigateToMatch(leg.match_id))"
                  :role="leg.match_id ? 'button' : undefined"
                >
                  <!-- 结果侧线 -->
                  <div class="sl-bar" :class="{ 'slbar-won': leg.won === true, 'slbar-lost': leg.won === false, 'slbar-pending': leg.won === undefined }" />

                  <div class="sl-content">
                    <div class="sl-line1">
                      <span class="sl-home">{{ leg.home_team ?? `赛事#${leg.match_id}` }}</span>
                      <span class="sl-vs">vs</span>
                      <span class="sl-away">{{ leg.away_team ?? '' }}</span>
                      <span v-if="leg.match_id" class="sl-nav">›</span>
                    </div>
                    <div class="sl-line2">
                      <span v-if="leg.league" class="sl-league">{{ leg.league }}</span>
                      <span class="pick-tag" :class="pickClass(leg.pick)">{{ pickLabel(leg.pick) }}</span>
                      <span class="sl-odds">×{{ leg.odds?.toFixed(2) ?? '—' }}</span>
                      <span class="sl-arrow">→</span>
                      <span v-if="leg.won !== undefined" :class="leg.won ? 'text-g' : 'text-r'" style="font-weight:700">
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
                          <button class="score-ok" :disabled="scoreSubmitting[leg.match_id]" @click="submitScore(leg.match_id, detailInfo.run.id, $event)">
                            {{ scoreSubmitting[leg.match_id] ? '…' : '确认' }}
                          </button>
                          <button class="score-cancel" @click="closeScoreEntry(leg.match_id, $event)">✕</button>
                        </template>
                        <button v-else class="score-entry" @click="openScoreEntry(leg.match_id, $event)">录入比分</button>
                      </template>
                      <span v-else class="text-muted">待结算</span>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 弹窗底部 -->
              <div class="sheet-foot">
                <span class="sheet-foot-info">每注 ¥{{ detailInfo.run.stake }} · 预期 ¥{{ (detailInfo.run.stake * calcSchemeOdds(detailInfo.scheme)).toFixed(0) }}</span>
                <button class="sheet-close" @click="closeDetail">关闭</button>
              </div>

            </div>
          </div>
        </Transition>
      </Teleport>

    </template>

  </div>
</template>

<style scoped>
/* ── 全局结构 ─────────────────────────────────────────────────── */
.view {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  background: var(--bg);
  padding-bottom: 32px;
}

/* ── Tab 栏 ─────────────────────────────────────────────────── */
.tab-rail {
  display: flex;
  background: var(--card);
  border-bottom: var(--card-bd);
  position: sticky;
  top: 0;
  z-index: 10;
}
.tab-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 13px 8px;
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font);
  color: var(--text3);
  background: transparent;
  border: none;
  border-bottom: 2.5px solid transparent;
  cursor: pointer;
  transition: color .15s, border-color .15s;
}
.tab-btn--on { color: var(--primary); border-bottom-color: var(--primary); }
.tab-cnt {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  background: var(--bg);
  color: var(--text3);
  font-family: var(--font-num);
  transition: background .15s, color .15s;
}
.tab-cnt--on { background: var(--primary-t); color: var(--primary); }

/* ── KPI 4格 ────────────────────────────────────────────────── */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border-bottom: 1px solid var(--line);
}
.kpi-cell {
  background: var(--card);
  padding: 14px 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-height: 70px;
}
.kpi-label { font-size: 10px; color: var(--text3); letter-spacing: .02em; }
.kpi-val {
  font-size: 20px;
  font-weight: 800;
  line-height: 1;
  font-family: var(--font-disp);
  letter-spacing: -.3px;
  color: var(--text);
}
.kpi--pos .kpi-val { color: var(--green); }
.kpi--neg .kpi-val { color: var(--red); }

/* ── 二级数据条 ─────────────────────────────────────────────── */
.aux-strip {
  display: flex;
  align-items: center;
  background: var(--bg);
  border-bottom: var(--card-bd);
  padding: 10px 6px;
}
.aux-item {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.aux-val {
  font-size: 16px;
  font-weight: 800;
  font-family: var(--font-disp);
  color: var(--text);
  line-height: 1;
}
.aux-lbl { font-size: 10px; color: var(--text3); }
.aux-div { width: 1px; height: 28px; background: var(--line); margin: 0 2px; }

/* ── 筛选栏 ────────────────────────────────────────────────── */
.filter-rail {
  display: flex;
  background: var(--card);
  border-bottom: var(--card-bd);
  padding: 0 8px;
  gap: 4px;
}
.filter-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 10px 4px;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font);
  color: var(--text3);
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color .12s, border-color .12s;
}
.filter-btn--on { color: var(--primary); border-bottom-color: var(--primary); }
.filter-n {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 8px;
  background: var(--bg);
  font-family: var(--font-num);
}
.filter-btn--on .filter-n { background: var(--primary-t); color: var(--primary); }

/* ── 加载 / 空状态 ──────────────────────────────────────────── */
.center-box {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}
.spinner {
  width: 26px; height: 26px;
  border: 2.5px solid var(--line);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin .8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.spin-anim { animation: spin .8s linear infinite; }

.empty-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 60px 20px;
  text-align: center;
}
.empty-icon { color: var(--text3); margin-bottom: 4px; }
.empty-title { font-size: 14px; color: var(--text2); font-weight: 600; }
.empty-hint { font-size: 11px; color: var(--text3); }
.empty-link {
  background: transparent;
  border: none;
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--font);
  padding: 4px 0;
  text-decoration: underline;
}

/* ── 投注记录卡 ─────────────────────────────────────────────── */
.card-list { display: flex; flex-direction: column; }
.bet-card {
  background: var(--card);
  border-bottom: var(--card-bd);
  border-left: 3px solid transparent;
  transition: border-color .1s;
}
.bet-card--won  { border-left-color: var(--green); }
.bet-card--lost { border-left-color: var(--red); }
.bet-card--pending { border-left-color: var(--gold); }

.bet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 11px 14px 8px;
  gap: 8px;
}
.bet-head-l { display: flex; align-items: center; gap: 7px; min-width: 0; flex: 1; }

.legs-wrap {
  display: flex;
  flex-direction: column;
  border-top: var(--card-bd);
  border-bottom: var(--card-bd);
  padding: 0 14px;
}
.leg-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 0;
  border-bottom: var(--card-bd);
  font-size: 12px;
}
.leg-row:last-child { border-bottom: none; }
.leg-teams { display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0; overflow: hidden; }
.leg-team { color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 72px; }
.leg-vs { color: var(--text3); font-size: 10px; flex-shrink: 0; }
.leg-odds { font-size: 12px; font-weight: 700; color: var(--text2); font-family: var(--font-num); flex-shrink: 0; }
.leg-res { font-size: 11px; font-weight: 700; flex-shrink: 0; }

.bet-foot {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  gap: 2px;
}
.foot-kv { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.foot-k { font-size: 9px; color: var(--text3); }
.foot-v { font-size: 14px; font-weight: 800; font-family: var(--font-disp); color: var(--text); }
.foot-sep { width: 1px; background: var(--line); align-self: stretch; margin: 0 6px; flex-shrink: 0; }
.del-btn {
  width: 30px; height: 30px;
  border-radius: 6px;
  background: transparent;
  border: var(--card-bd);
  color: var(--text3);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: color .12s, border-color .12s;
  flex-shrink: 0;
  margin-left: 4px;
}
.del-btn:hover { color: var(--red); border-color: var(--red); }
.del-btn:disabled { opacity: .4; }

.bet-note { font-size: 11px; color: var(--text3); padding: 0 14px 10px; font-style: italic; }

/* ── 通用标签 ─────────────────────────────────────────────────── */
.plan-tag {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: var(--radius-sm);
  white-space: nowrap;
  flex-shrink: 0;
}
.plan-conservative { background: rgba(22,163,74,.12); color: var(--green); }
.plan-balanced     { background: rgba(29,78,216,.12); color: var(--blue); }
.plan-high_odds    { background: rgba(180,83,9,.12);  color: var(--gold); }
.plan-scoreline    { background: var(--primary-t);    color: var(--primary); }
.plan-manual, .plan-conservative_cover, .plan-balanced_cover,
.plan-high_odds_cover, .plan-scoreline_cover {
  background: rgba(0,0,0,.06); color: var(--text3);
}

.status-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  white-space: nowrap;
  flex-shrink: 0;
}
.status-won     { background: rgba(22,163,74,.12);  color: var(--green); }
.status-lost    { background: rgba(197,48,48,.08);  color: var(--red); }
.status-pending { background: rgba(180,83,9,.10);   color: var(--gold); }
.status-void    { background: rgba(0,0,0,.06);      color: var(--text3); }

.pick-tag {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}
.pick-win     { background: var(--primary-t); color: var(--primary); }
.pick-draw    { background: rgba(180,83,9,.12); color: var(--gold); }
.pick-lose    { background: rgba(22,163,74,.12); color: var(--green); }
.pick-neutral { background: var(--bg); color: var(--text3); }

.meta-txt { font-size: 11px; color: var(--text3); white-space: nowrap; font-family: var(--font-num); }

/* ── 颜色工具 ─────────────────────────────────────────────────── */
.text-g    { color: var(--green) !important; }
.text-r    { color: var(--red) !important; }
.text-amber { color: var(--gold) !important; }
.text-muted { color: var(--text3); }

/* ── Error banner ─────────────────────────────────────────────── */
.err-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: rgba(197,48,48,.08);
  border-bottom: 1px solid rgba(197,48,48,.20);
  font-size: 12px;
  color: var(--red);
}
.err-retry {
  margin-left: auto;
  background: transparent;
  border: none;
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--font);
  text-decoration: underline;
}

/* ── Skeleton ─────────────────────────────────────────────────── */
.skel { animation: skel-pulse 1.4s ease-in-out infinite; }
@keyframes skel-pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }

/* ── Hero 区域 ──────────────────────────────────────────────── */
.hero-zone {
  display: flex;
  align-items: stretch;
  background: var(--card);
  border-bottom: var(--card-bd);
  padding: 0;
}
.hero-main {
  flex: 1;
  padding: 18px 16px;
  border-right: var(--card-bd);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.hero-label { font-size: 10px; color: var(--text3); font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.hero-rate {
  font-size: 48px;
  font-weight: 900;
  line-height: 1;
  font-family: var(--font-disp);
  letter-spacing: -1px;
  color: var(--text);
}
.hero-sub { font-size: 11px; color: var(--text3); margin-top: 2px; }

.hero-stats {
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 10px;
  min-width: 90px;
}
.hero-stat-item { display: flex; flex-direction: column; gap: 2px; }
.hero-stat-val {
  font-size: 18px;
  font-weight: 800;
  font-family: var(--font-disp);
  line-height: 1;
  color: var(--text);
}
.hero-stat-lbl { font-size: 9px; color: var(--text3); }
.hero-stat-sep { height: 1px; background: var(--line); }

/* ── Zone 容器 ──────────────────────────────────────────────── */
.zone { background: var(--bg); }
.zone-hd {
  font-size: 10px;
  font-weight: 700;
  color: var(--text3);
  letter-spacing: .07em;
  text-transform: uppercase;
  padding: 10px 14px 6px;
}
.zone-hint {
  font-size: 9px;
  font-weight: 400;
  color: var(--text3);
  letter-spacing: 0;
  text-transform: none;
  margin-left: 6px;
}

/* ── 4格准确率 ──────────────────────────────────────────────── */
.acc4-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border-bottom: 1px solid var(--line);
}
.acc4-cell {
  background: var(--card);
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
  cursor: pointer;
  border: none;
  font-family: var(--font);
  text-align: left;
  border-bottom: 2px solid transparent;
  transition: background .1s, border-color .1s;
}
.acc4-cell--on { background: var(--primary-d); border-bottom-color: var(--primary); }
.acc4-cell--best { border-bottom-color: var(--gold); }
.acc4-cell:active { opacity: .8; }
.acc4-name { font-size: 10px; font-weight: 700; color: var(--text2); display: flex; align-items: center; gap: 3px; }
.acc4-rate {
  font-size: 20px;
  font-weight: 900;
  line-height: 1;
  font-family: var(--font-disp);
  color: var(--text);
}
.acc4-na { font-size: 11px; font-weight: 500; color: var(--text3); }
.acc4-bar-track {
  height: 3px;
  background: var(--line);
  border-radius: 2px;
  overflow: hidden;
}
.acc4-bar-fill {
  height: 100%;
  border-radius: 2px;
  transition: width .4s ease;
}
.acc4-n { font-size: 9px; color: var(--text3); font-family: var(--font-num); }

/* ── 水平滚动区 ─────────────────────────────────────────────── */
.hscroll {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  padding: 8px 14px 12px;
  border-bottom: 1px solid var(--line);
  scrollbar-width: none;
}
.hscroll::-webkit-scrollbar { display: none; }

/* ── 模型卡 ─────────────────────────────────────────────────── */
.model-card {
  flex-shrink: 0;
  min-width: 130px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 11px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  font-family: var(--font);
  text-align: left;
  transition: border-color .1s, background .1s;
}
.model-card--on { border-color: var(--primary); background: var(--primary-d); }
.model-card--best { border-color: var(--gold); }
.mc-header { display: flex; align-items: center; gap: 4px; }
.mc-name { font-size: 11px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100px; }
.mc-type { font-size: 9px; color: var(--text3); }
.mc-rate { font-size: 20px; font-weight: 900; line-height: 1; font-family: var(--font-disp); margin-top: 2px; }
.mc-na { font-size: 10px; font-weight: 500; color: var(--text3); }

/* ── 串数卡 ─────────────────────────────────────────────────── */
.parlay-card {
  flex-shrink: 0;
  min-width: 72px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  cursor: pointer;
  font-family: var(--font);
  text-align: center;
  align-items: center;
  transition: border-color .1s, background .1s;
}
.parlay-card--on { border-color: var(--primary); background: var(--primary-d); }
.parlay-card--best { border-color: var(--gold); }
.pc-name { font-size: 11px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 3px; }

/* ── 联赛卡 ─────────────────────────────────────────────────── */
.league-card {
  flex-shrink: 0;
  min-width: 90px;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.league-card--best { border-color: var(--gold); }
.lc-name { font-size: 11px; font-weight: 700; color: var(--text); }
.lc-rate { font-size: 18px; font-weight: 900; font-family: var(--font-disp); }

/* ── 横向条形图 ─────────────────────────────────────────────── */
.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 0;
  background: var(--card);
  border-bottom: 1px solid var(--line);
}
.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: var(--card-bd);
}
.bar-row:last-child { border-bottom: none; }
.bar-lbl { font-size: 12px; color: var(--text2); font-weight: 600; min-width: 42px; display: flex; align-items: center; gap: 3px; }
.bar-track {
  flex: 1;
  height: 6px;
  background: var(--line);
  border-radius: 3px;
  overflow: hidden;
}
.bar-fill { height: 100%; border-radius: 3px; transition: width .4s ease; }
.bar-pct { font-size: 13px; font-weight: 800; font-family: var(--font-disp); min-width: 36px; text-align: right; }
.bar-detail { font-size: 10px; color: var(--text3); font-family: var(--font-num); min-width: 28px; text-align: right; }

/* ── 条形填充颜色 ───────────────────────────────────────────── */
.text-g-bar,  .pos-bar  { background: var(--green); }
.text-r-bar,  .neg-bar  { background: var(--red); }
.text-amber-bar         { background: var(--gold); }
.muted-bar              { background: var(--line); }

/* ── 赛果分布 ───────────────────────────────────────────────── */
.dist-strip {
  display: flex;
  gap: 1px;
  background: var(--line);
  border-bottom: 1px solid var(--line);
}
.dist-cell {
  flex: 1;
  background: var(--card);
  padding: 12px 10px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.dist-name { font-size: 10px; color: var(--text3); font-weight: 700; }
.dist-pct {
  font-size: 24px;
  font-weight: 900;
  font-family: var(--font-disp);
  line-height: 1;
}
.dist-H .dist-pct { color: var(--primary); }
.dist-D .dist-pct { color: var(--blue); }
.dist-A .dist-pct { color: var(--green); }
.dist-track { height: 3px; background: var(--line); border-radius: 2px; overflow: hidden; }
.dist-fill { height: 100%; border-radius: 2px; transition: width .4s ease; }
.dfill-H { background: var(--primary); }
.dfill-D { background: var(--blue); }
.dfill-A { background: var(--green); }
.dist-n { font-size: 10px; color: var(--text3); font-family: var(--font-num); }

/* ── ROI 分析 ─────────────────────────────────────────────── */
.roi-list {
  display: flex;
  flex-direction: column;
  background: var(--card);
  border-bottom: 1px solid var(--line);
}
.roi-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  border-bottom: var(--card-bd);
}
.roi-row:last-child { border-bottom: none; }
.roi-name { font-size: 12px; color: var(--text2); font-weight: 600; min-width: 52px; }
.roi-track { flex: 1; }
.roi-right { display: flex; flex-direction: column; align-items: flex-end; gap: 1px; min-width: 72px; }
.roi-profit { font-size: 14px; font-weight: 800; font-family: var(--font-disp); }
.roi-meta { font-size: 9px; color: var(--text3); font-family: var(--font-num); }

/* ── Best badge ─────────────────────────────────────────────── */
.best-badge {
  font-size: 9px;
  font-weight: 700;
  background: rgba(180,83,9,.12);
  color: var(--gold);
  padding: 1px 4px;
  border-radius: 3px;
}

/* ── 分析折叠按钮 ───────────────────────────────────────────── */
.stats-toggle-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 10px 14px;
  background: var(--card);
  border: none;
  border-bottom: 1px solid var(--line);
  color: var(--text2);
  font-family: var(--font);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
  transition: background .12s;
}
.stats-toggle-btn:hover { background: var(--bg); }
.stats-toggle-btn svg { flex-shrink: 0; color: var(--text3); }
.stats-toggle-filter {
  margin-left: auto;
  font-size: 10px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-t);
  padding: 1px 7px;
  border-radius: 10px;
}

/* ── 筛选状态条 ─────────────────────────────────────────────── */
.filter-bar {
  display: flex;
  align-items: center;
  padding: 8px 14px;
  background: var(--primary-d);
  border-bottom: 1px solid var(--primary-t);
  gap: 8px;
}
.fb-info { flex: 1; font-size: 11px; color: var(--primary); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.fb-chip {
  display: inline-block;
  background: var(--primary-t);
  color: var(--primary);
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 10px;
  font-weight: 700;
}
.fb-clear {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 4px 10px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--font);
  white-space: nowrap;
}

/* ── 跳过行 ─────────────────────────────────────────────────── */
.skipped-row {
  background: var(--card);
  border-bottom: var(--card-bd);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  padding: 10px 14px;
  gap: 6px;
  opacity: .7;
}
.sk-main { display: flex; align-items: center; gap: 8px; flex: 1; cursor: pointer; }
.sk-lbl { font-size: 10px; color: var(--text3); background: var(--bg); padding: 2px 7px; border-radius: 4px; }
.sk-toggle { background: transparent; border: none; color: var(--text3); cursor: pointer; padding: 4px; }
.sk-detail { width: 100%; font-size: 10px; color: var(--text3); padding-top: 4px; }

/* ── 运行卡片 ───────────────────────────────────────────────── */
.run-card {
  background: var(--card);
  border-bottom: var(--card-bd);
  display: flex;
  align-items: stretch;
}
.run-status-bar { width: 3px; flex-shrink: 0; }
.sbar-synced  { background: var(--green); }
.sbar-pending { background: var(--gold); }
.sbar-partial { background: #f97316; }
.sbar-failed  { background: var(--red); }

.run-body { flex: 1; padding: 10px 14px; display: flex; flex-direction: column; gap: 7px; min-width: 0; }

.run-r1 { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.run-date {
  font-size: 14px;
  font-weight: 800;
  font-family: var(--font-disp);
  color: var(--text);
}

.tag-chip {
  font-size: 10px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: var(--radius-sm);
}
.trigger-chip-manual { background: rgba(29,78,216,.10); color: var(--blue); }
.trigger-chip-scheduled { background: rgba(124,58,237,.10); color: #7c3aed; }
.sync-chip-pending  { background: rgba(180,83,9,.10);   color: var(--gold); }
.sync-chip-synced   { background: rgba(22,163,74,.10);  color: var(--green); }
.sync-chip-partial  { background: rgba(249,115,22,.10); color: #f97316; }
.sync-chip-failed   { background: rgba(197,48,48,.10);  color: var(--red); }

.sync-action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 700;
  padding: 4px 9px;
  border-radius: var(--radius-sm);
  background: var(--bg);
  border: var(--card-bd);
  color: var(--text2);
  cursor: pointer;
  font-family: var(--font);
  transition: border-color .1s;
  margin-left: auto;
}
.sync-action:hover { border-color: var(--primary); color: var(--primary); }
.sync-action:disabled { opacity: .5; cursor: not-allowed; }

.run-r2 { display: flex; align-items: center; gap: 8px; }
.run-model { font-size: 10px; color: var(--text3); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-model-type { font-size: 9px; color: var(--text3); background: var(--bg); padding: 1px 5px; border-radius: 3px; flex-shrink: 0; }
.run-match-n { font-size: 10px; color: var(--text3); font-family: var(--font-num); flex-shrink: 0; }
.run-tokens { font-size: 9px; color: var(--text3); opacity: .7; font-family: var(--font-num); flex-shrink: 0; }

/* ── 方案芯片行 ──────────────────────────────────────────────── */
.scheme-row {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(90px, 1fr));
  gap: 6px;
}
.s-chip {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 9px 10px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  cursor: pointer;
  font-family: var(--font);
  text-align: left;
  transition: border-color .1s, background .1s;
  min-height: 60px;
}
.s-chip:active { background: var(--primary-d); border-color: var(--primary); }
.s-chip--won { border-color: rgba(22,163,74,.3); }
.s-chip--won .sc-odds { color: var(--green); }
.s-chip--won .sc-st   { color: var(--green); }
.s-chip--lost { opacity: .7; }
.s-chip--lost .sc-odds { text-decoration: line-through; color: var(--text3); }
.sc-type { font-size: 10px; font-weight: 700; color: var(--text3); }
.sc-odds { font-size: 16px; font-weight: 900; font-family: var(--font-disp); color: var(--text); line-height: 1; }
.sc-st   { font-size: 10px; color: var(--text3); }

.run-foot { border-top: var(--card-bd); padding-top: 7px; margin-top: 2px; }
.run-foot-txt { font-size: 11px; color: var(--text3); }

/* ── 详情弹窗 ──────────────────────────────────────────────── */
.sheet-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.50);
  z-index: 9999;
  display: flex;
  align-items: flex-end;
  backdrop-filter: blur(2px);
}
.sheet-panel {
  width: 100%;
  max-height: 88dvh;
  background: var(--card);
  border-radius: 16px 16px 0 0;
  display: flex;
  flex-direction: column;
  box-shadow: var(--card-sh-h);
  overflow: hidden;
}
.sheet-handle {
  width: 36px;
  height: 4px;
  background: var(--line);
  border-radius: 2px;
  margin: 12px auto 8px;
  cursor: pointer;
  flex-shrink: 0;
}
.sheet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px 10px;
  border-bottom: var(--card-bd);
  flex-shrink: 0;
}
.sheet-head-l { display: flex; align-items: center; }
.sheet-odds { text-align: right; }
.sheet-odds-val { font-size: 28px; font-weight: 900; font-family: var(--font-disp); color: var(--text); line-height: 1; }
.sheet-odds-lbl { font-size: 10px; color: var(--text3); }

.sheet-meta {
  padding: 8px 18px;
  font-size: 11px;
  color: var(--text3);
  border-bottom: var(--card-bd);
  flex-shrink: 0;
}

.sheet-legs {
  flex: 1;
  overflow-y: auto;
  -webkit-overflow-scrolling: touch;
}
.sl-row {
  display: flex;
  align-items: stretch;
  border-bottom: var(--card-bd);
  min-height: 56px;
}
.sl-row:last-child { border-bottom: none; }
.sl-row--link { cursor: pointer; }
.sl-row--link:active { background: var(--primary-d); }
.sl-row--won  { background: rgba(22,163,74,.04); }
.sl-row--lost { background: rgba(197,48,48,.04); }

.sl-bar { width: 3px; flex-shrink: 0; }
.slbar-won     { background: var(--green); }
.slbar-lost    { background: var(--red); }
.slbar-pending { background: var(--line); }

.sl-content { flex: 1; padding: 10px 16px; display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.sl-line1 { display: flex; align-items: center; gap: 5px; font-size: 13px; }
.sl-home, .sl-away { color: var(--text); max-width: 80px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sl-vs { color: var(--text3); font-size: 10px; flex-shrink: 0; }
.sl-nav { color: var(--text3); flex-shrink: 0; }
.sl-line2 { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12px; }
.sl-league { font-size: 10px; color: var(--text3); }
.sl-odds { font-size: 12px; font-weight: 700; font-family: var(--font-num); color: var(--text2); }
.sl-arrow { color: var(--text3); }

.sheet-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 18px;
  border-top: var(--card-bd);
  flex-shrink: 0;
}
.sheet-foot-info { font-size: 12px; color: var(--text3); }
.sheet-close {
  background: var(--bg);
  border: var(--card-bd);
  color: var(--text2);
  padding: 8px 20px;
  border-radius: var(--radius);
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--font);
  transition: border-color .1s;
}
.sheet-close:hover { border-color: var(--primary); color: var(--primary); }

/* ── Score 录入 ─────────────────────────────────────────────── */
.score-input {
  width: 52px;
  padding: 3px 7px;
  font-size: 12px;
  border: var(--card-bd);
  border-radius: 4px;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-num);
  outline-color: var(--primary);
}
.score-ok {
  background: var(--primary);
  color: #fff;
  border: none;
  padding: 3px 9px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--font);
}
.score-ok:disabled { opacity: .5; }
.score-cancel {
  background: transparent;
  border: var(--card-bd);
  color: var(--text3);
  padding: 3px 7px;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  font-family: var(--font);
}
.score-entry {
  background: transparent;
  border: 1px dashed var(--primary);
  color: var(--primary);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  font-family: var(--font);
}

/* ── 弹窗动画 ───────────────────────────────────────────────── */
.sheet-enter-active, .sheet-leave-active {
  transition: opacity .2s ease;
}
.sheet-enter-active .sheet-panel, .sheet-leave-active .sheet-panel {
  transition: transform .25s cubic-bezier(.32,0,.67,0);
}
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-from .sheet-panel, .sheet-leave-to .sheet-panel { transform: translateY(100%); }

/* ── Tag chips (run card) ─────────────────────────────────── */
.trigger-chip-manual    { background: rgba(29,78,216,.10);  color: var(--blue); }
.trigger-chip-scheduled { background: rgba(124,58,237,.10); color: #7c3aed; }
</style>
