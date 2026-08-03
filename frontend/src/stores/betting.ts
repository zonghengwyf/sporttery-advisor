import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useBettingStore = defineStore('betting', () => {
  const schemes = ref<any>(null)
  const activeTab = ref<string>('conservative')
  const lastMatchIds = ref<number[]>([])

  function save(newSchemes: any, tab: string, matchIds: number[]) {
    schemes.value = newSchemes
    activeTab.value = tab as any
    lastMatchIds.value = [...matchIds]
  }

  function clear() {
    schemes.value = null
    lastMatchIds.value = []
    activeTab.value = 'conservative'
  }

  return { schemes, activeTab, lastMatchIds, save, clear }
})
