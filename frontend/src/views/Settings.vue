<script setup lang="ts">
import { ref, onMounted } from 'vue'
import api from '@/api'

interface LLMConfig {
  id?: number
  name: string
  provider: string
  model: string         // backend field name
  api_key: string
  base_url: string | null
  is_default: boolean   // backend field name
}

interface DSConfig {
  id?: number
  source_name: string   // backend field name
  use_scraper: boolean
  enabled: boolean      // backend field name
  has_api_key: boolean
  _api_key?: string     // write-only, not returned by backend
}

const llmConfigs = ref<LLMConfig[]>([])
const dsConfigs = ref<DSConfig[]>([])
const loading = ref(true)
const saving = ref(false)
const testing = ref<number | null>(null)
const testResult = ref<Record<number, string>>({})

const PROVIDERS = ['anthropic', 'openai', 'deepseek', 'kimi', 'glm', 'custom']

async function load() {
  loading.value = true
  try {
    const [llm, ds] = await Promise.all([
      api.get('/settings/llm'),
      api.get('/settings/datasource'),   // singular — backend route name
    ])
    llmConfigs.value = llm.data
    dsConfigs.value = ds.data
  } finally {
    loading.value = false
  }
}

async function saveLLM(cfg: LLMConfig) {
  saving.value = true
  try {
    if (cfg.id) {
      await api.put(`/settings/llm/${cfg.id}`, cfg)
    } else {
      const { data } = await api.post('/settings/llm', cfg)
      cfg.id = data.id
    }
  } finally {
    saving.value = false
  }
}

async function testLLM(cfg: LLMConfig) {
  if (!cfg.id) return
  testing.value = cfg.id
  try {
    const { data } = await api.post(`/settings/llm/${cfg.id}/test`)
    testResult.value[cfg.id] = data.success ? '✓ 连接成功' : '✗ ' + data.error
  } catch {
    testResult.value[cfg.id!] = '✗ 连接失败'
  } finally {
    testing.value = null
  }
}

async function saveDS(cfg: DSConfig) {
  saving.value = true
  try {
    // backend uses PUT /settings/datasource with body (upsert by source_name)
    await api.put('/settings/datasource', {
      source_name: cfg.source_name,
      api_key: cfg._api_key || undefined,
      use_scraper: cfg.use_scraper,
      enabled: cfg.enabled,
    })
  } finally {
    saving.value = false
  }
}

function addLLM() {
  llmConfigs.value.push({
    name: '新配置',
    provider: 'openai',
    model: '',
    api_key: '',
    base_url: null,
    is_default: false,
  })
}

onMounted(load)
</script>

<template>
  <div class="view">
    <div v-if="loading" class="p-5">
      <div class="skeleton" style="height:160px;margin-bottom:12px" />
      <div class="skeleton" style="height:160px" />
    </div>

    <div v-else class="settings-body">

      <!-- LLM Configs -->
      <section class="settings-section">
        <div class="flex items-center justify-between mb-3">
          <div class="section-label" style="margin:0">LLM 模型配置</div>
          <button class="btn btn-ghost btn-sm" @click="addLLM">+ 添加</button>
        </div>

        <div v-for="(cfg, i) in llmConfigs" :key="i" class="card no-accent settings-card">
          <!-- Active toggle + name -->
          <div class="cfg-head">
            <input v-model="cfg.name" class="input cfg-name-input" placeholder="配置名称" />
            <label class="toggle">
              <input type="checkbox" v-model="cfg.is_default" />
              <span class="toggle-track"><span class="toggle-thumb" /></span>
              <span class="text-xs">{{ cfg.is_default ? '默认' : '备用' }}</span>
            </label>
          </div>

          <div class="cfg-grid">
            <div class="field">
              <label class="field-label">服务商</label>
              <select v-model="cfg.provider" class="input">
                <option v-for="p in PROVIDERS" :key="p" :value="p">{{ p }}</option>
              </select>
            </div>
            <div class="field">
              <label class="field-label">模型名称</label>
              <input v-model="cfg.model" class="input" placeholder="claude-sonnet-4-6" />
            </div>
            <div class="field" style="grid-column:1/-1">
              <label class="field-label">API Key</label>
              <input v-model="cfg.api_key" class="input" type="password" placeholder="sk-..." />
            </div>
            <div class="field" style="grid-column:1/-1">
              <label class="field-label">Base URL（可选）</label>
              <input v-model="cfg.base_url" class="input" placeholder="https://api.openai.com/v1" />
            </div>
          </div>

          <div class="cfg-foot">
            <span
              v-if="cfg.id && testResult[cfg.id]"
              class="text-xs"
              :class="testResult[cfg.id].startsWith('✓') ? 'text-green' : 'text-primary'"
            >
              {{ testResult[cfg.id] }}
            </span>
            <div class="flex gap-2" style="margin-left:auto">
              <button
                v-if="cfg.id"
                class="btn btn-ghost btn-sm"
                :disabled="testing === cfg.id"
                @click="testLLM(cfg)"
              >
                {{ testing === cfg.id ? '测试中…' : '测试连接' }}
              </button>
              <button class="btn btn-primary btn-sm" :disabled="saving" @click="saveLLM(cfg)">
                保存
              </button>
            </div>
          </div>
        </div>
      </section>

      <!-- Data sources -->
      <section class="settings-section">
        <div class="section-label mb-3">数据源配置</div>

        <div v-for="(cfg, i) in dsConfigs" :key="i" class="card no-accent settings-card">
          <div class="cfg-head">
            <div>
              <div class="font-600" style="font-size:13px">{{ cfg.source_name }}</div>
              <div class="text-xs text-muted">{{ cfg.use_scraper ? '爬虫模式' : 'API 模式' }}</div>
            </div>
            <label class="toggle">
              <input type="checkbox" v-model="cfg.enabled" />
              <span class="toggle-track"><span class="toggle-thumb" /></span>
              <span class="text-xs">{{ cfg.enabled ? '启用' : '停用' }}</span>
            </label>
          </div>
          <div class="field" style="padding:0 14px 14px">
            <label class="field-label">API Key {{ cfg.has_api_key ? '(已配置)' : '(未配置)' }}</label>
            <input v-model="cfg._api_key" class="input" type="password" placeholder="留空使用爬虫/免费源" />
          </div>
          <div class="cfg-foot">
            <button class="btn btn-primary btn-sm" style="margin-left:auto" @click="saveDS(cfg)">保存</button>
          </div>
        </div>
      </section>

    </div>
  </div>
</template>

<style scoped>
.view { display: flex; flex-direction: column; }
.settings-body { padding: 16px; overflow-y: auto; flex: 1; }
.settings-section { margin-bottom: 24px; }

.settings-card { margin-bottom: 10px; }

.cfg-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px 8px;
}
.cfg-name-input {
  flex: 1;
  font-weight: 600;
  border: none;
  border-bottom: 1px solid var(--line);
  background: transparent;
  padding: 0 0 2px;
  font-size: 13px;
  outline: none;
  transition: border-color .15s;
}
.cfg-name-input:hover { border-bottom-color: var(--text3); }
.cfg-name-input:focus { border-bottom-color: var(--primary); }

.cfg-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 10px;
  padding: 0 14px;
}
@media (max-width: 500px) { .cfg-grid { grid-template-columns: 1fr; } }

.cfg-foot {
  display: flex;
  align-items: center;
  padding: 10px 14px;
  border-top: var(--card-bd);
  background: var(--bg);
}

/* Toggle */
.toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  flex-shrink: 0;
}
.toggle input { display: none; }
.toggle-track {
  width: 32px; height: 18px;
  border-radius: 9px;
  background: var(--line);
  position: relative;
  transition: background .2s;
}
.toggle input:checked + .toggle-track { background: var(--primary); }
.toggle-thumb {
  position: absolute;
  top: 2px; left: 2px;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: #fff;
  transition: transform .2s;
  box-shadow: 0 1px 3px rgba(0,0,0,.2);
}
.toggle input:checked + .toggle-track .toggle-thumb { transform: translateX(14px); }
</style>
