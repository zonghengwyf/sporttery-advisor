<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import api from '@/api'

// ── Types ────────────────────────────────────────────────────────────
interface MatchOdds {
  home: number
  draw: number
  away: number
  hhad?: { home: number; draw: number; away: number; handicap: number | null }
}
interface Match {
  id: number
  home_team: string
  away_team: string
  league: string
  kickoff_at: string
  sporttery_odds: MatchOdds | null
  available_markets: string[]
}
type Pick = 'home' | 'draw' | 'away'
interface Slot { match: Match; pick: Pick | null; checked: boolean }

// ── State ────────────────────────────────────────────────────────────
const tab       = ref<'custom' | 'ai'>('custom')
const slots     = ref<Slot[]>([])
const loading   = ref(true)
const parlayCode = ref('')
const stake     = ref(2)
const showSheet  = ref(false)
const aiTickets  = ref<Record<string, any>>({})
const aiLoading  = ref(false)
const aiTab      = ref('conservative')

const AI_TYPES = [
  { key: 'conservative', label: '稳健' },
  { key: 'balanced',     label: '均衡' },
  { key: 'aggressive',   label: '博高赔' },
  { key: 'score',        label: '比分' },
]

// ── Derived ──────────────────────────────────────────────────────────
const ready = computed(() => slots.value.filter(s => s.checked && s.pick))

const PICK_LABEL: Record<Pick, string> = { home: '主胜', draw: '平局', away: '客胜' }

function pickOdds(s: Slot): number {
  if (!s.pick || !s.match.sporttery_odds) return 1
  return s.match.sporttery_odds[s.pick] ?? 1
}

function comb(n: number, k: number): number {
  if (k > n || k < 0) return 0
  if (k === 0 || k === n) return 1
  let r = 1
  for (let i = 0; i < k; i++) r = r * (n - i) / (i + 1)
  return Math.round(r)
}

interface ParlayDef { code: string; label: string; bets: number; k: number }

const parlayOptions = computed<ParlayDef[]>(() => {
  const n = ready.value.length
  if (n < 1) return []
  const opts: ParlayDef[] = []
  // 2串1 through N串1 — typical 竞彩 options
  for (let k = Math.max(2, n > 1 ? 2 : 1); k <= n; k++) {
    opts.push({ code: `${k}x1`, label: `${k}串1`, bets: comb(n, k), k })
  }
  return opts
})

const activeParlayDef = computed(() =>
  parlayOptions.value.find(p => p.code === parlayCode.value) ?? null
)

// When selection changes, auto-pick the last (biggest accumulator) option
watch(() => ready.value.length, () => {
  const opts = parlayOptions.value
  if (!opts.length) { parlayCode.value = ''; return }
  if (!opts.find(o => o.code === parlayCode.value)) {
    parlayCode.value = opts[opts.length - 1].code
  }
})

// Total odds = accumulator of all selected picks (for N串1)
const accuOdds = computed(() => {
  if (!ready.value.length) return 1
  return ready.value.reduce((acc, s) => acc * pickOdds(s), 1)
})

const totalCost = computed(() => {
  const def = activeParlayDef.value
  if (!def) return 0
  return def.bets * stake.value
})

const maxReturn = computed(() => {
  // For simple N串1: total_odds * stake. For subset combos: average payout estimate
  const def = activeParlayDef.value
  if (!def || !ready.value.length) return 0
  if (def.k === ready.value.length) return accuOdds.value * stake.value
  // For subset combos, show single-combo potential (best case)
  const sorted = [...ready.value].sort((a, b) => pickOdds(b) - pickOdds(a))
  const best = sorted.slice(0, def.k).reduce((acc, s) => acc * pickOdds(s), 1)
  return best * stake.value
})

// ── Methods ───────────────────────────────────────────────────────────
function toggleCheck(i: number) {
  slots.value[i].checked = !slots.value[i].checked
  if (!slots.value[i].checked) slots.value[i].pick = null
}

function setPick(i: number, p: Pick) {
  slots.value[i].pick = p
  slots.value[i].checked = true
}

function pickClass(p: Pick | null) {
  if (p === 'home') return 'pk-h'
  if (p === 'draw') return 'pk-d'
  if (p === 'away') return 'pk-a'
  return ''
}

function fmtTime(iso: string) {
  return new Date(iso).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function fmtOdds(n: number) { return n.toFixed(2) }

function clearAll() { slots.value.forEach(s => { s.checked = false; s.pick = null }) }

async function loadMatches() {
  loading.value = true
  try {
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`
    const { data } = await api.get('/matches/', { params: { sale_date: today } })
    slots.value = (data as Match[]).map(m => ({ match: m, pick: null, checked: false }))
  } catch { slots.value = [] }
  finally { loading.value = false }
}

async function loadAI() {
  if (aiLoading.value || Object.keys(aiTickets.value).length) return
  aiLoading.value = true
  try {
    const ids = slots.value.map(s => s.match.id)
    if (!ids.length) return
    const { data } = await api.post('/tickets/generate', { match_ids: ids })
    aiTickets.value = {
      conservative: data.conservative,
      balanced:     data.balanced,
      aggressive:   data.high_odds,
      score:        data.scoreline,
    }
  } catch { aiTickets.value = {} }
  finally { aiLoading.value = false }
}

watch(tab, v => { if (v === 'ai') loadAI() })

function aiLeg(leg: any) {
  if (leg.pick === '主胜' || leg.pick === '3') return 'pk-h'
  if (leg.pick === '平局' || leg.pick === '1') return 'pk-d'
  return 'pk-a'
}

onMounted(loadMatches)
</script>

<template>
  <div class="view">

    <!-- ── Tab bar ─────────────────────────────────────────────── -->
    <div class="tab-bar">
      <button class="tab-btn" :class="{ on: tab === 'custom' }" @click="tab = 'custom'">
        自选串关
        <span v-if="ready.length" class="tab-count">{{ ready.length }}</span>
      </button>
      <button class="tab-btn" :class="{ on: tab === 'ai' }" @click="tab = 'ai'">AI 推荐</button>
    </div>

    <!-- ══════════════════════════════════════════════════════════ -->
    <!-- TAB: 自选串关                                              -->
    <!-- ══════════════════════════════════════════════════════════ -->
    <template v-if="tab === 'custom'">
      <div v-if="loading" class="match-scroll">
        <div v-for="i in 5" :key="i" class="skeleton" style="height:72px;margin-bottom:2px" />
      </div>

      <div v-else-if="!slots.length" class="empty-tip">
        <p class="empty-title">暂无赛事</p>
        <p class="text-sm text-muted mt-2">回到今日赛事同步赛单</p>
      </div>

      <div v-else class="match-scroll" :style="ready.length ? 'padding-bottom:160px' : ''">

        <!-- Section label -->
        <div class="section-label px-4 pt-3 pb-1">
          点击赛事选择投注方向 · 可多选
          <button v-if="ready.length" class="clear-btn" @click="clearAll">清空</button>
        </div>

        <!-- Match rows -->
        <div
          v-for="(s, i) in slots"
          :key="s.match.id"
          class="match-row"
          :class="{ 'match-row--on': s.checked }"
        >
          <!-- Left: checkbox + meta -->
          <button class="row-check" @click="toggleCheck(i)">
            <span class="chk" :class="{ 'chk--on': s.checked }">
              <svg v-if="s.checked" width="10" height="10" viewBox="0 0 10 10" fill="none">
                <path d="M2 5l2.5 2.5L8 3" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </span>
            <div class="row-meta">
              <span class="row-league">{{ s.match.league }}</span>
              <span class="row-time font-num">{{ fmtTime(s.match.kickoff_at) }}</span>
            </div>
          </button>

          <!-- Center: teams -->
          <div class="row-teams" @click="toggleCheck(i)">
            <span class="team-name">{{ s.match.home_team }}</span>
            <span class="row-vs">VS</span>
            <span class="team-name team-name--away">{{ s.match.away_team }}</span>
          </div>

          <!-- Right: pick buttons -->
          <div class="row-picks" v-if="s.match.sporttery_odds">
            <button
              class="pk pk-h"
              :class="{ 'pk--on': s.pick === 'home' }"
              @click.stop="setPick(i, 'home')"
            >
              <span class="pk-lbl">主胜</span>
              <span class="pk-odd font-num">{{ fmtOdds(s.match.sporttery_odds.home) }}</span>
            </button>
            <button
              class="pk pk-d"
              :class="{ 'pk--on': s.pick === 'draw' }"
              @click.stop="setPick(i, 'draw')"
            >
              <span class="pk-lbl">平</span>
              <span class="pk-odd font-num">{{ fmtOdds(s.match.sporttery_odds.draw) }}</span>
            </button>
            <button
              class="pk pk-a"
              :class="{ 'pk--on': s.pick === 'away' }"
              @click.stop="setPick(i, 'away')"
            >
              <span class="pk-lbl">客胜</span>
              <span class="pk-odd font-num">{{ fmtOdds(s.match.sporttery_odds.away) }}</span>
            </button>
          </div>
          <div v-else class="row-no-odds text-muted">赔率待更新</div>
        </div>
      </div>

      <!-- ── Sticky bottom action bar ────────────────────────── -->
      <Transition name="bar">
        <div v-if="ready.length" class="action-bar">

          <!-- Row 1: parlay type chips -->
          <div class="parlay-row">
            <span class="parlay-label">串关</span>
            <div class="parlay-chips">
              <button
                v-for="opt in parlayOptions"
                :key="opt.code"
                class="parlay-chip"
                :class="{ 'parlay-chip--on': parlayCode === opt.code }"
                @click="parlayCode = opt.code"
              >
                {{ opt.label }}
                <span class="chip-bets">{{ opt.bets }}注</span>
              </button>
            </div>
          </div>

          <!-- Row 2: stake + summary + generate -->
          <div class="bar-row2">
            <div class="stake-group">
              <span class="stake-label">每注</span>
              <span class="stake-sym">¥</span>
              <input
                v-model.number="stake"
                type="number"
                min="2"
                step="1"
                class="stake-input font-num"
              />
            </div>

            <div class="bar-summary">
              <div class="summary-item">
                <span class="s-label">总投入</span>
                <span class="s-val font-num">¥{{ totalCost.toFixed(0) }}</span>
              </div>
              <div class="summary-sep">·</div>
              <div class="summary-item">
                <span class="s-label">赔率</span>
                <span class="s-val font-num text-primary">×{{ accuOdds.toFixed(2) }}</span>
              </div>
            </div>

            <button
              class="gen-btn"
              :disabled="!parlayCode"
              @click="showSheet = true"
            >
              查看方案
            </button>
          </div>
        </div>
      </Transition>

      <!-- ── Result sheet ─────────────────────────────────────── -->
      <Transition name="sheet">
        <div v-if="showSheet && ready.length" class="sheet-overlay" @click.self="showSheet = false">
          <div class="sheet">
            <div class="sheet-handle" />
            <div class="sheet-head">
              <div>
                <div class="sheet-title font-disp">{{ activeParlayDef?.label ?? '' }} 投注方案</div>
                <div class="text-xs text-muted mt-1">{{ ready.length }} 场 · {{ activeParlayDef?.bets ?? 0 }} 注</div>
              </div>
              <button class="sheet-close" @click="showSheet = false">✕</button>
            </div>

            <div class="sheet-legs">
              <div v-for="(s, i) in ready" :key="i" class="sheet-leg">
                <div class="leg-idx font-num font-disp">{{ String(i+1).padStart(2,'0') }}</div>
                <div class="leg-info">
                  <div class="leg-teams">{{ s.match.home_team }} vs {{ s.match.away_team }}</div>
                  <div class="text-xs text-muted">{{ s.match.league }} · {{ fmtTime(s.match.kickoff_at) }}</div>
                </div>
                <span class="leg-pick" :class="pickClass(s.pick)">
                  {{ s.pick ? PICK_LABEL[s.pick] : '' }}
                </span>
                <span class="leg-odd-val font-num">{{ fmtOdds(pickOdds(s)) }}</span>
              </div>
            </div>

            <div class="sheet-dashed" />

            <div class="sheet-foot">
              <div class="foot-stat">
                <div class="text-xs text-muted">串关类型</div>
                <div class="foot-big font-disp">{{ activeParlayDef?.label }}</div>
              </div>
              <div class="foot-stat">
                <div class="text-xs text-muted">注数 × 每注</div>
                <div class="foot-big font-num">{{ activeParlayDef?.bets }} × ¥{{ stake }}</div>
              </div>
              <div class="foot-stat foot-stat--highlight">
                <div class="text-xs text-muted">总投入</div>
                <div class="foot-big font-num text-primary">¥{{ totalCost.toFixed(0) }}</div>
              </div>
              <div class="foot-stat foot-stat--highlight">
                <div class="text-xs text-muted">最高中奖</div>
                <div class="foot-big font-num text-green">¥{{ maxReturn.toFixed(0) }}</div>
              </div>
            </div>

            <div class="sheet-note text-muted">
              赔率实时变动，以竞彩官方出票时赔率为准
            </div>
          </div>
        </div>
      </Transition>
    </template>

    <!-- ══════════════════════════════════════════════════════════ -->
    <!-- TAB: AI 推荐                                               -->
    <!-- ══════════════════════════════════════════════════════════ -->
    <template v-else>
      <div class="ai-subtabs">
        <button
          v-for="t in AI_TYPES" :key="t.key"
          class="ai-subtab"
          :class="{ on: aiTab === t.key }"
          @click="aiTab = t.key"
        >{{ t.label }}</button>
      </div>

      <div v-if="aiLoading" class="p-5">
        <div class="skeleton" style="height:280px" />
      </div>

      <div v-else class="ticket-wrap">
        <template v-if="aiTickets[aiTab]">
          <div class="card no-accent ticket-card">
            <div class="ticket-head">
              <div>
                <div class="font-disp" style="font-size:14px;font-weight:700">
                  {{ AI_TYPES.find(t => t.key === aiTab)?.label }}方案
                </div>
                <div class="text-xs text-muted mt-1">AI 综合概率分析</div>
              </div>
              <span class="badge badge-red">{{ aiTickets[aiTab].risk_label || '中风险' }}</span>
            </div>
            <div class="divider" />
            <div class="legs">
              <div v-for="(leg, i) in aiTickets[aiTab].legs" :key="i" class="leg-row">
                <div class="leg-num font-disp">{{ String(i+1).padStart(2,'0') }}</div>
                <div class="leg-match">
                  <div style="font-size:13px;font-weight:600">{{ leg.home_team }} vs {{ leg.away_team }}</div>
                  <div class="text-xs text-muted">{{ leg.league }}</div>
                </div>
                <span class="leg-pick" :class="aiLeg(leg)">{{ leg.pick }}</span>
                <span class="leg-odd-val font-num">{{ leg.odds?.toFixed(2) ?? '-' }}</span>
              </div>
            </div>
            <div class="sheet-dashed" style="margin:0 14px" />
            <div class="sheet-foot" style="padding:12px 16px">
              <div class="foot-stat">
                <div class="text-xs text-muted">建议投注</div>
                <div class="foot-big font-num">¥{{ aiTickets[aiTab].stake ?? 20 }}</div>
              </div>
              <div class="foot-stat">
                <div class="text-xs text-muted">总赔率</div>
                <div class="foot-big font-num text-primary">×{{ aiTickets[aiTab].total_odds?.toFixed(2) ?? '-' }}</div>
              </div>
              <div class="foot-stat">
                <div class="text-xs text-muted">预期收益</div>
                <div class="foot-big font-num text-green">
                  ¥{{ Math.round((aiTickets[aiTab].total_odds ?? 1) * (aiTickets[aiTab].stake ?? 20)) }}
                </div>
              </div>
            </div>
          </div>

          <div v-if="aiTickets[aiTab].rationale" class="rationale">
            <div class="flex items-center gap-2 mb-2">
              <div class="chat-avatar chat-avatar--sm">AI</div>
              <span class="text-xs font-disp text-muted">方案说明</span>
            </div>
            <p class="chat-bubble-ai">{{ aiTickets[aiTab].rationale }}</p>
          </div>
        </template>

        <div v-else class="empty-tip">
          <p class="empty-title">暂无 AI 方案</p>
          <p class="text-sm text-muted mt-2">请先完成赛事分析</p>
        </div>
      </div>
    </template>

  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; height: 100%; overflow: hidden; }

/* ── Tabs ─────────────────────────────────────────────────────── */
.tab-bar {
  display: flex;
  border-bottom: var(--card-bd);
  flex-shrink: 0;
}
.tab-btn {
  flex: 1;
  padding: 11px 8px;
  font-size: 13px;
  font-weight: 600;
  font-family: var(--font);
  background: transparent;
  cursor: pointer;
  color: var(--text2);
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.tab-btn.on { color: var(--text); border-bottom-color: var(--primary); }
.tab-count {
  background: var(--primary);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 8px;
  font-family: var(--font-num);
}

/* ── Match list ───────────────────────────────────────────────── */
.match-scroll {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.section-label {
  font-size: 11px;
  color: var(--text3);
  letter-spacing: .3px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.clear-btn {
  font-size: 11px;
  color: var(--primary);
  background: transparent;
  cursor: pointer;
  font-family: var(--font);
}

.match-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px 10px 10px;
  border-bottom: var(--card-bd);
  transition: background .12s;
  cursor: pointer;
}
.match-row--on { background: color-mix(in srgb, var(--primary) 6%, transparent); }

.row-check {
  display: flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  cursor: pointer;
  flex-shrink: 0;
  padding: 0;
}
.chk {
  width: 16px;
  height: 16px;
  border-radius: 4px;
  border: 1.5px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: all .12s;
  color: #fff;
}
.chk--on { background: var(--primary); border-color: var(--primary); }

.row-meta {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 30px;
}
.row-league { font-size: 10px; color: var(--text3); white-space: nowrap; max-width: 52px; overflow: hidden; text-overflow: ellipsis; }
.row-time { font-size: 11px; color: var(--text2); }

.row-teams {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  cursor: pointer;
}
.team-name { font-size: 12px; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.team-name--away { text-align: right; }
.row-vs { font-size: 10px; color: var(--text3); font-family: var(--font-disp); flex-shrink: 0; }

.row-picks {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.row-no-odds { font-size: 10px; color: var(--text3); flex-shrink: 0; }

/* Pick buttons */
.pk {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  padding: 4px 6px;
  border-radius: 5px;
  border: 1px solid var(--line);
  background: transparent;
  cursor: pointer;
  transition: all .12s;
  min-width: 42px;
}
.pk:active { transform: translateY(1px); }
.pk-lbl { font-size: 9px; color: var(--text3); font-family: var(--font); white-space: nowrap; }
.pk-odd { font-size: 12px; font-weight: 600; color: var(--text2); }

/* Pick selected states */
.pk-h.pk--on { background: color-mix(in srgb, var(--primary) 15%, transparent); border-color: var(--primary); }
.pk-h.pk--on .pk-lbl { color: var(--primary); }
.pk-h.pk--on .pk-odd { color: var(--primary); }

.pk-d.pk--on { background: color-mix(in srgb, var(--draw-c, #f59e0b) 15%, transparent); border-color: var(--draw-c, #f59e0b); }
.pk-d.pk--on .pk-lbl { color: var(--draw-c, #f59e0b); }
.pk-d.pk--on .pk-odd { color: var(--draw-c, #f59e0b); }

.pk-a.pk--on { background: color-mix(in srgb, var(--green, #22c55e) 15%, transparent); border-color: var(--green, #22c55e); }
.pk-a.pk--on .pk-lbl { color: var(--green, #22c55e); }
.pk-a.pk--on .pk-odd { color: var(--green, #22c55e); }

/* ── Action bar ───────────────────────────────────────────────── */
.action-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: var(--card);
  border-top: 1.5px solid var(--primary);
  padding: 10px 14px calc(10px + env(safe-area-inset-bottom));
  display: flex;
  flex-direction: column;
  gap: 10px;
  z-index: 40;
}

.parlay-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.parlay-label { font-size: 11px; color: var(--text3); flex-shrink: 0; }
.parlay-chips { display: flex; gap: 5px; flex-wrap: wrap; }
.parlay-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 14px;
  border: 1.5px solid var(--line);
  background: transparent;
  font-size: 12px;
  font-weight: 600;
  color: var(--text2);
  cursor: pointer;
  font-family: var(--font);
  transition: all .12s;
}
.parlay-chip.parlay-chip--on {
  border-color: var(--primary);
  background: color-mix(in srgb, var(--primary) 12%, transparent);
  color: var(--primary);
}
.chip-bets { font-size: 10px; color: inherit; opacity: .7; font-family: var(--font-num); }

.bar-row2 { display: flex; align-items: center; gap: 10px; }

.stake-group {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
}
.stake-label { font-size: 11px; color: var(--text3); }
.stake-sym { font-size: 13px; color: var(--text2); }
.stake-input {
  width: 44px;
  background: var(--bg);
  border: 1.5px solid var(--line);
  border-radius: 5px;
  color: var(--text);
  font-size: 13px;
  font-weight: 600;
  padding: 3px 5px;
  text-align: center;
  font-family: var(--font-num);
}
.stake-input:focus { outline: none; border-color: var(--primary); }

.bar-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
}
.summary-item { display: flex; flex-direction: column; gap: 1px; }
.s-label { font-size: 9px; color: var(--text3); }
.s-val { font-size: 13px; font-weight: 700; color: var(--text); }
.summary-sep { color: var(--text3); font-size: 12px; }

.gen-btn {
  padding: 8px 16px;
  background: var(--primary);
  color: #fff;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 700;
  font-family: var(--font-disp);
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition: opacity .12s;
  letter-spacing: .3px;
}
.gen-btn:disabled { opacity: .4; cursor: not-allowed; }
.gen-btn:not(:disabled):active { opacity: .8; transform: translateY(1px); }

/* ── Sheet (result overlay) ───────────────────────────────────── */
.sheet-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.6);
  z-index: 50;
  display: flex;
  align-items: flex-end;
}
.sheet {
  width: 100%;
  max-height: 85dvh;
  background: var(--card);
  border-radius: 14px 14px 0 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.sheet-handle {
  width: 36px;
  height: 4px;
  background: var(--line);
  border-radius: 2px;
  margin: 10px auto 0;
  flex-shrink: 0;
}
.sheet-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 14px 16px 10px;
  flex-shrink: 0;
}
.sheet-title { font-size: 15px; font-weight: 700; }
.sheet-close {
  font-size: 14px;
  color: var(--text3);
  background: transparent;
  cursor: pointer;
  padding: 4px;
  line-height: 1;
}

.sheet-legs {
  flex: 1;
  overflow-y: auto;
  border-top: var(--card-bd);
}
.sheet-leg {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  border-bottom: var(--card-bd);
}
.sheet-leg:last-child { border-bottom: none; }
.leg-idx { font-size: 12px; font-weight: 700; color: var(--text3); min-width: 20px; }
.leg-info { flex: 1; min-width: 0; }
.leg-teams { font-size: 13px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.leg-pick {
  font-size: 11px;
  font-weight: 700;
  padding: 3px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
.pk-h { background: color-mix(in srgb, var(--primary) 15%, transparent); color: var(--primary); }
.pk-d { background: color-mix(in srgb, var(--draw-c, #f59e0b) 15%, transparent); color: var(--draw-c, #f59e0b); }
.pk-a { background: color-mix(in srgb, var(--green, #22c55e) 15%, transparent); color: var(--green, #22c55e); }
.leg-odd-val { font-size: 14px; font-weight: 700; color: var(--text); min-width: 36px; text-align: right; }

.sheet-dashed {
  border: none;
  border-top: 1.5px dashed var(--line);
  flex-shrink: 0;
}
.sheet-foot {
  display: flex;
  gap: 0;
  flex-shrink: 0;
  padding: 14px 16px;
  flex-wrap: wrap;
  row-gap: 10px;
}
.foot-stat { flex: 1; min-width: 80px; display: flex; flex-direction: column; gap: 3px; }
.foot-big { font-size: 18px; font-weight: 700; line-height: 1; }
.sheet-note {
  font-size: 10px;
  text-align: center;
  padding: 0 16px 14px;
  flex-shrink: 0;
}

/* ── AI sub-tab ───────────────────────────────────────────────── */
.ai-subtabs {
  display: flex;
  border-bottom: var(--card-bd);
  flex-shrink: 0;
}
.ai-subtab {
  flex: 1;
  padding: 9px 4px;
  font-size: 12px;
  font-weight: 600;
  font-family: var(--font);
  background: transparent;
  cursor: pointer;
  color: var(--text2);
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
}
.ai-subtab.on { color: var(--primary); border-bottom-color: var(--primary); }

.ticket-wrap { padding: 14px; flex: 1; overflow-y: auto; }
.ticket-card { margin-bottom: 12px; }
.ticket-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
}
.legs { display: flex; flex-direction: column; }
.leg-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: var(--card-bd);
}
.leg-row:last-child { border-bottom: none; }
.leg-num { font-size: 12px; font-weight: 700; color: var(--text3); min-width: 22px; }
.leg-match { flex: 1; }
.leg-odd-val { font-size: 14px; font-weight: 600; min-width: 36px; text-align: right; }

.rationale { padding: 0 0 8px; }

/* ── Shared ───────────────────────────────────────────────────── */
.empty-tip {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}

/* ── Transitions ─────────────────────────────────────────────── */
.bar-enter-active, .bar-leave-active { transition: transform .2s ease, opacity .2s ease; }
.bar-enter-from, .bar-leave-to { transform: translateY(100%); opacity: 0; }

.sheet-enter-active, .sheet-leave-active { transition: opacity .2s ease; }
.sheet-enter-from, .sheet-leave-to { opacity: 0; }
.sheet-enter-active .sheet, .sheet-leave-active .sheet { transition: transform .25s cubic-bezier(.32,0,.67,0); }
.sheet-enter-from .sheet, .sheet-leave-to .sheet { transform: translateY(100%); }
</style>
