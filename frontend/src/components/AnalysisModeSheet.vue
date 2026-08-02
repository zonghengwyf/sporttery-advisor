<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useAnalysisPreference, type AnalysisMode } from "@/composables/useAnalysisPreference";
import {
  Sheet, SheetContent, SheetHeader, SheetTitle,
} from "@/components/ui/sheet";

const props = defineProps<{
  open: boolean;
  latestAt: string | null;
  matchCount: number;
  modelCount: number;
  avgSecsPerMatch?: number;
}>();

const emit = defineEmits<{
  (e: "update:open", value: boolean): void;
  (e: "select", mode: AnalysisMode): void;
}>();

const { getPreference } = useAnalysisPreference();
const hasCache = computed(() => !!props.latestAt);
const highlighted = ref<AnalysisMode>("cache");

watch(() => props.open, (isOpen) => {
  if (!isOpen) return;
  const saved = getPreference();
  highlighted.value = (!hasCache.value) ? "fresh" : (saved ?? "cache");
}, { immediate: true });

const latestLabel = computed(() => {
  if (!props.latestAt) return "";
  try {
    const d = new Date(props.latestAt);
    return `最近分析于 ${d.getHours().toString().padStart(2,"0")}:${d.getMinutes().toString().padStart(2,"0")}`;
  } catch { return ""; }
});

const estimatedMinutes = computed(() =>
  Math.max(1, Math.round((props.avgSecsPerMatch ?? 20) * props.matchCount / 60))
);

function select(mode: AnalysisMode) {
  if (mode === "cache" && !hasCache.value) return;
  emit("select", mode);
  emit("update:open", false);
}
</script>

<template>
  <Sheet :open="open" @update:open="emit('update:open', $event)">
    <SheetContent
      side="bottom"
      class="rounded-t-2xl px-4 pb-8 pt-3 flex flex-col gap-3 max-w-xl mx-auto"
    >
      <!-- drag handle -->
      <div class="w-9 h-1 rounded-full mx-auto" style="background:var(--line-dash)" />

      <SheetHeader class="text-center pb-1">
        <SheetTitle class="text-[15px] font-semibold" style="color:var(--text)">
          选择分析模式
        </SheetTitle>
      </SheetHeader>

      <!-- Cache option -->
      <button
        class="option-btn"
        :class="{ 'option-btn--active': highlighted === 'cache', 'option-btn--disabled': !hasCache }"
        :disabled="!hasCache"
        :aria-pressed="highlighted === 'cache'"
        @click="select('cache')"
      >
        <div class="option-left">
          <span class="option-icon">⚡</span>
          <div class="option-body">
            <span class="option-title">使用今日缓存</span>
            <span class="option-sub">{{ hasCache ? latestLabel : '今日尚未分析' }}</span>
          </div>
        </div>
        <span class="option-badge option-badge--fast">快速 &lt;5s</span>
      </button>

      <!-- Fresh analysis option -->
      <button
        class="option-btn"
        :class="{ 'option-btn--active': highlighted === 'fresh' }"
        :aria-pressed="highlighted === 'fresh'"
        @click="select('fresh')"
      >
        <div class="option-left">
          <span class="option-icon">🔄</span>
          <div class="option-body">
            <span class="option-title">重新全量分析</span>
            <span class="option-sub">{{ matchCount }} 场 · {{ modelCount }} 个模型 · 约 {{ estimatedMinutes }} 分钟</span>
          </div>
        </div>
        <span class="option-badge option-badge--slow">约 {{ estimatedMinutes }}min</span>
      </button>

      <button
        class="cancel-btn mt-1 w-full rounded py-3.5 text-[15px] min-h-[44px] transition-colors"
        style="color:var(--text2)"
        @click="emit('update:open', false)"
      >
        取消
      </button>
    </SheetContent>
  </Sheet>
</template>

<style scoped>
.option-btn {
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
  transition: border-color .15s, background .15s;
}
.option-btn--active {
  border-color: var(--primary);
  background: var(--primary-d);
}
.option-btn--disabled { opacity: .45; cursor: not-allowed; }
.cancel-btn:hover { background: var(--line); }
.option-btn:not(.option-btn--disabled):hover { border-color: var(--primary); }

.option-left { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.option-icon { font-size: 20px; flex-shrink: 0; }
.option-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.option-title { font-size: 14px; font-weight: 600; color: var(--text); white-space: nowrap; }
.option-sub { font-size: 12px; color: var(--text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.option-badge {
  font-size: 11px; font-weight: 600;
  padding: 3px 8px; border-radius: var(--radius-pill);
  white-space: nowrap; flex-shrink: 0;
}
.option-badge--fast { background: #DCFCE7; color: #15803D; }
.option-badge--slow { background: #FEF3C7; color: var(--gold); }
</style>
