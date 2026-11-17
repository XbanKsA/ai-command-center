import { useEffect, useState } from 'react'

const STORAGE = 'kageon_decks'
const OLD_STORAGE = 'jarvis_keys' // the single page of keys from before deck pages existed
export const TOTAL_SLOTS = 15
const PAGE_NAMES = ['Main', 'Gaming', 'Work']

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

function emptySlots() {
  return Array.from({ length: TOTAL_SLOTS }, () => null)
}

function loadDecks() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE))
    if (Array.isArray(saved) && saved.length === PAGE_NAMES.length) return saved
  } catch {
    // saved data was broken -> rebuild it below
  }

  // First run with pages: the keys you already had become the Main page
  let main = Array.from({ length: TOTAL_SLOTS }, (_, i) => DEFAULT_KEYS[i] ?? null)
  try {
    const old = JSON.parse(localStorage.getItem(OLD_STORAGE))
    if (Array.isArray(old) && old.length === TOTAL_SLOTS) main = old
  } catch {
    // no old keys -> keep the defaults
  }

  return PAGE_NAMES.map((name, i) => ({ name, slots: i === 0 ? main : emptySlots() }))
}

export function useKeys() {
  const [decks, setDecks] = useState(loadDecks)

  useEffect(() => {
    localStorage.setItem(STORAGE, JSON.stringify(decks))
  }, [decks])

  function saveKey(page, index, key) {
    setDecks((prev) =>
      prev.map((deck, p) =>
        p !== page ? deck : { ...deck, slots: deck.slots.map((slot, i) => (i === index ? key : slot)) }
      )
    )
  }

  function deleteKey(page, index) {
    saveKey(page, index, null)
  }

  return { decks, saveKey, deleteKey }
}