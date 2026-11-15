import { useEffect, useState } from 'react'

const STORAGE = 'jarvis_keys'
export const TOTAL_SLOTS = 15

const DEFAULT_KEYS = [
  { title: 'Steam', subtitle: 'App', action: { type: 'launch', target: 'steam' } },
  { title: 'Discord', subtitle: 'App', action: { type: 'launch', target: 'discord' } },
  { title: 'YouTube', subtitle: 'Website', action: { type: 'launch', target: 'https://www.youtube.com' } },
  { title: 'Spotify', subtitle: 'App', action: { type: 'launch', target: 'spotify' } },
  { title: 'Deadlock', subtitle: 'Game', action: { type: 'launch', target: 'deadlock' } },
  { title: 'Gaming time', subtitle: 'Routine', action: { type: 'ask', text: 'gaming time' } },
  { title: 'VS Code', subtitle: 'App', action: { type: 'launch', target: 'visual studio code' } },
  { title: 'Which model?', subtitle: 'Ask KAGEON', action: { type: 'ask', text: 'which model are you using' } },
]

function loadSlots() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE))
    if (Array.isArray(saved) && saved.length === TOTAL_SLOTS) return saved
  } catch {
    // saved data was broken -> fall back to the defaults below
  }
  return Array.from({ length: TOTAL_SLOTS }, (_, i) => DEFAULT_KEYS[i] ?? null)
}

export function useKeys() {
  const [slots, setSlots] = useState(loadSlots)

  useEffect(() => {
    localStorage.setItem(STORAGE, JSON.stringify(slots))
  }, [slots])

  function saveKey(index, key) {
    setSlots((prev) => prev.map((slot, i) => (i === index ? key : slot)))
  }

  function deleteKey(index) {
    saveKey(index, null)
  }

  return { slots, saveKey, deleteKey }
}