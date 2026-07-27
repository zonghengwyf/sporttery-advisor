<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { betsApi, type BetRecord, type BetSummary } from '@/api'

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

function planLabel(planId: string) {
  return { conservative: '稳健', balanced: '均衡', high_odds: '博高赔', scoreline: '比分', manual: '手动' }[planId] ?? planId
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
</script>

<template>
  <div class="view">

    <!-- ── Summary cards ─────────────────────────────────────── -->
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

    <!-- ── Filter tabs ────────────────────────────────────────── -->
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

    <!-- ── Loading ────────────────────────────────────────────── -->
    <div v-if="loading" class="center-msg">
      <div class="spin-ring" />
    </div>

    <!-- ── Empty ──────────────────────────────────────────────── -->
    <div v-else-if="!filtered.length" class="center-msg empty-msg">
      <svg width="40" height="40" viewBox="0 0 40 40" fill="none" stroke="currentColor" stroke-width="1.4" class="empty-icon">
        <rect x="8" y="8" width="24" height="24" rx="4"/>
        <path d="M14 20h12M14 15h8M14 25h6"/>
      </svg>
      <p>{{ filter === 'all' ? '还没有投注记录' : `暂无${{ pending:'待结算', won:'已中', lost:'未中' }[filter]}记录` }}</p>
      <p class="empty-hint">在投注方案页标记您购买的方案</p>
    </div>

    <!-- ── Timeline ───────────────────────────────────────────── -->
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

  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; min-height: 100%; padding-bottom: 32px; }

/* ── Summary ─────────────────────────────────────────────────── */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--line);
  border-bottom: 1px solid var(--line);
  margin-bottom: 0;
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

.sub-stats {
  display: flex;
  align-items: center;
  gap: 0;
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
  gap: 0;
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
@keyframes spin { to { transform: rotate(360deg); } }
.empty-msg { color: var(--text2); font-size: 13px; text-align: center; }
.empty-icon { color: var(--text3); margin-bottom: 4px; }
.empty-hint { font-size: 11px; color: var(--text3); }

/* ── Timeline ────────────────────────────────────────────────── */
.timeline { display: flex; flex-direction: column; gap: 0; }
.bet-card {
  background: var(--card);
  border-bottom: var(--card-bd);
}

/* Card header */
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

/* Legs */
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

/* Card footer */
.bet-card-foot {
  display: flex; align-items: center;
  padding: 10px 14px;
  gap: 0;
}
.foot-cell { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.foot-label { font-size: 10px; color: var(--text3); }
.foot-val { font-size: 14px; font-weight: 700; }
.foot-sep { width: 1px; background: var(--line); align-self: stretch; margin: 0 8px; }

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
</style>
