<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/api'

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
  _confirmDelete?: boolean
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
const activeTab = ref<'llm' | 'ds' | 'webhook' | 'ensemble'>('llm')
const llmConfigs = ref<LLMConfig[]>([])
const dsConfigs = ref<DSConfig[]>([])
const webhook = ref<WebhookConfig>({ url: '', webhook_type: 'generic', enabled: true })
const ensemble = ref<EnsembleConfig>({
  models: 'all', strategy: 'majority',
  min_consensus: 0.5, min_confidence: 40,
  default_multiplier: 2, budget: 100,
})
const loading = ref(true)
const saving = ref(false)
const testingLLM = ref<number | null>(null)
const testingWebhook = ref(false)
const llmResult = ref<Record<number, { ok: boolean; msg: string }>>({})

const toast = ref<{ msg: string; type: 'ok' | 'err' } | null>(null)
let toastTimer: ReturnType<typeof setTimeout>
function showToast(msg: string, type: 'ok' | 'err' = 'ok') {
  clearTimeout(toastTimer)
  toast.value = { msg, type }
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}

// ── Constants ──────────────────────────────────────────────────────────────
const PROVIDERS = ['claude', 'openai', 'gemini', 'deepseek', 'kimi', 'glm', 'custom'] as const

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

const PROVIDER_ACCENT: Record<string, string> = {
  claude:   'var(--red)',
  openai:   'var(--green)',
  gemini:   'var(--blue)',
  deepseek: 'var(--gold)',
  kimi:     'var(--text3)',
  glm:      'var(--blue)',
  custom:   'var(--text3)',
}

const PROVIDER_META: Record<string, { label: string; badge: string; default_model: string; default_base_url: string }> = {
  claude:   { label: 'Claude',   badge: 'badge-red',   default_model: 'claude-sonnet-4-6',                           default_base_url: 'https://api.anthropic.com' },
  openai:   { label: 'OpenAI',   badge: 'badge-green', default_model: 'gpt-4o',                                      default_base_url: 'https://api.openai.com/v1' },
  gemini:   { label: 'Gemini',   badge: 'badge-blue',  default_model: 'gemini-2.0-flash',                            default_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai' },
  deepseek: { label: 'DeepSeek', badge: 'badge-gold',  default_model: 'deepseek-chat',                               default_base_url: 'https://api.deepseek.com/v1' },
  kimi:     { label: 'Kimi',     badge: 'badge-gray',  default_model: 'moonshot-v1-8k',                              default_base_url: 'https://api.moonshot.cn/v1' },
  glm:      { label: 'GLM',      badge: 'badge-blue',  default_model: 'glm-4-flash',                                 default_base_url: 'https://open.bigmodel.cn/api/paas/v4' },
  custom:   { label: '自定义',   badge: 'badge-gray',  default_model: '',                                            default_base_url: '' },
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
    const [llmRes, dsRes, whRes, ensRes] = await Promise.all([
      api.get('/settings/llm'),
      api.get('/settings/datasource'),
      api.get('/settings/webhook').catch(() => ({ data: null })),
      api.get('/settings/ensemble').catch(() => ({ data: null })),
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

    // 并发预加载所有 provider 的模型列表
    PROVIDERS.forEach(p => loadProviderModels(p))
  } finally {
    loading.value = false
  }
}

// ── LLM ────────────────────────────────────────────────────────────────────
function addLLM() {
  const meta = PROVIDER_META['deepseek']
  llmConfigs.value.unshift({
    name: 'DeepSeek 配置',
    provider: 'deepseek',
    model: meta.default_model,
    api_key: '',
    base_url: null,
    is_default: llmConfigs.value.length === 0,
  })
}

function onProviderChange(cfg: LLMConfig) {
  loadProviderModels(cfg.provider)
  if (cfg.id) return  // 已保存配置不自动覆盖字段
  const meta = PROVIDER_META[cfg.provider]
  if (!meta) return
  cfg.model = meta.default_model
  cfg.base_url = null
  cfg.name = meta.label ? `${meta.label} 配置` : '新配置'
}

function setDefault(cfg: LLMConfig) {
  llmConfigs.value.forEach(c => { c.is_default = false })
  cfg.is_default = true
}

async function saveLLM(cfg: LLMConfig) {
  saving.value = true
  try {
    if (cfg.id) {
      // api_key is write-only: only send when user explicitly enters a new key
      const payload: Record<string, unknown> = {
        name: cfg.name, provider: cfg.provider, model: cfg.model,
        base_url: cfg.base_url, is_default: cfg.is_default,
      }
      if (cfg._new_api_key) payload.api_key = cfg._new_api_key
      await api.put(`/settings/llm/${cfg.id}`, payload)
      cfg._new_api_key = ''
    } else {
      const { data } = await api.post('/settings/llm', { ...cfg, api_key: cfg.api_key })
      cfg.id = data.id
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
    llmResult.value[cfg.id] = (data.success || data.ok)
      ? { ok: true,  msg: '连接成功' }
      : { ok: false, msg: data.error || '连接失败' }
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
    <!-- Toast -->
    <transition name="toast-slide">
      <div v-if="toast" class="s-toast" :class="toast.type === 'err' ? 's-toast--err' : ''">
        <svg v-if="toast.type === 'ok'" width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
        </svg>
        <svg v-else width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
          <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
        </svg>
        {{ toast.msg }}
      </div>
    </transition>

    <!-- Tab bar -->
    <div class="s-tabs">
      <button
        v-for="tab in [
          { key: 'llm',     label: 'LLM 模型' },
          { key: 'ds',      label: '数据源' },
          { key: 'webhook', label: '通知推送' },
          { key: 'ensemble',label: '集成分析' },
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
        <div class="s-section-head">
          <span class="section-label" style="margin:0">LLM 模型配置</span>
          <button class="btn btn-ghost btn-sm" @click="addLLM">
            <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor">
              <path fill-rule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" clip-rule="evenodd"/>
            </svg>
            添加配置
          </button>
        </div>

        <div v-if="llmConfigs.length === 0" class="s-empty">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
          </svg>
          <span>暂无 LLM 配置，点击「添加配置」开始</span>
        </div>

        <div
          v-for="(cfg, i) in llmConfigs"
          :key="i"
          class="card s-llm-card"
          :class="{ 's-llm-card--default': cfg.is_default }"
          :style="{ '--s-accent': PROVIDER_ACCENT[cfg.provider] ?? 'var(--text3)' }"
        >
          <!-- Card head -->
          <div class="s-llm-head" :class="{ 's-llm-head--default': cfg.is_default }">
            <span :class="['badge', PROVIDER_META[cfg.provider]?.badge ?? 'badge-gray']" style="flex-shrink:0;font-size:11px">
              {{ PROVIDER_META[cfg.provider]?.label ?? cfg.provider }}
            </span>
            <input v-model="cfg.name" class="s-name-input" placeholder="配置名称" />
            <button
              v-if="!cfg.is_default"
              class="s-default-btn"
              title="点击设为默认模型"
              @click="setDefault(cfg)"
            >
              <svg width="11" height="11" viewBox="0 0 20 20" fill="currentColor"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg>
              设默认
            </button>
            <span v-else class="s-default-indicator" title="当前默认模型">
              <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor"><path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z"/></svg>
              默认
            </span>
          </div>

          <!-- Fields -->
          <div class="s-llm-grid">
            <div class="field">
              <label class="field-label">服务商</label>
              <select v-model="cfg.provider" class="input" @change="onProviderChange(cfg)">
                <option v-for="p in PROVIDERS" :key="p" :value="p">
                  {{ PROVIDER_META[p]?.label ?? p }}
                </option>
              </select>
            </div>
            <div class="field">
              <label class="field-label">
                模型
                <button
                  v-if="cfg.id"
                  class="s-refresh-btn"
                  :disabled="refreshingModels === cfg.id"
                  :title="refreshingModels === cfg.id ? '获取中…' : '从 Provider 获取最新模型列表'"
                  @click.prevent="refreshLiveModels(cfg)"
                >
                  <svg :class="{ 's-spin': refreshingModels === cfg.id }" width="11" height="11" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clip-rule="evenodd"/>
                  </svg>
                  {{ modelLists['live-' + cfg.id] ? modelLists['live-' + cfg.id].length + ' 个' : '刷新' }}
                </button>
              </label>
              <input
                v-model="cfg.model"
                class="input"
                :list="`model-list-${i}`"
                :placeholder="PROVIDER_META[cfg.provider]?.default_model || 'model-name'"
                autocomplete="off"
              />
              <datalist :id="`model-list-${i}`">
                <option v-for="m in modelOptions(cfg)" :key="m" :value="m" />
              </datalist>
            </div>
            <div class="field" style="grid-column:1/-1">
              <label class="field-label">
                API Key
                <span v-if="cfg.id" style="font-weight:400;text-transform:none;letter-spacing:0">(已配置，留空不变)</span>
              </label>
              <input
                v-if="cfg.id"
                v-model="cfg._new_api_key"
                class="input" type="password"
                placeholder="粘贴新 Key 以替换…"
              />
              <input
                v-else
                v-model="cfg.api_key"
                class="input" type="password"
                placeholder="sk-…"
              />
            </div>
            <div class="field" style="grid-column:1/-1">
              <label class="field-label">Base URL <span style="font-weight:400;text-transform:none;letter-spacing:0">(可选，留空使用默认)</span></label>
              <input
                v-model="cfg.base_url"
                class="input"
                :placeholder="cfg.provider === 'custom' ? 'https://your-api.com/v1' : (PROVIDER_META[cfg.provider]?.default_base_url || '使用内置默认地址')"
              />
            </div>
          </div>

          <!-- Card foot -->
          <div class="s-llm-foot" :class="{ 's-llm-foot--danger': cfg._confirmDelete }">
            <template v-if="cfg._confirmDelete">
              <span class="s-del-warn">确认删除此配置？此操作不可撤销</span>
              <div class="flex gap-2" style="margin-left:auto">
                <button class="btn btn-ghost btn-sm" @click="cfg._confirmDelete = false">取消</button>
                <button class="btn btn-sm s-del-confirm-btn" @click="deleteLLM(cfg, i)">确认删除</button>
              </div>
            </template>
            <template v-else>
              <span
                v-if="cfg.id && llmResult[cfg.id]"
                class="s-test-result"
                :class="llmResult[cfg.id].ok ? 'ok' : 'err'"
              >
                <svg v-if="llmResult[cfg.id].ok" width="11" height="11" viewBox="0 0 20 20" fill="currentColor" style="flex-shrink:0"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>
                <svg v-else width="11" height="11" viewBox="0 0 20 20" fill="currentColor" style="flex-shrink:0"><path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>
                {{ llmResult[cfg.id].msg }}
              </span>
              <div class="flex gap-2" style="margin-left:auto">
                <button
                  v-if="cfg.id"
                  class="btn btn-ghost btn-sm"
                  :disabled="testingLLM === cfg.id"
                  @click="testLLM(cfg)"
                >
                  <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd"/>
                  </svg>
                  {{ testingLLM === cfg.id ? '测试中…' : '测试' }}
                </button>
                <button class="btn btn-primary btn-sm" :disabled="saving" @click="saveLLM(cfg)">保存</button>
                <button class="btn btn-ghost btn-sm s-del-btn" title="删除此配置" @click="confirmDeleteLLM(cfg)">
                  <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
                  </svg>
                </button>
              </div>
            </template>
          </div>
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
                <select v-model="webhook.webhook_type" class="input">
                  <option v-for="t in WEBHOOK_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
                </select>
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
                <select v-model="ensemble.models" class="input">
                  <option value="all">全部已配置模型</option>
                  <option value="default">仅默认模型</option>
                </select>
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

    </div>
  </div>
</template>

<style scoped>
/* ── Layout ──────────────────────────────────────────────────────────────── */
.view { display: flex; flex-direction: column; height: 100%; }


/* ── Tabs ────────────────────────────────────────────────────────────────── */
.s-tabs {
  display: flex;
  gap: 0;
  border-bottom: var(--card-bd);
  background: var(--card);
  flex-shrink: 0;
  padding: 0 16px;
  overflow-x: auto;
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
.s-body { padding: 14px 16px; overflow-y: auto; flex: 1; display: flex; flex-direction: column; gap: 8px; }

/* ── Section head ────────────────────────────────────────────────────────── */
.s-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

/* ── LLM card ────────────────────────────────────────────────────────────── */
.s-llm-card { margin: 0; }
.s-llm-card::before { background: var(--s-accent, var(--line)); }
.s-llm-card:hover::before { background: var(--s-accent, var(--primary)); }

.s-llm-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px 9px;
  border-bottom: var(--card-bd);
}
.s-llm-head--default {
  background: linear-gradient(90deg, var(--primary-d), transparent 60%);
}
.s-default-indicator {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  font-weight: 600;
  color: var(--gold);
  flex-shrink: 0;
  white-space: nowrap;
}
.s-name-input {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--line-dash);
  padding: 0 0 1px;
  outline: none;
  transition: border-color .15s;
  min-width: 0;
}
.s-name-input:hover { border-bottom-color: var(--line); }
.s-name-input:focus { border-bottom-color: var(--primary); }
.s-default-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10px;
  color: var(--text3);
  padding: 2px 7px;
  border: var(--card-bd);
  border-radius: var(--radius-pill);
  cursor: pointer;
  background: transparent;
  transition: color .15s, border-color .15s;
  flex-shrink: 0;
  white-space: nowrap;
}
.s-default-btn:hover { color: var(--gold); border-color: var(--gold); }

.s-llm-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 10px;
  padding: 10px 14px 0;
}
@media (max-width: 480px) { .s-llm-grid { grid-template-columns: 1fr; } }

.s-llm-foot {
  display: flex;
  align-items: center;
  padding: 8px 14px;
  border-top: var(--card-bd);
  background: var(--bg);
  gap: 8px;
}
.s-test-result {
  font-size: 11px;
  font-weight: 500;
}
.s-test-result.ok { color: var(--green); }
.s-test-result.err { color: var(--primary); }

.s-del-btn { color: var(--text3); border-color: transparent; padding: 5px 7px; }
.s-del-btn:hover { color: var(--primary); border-color: var(--primary); }
/* Danger state for delete confirmation — full-width, red tint */
.s-llm-foot--danger { background: var(--win-bg); }
.s-del-warn { font-size: 11px; color: var(--primary); font-weight: 600; }
.s-del-confirm-btn { padding: 5px 10px; font-size: 11px; font-family: var(--font-disp); font-weight: 600; text-transform: uppercase; letter-spacing: .4px; background: var(--primary); color: #fff; border-radius: var(--radius-sm); cursor: pointer; }
.s-del-confirm-btn:hover { opacity: .85; }

/* ── Empty state ─────────────────────────────────────────────────────────── */
.s-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 36px 20px;
  color: var(--text3);
  font-size: 13px;
  text-align: center;
}

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

/* ── Toast ───────────────────────────────────────────────────────────────── */
.s-toast {
  position: fixed;
  bottom: calc(64px + env(safe-area-inset-bottom, 0px));
  left: 50%;
  transform: translateX(-50%);
  background: var(--text);
  color: var(--card);
  font-size: 12px;
  font-weight: 500;
  padding: 7px 14px;
  border-radius: var(--radius-pill);
  display: flex;
  align-items: center;
  gap: 6px;
  z-index: 999;
  white-space: nowrap;
  box-shadow: 0 4px 16px rgba(0,0,0,.2);
}
.s-toast--err { background: var(--primary); }

.toast-slide-enter-active, .toast-slide-leave-active { transition: opacity .2s, transform .2s; }
.toast-slide-enter-from, .toast-slide-leave-to { opacity: 0; transform: translateX(-50%) translateY(8px); }

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

/* ── Toast desktop position ──────────────────────────────────────────────── */
@media (min-width: 768px) {
  .s-toast { bottom: 20px; }
}

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
