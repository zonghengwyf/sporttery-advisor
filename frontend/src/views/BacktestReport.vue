<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import api from '@/api'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

interface MetricsData {
  brier: number | null
  log_loss: number | null
  rps: number | null
  ece: number | null
  n?: number
}

type MetricKey = 'brier' | 'log_loss' | 'rps' | 'ece'

interface HistoryItem {
  match_id: number
  home_team: string
  away_team: string
  risk_label: string | null
  actual_result: string | null
  predicted_outcome: string | null
  correct: boolean | null
}

interface ModelStat {
  key: string
  provider: string
  model: string
  total: number
  correct: number
  accuracy: number
}

const metrics = ref<MetricsData | null>(null)
const chartData = ref<{ dates: string[]; brier_series: number[]; baseline_series: number[] }>({
  dates: [], brier_series: [], baseline_series: [],
})
const history = ref<HistoryItem[]>([])
const modelStats = ref<ModelStat[]>([])
const loading = ref(true)
const noData = ref(false)

const byRisk = computed(() => {
  const groups: Record<string, { count: number; correct: number }> = {}
  for (const h of history.value) {
    if (h.correct == null) continue
    const label = riskLabel(h.risk_label)
    if (!groups[label]) groups[label] = { count: 0, correct: 0 }
    groups[label].count++
    if (h.correct) groups[label].correct++
  }
  return Object.entries(groups).map(([label, g]) => ({
    label,
    count: g.count,
    accuracy: g.count > 0 ? g.correct / g.count : 0,
    roi: g.count > 0 ? (g.correct / g.count - 0.5) * 0.9 : 0,
  }))
})

function riskLabel(r: string | null) {
  if (r === 'mainline') return '低风险'
  if (r === 'guarded') return '中风险'
  if (r === 'upset_cover' || r === 'upset') return '高风险'
  return '待评估'
}

async function load() {
  loading.value = true
  noData.value = false
  try {
    const [metricsRes, historyRes] = await Promise.allSettled([
      api.get('/backtest/metrics', { params: { days: 30 } }),
      api.get('/backtest/history', { params: { days: 30 } }),
    ])

    if (metricsRes.status === 'fulfilled') {
      const d = metricsRes.value.data
      metrics.value = d.metrics?.brier != null ? d.metrics : null
      if (d.chart?.dates?.length) chartData.value = d.chart
      if (d.message) noData.value = true
    }

    if (historyRes.status === 'fulfilled') {
      history.value = historyRes.value.data.history ?? []
      modelStats.value = historyRes.value.data.model_stats ?? []
    }
  } finally {
    loading.value = false
  }
}

function metricVal(v: number | null) {
  return v != null ? v.toFixed(4) : '–'
}

function metricClass(key: string, v: number | null) {
  if (v == null) return 'text-muted'
  if (key === 'brier') return v < 0.2 ? 'text-green' : v < 0.25 ? '' : 'text-primary'
  if (key === 'log_loss') return v < 0.5 ? 'text-green' : ''
  return ''
}

const chartOption = computed(() => ({
  backgroundColor: 'transparent',
  tooltip: { trigger: 'axis', confine: true },
  legend: { bottom: 0, textStyle: { color: 'var(--text2)', fontSize: 11 } },
  grid: { top: 12, left: 8, right: 8, bottom: 36, containLabel: true },
  xAxis: {
    type: 'category',
    data: chartData.value.dates,
    axisLine: { lineStyle: { color: 'var(--line)' } },
    axisLabel: { color: 'var(--text3)', fontSize: 11 },
  },
  yAxis: {
    type: 'value',
    min: 0, max: 0.35,
    axisLabel: { color: 'var(--text3)', fontSize: 11 },
    splitLine: { lineStyle: { color: 'var(--line)' } },
  },
  series: [
    {
      name: '模型 Brier',
      type: 'line',
      data: chartData.value.brier_series,
      smooth: true,
      symbol: 'none',
      lineStyle: { color: 'var(--primary)', width: 2 },
    },
    {
      name: '随机基线',
      type: 'line',
      data: chartData.value.baseline_series,
      smooth: true,
      symbol: 'none',
      lineStyle: { color: 'var(--text3)', width: 1.5, type: 'dashed' },
    },
  ],
}))

const METRIC_DEFS: { key: MetricKey; label: string; desc: string }[] = [
  { key: 'brier',    label: 'Brier 分',  desc: '越低越好，< 0.2 优秀' },
  { key: 'log_loss', label: '对数损失',  desc: '越低越好，< 0.5 良好' },
  { key: 'rps',      label: 'RPS',       desc: '等级概率分，越低越好' },
  { key: 'ece',      label: 'ECE',       desc: '校准误差，越低越好' },
]

onMounted(load)
</script>

<template>
  <div class="view">
    <div v-if="loading" class="p-5">
      <div class="skeleton" style="height:100px;margin-bottom:12px" />
      <div class="skeleton" style="height:240px;margin-bottom:12px" />
      <div class="skeleton" style="height:120px" />
    </div>

    <template v-else>
      <!-- No-data banner -->
      <div v-if="noData && !history.length" class="no-data-banner">
        <p class="text-sm text-muted">暂无回测数据 — 录入比赛实际结果后将自动更新</p>
      </div>

      <!-- Key metrics -->
      <div class="metrics-grid p-4">
        <div
          v-for="def in METRIC_DEFS"
          :key="def.key"
          class="metric-card card no-accent p-4"
        >
          <div class="section-label" style="margin-bottom:4px">{{ def.label }}</div>
          <div
            class="stat-val"
            :class="metricClass(def.key, metrics ? metrics[def.key] : null)"
          >
            {{ metricVal(metrics ? metrics[def.key] : null) }}
          </div>
          <div class="text-xs text-muted mt-1">{{ def.desc }}</div>
        </div>
      </div>

      <!-- Brier trend chart -->
      <div class="chart-section">
        <div class="section-label px-4 mb-0">Brier Score 趋势（近30天）</div>
        <div class="chart-wrap">
          <VChart v-if="chartData.dates.length" :option="chartOption" autoresize style="height:100%" />
          <div v-else class="chart-empty">暂无趋势数据</div>
        </div>
      </div>

      <!-- By-risk table -->
      <div class="px-4 pb-4">
        <div class="section-label mb-2">按风险等级（近30天）</div>
        <div class="card no-accent">
          <table v-if="byRisk.length" class="summary-table">
            <thead>
              <tr>
                <th class="font-disp">风险等级</th>
                <th class="font-disp">场次</th>
                <th class="font-disp">准确率</th>
                <th class="font-disp">估算 ROI</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in byRisk" :key="row.label">
                <td>
                  <span
                    class="badge"
                    :class="row.label === '低风险' ? 'badge-green' : row.label === '高风险' ? 'badge-red' : 'badge-gold'"
                  >
                    {{ row.label }}
                  </span>
                </td>
                <td class="font-num">{{ row.count }}</td>
                <td class="font-num" :class="row.accuracy > 0.6 ? 'text-green' : ''">
                  {{ (row.accuracy * 100).toFixed(1) }}%
                </td>
                <td class="font-num" :class="row.roi >= 0 ? 'text-green' : 'text-primary'">
                  {{ row.roi >= 0 ? '+' : '' }}{{ (row.roi * 100).toFixed(1) }}%
                </td>
              </tr>
            </tbody>
          </table>
          <div v-else class="empty-row">暂无已结算历史记录</div>
        </div>
      </div>

      <!-- Model accuracy table -->
      <div v-if="modelStats.length" class="px-4 pb-5">
        <div class="section-label mb-2">各模型准确率对比</div>
        <div class="card no-accent">
          <table class="summary-table">
            <thead>
              <tr>
                <th class="font-disp">模型</th>
                <th class="font-disp">场次</th>
                <th class="font-disp">正确</th>
                <th class="font-disp">准确率</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in modelStats" :key="s.key">
                <td>
                  <div class="model-name">{{ s.model }}</div>
                  <div class="text-xs text-muted">{{ s.provider }}</div>
                </td>
                <td class="font-num">{{ s.total }}</td>
                <td class="font-num">{{ s.correct }}</td>
                <td>
                  <div class="accuracy-bar-wrap">
                    <div class="accuracy-bar">
                      <div
                        class="accuracy-fill"
                        :class="s.accuracy >= 0.6 ? 'accuracy-fill--good' : s.accuracy >= 0.45 ? 'accuracy-fill--mid' : 'accuracy-fill--low'"
                        :style="{ width: (s.accuracy * 100).toFixed(0) + '%' }"
                      />
                    </div>
                    <span class="font-num accuracy-val" :class="s.accuracy >= 0.6 ? 'text-green' : ''">
                      {{ (s.accuracy * 100).toFixed(1) }}%
                    </span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- History empty state -->
      <div v-if="!history.length && !noData" class="empty-tip">
        <p class="empty-title">暂无报告</p>
        <p class="text-sm text-muted mt-2">完成若干场次预测并录入结果后自动生成</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; }

.no-data-banner {
  margin: 12px 16px 0;
  padding: 10px 14px;
  background: var(--primary-d);
  border-left: 3px solid var(--primary);
  border-radius: 4px;
  font-size: 12px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}
@media (min-width: 768px) {
  .metrics-grid { grid-template-columns: repeat(4, 1fr); }
}

.chart-section { padding: 0 16px; margin-bottom: 16px; }
.chart-wrap {
  height: 220px;
  background: var(--card);
  border: var(--card-bd);
  border-radius: var(--radius);
  margin-top: 8px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}
.chart-empty { font-size: 12px; color: var(--text3); }

.summary-table {
  width: 100%;
  border-collapse: collapse;
}
.summary-table th {
  text-align: left;
  padding: 8px 14px;
  font-size: 10px;
  letter-spacing: .5px;
  color: var(--text3);
  border-bottom: var(--card-bd);
}
.summary-table td {
  padding: 10px 14px;
  font-size: 12px;
  border-bottom: var(--card-bd);
}
.summary-table tr:last-child td { border-bottom: none; }

.empty-row {
  padding: 20px 16px;
  font-size: 12px;
  color: var(--text3);
  text-align: center;
}

.empty-tip {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
}

.model-name { font-size: 13px; font-weight: 600; line-height: 1.3; }

.accuracy-bar-wrap { display: flex; align-items: center; gap: 8px; }
.accuracy-bar {
  flex: 1;
  height: 6px;
  background: var(--line);
  border-radius: 3px;
  overflow: hidden;
  min-width: 60px;
}
.accuracy-fill {
  height: 100%;
  border-radius: 3px;
  transition: width .4s ease;
}
.accuracy-fill--good { background: var(--green, #22c55e); }
.accuracy-fill--mid  { background: var(--draw-c, #f59e0b); }
.accuracy-fill--low  { background: var(--primary); }
.accuracy-val { font-size: 12px; min-width: 40px; }
</style>
