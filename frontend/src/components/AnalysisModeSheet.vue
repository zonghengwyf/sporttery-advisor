<template>
  <Teleport to="body">
    <Transition name="sheet-fade">
      <div
        v-if="visible"
        class="sheet-backdrop"
        role="dialog"
        aria-modal="true"
        aria-label="选择分析模式"
        @click.self="emit('cancel')"
        @keydown.esc="emit('cancel')"
      >
        <Transition name="sheet-slide">
          <div v-if="visible" class="sheet-panel" tabindex="-1">
            <div class="sheet-handle" />
            <h2 class="sheet-title">📊 选择分析模式</h2>

            <!-- Cache option -->
            <button
              class="sheet-option"
              :class="{ 'sheet-option--active': highlighted === 'cache', 'sheet-option--disabled': !hasCache }"
              :disabled="!hasCache"
              :aria-pressed="highlighted === 'cache'"
              @click="select('cache')"
            >
              <div class="sheet-option-left">
                <span class="sheet-option-icon">⚡</span>
                <div class="sheet-option-body">
                  <span class="sheet-option-title">使用今日缓存</span>
                  <span class="sheet-option-sub">
                    {{ hasCache ? latestLabel : '今日尚未分析' }}
                  </span>
                </div>
              </div>
              <span class="sheet-option-badge sheet-option-badge--fast">快速 &lt;5s</span>
            </button>

            <!-- Fresh analysis option -->
            <button
              class="sheet-option"
              :class="{ 'sheet-option--active': highlighted === 'fresh' }"
              :aria-pressed="highlighted === 'fresh'"
              @click="select('fresh')"
            >
              <div class="sheet-option-left">
                <span class="sheet-option-icon">🔄</span>
                <div class="sheet-option-body">
                  <span class="sheet-option-title">重新全量分析</span>
                  <span class="sheet-option-sub">
                    {{ matchCount }} 场 · {{ modelCount }} 个模型 · 约 {{ estimatedMinutes }} 分钟
                  </span>
                </div>
              </div>
              <span class="sheet-option-badge sheet-option-badge--slow">约 {{ estimatedMinutes }}min</span>
            </button>

            <button class="sheet-cancel" @click="emit('cancel')">取消</button>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useAnalysisPreference, type AnalysisMode } from "@/composables/useAnalysisPreference";

const props = defineProps<{
  visible: boolean;
  latestAt: string | null;   // ISO8601 or null
  matchCount: number;
  modelCount: number;
  avgSecsPerMatch?: number;  // default 20
}>();

const emit = defineEmits<{
  (e: "select", mode: AnalysisMode): void;
  (e: "cancel"): void;
}>();

const { getPreference } = useAnalysisPreference();

const hasCache = computed(() => !!props.latestAt);

const highlighted = ref<AnalysisMode>("cache");

// Reset highlighted every time the sheet opens, reflecting current cache state + user preference
watch(() => props.visible, (isOpen) => {
  if (!isOpen) return;
  const saved = getPreference();
  if (!hasCache.value) {
    highlighted.value = "fresh";
  } else if (saved) {
    highlighted.value = saved;
  } else {
    highlighted.value = "cache";
  }
}, { immediate: true });

const latestLabel = computed(() => {
  if (!props.latestAt) return "";
  try {
    const d = new Date(props.latestAt);
    const hh = d.getHours().toString().padStart(2, "0");
    const mm = d.getMinutes().toString().padStart(2, "0");
    return `最近分析于 ${hh}:${mm}`;
  } catch {
    return "";
  }
});

const estimatedMinutes = computed(() => {
  const secs = (props.avgSecsPerMatch ?? 20) * props.matchCount;
  const mins = Math.max(1, Math.round(secs / 60));
  return mins;
});

function select(mode: AnalysisMode) {
  if (mode === "cache" && !hasCache.value) return;
  emit("select", mode);
}
</script>

<style scoped>
.sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: flex-end;
}

.sheet-panel {
  width: 100%;
  max-width: 640px;
  margin: 0 auto;
  background: var(--card);
  border-radius: 16px 16px 0 0;
  padding: 12px 16px 32px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  outline: none;
}

.sheet-handle {
  width: 36px;
  height: 4px;
  background: var(--line-dash);
  border-radius: 2px;
  margin: 0 auto 4px;
}

.sheet-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  text-align: center;
  margin-bottom: 4px;
}

.sheet-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-height: 64px;
  padding: 12px 14px;
  border: 1.5px solid var(--line);
  border-radius: var(--radius);
  background: transparent;
  cursor: pointer;
  text-align: left;
  transition: border-color 0.15s, background 0.15s;
}

.sheet-option--active {
  border-color: var(--primary);
  background: var(--primary-d);
}

.sheet-option--disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.sheet-option:not(.sheet-option--disabled):hover {
  border-color: var(--primary);
}

.sheet-option-left {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.sheet-option-icon {
  font-size: 20px;
  flex-shrink: 0;
}

.sheet-option-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.sheet-option-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
}

.sheet-option-sub {
  font-size: 12px;
  color: var(--text2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.sheet-option-badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: var(--radius-pill);
  white-space: nowrap;
  flex-shrink: 0;
}

.sheet-option-badge--fast {
  background: #DCFCE7;
  color: #15803D;
}

.sheet-option-badge--slow {
  background: #FEF3C7;
  color: var(--gold);
}

.sheet-cancel {
  margin-top: 4px;
  padding: 14px;
  width: 100%;
  border: none;
  background: transparent;
  font-size: 15px;
  color: var(--text2);
  cursor: pointer;
  border-radius: var(--radius);
  min-height: 44px;
}

.sheet-cancel:hover {
  background: var(--line);
  color: var(--text);
}

/* Transitions */
.sheet-fade-enter-active,
.sheet-fade-leave-active {
  transition: opacity 0.2s;
}
.sheet-fade-enter-from,
.sheet-fade-leave-to {
  opacity: 0;
}

.sheet-slide-enter-active,
.sheet-slide-leave-active {
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.sheet-slide-enter-from,
.sheet-slide-leave-to {
  transform: translateY(100%);
}
</style>
