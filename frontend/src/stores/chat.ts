import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useChatStore = defineStore('chat', () => {
  const open = ref(false)
  const requestMatchId = ref<number | null>(null)

  function openWith(matchId?: number | null) {
    requestMatchId.value = matchId ?? null
    open.value = true
  }

  function close() {
    open.value = false
  }

  return { open, requestMatchId, openWith, close }
})
