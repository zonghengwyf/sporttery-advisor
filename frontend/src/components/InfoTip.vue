<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'

const props = defineProps<{
  text: string
}>()

const open = ref(false)
const el = ref<HTMLElement>()

function handleOutside(e: Event) {
  if (!el.value?.contains(e.target as Node)) open.value = false
}

onMounted(() => document.addEventListener('click', handleOutside, true))
onUnmounted(() => document.removeEventListener('click', handleOutside, true))
</script>

<template>
  <span ref="el" class="itip" @click.stop="open = !open" role="button" :aria-expanded="open">
    <svg class="itip-icon" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="8" cy="8" r="7" stroke="currentColor" stroke-width="1.3"/>
      <line x1="8" y1="7" x2="8" y2="11.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
      <circle cx="8" cy="5" r=".8" fill="currentColor"/>
    </svg>
    <transition name="itip-fade">
      <div v-if="open" class="itip-card" @click.stop>
        {{ text }}
      </div>
    </transition>
  </span>
</template>

<style scoped>
.itip {
  position: relative;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  vertical-align: middle;
  padding: 2px;
  margin-left: 2px;
}
.itip-icon {
  width: 13px;
  height: 13px;
  color: var(--text3);
  flex-shrink: 0;
  transition: color .15s;
}
.itip:hover .itip-icon,
.itip:active .itip-icon {
  color: var(--primary);
}
.itip-card {
  position: fixed;
  bottom: 72px;
  left: 12px;
  right: 12px;
  z-index: 300;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text2);
  box-shadow: 0 8px 32px rgba(0,0,0,.22);
  white-space: normal;
  pointer-events: auto;
  max-width: 480px;
  margin: 0 auto;
}

.itip-fade-enter-active,
.itip-fade-leave-active { transition: opacity .15s, transform .15s; }
.itip-fade-enter-from,
.itip-fade-leave-to { opacity: 0; transform: translateY(6px); }
</style>
