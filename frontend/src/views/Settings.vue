<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import api from '@/api'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'

// ── Types ──────────────────────────────────────────────────────────────────
interface LLMConfig {
  id?: number
  name: string
  provider: string
  model: string
  api_key: string        // for new configs; empty for existing (never returned by API)
  _new_api_key?: string  // write-only: user-entered key when editing existing config
  base_url: string | null
  is_default: boolean
  status?: string                  // ok / error / unknown
  last_error?: string | null
  last_used_at?: string | null
  total_calls?: number
  total_prompt_tokens?: number
  total_completion_tokens?: number
  _confirmDelete?: boolean
  _open?: boolean
}

interface DSConfig {
  id?: number
  source_name: string
  use_scraper: boolean
  enabled: boolean
  has_api_key: boolean
  _api_key?: string
  _open?: boolean
}

interface WebhookConfig {
  url: string
  webhook_type: string
  enabled: boolean
}

interface EnsembleConfig {
  models: string
  strategy: string
  min_consensus: number
  min_confidence: number
  default_multiplier: number
  budget: number
}

// ── State ──────────────────────────────────────────────────────────────────
const activeTab = ref<'llm' | 'ds' | 'webhook' | 'ensemble' | 'auto_ticket'>('llm')
const llmConfigs = ref<LLMConfig[]>([])
const dsConfigs = ref<DSConfig[]>([])
const webhook = ref<WebhookConfig>({ url: '', webhook_type: 'generic', enabled: true })
const ensemble = ref<EnsembleConfig>({
  models: 'all', strategy: 'majority',
  min_consensus: 0.5, min_confidence: 40,
  default_multiplier: 2, budget: 100,
})

interface AutoTicketConfig {
  enabled: boolean
  cron: string
  sync_cron: string
  stake: number
}
const autoTicket = ref<AutoTicketConfig>({
  enabled: false,
  cron: '30 9 * * *',
  sync_cron: '0 2 * * *',
  stake: 100,
})
const newProvider = ref<string>('deepseek')
const loading = ref(true)
const saving = ref(false)
const testingLLM = ref<number | null>(null)
const testingWebhook = ref(false)
const llmResult = ref<Record<number, { ok: boolean; msg: string }>>({})

function showToast(msg: string, type: 'ok' | 'err' = 'ok') {
  if (type === 'ok') toast.success(msg)
  else toast.error(msg)
}

// ── Constants ──────────────────────────────────────────────────────────────
const PROVIDERS = ['claude', 'openai', 'gemini', 'deepseek', 'kimi', 'glm', 'custom'] as const

const PROVIDER_ACCENT: Record<string, string> = {
  claude:   'var(--red)',
  openai:   'var(--green)',
  gemini:   'var(--blue)',
  deepseek: 'var(--gold)',
  kimi:     'var(--text3)',
  glm:      'var(--blue)',
  custom:   'var(--text3)',
}

// 按 provider 缓存模型列表；key = provider name 或 `live-{config_id}`
const modelLists = ref<Record<string, string[]>>({})
const refreshingModels = ref<number | null>(null)

async function loadProviderModels(provider: string) {
  if (modelLists.value[provider]) return
  try {
    const { data } = await api.get('/settings/llm/models', { params: { provider } })
    modelLists.value[provider] = data
  } catch { /* 网络失败时 datalist 为空，不影响手动输入 */ }
}

async function refreshLiveModels(cfg: LLMConfig) {
  if (!cfg.id) return
  refreshingModels.value = cfg.id
  try {
    const { data } = await api.get(`/settings/llm/${cfg.id}/models`)
    modelLists.value[`live-${cfg.id}`] = data
    showToast(`已获取 ${data.length} 个可用模型`)
  } catch {
    showToast('获取模型列表失败', 'err')
  } finally {
    refreshingModels.value = null
  }
}

function modelOptions(cfg: LLMConfig): string[] {
  if (cfg.id && modelLists.value[`live-${cfg.id}`]) return modelLists.value[`live-${cfg.id}`]
  return modelLists.value[cfg.provider] ?? []
}

// 兼容 Kimi 等 provider 的版本后缀（moonshot-v1-8k-20240901 vs moonshot-v1-8k）
function isModelMismatch(cfg: LLMConfig): boolean {
  const opts = modelOptions(cfg)
  if (!cfg.model || opts.length === 0) return false
  if (opts.includes(cfg.model)) return false
  return !opts.some(m => m.startsWith(cfg.model + '-') || cfg.model.startsWith(m + '-'))
}


const PROVIDER_META: Record<string, { label: string; badge: string; chip: string; default_model: string; default_base_url: string }> = {
  claude:   { label: 'Claude',   badge: 'badge-red',   chip: 'CL',  default_model: 'claude-sonnet-4-6',  default_base_url: 'https://api.anthropic.com' },
  openai:   { label: 'OpenAI',   badge: 'badge-green', chip: 'GPT', default_model: 'gpt-4o',             default_base_url: 'https://api.openai.com/v1' },
  gemini:   { label: 'Gemini',   badge: 'badge-blue',  chip: 'GM',  default_model: 'gemini-2.5-flash',   default_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai' },
  deepseek: { label: 'DeepSeek', badge: 'badge-gold',  chip: 'DS',  default_model: 'deepseek-chat',      default_base_url: 'https://api.deepseek.com/v1' },
  kimi:     { label: 'Kimi',     badge: 'badge-gray',  chip: 'KI',  default_model: 'moonshot-v1-8k',     default_base_url: 'https://api.moonshot.cn/v1' },
  glm:      { label: 'GLM',      badge: 'badge-blue',  chip: 'GLM', default_model: 'glm-4-flash',        default_base_url: 'https://open.bigmodel.cn/api/paas/v4' },
  custom:   { label: '自定义',   badge: 'badge-gray',  chip: '~',   default_model: '',                   default_base_url: '' },
}

// Known data sources — merge with backend data
const KNOWN_SOURCES = [
  { source_name: 'sporttery',     label: '竞彩官方',       desc: '赛单与官方赔率',   role: '主数据源', roleColor: 'badge-red' },
  { source_name: 'odds_api',      label: 'The Odds API',   desc: '海外盘口先验概率', role: 'REFERENCE', roleColor: 'badge-blue' },
  { source_name: 'api_football',  label: 'API-Football',   desc: '伤停 / 阵容情报',  role: '情报源',   roleColor: 'badge-gold' },
  { source_name: 'football_data', label: 'football-data',  desc: '历史战绩数据集',   role: 'BENCHMARK', roleColor: 'badge-gray' },
  { source_name: 'clubelo',       label: 'ClubElo',        desc: '俱乐部 Elo 评分',  role: '基准',     roleColor: 'badge-gray' },
]

const WEBHOOK_TYPES = [
  { value: 'generic',  label: '通用 Webhook' },
  { value: 'wechat',   label: '企业微信' },
  { value: 'dingtalk', label: '钉钉' },
  { value: 'feishu',   label: '飞书' },
]

// ── Load ───────────────────────────────────────────────────────────────────
async function load() {
  loading.value = true
  try {
    const [llmRes, dsRes, whRes, ensRes, atRes] = await Promise.all([
      api.get('/settings/llm'),
      api.get('/settings/datasource'),
      api.get('/settings/webhook').catch(() => ({ data: null })),
      api.get('/settings/ensemble').catch(() => ({ data: null })),
      api.get('/settings/auto-ticket').catch(() => ({ data: null })),
    ])
    llmConfigs.value = llmRes.data

    // Merge known sources with backend data
    const dsMap = new Map<string, DSConfig>(dsRes.data.map((d: DSConfig) => [d.source_name, d]))
    dsConfigs.value = KNOWN_SOURCES.map(s => ({
      source_name: s.source_name,
      use_scraper: true,
      enabled: false,
      has_api_key: false,
      _open: false,
      ...(dsMap.get(s.source_name) ?? {}),
    }))

    if (whRes.data) webhook.value = whRes.data
    if (ensRes.data) ensemble.value = { ...ensemble.value, ...ensRes.data }
    if (atRes.data) autoTicket.value = { ...autoTicket.value, ...atRes.data }

    // 并发预加载所有 provider 的模型列表
    PROVIDERS.forEach(p => loadProviderModels(p))
  } finally {
    loading.value = false
  }
}

// ── LLM ────────────────────────────────────────────────────────────────────
function fmtTokens(n?: number): string {
  const v = n ?? 0
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M'
  if (v >= 1_000) return (v / 1_000).toFixed(1) + 'k'
  return String(v)
}
function addLLM() {
  const provider = newProvider.value || 'deepseek'
  const meta = PROVIDER_META[provider]
  llmConfigs.value.forEach(c => { c._open = false })
  llmConfigs.value.unshift({
    name: `${meta?.label ?? provider} 配置`,
    provider,
    model: meta?.default_model ?? '',
    api_key: '',
    base_url: null,
    is_default: llmConfigs.value.length === 0,
    _open: true,
  })
}

function toggleLLMCard(cfg: LLMConfig) {
  const opening = !cfg._open
  llmConfigs.value.forEach(c => { c._open = false })
  cfg._open = opening
}

function onProviderChange(cfg: LLMConfig) {
  loadProviderModels(cfg.provider)
  const meta = PROVIDER_META[cfg.provider]
  if (!meta) return
  cfg.model = meta.default_model
  cfg.base_url = null  // 切换服务商时总是清空 URL，避免 Kimi URL 挂在 DeepSeek 上
  if (!cfg.id) {
    cfg.name = meta.label ? `${meta.label} 配置` : '新配置'
  }
}

async function fixMismatch(cfg: LLMConfig) {
  const model = cfg.model
  let found = ''

  // 1. 精确匹配已缓存模型列表
  for (const [provider, models] of Object.entries(modelLists.value)) {
    if (provider.startsWith('live-')) continue
    if ((models as string[]).includes(model)) { found = provider; break }
  }

  // 2. 前缀启发式
  if (!found) {
    const m = model.toLowerCase()
    const guessMap: [string, string][] = [
      ['deepseek', 'deepseek'], ['moonshot', 'kimi'],
      ['glm', 'glm'], ['chatglm', 'glm'], ['claude', 'claude'],
      ['gemini', 'gemini'], ['gpt', 'openai'],
      ['o1', 'openai'], ['o3', 'openai'], ['o4', 'openai'],
    ]
    for (const [prefix, p] of guessMap) {
      if (m.startsWith(prefix)) { found = p; break }
    }
  }

  if (!found) {
    showToast('无法自动识别服务商，请手动选择', 'err')
    return
  }

  cfg.provider = found
  cfg.base_url = null
  loadProviderModels(found)

  // 已保存的配置直接写库，防止刷新复现
  if (cfg.id) {
    await saveLLM(cfg)
  }
}

function setDefault(cfg: LLMConfig) {
  llmConfigs.value.forEach(c => { c.is_default = false })
  cfg.is_default = true
}

async function saveLLM(cfg: LLMConfig) {
  saving.value = true
  try {
    const normalizedUrl = cfg.base_url?.trim() || null  // "" → null
    if (cfg.id) {
      const payload: Record<string, unknown> = {
        name: cfg.name, provider: cfg.provider, model: cfg.model,
        base_url: normalizedUrl, is_default: cfg.is_default,
      }
      if (cfg._new_api_key) payload.api_key = cfg._new_api_key
      await api.put(`/settings/llm/${cfg.id}`, payload)
      cfg.base_url = normalizedUrl
      cfg._new_api_key = ''
    } else {
      const { data } = await api.post('/settings/llm', {
        name: cfg.name, provider: cfg.provider, model: cfg.model,
        api_key: cfg.api_key, base_url: normalizedUrl, is_default: cfg.is_default,
      })
      cfg.id = data.id
      cfg.base_url = normalizedUrl
    }
    // Keep is_default in sync locally so other cards update without a full reload
    if (cfg.is_default) {
      llmConfigs.value.forEach(c => { if (c !== cfg) c.is_default = false })
    }
    showToast('LLM 配置已保存')
  } catch {
    showToast('保存失败', 'err')
  } finally {
    saving.value = false
  }
}

function confirmDeleteLLM(cfg: LLMConfig) {
  cfg._confirmDelete = true
}

async function deleteLLM(cfg: LLMConfig, idx: number) {
  cfg._confirmDelete = false
  if (!cfg.id) { llmConfigs.value.splice(idx, 1); return }
  try {
    await api.delete(`/settings/llm/${cfg.id}`)
    llmConfigs.value.splice(idx, 1)
    showToast('已删除')
  } catch {
    showToast('删除失败', 'err')
  }
}

async function testLLM(cfg: LLMConfig) {
  if (!cfg.id) return
  testingLLM.value = cfg.id
  try {
    const { data } = await api.post(`/settings/llm/${cfg.id}/test`)
    const ok = !!(data.success || data.ok)
    llmResult.value[cfg.id] = ok
      ? { ok: true,  msg: '连接成功' }
      : { ok: false, msg: data.error || '连接失败' }
    cfg.status = ok ? 'ok' : 'error'
    cfg.last_error = ok ? null : (data.error || '连接失败')
    cfg.total_calls = (cfg.total_calls ?? 0) + (ok ? 1 : 0)
  } catch {
    llmResult.value[cfg.id!] = { ok: false, msg: '连接失败' }
  } finally {
    testingLLM.value = null
  }
}

// ── Data Sources ────────────────────────────────────────────────────────────
async function toggleDS(cfg: DSConfig) {
  const prev = cfg.enabled
  try {
    await api.put('/settings/datasource', {
      source_name: cfg.source_name,
      use_scraper: cfg.use_scraper,
      enabled: cfg.enabled,
    })
    showToast(cfg.enabled ? `${cfg.source_name} 已启用` : `${cfg.source_name} 已停用`)
  } catch {
    cfg.enabled = prev
    showToast('保存失败', 'err')
  }
}

async function saveDS(cfg: DSConfig) {
  saving.value = true
  try {
    await api.put('/settings/datasource', {
      source_name: cfg.source_name,
      api_key: cfg._api_key || undefined,
      use_scraper: cfg.use_scraper,
      enabled: cfg.enabled,
    })
    if (cfg._api_key) { cfg.has_api_key = true; cfg._api_key = '' }
    cfg._open = false
    showToast(`${cfg.source_name} 已更新`)
  } catch {
    showToast('保存失败', 'err')
  } finally {
    saving.value = false
  }
}

// ── Webhook ─────────────────────────────────────────────────────────────────
async function saveWebhook() {
  saving.value = true
  try {
    await api.put('/settings/webhook', webhook.value)
    showToast('Webhook 已保存')
  } catch {
    showToast('保存失败', 'err')
  } finally {
    saving.value = false
  }
}

async function testWebhook() {
  testingWebhook.value = true
  try {
    await api.post('/settings/webhook/test')
    showToast('测试消息已发送')
  } catch (e: any) {
    showToast(e?.response?.data?.detail || 'Webhook 测试失败', 'err')
  } finally {
    testingWebhook.value = false
  }
}

// ── Auto Ticket ───────────────────────────────────────────────────────────────
function cronToTime(cron: string): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length < 2) return '09:30'
  const h = parseInt(parts[1]) || 0
  const m = parseInt(parts[0]) || 0
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
function timeToCron(time: string): string {
  const [hStr, mStr] = time.split(':')
  return `${parseInt(mStr) || 0} ${parseInt(hStr) || 0} * * *`
}
const ticketTime = ref(cronToTime(autoTicket.value.cron))
const syncTime   = ref(cronToTime(autoTicket.value.sync_cron))
watch(autoTicket, (v) => {
  ticketTime.value = cronToTime(v.cron)
  syncTime.value   = cronToTime(v.sync_cron)
}, { deep: true, once: true })

async function saveAutoTicket() {
  autoTicket.value.cron = timeToCron(ticketTime.value)
  autoTicket.value.sync_cron = timeToCron(syncTime.value)
  saving.value = true
  try {
    await api.put('/settings/auto-ticket', autoTicket.value)
    showToast('自动出票配置已保存')
  } catch {
    showToast('保存失败', 'err')
  } finally {
    saving.value = false
  }
}

// ── Ensemble ─────────────────────────────────────────────────────────────────
async function saveEnsemble() {
  saving.value = true
  try {
    await api.put('/settings/ensemble', ensemble.value)
    showToast('集成分析配置已保存')
  } catch {
    showToast('保存失败', 'err')
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="view">

    <!-- Tab bar -->
    <div class="s-tabs">
      <button
        v-for="tab in [
          { key: 'llm',     label: 'LLM 模型' },
          { key: 'ds',      label: '数据源' },
          { key: 'webhook', label: '通知推送' },
          { key: 'ensemble',   label: '集成分析' },
          { key: 'auto_ticket', label: '自动出票' },
        ]"
        :key="tab.key"
        class="s-tab"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key as any"
      >{{ tab.label }}</button>
    </div>

    <div v-if="loading" class="s-body">
      <div class="skeleton" style="height:80px;margin-bottom:8px"/>
      <div class="skeleton" style="height:80px;margin-bottom:8px"/>
      <div class="skeleton" style="height:80px"/>
    </div>

    <div v-else class="s-body">

      <!-- ══ LLM 模型 ══════════════════════════════════════════════════════ -->
      <template v-if="activeTab === 'llm'">

        <!-- toolbar -->
        <div class="lc-bar">
          <div class="lc-bar-l">
            <span class="lc-title">模型配置</span>
            <span v-if="llmConfigs.length" class="lc-count">{{ llmConfigs.length }}</span>
          </div>
          <div class="lc-bar-r">
            <label class="lc-pick-lbl" for="new-provider-sel">服务商</label>
            <Select v-model="newProvider">
              <SelectTrigger class="lc-pick" id="new-provider-sel">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem v-for="p in PROVIDERS" :key="p" :value="p">{{ PROVIDER_META[p]?.label ?? p }}</SelectItem>
              </SelectContent>
            </Select>
            <button class="lc-add" @click="addLLM">
              <svg width="11" height="11" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
              </svg>
              添加
            </button>
          </div>
        </div>

        <!-- Usage summary strip -->
        <div v-if="llmConfigs.filter(c => c.id).length > 0" class="lc-summary">
          <span class="lc-sum-item">
            <span class="lc-sum-val font-num">{{ llmConfigs.reduce((a, c) => a + (c.total_calls ?? 0), 0) }}</span>
            <span class="lc-sum-lbl">次调用</span>
          </span>
          <span class="lc-sum-sep">·</span>
          <span class="lc-sum-item">
            <span class="lc-sum-val font-num">{{ fmtTokens(llmConfigs.reduce((a, c) => a + (c.total_prompt_tokens ?? 0) + (c.total_completion_tokens ?? 0), 0)) }}</span>
            <span class="lc-sum-lbl">总 tokens</span>
          </span>
          <span class="lc-sum-sep">·</span>
          <span class="lc-sum-item">
            <span class="lc-sum-val font-num">{{ llmConfigs.filter(c => c.status === 'ok').length }}</span>
            <span class="lc-sum-lbl">/ {{ llmConfigs.filter(c => c.id).length }} 在线</span>
          </span>
          <span v-if="llmConfigs.some(c => c.status === 'error')" class="lc-sum-warn">
            <svg width="9" height="9" viewBox="0 0 20 20" fill="currentColor" style="flex-shrink:0">
              <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H2.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
            </svg>
            有配置异常
          </span>
        </div>

        <!-- empty state -->
        <div v-if="llmConfigs.length === 0" class="lc-empty">
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>
          </svg>
          <div>暂无 LLM 配置</div>
          <div class="lc-empty-sub">在上方选择服务商后点击「添加」</div>
        </div>

        <!-- config cards -->
        <div
          v-for="(cfg, i) in llmConfigs" :key="i"
          class="lc-card"
          :class="{ 'lc-card--default': cfg.is_default, 'lc-card--open': cfg._open }"
          :style="`--pa: ${PROVIDER_ACCENT[cfg.provider] ?? 'var(--text3)'}`"
        >
          <!-- card header (clickable, toggles expand) -->
          <div class="lc-head lc-head--btn" @click="toggleLLMCard(cfg)">
            <div class="lc-chip">{{ PROVIDER_META[cfg.provider]?.chip ?? cfg.provider.slice(0, 2).toUpperCase() }}</div>
            <div class="lc-meta">
              <span class="lc-pname">{{ cfg.name || '未命名' }}</span>
              <code class="lc-mslug">{{ cfg.model || '—' }}</code>
            </div>
            <div class="lc-tags">
              <template v-if="isModelMismatch(cfg)">
                <span class="lc-tag lc-tag--gold">
                  <svg width="8" height="8" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H2.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                  </svg>
                  不匹配
                </span>
                <button class="lc-fix-btn" @click.stop="fixMismatch(cfg)">修复</button>
              </template>
              <span v-if="cfg.id && llmResult[cfg.id]" class="lc-tag"
                :class="llmResult[cfg.id].ok ? 'lc-tag--ok' : 'lc-tag--err'">
                {{ llmResult[cfg.id].ok ? '✓ 连通' : '✗ 失败' }}
              </span>
              <span v-else-if="cfg.id && cfg.status && cfg.status !== 'unknown'" class="lc-tag"
                :class="cfg.status === 'ok' ? 'lc-tag--ok' : 'lc-tag--err'"
                :title="cfg.last_error || ''">
                {{ cfg.status === 'ok' ? '● 正常' : '● 异常' }}
              </span>
              <span v-if="cfg.id && (cfg.total_calls ?? 0) > 0" class="lc-tag lc-tag--muted"
                :title="`输入 ${fmtTokens(cfg.total_prompt_tokens)} / 输出 ${fmtTokens(cfg.total_completion_tokens)} tokens`">
                {{ cfg.total_calls }} 次 · {{ fmtTokens((cfg.total_prompt_tokens ?? 0) + (cfg.total_completion_tokens ?? 0)) }}
              </span>
              <span v-if="cfg.is_default" class="lc-tag lc-tag--gold">★ 默认</span>
            </div>
            <svg class="lc-chevron" :class="{ open: cfg._open }" width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
            </svg>
          </div>

          <!-- collapsible body -->
          <transition name="lc-body">
            <div v-show="cfg._open" class="lc-body">
              <!-- form -->
              <div class="lc-form">
                <div class="lc-field">
                  <label class="lc-lbl">配置名称</label>
                  <input v-model="cfg.name" class="lc-inp" placeholder="如：My DeepSeek" />
                </div>
                <div class="lc-g2">
                  <div class="lc-field">
                    <label class="lc-lbl">服务商</label>
                    <Select v-model="cfg.provider" @update:model-value="onProviderChange(cfg)">
                      <SelectTrigger class="lc-inp lc-sel">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem v-for="p in PROVIDERS" :key="p" :value="p">{{ PROVIDER_META[p]?.label ?? p }}</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div class="lc-field">
                    <div class="lc-lbl-row">
                      <label class="lc-lbl">模型</label>
                      <button v-if="cfg.id" class="lc-refresh" :disabled="refreshingModels === cfg.id"
                        @click.prevent="refreshLiveModels(cfg)">
                        <svg :style="refreshingModels === cfg.id ? 'animation:lc-rotate .7s linear infinite' : ''"
                          width="10" height="10" viewBox="0 0 20 20" fill="currentColor">
                          <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/>
                        </svg>
                        {{ modelLists['live-' + cfg.id] ? modelLists['live-' + cfg.id].length + ' 个' : '刷新' }}
                      </button>
                    </div>
                    <Select v-if="modelOptions(cfg).length > 0" v-model="cfg.model">
                      <SelectTrigger class="lc-inp lc-sel">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem v-if="cfg.model && !modelOptions(cfg).includes(cfg.model)" :value="cfg.model">{{ cfg.model }}</SelectItem>
                        <SelectItem v-for="m in modelOptions(cfg)" :key="m" :value="m">{{ m }}</SelectItem>
                      </SelectContent>
                    </Select>
                    <input v-else v-model="cfg.model" class="lc-inp lc-mono"
                      :placeholder="PROVIDER_META[cfg.provider]?.default_model || 'model-id'" />
                  </div>
                </div>
                <div class="lc-field">
                  <label class="lc-lbl">API Key
                    <span v-if="cfg.id" class="lc-hint">· 已配置，留空不变</span>
                  </label>
                  <input v-if="cfg.id" v-model="cfg._new_api_key" class="lc-inp lc-mono" type="password"
                    placeholder="粘贴新 Key 以替换当前值…" />
                  <input v-else v-model="cfg.api_key" class="lc-inp lc-mono" type="password" placeholder="sk-…" />
                </div>
                <div class="lc-field" style="margin-bottom:0">
                  <label class="lc-lbl">Base URL
                    <span class="lc-hint">· 可选，留空使用内置默认</span>
                  </label>
                  <input v-model="cfg.base_url" class="lc-inp lc-mono"
                    :placeholder="cfg.provider === 'custom' ? 'https://your-api.com/v1' : (PROVIDER_META[cfg.provider]?.default_base_url || '内置默认')" />
                </div>
              </div>

              <!-- footer -->
              <div class="lc-foot" :class="{ 'lc-foot--danger': cfg._confirmDelete }">
                <template v-if="cfg._confirmDelete">
                  <span class="lc-del-warn">确认删除此配置？操作不可撤销</span>
                  <div class="lc-foot-r">
                    <button class="lc-btn-ghost" @click="cfg._confirmDelete = false">取消</button>
                    <button class="lc-btn-danger" @click="deleteLLM(cfg, i)">确认删除</button>
                  </div>
                </template>
                <template v-else>
                  <span v-if="cfg.id && llmResult[cfg.id]" class="lc-result"
                    :class="llmResult[cfg.id].ok ? 'ok' : 'err'">{{ llmResult[cfg.id].msg }}</span>
                  <span v-else-if="cfg.id && cfg.status === 'error' && cfg.last_error"
                    class="lc-result err" :title="cfg.last_error">最近错误：{{ cfg.last_error.slice(0, 60) }}</span>
                  <span v-else style="flex:1"></span>
                  <div class="lc-foot-r">
                    <button v-if="!cfg.is_default" class="lc-btn-text" @click="setDefault(cfg)">设为默认</button>
                    <button v-if="cfg.id" class="lc-btn-ghost" :disabled="testingLLM === cfg.id" @click="testLLM(cfg)">
                      {{ testingLLM === cfg.id ? '测试中…' : '测试' }}
                    </button>
                    <button class="lc-btn-primary" :disabled="saving" @click="saveLLM(cfg)">保存</button>
                    <button class="lc-btn-del" @click="confirmDeleteLLM(cfg)" title="删除">
                      <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor">
                        <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
                      </svg>
                    </button>
                  </div>
                </template>
              </div>
            </div>
          </transition>
        </div>

      </template>

      <!-- ══ 数据源 ══════════════════════════════════════════════════════════ -->
      <template v-if="activeTab === 'ds'">
        <div class="s-section-head">
          <span class="section-label" style="margin:0">数据源配置</span>
          <span class="text-xs" style="color:var(--text3)">优先级：API Key → 爬虫 → 免费源</span>
        </div>

        <div v-for="(cfg, i) in dsConfigs" :key="cfg.source_name" class="card no-accent s-ds-card">
          <div class="s-ds-head" @click="cfg._open = !cfg._open">
            <!-- Status dot -->
            <span class="s-ds-dot" :class="cfg.enabled ? 's-ds-dot--on' : 's-ds-dot--off'" />

            <!-- Source info -->
            <div class="s-ds-info">
              <div class="s-ds-name">{{ KNOWN_SOURCES.find(s => s.source_name === cfg.source_name)?.label ?? cfg.source_name }}</div>
              <div class="s-ds-desc">{{ KNOWN_SOURCES.find(s => s.source_name === cfg.source_name)?.desc }}</div>
            </div>

            <!-- Badges -->
            <div class="flex gap-1 flex-shrink-0 s-ds-badges">
              <span :class="['badge', KNOWN_SOURCES.find(s => s.source_name === cfg.source_name)?.roleColor ?? 'badge-gray']" style="font-size:10px">
                {{ KNOWN_SOURCES.find(s => s.source_name === cfg.source_name)?.role }}
              </span>
              <span class="badge" :class="cfg.has_api_key ? 'badge-green' : 'badge-gray'" style="font-size:10px">
                {{ cfg.has_api_key ? 'KEY ✓' : '爬虫' }}
              </span>
            </div>

            <!-- Inline enable toggle -->
            <label class="s-toggle s-ds-toggle" @click.stop title="启用/停用此数据源">
              <input type="checkbox" v-model="cfg.enabled" @change="toggleDS(cfg)" />
              <span class="s-toggle-track"><span class="s-toggle-thumb"/></span>
            </label>

            <!-- Expand chevron -->
            <svg
              class="s-chevron"
              :class="{ open: cfg._open }"
              width="14" height="14" viewBox="0 0 20 20" fill="currentColor"
            >
              <path fill-rule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clip-rule="evenodd"/>
            </svg>
          </div>

          <!-- Expanded config -->
          <transition name="ds-body">
          <div v-if="cfg._open" class="s-ds-body">
            <div class="s-ds-grid">
              <div class="field">
                <label class="field-label">API Key <span style="font-weight:400;text-transform:none;letter-spacing:0">{{ cfg.has_api_key ? '(已配置，留空不变)' : '(留空用爬虫/免费源)' }}</span></label>
                <input v-model="cfg._api_key" class="input" type="password" placeholder="粘贴新 Key…" />
              </div>
              <div class="field" style="display:flex;flex-direction:column;justify-content:flex-end">
                <label class="field-label">模式</label>
                <div class="s-radio-group">
                  <label class="s-radio" :class="{ active: !cfg.use_scraper }">
                    <input type="radio" :name="`mode-${i}`" :value="false" v-model="cfg.use_scraper" />
                    API 直连
                  </label>
                  <label class="s-radio" :class="{ active: cfg.use_scraper }">
                    <input type="radio" :name="`mode-${i}`" :value="true" v-model="cfg.use_scraper" />
                    爬虫降级
                  </label>
                </div>
              </div>
            </div>

            <div class="s-ds-foot">
              <label class="s-toggle">
                <input type="checkbox" v-model="cfg.enabled" />
                <span class="s-toggle-track"><span class="s-toggle-thumb"/></span>
                <span>{{ cfg.enabled ? '已启用' : '已停用' }}</span>
              </label>
              <div class="flex gap-2" style="margin-left:auto">
                <button class="btn btn-ghost btn-sm" @click="cfg._open = false">取消</button>
                <button class="btn btn-primary btn-sm" :disabled="saving" @click="saveDS(cfg)">保存</button>
              </div>
            </div>
          </div>
          </transition>
        </div>
      </template>

      <!-- ══ 通知推送 ════════════════════════════════════════════════════════ -->
      <template v-if="activeTab === 'webhook'">
        <div class="s-section-head">
          <span class="section-label" style="margin:0">通知推送</span>
          <span class="text-xs" style="color:var(--text3)">每日分析完成后自动推送</span>
        </div>

        <div class="card no-accent s-form-card">
          <div class="s-form-body">
            <div class="s-form-grid">
              <div class="field">
                <label class="field-label">推送类型</label>
                <Select v-model="webhook.webhook_type">
                  <SelectTrigger class="input">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem v-for="t in WEBHOOK_TYPES" :key="t.value" :value="t.value">{{ t.label }}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div class="field">
                <label class="field-label">状态</label>
                <div style="padding-top:4px">
                  <label class="s-toggle">
                    <input type="checkbox" v-model="webhook.enabled" />
                    <span class="s-toggle-track"><span class="s-toggle-thumb"/></span>
                    <span>{{ webhook.enabled ? '启用推送' : '已停用' }}</span>
                  </label>
                </div>
              </div>
              <div class="field" style="grid-column:1/-1">
                <label class="field-label">Webhook URL</label>
                <input v-model="webhook.url" class="input" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…" />
              </div>
            </div>

            <!-- Hint per type -->
            <div v-if="webhook.webhook_type === 'wechat'" class="s-hint">
              企业微信群机器人 Webhook — 在群内「添加机器人」后获取 URL
            </div>
            <div v-else-if="webhook.webhook_type === 'dingtalk'" class="s-hint">
              钉钉自定义机器人 Webhook — 安全设置选「加签」或「自定义关键词：竞彩」
            </div>
            <div v-else-if="webhook.webhook_type === 'feishu'" class="s-hint">
              飞书自定义机器人 Webhook — 在「群设置 › 机器人」中添加自定义机器人
            </div>
          </div>

          <div class="s-form-foot">
            <button class="btn btn-ghost btn-sm" :disabled="testingWebhook || !webhook.url" @click="testWebhook">
              <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor">
                <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd"/>
              </svg>
              {{ testingWebhook ? '发送中…' : '发送测试' }}
            </button>
            <button class="btn btn-primary btn-sm" :disabled="saving" @click="saveWebhook" style="margin-left:auto">保存</button>
          </div>
        </div>
      </template>

      <!-- ══ 集成分析 ════════════════════════════════════════════════════════ -->
      <template v-if="activeTab === 'ensemble'">
        <div class="s-section-head">
          <span class="section-label" style="margin:0">集成分析配置</span>
          <span class="text-xs" style="color:var(--text3)">多模型融合策略</span>
        </div>

        <div class="card no-accent s-form-card">
          <div class="s-form-body">
            <div class="s-ens-grid">
              <div class="field">
                <label class="field-label">参与模型</label>
                <Select v-model="ensemble.models">
                  <SelectTrigger class="input">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部已配置模型</SelectItem>
                    <SelectItem value="default">仅默认模型</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div class="field">
                <label class="field-label">
                  融合策略
                  <span class="param-tip" data-tip="多数投票：过半模型同意同一结果才纳入推荐。加权平均：按模型历史置信度加权融合，质量差异明显时更准确。">?</span>
                </label>
                <div class="s-radio-group">
                  <label class="s-radio" :class="{ active: ensemble.strategy === 'majority' }">
                    <input type="radio" name="strategy" value="majority" v-model="ensemble.strategy" />
                    多数投票
                  </label>
                  <label class="s-radio" :class="{ active: ensemble.strategy === 'weighted' }">
                    <input type="radio" name="strategy" value="weighted" v-model="ensemble.strategy" />
                    加权平均
                  </label>
                </div>
              </div>

              <div class="field">
                <label class="field-label">
                  最低共识度 <span class="s-val-badge">{{ Math.round(ensemble.min_consensus * 100) }}%</span>
                  <span class="param-tip" data-tip="参与投票的模型中，至少需要这一比例的模型投票一致，才将该场次纳入方案。越高越严格，推荐场次越少但更稳健。">?</span>
                </label>
                <input type="range" v-model.number="ensemble.min_consensus" min="0" max="1" step="0.05" class="s-range" />
              </div>
              <div class="field">
                <label class="field-label">
                  最低置信度 <span class="s-val-badge">{{ ensemble.min_confidence }}%</span>
                  <span class="param-tip" data-tip="单场预测置信度低于此阈值的场次将被排除出串关。建议 40-60%：低于 40% 则纳入太多不确定场次，高于 60% 可能无法凑够串关腿数。">?</span>
                </label>
                <input type="range" v-model.number="ensemble.min_confidence" min="0" max="100" step="5" class="s-range" />
              </div>
              <div class="field">
                <label class="field-label">
                  默认倍投系数
                  <span class="param-tip" data-tip="连败后每轮注额的递增倍数（马丁格尔策略）。2 = 每输一场下次翻倍。注意：倍投会快速放大资金风险，建议结合总预算严格控制。">?</span>
                </label>
                <input type="number" v-model.number="ensemble.default_multiplier" class="input" min="1" max="10" step="1" />
              </div>
              <div class="field">
                <label class="field-label">
                  总预算 (元)
                  <span class="param-tip" data-tip="每日方案生成时用于分配各票型注额的总资金。系统会按风险比例将预算分配到稳健/均衡/博高赔三套方案。">?</span>
                </label>
                <input type="number" v-model.number="ensemble.budget" class="input" min="1" step="10" />
              </div>
            </div>

            <!-- Strategy note -->
            <div class="s-hint">
              <template v-if="ensemble.strategy === 'majority'">多数投票：过半模型同意同一结果才纳入推荐，共识度越高要求越严格</template>
              <template v-else>加权平均：按模型历史准确率加权融合概率，适合模型质量差异明显的场景</template>
            </div>
          </div>

          <div class="s-form-foot">
            <button class="btn btn-primary btn-sm" :disabled="saving" @click="saveEnsemble" style="margin-left:auto">保存配置</button>
          </div>
        </div>
      </template>

      <!-- ══ 自动出票 ════════════════════════════════════════════════════════ -->
      <template v-if="activeTab === 'auto_ticket'">
        <div class="card no-accent at-card">

          <!-- 开关行 -->
          <div class="at-row at-row--toggle">
            <div class="at-meta">
              <span class="at-title">启用自动出票</span>
              <span class="at-desc">每日定时生成投注方案，在「追踪」页查看历史记录</span>
            </div>
            <label class="s-toggle">
              <input type="checkbox" v-model="autoTicket.enabled" />
              <span class="s-toggle-track"><span class="s-toggle-thumb" /></span>
            </label>
          </div>

          <!-- Schedule preview timeline -->
          <div class="at-timeline" :class="{ 'at-timeline--off': !autoTicket.enabled }">
            <div class="at-tl-item">
              <div class="at-tl-time font-num">{{ ticketTime }}</div>
              <div class="at-tl-dot at-tl-dot--ticket"></div>
              <div class="at-tl-label">每日出票</div>
            </div>
            <div class="at-tl-line"></div>
            <div class="at-tl-item">
              <div class="at-tl-time font-num">次日 {{ syncTime }}</div>
              <div class="at-tl-dot at-tl-dot--sync"></div>
              <div class="at-tl-label">同步赛果</div>
            </div>
          </div>

          <div class="at-divider" />

          <!-- 出票时间 -->
          <div class="at-row">
            <div class="at-meta">
              <span class="at-title">每日出票时间</span>
              <span class="at-desc">建议 AI 分析完成（09:00）后，默认 09:30</span>
            </div>
            <input class="input at-time-input" type="time" v-model="ticketTime" :disabled="!autoTicket.enabled" />
          </div>

          <!-- 赛果同步时间 -->
          <div class="at-row">
            <div class="at-meta">
              <span class="at-title">赛果同步时间</span>
              <span class="at-desc">批量同步前日赛果，建议赛事结束后，默认 02:00</span>
            </div>
            <input class="input at-time-input" type="time" v-model="syncTime" :disabled="!autoTicket.enabled" />
          </div>

          <!-- 每日预算 -->
          <div class="at-row">
            <div class="at-meta">
              <span class="at-title">每日出票预算</span>
              <span class="at-desc">Kelly 分配的上限金额（元），保存后下一轮出票即生效</span>
            </div>
            <input class="input at-time-input" type="number" min="2" step="1" v-model.number="autoTicket.stake" :disabled="!autoTicket.enabled" />
          </div>

          <div class="at-divider" />

          <!-- 提示 + 保存 -->
          <div class="at-foot">
            <span class="at-foot-hint">保存后 worker 自动热更新，无需重启</span>
            <button class="btn btn-primary btn-sm" :disabled="saving" @click="saveAutoTicket">
              {{ saving ? '保存中…' : '保存配置' }}
            </button>
          </div>
        </div>
      </template>

    </div>
  </div>
</template>

<style scoped>
/* ── Layout ──────────────────────────────────────────────────────────────── */
.view { display: flex; flex-direction: column; }
.input--time { max-width: 130px; }
.s-hint-block { font-size: 11px; color: var(--text3); line-height: 1.5; padding: 8px 12px; background: color-mix(in srgb, var(--primary) 4%, var(--card)); border-radius: 6px; }

/* ── 自动出票配置卡 ───────────────────────────────────────────────────────── */
.at-card { padding: 0; overflow: hidden; }
.at-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
}
.at-row--toggle { padding: 16px; }
.at-meta {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}
.at-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text1);
  white-space: nowrap;
}
.at-desc {
  font-size: 11px;
  color: var(--text3);
  line-height: 1.4;
}
.at-time-input {
  width: 110px;
  flex-shrink: 0;
  text-align: center;
}
.at-time-input:disabled { opacity: .4; }
.at-divider { height: 1px; background: var(--line, rgba(255,255,255,.07)); margin: 0; }
.at-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  gap: 8px;
}
.at-foot-hint { font-size: 11px; color: var(--text3); }


/* ── Tabs ────────────────────────────────────────────────────────────────── */
.s-tabs {
  display: flex;
  gap: 0;
  border-bottom: var(--card-bd);
  background: var(--card);
  flex-shrink: 0;
  padding: 0 16px;
  overflow-x: auto;
  position: sticky;
  top: 0;
  z-index: 10;
}
.s-tab {
  padding: 10px 16px;
  font-family: var(--font-disp);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--text3);
  border: none;
  background: none;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: color .15s, border-color .15s;
  white-space: nowrap;
  margin-bottom: -1px;
}
.s-tab:hover { color: var(--text2); }
.s-tab.active { color: var(--primary); border-bottom-color: var(--primary); }

/* ── Body ────────────────────────────────────────────────────────────────── */
.s-body { padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }

/* ── Section head ────────────────────────────────────────────────────────── */
.s-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

/* ── LLM Config (lc-*) ──────────────────────────────────────────────────── */

/* Toolbar */
.lc-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 2px 12px;
}
.lc-bar-l { display: flex; align-items: center; gap: 8px; }
.lc-title {
  font-family: var(--font-disp);
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .6px;
  color: var(--text2);
}
.lc-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--primary-t);
  color: var(--primary);
  font-family: var(--font-num);
  font-size: 10px;
  font-weight: 700;
}
.lc-bar-r { display: flex; align-items: center; gap: 7px; }
.lc-pick-lbl {
  font-family: var(--font-disp);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .4px;
  color: var(--text3);
  white-space: nowrap;
}
.lc-pick {
  appearance: none;
  background: var(--card);
  border: var(--card-bd);
  border-radius: var(--radius-sm);
  color: var(--text2);
  cursor: pointer;
  font-family: var(--font-disp);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .3px;
  padding: 6px 26px 6px 10px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 20 20' fill='%23999'%3E%3Cpath fill-rule='evenodd' d='M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 7px center;
  outline: none;
  transition: border-color .15s;
}
.lc-pick:focus { border-color: var(--primary); }
.lc-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 13px;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: #fff;
  font-family: var(--font-disp);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .4px;
  cursor: pointer;
  border: none;
  transition: opacity .15s, transform .1s;
  white-space: nowrap;
}
.lc-add:hover { opacity: .88; }
.lc-add:active { transform: scale(0.97); }

/* Empty state */
.lc-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 20px;
  color: var(--text3);
  font-size: 13px;
  text-align: center;
}
.lc-empty-sub { font-size: 11px; color: var(--text3); opacity: .7; }

/* Card */
.lc-card {
  background: var(--card);
  border: var(--card-bd);
  border-left: 3px solid var(--pa, var(--line));
  border-radius: var(--radius);
  overflow: hidden;
  transition: box-shadow .15s;
}
.lc-card::before { display: none; }
.lc-card--default {
  box-shadow: 0 0 0 1px color-mix(in srgb, var(--pa, var(--primary)) 30%, transparent);
}
.lc-card:hover { box-shadow: 0 4px 14px rgba(0,0,0,.09); }

/* Card header */
.lc-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: color-mix(in srgb, var(--pa, var(--primary)) 5%, var(--card));
  border-bottom: var(--card-bd);
}
.lc-chip {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: var(--pa, var(--text3));
  color: #fff;
  font-family: var(--font-disp);
  font-size: 13px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  letter-spacing: -0.5px;
  text-shadow: 0 1px 3px rgba(0,0,0,.25);
}
.lc-meta {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.lc-pname {
  font-family: var(--font-disp);
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lc-mslug {
  font-family: var(--font-num);
  font-size: 11px;
  color: var(--text3);
  letter-spacing: .2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-style: normal;
}
.lc-tags { display: flex; align-items: center; gap: 5px; flex-shrink: 0; }
.lc-tag {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  font-family: var(--font-disp);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .6px;
  text-transform: uppercase;
  border: 1px solid;
  white-space: nowrap;
}
.lc-tag--ok {
  color: var(--green);
  border-color: color-mix(in srgb, var(--green) 35%, transparent);
  background: color-mix(in srgb, var(--green) 8%, transparent);
}
.lc-tag--err {
  color: var(--red);
  border-color: color-mix(in srgb, var(--red) 35%, transparent);
  background: color-mix(in srgb, var(--red) 8%, transparent);
}
.lc-tag--gold {
  color: var(--gold);
  border-color: color-mix(in srgb, var(--gold) 35%, transparent);
  background: color-mix(in srgb, var(--gold) 8%, transparent);
}
.lc-tag--muted {
  color: var(--text3);
  border-color: color-mix(in srgb, var(--text3) 30%, transparent);
  background: color-mix(in srgb, var(--text3) 6%, transparent);
  text-transform: none;
  letter-spacing: 0;
}

.lc-fix-btn {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: var(--radius-pill);
  font-family: var(--font-disp);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .6px;
  text-transform: uppercase;
  border: 1px solid color-mix(in srgb, var(--primary) 40%, transparent);
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: var(--primary);
  cursor: pointer;
  transition: background .12s, border-color .12s;
  white-space: nowrap;
}
.lc-fix-btn:hover {
  background: color-mix(in srgb, var(--primary) 18%, transparent);
  border-color: var(--primary);
}

/* Accordion */
.lc-head--btn { cursor: pointer; user-select: none; }
.lc-head--btn:hover {
  background: color-mix(in srgb, var(--pa, var(--primary)) 9%, var(--card));
}
.lc-card--open > .lc-head--btn {
  background: color-mix(in srgb, var(--pa, var(--primary)) 7%, var(--card));
}
.lc-chevron { color: var(--text3); flex-shrink: 0; transition: transform .2s; margin-left: 4px; }
.lc-chevron.open { transform: rotate(180deg); }
.lc-body { }
.lc-body-enter-active { transition: opacity .2s ease, transform .18s ease; }
.lc-body-leave-active { transition: opacity .14s ease, transform .12s ease; }
.lc-body-enter-from, .lc-body-leave-to { opacity: 0; transform: translateY(-6px); }

/* Form */
.lc-form {
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.lc-field { display: flex; flex-direction: column; gap: 4px; }
.lc-g2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
@media (max-width: 480px) { .lc-g2 { grid-template-columns: 1fr; } }

.lc-lbl-row {
  display: flex;
  align-items: center;
  gap: 5px;
}
.lc-lbl {
  display: flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-disp), var(--font);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .5px;
  color: var(--text3);
}
.lc-hint {
  font-size: 9px;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
  color: var(--text3);
  opacity: .7;
}
.lc-inp {
  width: 100%;
  padding: 7px 10px;
  border: var(--card-bd);
  border-radius: var(--radius-sm);
  background: var(--bg);
  color: var(--text);
  font-family: inherit;
  font-size: 13px;
  outline: none;
  transition: border-color .15s;
  min-width: 0;
}
.lc-inp:focus { border-color: var(--pa, var(--primary)); }
.lc-inp::placeholder { color: var(--text3); font-size: 11px; }
.lc-mono { font-family: var(--font-num); font-size: 12px; letter-spacing: .2px; }
.lc-sel {
  appearance: none;
  cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 20 20' fill='%23999'%3E%3Cpath fill-rule='evenodd' d='M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 8px center;
  padding-right: 26px;
}
.lc-refresh {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-family: var(--font-disp);
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .4px;
  color: var(--text3);
  padding: 1px 5px;
  border: 1px solid var(--line);
  border-radius: var(--radius-pill);
  cursor: pointer;
  background: transparent;
  transition: color .12s, border-color .12s;
}
.lc-refresh:hover { color: var(--primary); border-color: var(--primary); }
.lc-refresh:disabled { opacity: .4; cursor: not-allowed; }
@keyframes lc-rotate { to { transform: rotate(360deg); } }
.lc-spin { animation: lc-rotate .7s linear infinite; }

/* Footer */
.lc-foot {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 8px 12px;
  border-top: var(--card-bd);
  background: var(--bg);
  min-height: 42px;
}
.lc-foot--danger { background: var(--win-bg); }
.lc-foot-r { display: flex; align-items: center; gap: 6px; margin-left: auto; }
.lc-result {
  font-family: var(--font-num);
  font-size: 11px;
  font-weight: 500;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.lc-result.ok { color: var(--green); }
.lc-result.err { color: var(--red); }
.lc-del-warn { font-size: 11px; color: var(--red); font-weight: 600; flex: 1; }

/* Buttons */
.lc-btn-text {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text3);
  font-family: var(--font-disp);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .4px;
  cursor: pointer;
  border: none;
  transition: color .12s;
  white-space: nowrap;
}
.lc-btn-text:hover { color: var(--gold); }
.lc-btn-ghost {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text2);
  font-family: var(--font-disp);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .4px;
  cursor: pointer;
  border: var(--card-bd);
  transition: border-color .15s, color .15s, transform .1s;
  white-space: nowrap;
}
.lc-btn-ghost:hover { border-color: var(--primary); color: var(--primary); }
.lc-btn-ghost:active { transform: scale(0.97); }
.lc-btn-ghost:disabled { opacity: .4; cursor: not-allowed; }
.lc-btn-primary {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 14px;
  border-radius: var(--radius-sm);
  background: var(--primary);
  color: #fff;
  font-family: var(--font-disp);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .4px;
  cursor: pointer;
  border: none;
  transition: opacity .15s, transform .1s;
  white-space: nowrap;
}
.lc-btn-primary:hover { opacity: .88; }
.lc-btn-primary:active { transform: scale(0.97); }
.lc-btn-primary:disabled { opacity: .4; cursor: not-allowed; }
.lc-btn-danger {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 12px;
  border-radius: var(--radius-sm);
  background: var(--red);
  color: #fff;
  font-family: var(--font-disp);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .4px;
  cursor: pointer;
  border: none;
  transition: opacity .15s;
  white-space: nowrap;
}
.lc-btn-danger:hover { opacity: .85; }
.lc-btn-del {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 29px;
  height: 29px;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text3);
  border: var(--card-bd);
  cursor: pointer;
  transition: color .15s, border-color .15s;
  flex-shrink: 0;
}
.lc-btn-del:hover { color: var(--red); border-color: var(--red); }

/* ── Data source card ────────────────────────────────────────────────────── */
.s-ds-card { margin: 0; }

.s-ds-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  user-select: none;
}
.s-ds-head:hover { background: var(--bg); }
.s-ds-info { flex: 1; min-width: 0; }
.s-ds-name { font-size: 13px; font-weight: 600; color: var(--text); }
.s-ds-desc { font-size: 11px; color: var(--text3); margin-top: 1px; }
.s-chevron { color: var(--text3); flex-shrink: 0; transition: transform .2s; }
.s-chevron.open { transform: rotate(180deg); }

.s-ds-body { border-top: var(--card-bd); }
.s-ds-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 10px;
  padding: 10px 14px 0;
}
@media (max-width: 480px) { .s-ds-grid { grid-template-columns: 1fr; } }

.s-ds-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-top: var(--card-bd);
  background: var(--bg);
}

/* ── Generic form card (Webhook / Ensemble) ──────────────────────────────── */
.s-form-card { margin: 0; }
.s-form-body { padding: 14px; }
.s-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 10px;
}
@media (max-width: 480px) { .s-form-grid { grid-template-columns: 1fr; } }
.s-ens-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 10px;
}
@media (max-width: 480px) { .s-ens-grid { grid-template-columns: 1fr; } }

.s-form-foot {
  display: flex;
  align-items: center;
  padding: 8px 14px;
  border-top: var(--card-bd);
  background: var(--bg);
}

/* Hint text below form section */
.s-hint {
  font-size: 11px;
  color: var(--text3);
  background: var(--bg);
  border: var(--card-bd);
  border-radius: var(--radius-sm);
  padding: 7px 10px;
  margin-top: 4px;
  line-height: 1.55;
}

/* ── Radio group ─────────────────────────────────────────────────────────── */
.s-radio-group {
  display: flex;
  gap: 6px;
}
.s-radio {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border-radius: var(--radius-sm);
  border: var(--card-bd);
  font-size: 12px;
  cursor: pointer;
  color: var(--text2);
  transition: border-color .15s, color .15s, background .15s;
  user-select: none;
}
.s-radio input { display: none; }
.s-radio:hover { border-color: var(--primary); color: var(--primary); }
.s-radio.active { border-color: var(--primary); color: var(--primary); background: var(--primary-t); }

/* ── Range slider ────────────────────────────────────────────────────────── */
.s-range {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 4px;
  accent-color: var(--primary);
  cursor: pointer;
  margin-top: 8px;
  border-radius: 2px;
  background: var(--line);
  outline: none;
}
.s-range::-webkit-slider-runnable-track {
  height: 4px;
  border-radius: 2px;
  background: var(--line);
}
.s-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: var(--primary);
  margin-top: -5px;
  box-shadow: 0 1px 4px rgba(0,0,0,.2);
  transition: transform .1s;
}
.s-range::-webkit-slider-thumb:hover { transform: scale(1.15); }
.s-range::-moz-range-track {
  height: 4px;
  border-radius: 2px;
  background: var(--line);
}
.s-range::-moz-range-thumb {
  width: 14px; height: 14px;
  border: none;
  border-radius: 50%;
  background: var(--primary);
  box-shadow: 0 1px 4px rgba(0,0,0,.2);
}
.s-val-badge {
  font-family: var(--font-num);
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  background: var(--primary-t);
  padding: 1px 5px;
  border-radius: 3px;
  margin-left: 4px;
}

/* ── Param tooltip (?) ────────────────────────────────────────────────────── */
.param-tip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--line);
  color: var(--text3);
  font-size: 9px;
  font-weight: 700;
  font-family: var(--font);
  text-transform: none;
  letter-spacing: 0;
  cursor: help;
  vertical-align: middle;
  margin-left: 5px;
  position: relative;
  flex-shrink: 0;
  transition: background .12s, color .12s;
}
.param-tip:hover { background: var(--primary-t); color: var(--primary); }
.param-tip::after {
  content: attr(data-tip);
  position: absolute;
  bottom: calc(100% + 7px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--text);
  color: var(--card);
  font-size: 11px;
  font-weight: 400;
  line-height: 1.55;
  padding: 7px 10px;
  border-radius: 6px;
  width: 230px;
  white-space: pre-wrap;
  text-align: left;
  pointer-events: none;
  opacity: 0;
  transition: opacity .15s;
  z-index: 500;
  font-family: var(--font);
  text-transform: none;
  letter-spacing: 0;
  box-shadow: 0 4px 16px rgba(0,0,0,.25);
}
.param-tip:hover::after { opacity: 1; }
@media (max-width: 767px) {
  .param-tip::after {
    left: auto;
    right: 0;
    transform: none;
    width: min(230px, calc(100vw - 32px));
  }
}

/* ── Toggle ──────────────────────────────────────────────────────────────── */
.s-toggle {
  display: flex;
  align-items: center;
  gap: 7px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text2);
  user-select: none;
}
.s-toggle input { display: none; }
.s-toggle-track {
  width: 32px; height: 18px;
  border-radius: 9px;
  background: var(--line);
  position: relative;
  transition: background .2s;
  flex-shrink: 0;
}
.s-toggle input:checked + .s-toggle-track { background: var(--primary); }
.s-toggle-thumb {
  position: absolute;
  top: 2px; left: 2px;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(0,0,0,.2);
  transition: transform .2s;
}
.s-toggle input:checked + .s-toggle-track .s-toggle-thumb { transform: translateX(14px); }

/* ── LLM usage summary strip ─────────────────────────────────────────────── */
.lc-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px 12px;
  flex-wrap: wrap;
}
.lc-sum-item { display: flex; align-items: baseline; gap: 4px; }
.lc-sum-val {
  font-size: 16px;
  font-weight: 800;
  color: var(--text);
  line-height: 1;
}
.lc-sum-lbl { font-size: 11px; color: var(--text3); }
.lc-sum-sep { font-size: 11px; color: var(--line); }
.lc-sum-warn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 10px;
  font-weight: 700;
  color: var(--gold);
  background: color-mix(in srgb, var(--gold) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--gold) 30%, transparent);
  padding: 2px 7px;
  border-radius: 10px;
}

/* ── Auto-ticket timeline ────────────────────────────────────────────────── */
.at-timeline {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 14px 24px 10px;
  background: color-mix(in srgb, var(--primary) 4%, var(--card));
  border-bottom: var(--card-bd);
  transition: opacity .2s;
}
.at-timeline--off { opacity: .38; }

.at-tl-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  flex: 0 0 auto;
  min-width: 80px;
}
.at-tl-time {
  font-family: var(--font-disp);
  font-size: 20px;
  font-weight: 900;
  color: var(--text);
  line-height: 1;
  letter-spacing: -.5px;
}
.at-tl-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  border: 2px solid var(--card);
  box-shadow: 0 0 0 2px;
  flex-shrink: 0;
}
.at-tl-dot--ticket { background: var(--primary); box-shadow: 0 0 0 2px color-mix(in srgb, var(--primary) 30%, transparent); }
.at-tl-dot--sync { background: var(--blue, #1D4ED8); box-shadow: 0 0 0 2px color-mix(in srgb, var(--blue, #1D4ED8) 30%, transparent); }
.at-tl-label { font-size: 10px; color: var(--text3); font-weight: 600; letter-spacing: .3px; text-transform: uppercase; font-family: var(--font-disp); }

.at-tl-line {
  flex: 1;
  height: 2px;
  background: repeating-linear-gradient(to right, var(--line) 0, var(--line) 4px, transparent 4px, transparent 8px);
  margin: 0 8px;
  margin-top: -14px;
}

/* ── Accordion body transition ───────────────────────────────────────────── */
.ds-body-enter-active { transition: opacity .18s ease, transform .18s ease; }
.ds-body-leave-active { transition: opacity .12s ease, transform .12s ease; }
.ds-body-enter-from, .ds-body-leave-to { opacity: 0; transform: translateY(-6px); }

/* ── Data source badge alignment ─────────────────────────────────────────── */
.s-ds-badges { align-items: center; }

/* Status dot (collapsed state indicator) */
.s-ds-dot {
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}
.s-ds-dot--on  { background: var(--green); box-shadow: 0 0 0 2px rgba(22,163,74,.18); }
.s-ds-dot--off { background: var(--text3); }

/* Inline DS toggle (no label text) */
.s-ds-toggle { margin-left: 2px; }

/* ── Model refresh button (inside field-label) ───────────────────────────── */
.s-refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  margin-left: 6px;
  font-family: var(--font-disp);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: .3px;
  color: var(--text3);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  transition: color .15s;
  vertical-align: middle;
}
.s-refresh-btn:hover:not(:disabled) { color: var(--primary); }
.s-refresh-btn:disabled { opacity: .5; cursor: not-allowed; }
@keyframes spin { to { transform: rotate(360deg); } }
.s-spin { animation: spin .7s linear infinite; }
</style>
