<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const match = ref<any>(null)
const prediction = ref<any>(null)
const loading = ref(true)
const analyzing = ref(false)
const votesExpanded = ref(false)
const isLoggedIn = computed(() => auth.isLoggedIn)

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
  if (!isLoggedIn.value) {
    router.push(`/login?redirect=${encodeURIComponent(route.fullPath)}`)
    return
  }
  analyzing.value = true
  try {
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

function homePct() {
  const v = prediction.value?.fused_probs?.home
  return v != null ? Math.round(v * 100) + '%' : '-'
}
function drawPct() {
  const v = prediction.value?.fused_probs?.draw
  return v != null ? Math.round(v * 100) + '%' : '-'
}
function awayPct() {
  const v = prediction.value?.fused_probs?.away
  return v != null ? Math.round(v * 100) + '%' : '-'
}
function homeOdds() { return match.value?.sporttery_odds?.home ?? null }
function drawOdds() { return match.value?.sporttery_odds?.draw ?? null }
function awayOdds() { return match.value?.sporttery_odds?.away ?? null }
function aiSummary() { return prediction.value?.intel_summary ?? null }

const ensembleVotes = computed<any[]>(() => {
  return prediction.value?.tickets?.ensemble_votes ?? []
})

const voteSummary = computed(() => {
  const votes = ensembleVotes.value
  const valid = votes.filter((v: any) => !v.error && v.outcome)
  if (!valid.length) return null
  const finalOutcome = prediction.value?.tickets?.final_outcome || ''
  const agree = valid.filter((v: any) => v.outcome === finalOutcome).length
  return { total: votes.length, valid: valid.length, agree, finalOutcome }
})

function outcomeLabel(o: string) {
  if (o === 'H') return '主胜'
  if (o === 'D') return '平局'
  if (o === 'A') return '客胜'
  return o
}

function outcomeClass(o: string) {
  if (o === 'H') return 'vote-win'
  if (o === 'D') return 'vote-draw'
  if (o === 'A') return 'vote-away'
  return ''
}

onMounted(load)
</script>

<template>
  <div class="view">
    <!-- Back bar -->
    <div class="back-bar">
      <button class="back-btn" @click="router.back()">
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M10 3L5 8l5 5"/>
        </svg>
        返回
      </button>
    </div>

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
            <div class="hero-vs-label">VS</div>
            <div class="text-xs text-muted">{{ formatTime(match.kickoff_at) }}</div>
          </div>
          <div class="hero-team">
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
              <div class="odds-prob mt-2">{{ homePct() }}</div>
            </div>
            <div class="odds-divider" />
            <div class="odds-col">
              <div class="odds-head font-disp">平局</div>
              <div class="odds-num draw">{{ drawOdds()?.toFixed(2) }}</div>
              <div class="odds-prob mt-2">{{ drawPct() }}</div>
            </div>
            <div class="odds-divider" />
            <div class="odds-col">
              <div class="odds-head font-disp">客胜</div>
              <div class="odds-num lose">{{ awayOdds()?.toFixed(2) }}</div>
              <div class="odds-prob mt-2">{{ awayPct() }}</div>
            </div>
          </div>
          <div v-if="prediction?.fused_probs" class="triple-bar">
            <div class="triple-seg triple-win"  :style="{ flex: prediction.fused_probs.home }"></div>
            <div class="triple-seg triple-draw" :style="{ flex: prediction.fused_probs.draw }"></div>
            <div class="triple-seg triple-away" :style="{ flex: prediction.fused_probs.away }"></div>
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
              <div v-if="voteSummary" class="ml-auto text-xs text-muted">
                {{ voteSummary.agree }}/{{ voteSummary.valid }} 模型共识
              </div>
            </div>
            <p class="ai-summary">
              {{ aiSummary() || '暂无分析摘要' }}
            </p>
            <div v-if="prediction.tickets?.key_factors?.length" class="mt-3">
              <div class="text-xs font-disp text-muted mb-2">关键因素</div>
              <div class="flex flex-col gap-1">
                <div
                  v-for="(f, i) in (prediction.tickets?.key_factors ?? []).slice(0, 4)"
                  :key="i"
                  class="factor-item"
                >{{ f }}</div>
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
            {{ analyzing ? '分析中…' : isLoggedIn ? '立即 AI 分析' : '登录后 AI 分析' }}
          </button>
        </div>
      </div>

      <!-- Ensemble votes -->
      <div v-if="ensembleVotes.length" class="section px-4 pb-4">
        <button class="votes-toggle" @click="votesExpanded = !votesExpanded">
          <span class="section-label" style="margin:0">模型投票</span>
          <span class="text-xs text-muted ml-2">{{ ensembleVotes.length }} 个模型参与</span>
          <svg
            class="toggle-icon"
            :class="{ 'rotate-180': votesExpanded }"
            width="14" height="14" viewBox="0 0 16 16" fill="none"
            stroke="currentColor" stroke-width="1.5"
          >
            <path d="M4 6l4 4 4-4"/>
          </svg>
        </button>

        <div v-if="votesExpanded" class="card no-accent votes-card">
          <!-- Summary row -->
          <div v-if="voteSummary" class="votes-summary">
            <span class="text-xs text-muted">共识方向：</span>
            <span class="vote-outcome-badge" :class="outcomeClass(voteSummary.finalOutcome)">
              {{ outcomeLabel(voteSummary.finalOutcome) }}
            </span>
            <span class="text-xs text-muted ml-2">{{ voteSummary.agree }}/{{ voteSummary.valid }} 有效票支持</span>
          </div>

          <!-- Vote rows -->
          <div class="votes-list">
            <div
              v-for="(vote, i) in ensembleVotes"
              :key="i"
              class="vote-row"
              :class="{ 'vote-row--error': !!vote.error }"
            >
              <div class="vote-model">
                <div class="vote-model-name">{{ vote.model }}</div>
                <div class="text-xs text-muted">{{ vote.provider }}</div>
              </div>
              <div v-if="!vote.error" class="vote-right">
                <span class="vote-outcome-badge mr-2" :class="outcomeClass(vote.outcome)">
                  {{ outcomeLabel(vote.outcome) }}
                </span>
                <div class="vote-conf-bar">
                  <div
                    class="vote-conf-fill"
                    :style="{ width: vote.confidence + '%' }"
                    :class="vote.confidence >= 60 ? 'conf-high' : vote.confidence >= 40 ? 'conf-mid' : 'conf-low'"
                  />
                </div>
                <span class="font-num text-xs ml-1" style="min-width:28px">{{ vote.confidence }}%</span>
                <span class="badge badge-gray ml-1" style="font-size:10px">{{ vote.risk_label }}</span>
              </div>
              <div v-else class="vote-right vote-error-msg">
                <span class="text-xs text-muted">{{ vote.error || '调用失败' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Go to chat -->
      <div class="section px-4 pb-5">
        <button class="btn btn-ghost w-full" @click="router.push(`/chat?match=${match.id}`)">
          继续追问
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 8h10M9 4l4 4-4 4"/>
          </svg>
        </button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; }

.back-bar { padding: 8px 16px; flex-shrink: 0; }
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

.match-hero { padding: 16px 20px 20px; border-bottom: var(--card-bd); }
.hero-teams { display: flex; align-items: center; gap: 12px; margin-top: 8px; }
.hero-team { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.hero-team:last-child { align-items: flex-end; }
.hero-team-name { font-size: 24px; font-weight: 700; line-height: 1.2; }
.hero-vs { display: flex; flex-direction: column; align-items: center; flex-shrink: 0; gap: 4px; }
.hero-vs-label { font-family: var(--font-disp); font-size: 16px; font-weight: 700; letter-spacing: 2px; color: var(--text3); }

.section { margin-top: 16px; }

.odds-table { display: flex; padding: 16px; }
.odds-col { flex: 1; display: flex; flex-direction: column; align-items: center; text-align: center; }
.odds-head { font-size: 10px; font-weight: 600; letter-spacing: .6px; color: var(--text3); margin-bottom: 6px; }
.odds-num { font-family: var(--font-disp); font-size: 44px; font-weight: 700; line-height: 1; }
.odds-num.win  { color: var(--win-c); }
.odds-num.draw { color: var(--draw-c); }
.odds-num.lose { color: var(--text2); }
.odds-prob { font-size: 12px; color: var(--text2); font-weight: 500; }
.odds-divider { width: 1px; background: var(--line); margin: 0 8px; }

.triple-bar { display: flex; height: 8px; margin: 4px 16px 16px; border-radius: 4px; overflow: hidden; gap: 2px; }
.triple-seg { transition: flex-grow .5s ease; }
.triple-win  { background: var(--win-c); }
.triple-draw { background: var(--draw-c); }
.triple-away { background: var(--lose-c); }

.ai-summary { font-size: 13px; line-height: 1.7; color: var(--text2); }
.factor-item { font-size: 12px; color: var(--text2); line-height: 1.6; padding-left: 10px; position: relative; }
.factor-item::before { content: ''; position: absolute; left: 0; top: 8px; width: 3px; height: 3px; border-radius: 50%; background: var(--text3); }
.empty-analysis { background: var(--card); border: var(--card-bd); border-radius: var(--radius); padding: 24px; text-align: center; }

/* Ensemble votes */
.votes-toggle {
  display: flex;
  align-items: center;
  width: 100%;
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 0 8px;
  font-family: var(--font);
  color: var(--text);
}
.toggle-icon { margin-left: auto; color: var(--text3); transition: transform .2s; }
.rotate-180 { transform: rotate(180deg); }

.votes-card { overflow: hidden; }
.votes-summary {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  border-bottom: var(--card-bd);
  gap: 6px;
}
.votes-list { display: flex; flex-direction: column; }
.vote-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: var(--card-bd);
}
.vote-row:last-child { border-bottom: none; }
.vote-row--error { opacity: 0.55; }
.vote-model { min-width: 100px; }
.vote-model-name { font-size: 13px; font-weight: 600; line-height: 1.3; }
.vote-right { display: flex; align-items: center; flex: 1; }
.vote-error-msg { justify-content: flex-end; }

.vote-outcome-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-disp);
  letter-spacing: .3px;
}
.vote-win  { background: rgba(34,197,94,.15); color: var(--win-c, #22c55e); }
.vote-draw { background: rgba(245,158,11,.15); color: var(--draw-c, #f59e0b); }
.vote-away { background: rgba(239,68,68,.15); color: var(--primary); }

.vote-conf-bar {
  flex: 1;
  height: 5px;
  background: var(--line);
  border-radius: 3px;
  overflow: hidden;
  max-width: 80px;
}
.vote-conf-fill { height: 100%; border-radius: 3px; transition: width .3s ease; }
.conf-high { background: var(--green, #22c55e); }
.conf-mid  { background: var(--draw-c, #f59e0b); }
.conf-low  { background: var(--primary); }
</style>
