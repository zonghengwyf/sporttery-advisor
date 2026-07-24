<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/api'

const TYPES = [
  { key: 'conservative', label: 'CONSERVATIVE', sub: '稳健票' },
  { key: 'balanced', label: 'BALANCED', sub: '均衡票' },
  { key: 'aggressive', label: 'AGGRESSIVE', sub: '博高赔' },
  { key: 'score', label: 'SCORE BET', sub: '比分小注' },
]

const activeType = ref('conservative')
const tickets = ref<Record<string, any>>({})
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const today = new Date().toISOString().split('T')[0]
    // Get today's matches first, then generate tickets
    const { data: matches } = await api.get('/matches/', { params: { sale_date: today } })
    if (!matches?.length) { tickets.value = {}; return }
    const matchIds: number[] = matches.map((m: any) => m.id)
    const { data } = await api.post('/tickets/generate', { match_ids: matchIds })
    // Backend returns {conservative, balanced, high_odds, scoreline, stake_allocation}
    tickets.value = {
      conservative: data.conservative,
      balanced: data.balanced,
      aggressive: data.high_odds,
      score: data.scoreline,
    }
  } catch {
    tickets.value = {}
  } finally {
    loading.value = false
  }
}

function pickClass(pick: string) {
  if (pick === '主胜' || pick === '3') return 'pick-win'
  if (pick === '平局' || pick === '1') return 'pick-draw'
  return 'pick-lose'
}

function totalOdds(legs: any[]) {
  return legs.reduce((acc, l) => acc * (l.odds ?? 1), 1).toFixed(2)
}

onMounted(load)
</script>

<template>
  <div class="view">
    <header class="page-header">
      <h1 class="page-title">投注方案</h1>
      <p class="page-sub">今日推荐方案 · 4 种票型</p>
    </header>

    <!-- Type tabs (editorial ALL CAPS) -->
    <div class="type-tabs">
      <button
        v-for="t in TYPES"
        :key="t.key"
        class="type-tab"
        :class="{ on: activeType === t.key }"
        @click="activeType = t.key"
      >
        <span class="tab-label">{{ t.label }}</span>
        <span class="tab-sub">{{ t.sub }}</span>
      </button>
    </div>

    <div v-if="loading" class="p-5">
      <div class="skeleton" style="height:240px" />
    </div>

    <div v-else class="ticket-wrap">
      <template v-if="tickets[activeType]">
        <div class="card no-accent active-accent ticket-card">
          <!-- Ticket head -->
          <div class="ticket-head">
            <div>
              <div class="font-disp" style="font-size:15px;font-weight:700;text-transform:uppercase">
                {{ TYPES.find(t => t.key === activeType)?.label }}
              </div>
              <div class="text-xs text-muted mt-1">{{ TYPES.find(t => t.key === activeType)?.sub }}</div>
            </div>
            <span class="badge badge-red">{{ tickets[activeType].risk_label || '中风险' }}</span>
          </div>

          <!-- Legs -->
          <div class="divider" />
          <div class="legs">
            <div
              v-for="(leg, i) in tickets[activeType].legs"
              :key="i"
              class="leg-row"
            >
              <div class="leg-num font-disp">{{ String(i + 1).padStart(2, '0') }}</div>
              <div class="leg-match">
                <div class="font-600" style="font-size:13px">{{ leg.home_team }} vs {{ leg.away_team }}</div>
                <div class="text-xs text-muted">{{ leg.league }}</div>
              </div>
              <span class="pick" :class="pickClass(leg.pick)">{{ leg.pick }}</span>
              <span class="leg-odd font-num">{{ leg.odds?.toFixed(2) ?? '—' }}</span>
            </div>
          </div>

          <!-- Footer summary -->
          <div class="divider" />
          <div class="ticket-foot">
            <div class="foot-left">
              <div class="text-xs text-muted">建议投注</div>
              <div class="font-disp" style="font-size:18px;font-weight:700;color:var(--text)">
                ¥{{ tickets[activeType].stake ?? 20 }}
              </div>
            </div>
            <div class="foot-right">
              <div class="text-xs text-muted">总赔率</div>
              <div class="font-disp" style="font-size:18px;font-weight:700;color:var(--primary)">
                × {{ tickets[activeType].total_odds?.toFixed(2) ?? totalOdds(tickets[activeType].legs) }}
              </div>
            </div>
            <div class="foot-right">
              <div class="text-xs text-muted">预期盈利</div>
              <div class="font-disp" style="font-size:18px;font-weight:700;color:var(--green)">
                ¥{{ Math.round((tickets[activeType].total_odds ?? 1) * (tickets[activeType].stake ?? 20)) }}
              </div>
            </div>
          </div>
        </div>

        <!-- AI rationale -->
        <div v-if="tickets[activeType].rationale" class="rationale">
          <div class="flex items-center gap-2 mb-2">
            <div class="chat-avatar" style="font-size:10px;width:22px;height:22px">AI</div>
            <span class="text-xs font-disp" style="color:var(--text3)">方案说明</span>
          </div>
          <p class="chat-bubble-ai">{{ tickets[activeType].rationale }}</p>
        </div>
      </template>

      <div v-else class="empty-tip">
        <p class="font-disp" style="font-size:18px;color:var(--text3)">No Ticket</p>
        <p class="text-sm text-muted mt-2">请先同步赛事并完成分析</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; }

.type-tabs {
  display: flex;
  gap: 0;
  border-bottom: var(--card-bd);
  overflow-x: auto;
  flex-shrink: 0;
}
.type-tab {
  flex: 1;
  min-width: 80px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 10px 8px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all .15s;
  background: transparent;
  font-family: var(--font);
}
.type-tab.on {
  border-bottom-color: var(--primary);
  color: var(--primary);
}
.tab-label {
  font-family: var(--font-disp);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .4px;
}
.tab-sub {
  font-size: 10px;
  color: var(--text3);
}

.ticket-wrap {
  padding: 16px;
  flex: 1;
  overflow-y: auto;
}

.ticket-card { margin-bottom: 12px; }
.ticket-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
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
.leg-num {
  font-size: 13px;
  font-weight: 700;
  color: var(--text3);
  min-width: 22px;
}
.leg-match { flex: 1; }
.leg-odd {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  min-width: 36px;
  text-align: right;
}

.ticket-foot {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: var(--bg);
}
.foot-left, .foot-right {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.foot-right { margin-left: auto; }
.foot-right + .foot-right { margin-left: 16px; }

.rationale {
  padding: 4px 0 8px;
}

.empty-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}
</style>
