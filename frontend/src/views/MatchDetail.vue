<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '@/api'

const route = useRoute()
const router = useRouter()

const match = ref<any>(null)
const prediction = ref<any>(null)
const loading = ref(true)
const analyzing = ref(false)

async function load() {
  loading.value = true
  try {
    const id = route.params.id
    const [mRes, pRes] = await Promise.allSettled([
      api.get(`/matches/${id}`),
      api.get(`/predictions/${id}`),
    ])
    if (mRes.status === 'fulfilled') match.value = mRes.value.data
    if (pRes.status === 'fulfilled') prediction.value = pRes.value.data
  } finally {
    loading.value = false
  }
}

async function triggerAnalysis() {
  analyzing.value = true
  try {
    // backend route: POST /predictions/{match_id}/analyze
    const { data } = await api.post(`/predictions/${route.params.id}/analyze`)
    prediction.value = data
  } finally {
    analyzing.value = false
  }
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleString('zh-CN', {
    month: 'numeric', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// fused_probs = {home, draw, away}
function homePct() {
  const v = prediction.value?.fused_probs?.home
  return v != null ? Math.round(v * 100) + '%' : '—'
}
function drawPct() {
  const v = prediction.value?.fused_probs?.draw
  return v != null ? Math.round(v * 100) + '%' : '—'
}
function awayPct() {
  const v = prediction.value?.fused_probs?.away
  return v != null ? Math.round(v * 100) + '%' : '—'
}
function homeOdds() { return match.value?.sporttery_odds?.home ?? null }
function drawOdds() { return match.value?.sporttery_odds?.draw ?? null }
function awayOdds() { return match.value?.sporttery_odds?.away ?? null }
function aiSummary() { return prediction.value?.intel_summary ?? null }

onMounted(load)
</script>

<template>
  <div class="view">
    <!-- Back header -->
    <header class="page-header">
      <button class="back-btn" @click="router.back()">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M10 3L5 8l5 5"/>
        </svg>
        返回
      </button>
    </header>

    <div v-if="loading" class="p-5">
      <div class="skeleton" style="height:120px;margin-bottom:12px" />
      <div class="skeleton" style="height:80px;margin-bottom:12px" />
      <div class="skeleton" style="height:200px" />
    </div>

    <template v-else-if="match">
      <!-- Match hero -->
      <div class="match-hero">
        <div class="text-xs text-muted font-disp mb-2">{{ match.league }}</div>
        <div class="hero-teams">
          <div class="hero-team">
            <div class="hero-team-name">{{ match.home_team }}</div>
            <div class="text-xs text-muted">主场</div>
          </div>
          <div class="hero-vs">
            <div class="font-disp" style="font-size:12px;color:var(--text3)">VS</div>
            <div class="text-xs text-muted mt-1">{{ formatTime(match.kickoff_at) }}</div>
          </div>
          <div class="hero-team" style="align-items:flex-end">
            <div class="hero-team-name">{{ match.away_team }}</div>
            <div class="text-xs text-muted">客场</div>
          </div>
        </div>
      </div>

      <!-- Odds + probs -->
      <div class="section px-4 pb-4" v-if="homeOdds()">
        <div class="section-label">赔率 & 概率</div>
        <div class="card no-accent">
          <div class="odds-table">
            <div class="odds-col">
              <div class="odds-head font-disp">主胜</div>
              <div class="odds-num win">{{ homeOdds()?.toFixed(2) }}</div>
              <div class="prob-bar mt-2" style="height:4px">
                <div class="prob-fill" :style="{ width: homePct() }" />
              </div>
              <div class="odds-prob">{{ homePct() }}</div>
            </div>
            <div class="odds-divider" />
            <div class="odds-col">
              <div class="odds-head font-disp">平局</div>
              <div class="odds-num draw">{{ drawOdds()?.toFixed(2) }}</div>
              <div class="prob-bar mt-2" style="height:4px">
                <div class="prob-fill blue" :style="{ width: drawPct() }" />
              </div>
              <div class="odds-prob">{{ drawPct() }}</div>
            </div>
            <div class="odds-divider" />
            <div class="odds-col">
              <div class="odds-head font-disp">客胜</div>
              <div class="odds-num lose">{{ awayOdds()?.toFixed(2) }}</div>
              <div class="prob-bar mt-2" style="height:4px">
                <div class="prob-fill" style="background:var(--text3)" :style="{ width: awayPct() }" />
              </div>
              <div class="odds-prob">{{ awayPct() }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- AI analysis -->
      <div class="section px-4 pb-4">
        <div class="section-label">AI 分析</div>

        <div v-if="prediction" class="card no-accent active-accent">
          <div class="p-4">
            <div class="flex items-center gap-2 mb-3">
              <div class="chat-avatar">AI</div>
              <div>
                <span class="badge badge-red">{{ prediction.risk_label || '中风险' }}</span>
              </div>
            </div>
            <p style="font-size:13px;line-height:1.7;color:var(--text2)">
              {{ aiSummary() || '暂无分析摘要' }}
            </p>
            <div v-if="prediction.tickets?.key_factors?.length" class="mt-3">
              <div class="text-xs font-disp" style="color:var(--text3);margin-bottom:6px">关键因素</div>
              <div class="flex flex-col gap-1">
                <div
                  v-for="(f, i) in (prediction.tickets?.key_factors ?? []).slice(0, 4)"
                  :key="i"
                  class="factor-item"
                >
                  <span class="factor-dot" />
                  <span>{{ f }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="empty-analysis">
          <p class="text-sm text-muted mb-3">尚未分析此场比赛</p>
          <button class="btn btn-primary" :disabled="analyzing" @click="triggerAnalysis">
            <svg v-if="!analyzing" width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <circle cx="8" cy="8" r="6"/><path d="M8 4v4.5l3 1.5"/>
            </svg>
            {{ analyzing ? '分析中…' : '立即 AI 分析' }}
          </button>
        </div>
      </div>

      <!-- Go to chat -->
      <div class="section px-4 pb-5">
        <button class="btn btn-ghost w-full" @click="router.push(`/chat?match=${match.id}`)">
          继续 AI 追问对话 →
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; }

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-disp);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .4px;
  color: var(--text2);
  cursor: pointer;
  background: none;
  border: none;
  transition: color .15s;
}
.back-btn:hover { color: var(--primary); }

.match-hero {
  padding: 16px 20px 20px;
  border-bottom: var(--card-bd);
}
.hero-teams {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
}
.hero-team {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.hero-team:last-child { align-items: flex-end; }
.hero-team-name {
  font-size: 18px;
  font-weight: 700;
}
.hero-vs {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
}

.section { margin-top: 16px; }

.odds-table {
  display: flex;
  padding: 16px;
}
.odds-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.odds-head {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .6px;
  color: var(--text3);
  margin-bottom: 6px;
}
.odds-num {
  font-family: var(--font-disp);
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
}
.odds-num.win  { color: var(--win-c); }
.odds-num.draw { color: var(--draw-c); }
.odds-num.lose { color: var(--text3); }
.odds-prob { font-size: 12px; color: var(--text2); margin-top: 6px; font-weight: 500; }
.odds-divider { width: 1px; background: var(--line); margin: 0 8px; }

.factor-item {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: var(--text2);
}
.factor-dot {
  width: 5px; height: 5px;
  border-radius: 50%;
  background: var(--primary);
  flex-shrink: 0;
  margin-top: 5px;
}

.empty-analysis {
  background: var(--card);
  border: var(--card-bd);
  border-radius: var(--radius);
  padding: 24px;
  text-align: center;
}
</style>
