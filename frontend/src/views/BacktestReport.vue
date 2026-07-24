<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import api from '@/api'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const report = ref<any>(null)
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    // backend: GET /backtest/metrics returns {days, metrics: {brier, log_loss, rps, ece}}
    const { data } = await api.get('/backtest/metrics')
    const m = data.metrics ?? {}
    report.value = {
      metrics: [
        { key: 'brier',    label: 'Brier Score', value: m.brier    ?? 0, desc: '越低越好，< 0.2 优秀', vs_baseline: null },
        { key: 'log_loss', label: 'Log Loss',     value: m.log_loss ?? 0, desc: '越低越好，< 0.5 良好', vs_baseline: null },
        { key: 'rps',      label: 'RPS',          value: m.rps      ?? 0, desc: '等级概率分',           vs_baseline: null },
        { key: 'ece',      label: 'ECE',          value: m.ece      ?? 0, desc: '校准误差，越低越好',   vs_baseline: null },
      ],
      dates: [],
      brier_series: [],
      baseline_series: [],
      by_risk: [],
    }
  } catch {
    report.value = null
  } finally {
    loading.value = false
  }
}

function metricClass(key: string, val: number) {
  if (key === 'brier') return val < 0.2 ? 'text-primary' : val < 0.25 ? '' : 'text-muted'
  if (key === 'log_loss') return val < 0.5 ? 'text-primary' : ''
  return ''
}

const chartOption = () => ({
  backgroundColor: 'transparent',
  tooltip: { trigger: 'axis', confine: true },
  legend: { bottom: 0, textStyle: { color: 'var(--text2)', fontSize: 11 } },
  grid: { top: 12, left: 8, right: 8, bottom: 36, containLabel: true },
  xAxis: {
    type: 'category',
    data: report.value?.dates ?? [],
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
      name: 'Brier',
      type: 'line',
      data: report.value?.brier_series ?? [],
      smooth: true,
      symbol: 'none',
      lineStyle: { color: 'var(--primary)', width: 2 },
    },
    {
      name: '基线',
      type: 'line',
      data: report.value?.baseline_series ?? [],
      smooth: true,
      symbol: 'none',
      lineStyle: { color: 'var(--text3)', width: 1.5, type: 'dashed' },
    },
  ],
})

onMounted(load)
</script>

<template>
  <div class="view">
    <header class="page-header">
      <h1 class="page-title">回测报告</h1>
      <p class="page-sub">预测精度评估 · Dixon-Coles 基线对标</p>
    </header>

    <div v-if="loading" class="p-5">
      <div class="skeleton" style="height:100px;margin-bottom:12px" />
      <div class="skeleton" style="height:240px" />
    </div>

    <template v-else-if="report">
      <!-- Key metrics -->
      <div class="metrics-grid p-4">
        <div
          v-for="m in report.metrics"
          :key="m.key"
          class="metric-card card no-accent p-4"
        >
          <div class="section-label" style="margin-bottom:4px">{{ m.label }}</div>
          <div class="stat-val" :class="metricClass(m.key, m.value)">{{ m.value.toFixed(4) }}</div>
          <div class="text-xs text-muted mt-1">{{ m.desc }}</div>
          <div
            v-if="m.vs_baseline != null"
            class="text-xs mt-2 font-600"
            :style="m.vs_baseline < 0 ? 'color:var(--green)' : 'color:var(--primary)'"
          >
            vs 基线 {{ m.vs_baseline > 0 ? '+' : '' }}{{ m.vs_baseline.toFixed(4) }}
          </div>
        </div>
      </div>

      <!-- Trend chart -->
      <div class="chart-section">
        <div class="section-label px-4 mb-0">Brier Score 趋势</div>
        <div class="chart-wrap">
          <VChart :option="chartOption()" autoresize style="height:100%" />
        </div>
      </div>

      <!-- Summary table -->
      <div class="px-4 pb-5">
        <div class="section-label mb-2">按风险等级</div>
        <div class="card no-accent">
          <table class="summary-table">
            <thead>
              <tr>
                <th class="font-disp">风险等级</th>
                <th class="font-disp">场次</th>
                <th class="font-disp">准确率</th>
                <th class="font-disp">ROI</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in report.by_risk" :key="row.label">
                <td>
                  <span class="badge" :class="row.label === '低风险' ? 'badge-green' : row.label === '高风险' ? 'badge-red' : 'badge-gold'">
                    {{ row.label }}
                  </span>
                </td>
                <td class="font-num">{{ row.count }}</td>
                <td class="font-num" :style="row.accuracy > 0.6 ? 'color:var(--green)' : ''">
                  {{ (row.accuracy * 100).toFixed(1) }}%
                </td>
                <td class="font-num" :style="row.roi >= 0 ? 'color:var(--green)' : 'color:var(--primary)'">
                  {{ row.roi >= 0 ? '+' : '' }}{{ (row.roi * 100).toFixed(1) }}%
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <div v-else class="empty-tip">
      <p class="font-disp" style="font-size:18px;color:var(--text3)">No Report</p>
      <p class="text-sm text-muted mt-2">回测数据不足，请先完成若干场次预测</p>
    </div>
  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; }

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
}
@media (min-width: 768px) {
  .metrics-grid { grid-template-columns: repeat(4, 1fr); }
}
.metric-card { }

.chart-section { padding: 0 16px; margin-bottom: 16px; }
.chart-wrap {
  height: 220px;
  background: var(--card);
  border: var(--card-bd);
  border-radius: var(--radius);
  margin-top: 8px;
  overflow: hidden;
}

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

.empty-tip {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
}
</style>
