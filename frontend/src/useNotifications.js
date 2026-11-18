import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE = 'kageon_notify'

// Kageon's own alerts, and whether each one is on (all on to start with)
export const KAGEON_KINDS = [
  { id: 'replies', label: 'Kageon answers something said on the PC' },
  { id: 'ask', label: 'Questions that need a yes or no' },
  { id: 'offline', label: 'The PC went offline' },
  { id: 'hot', label: 'GPU running hot' },
]
const DEFAULT_KINDS = { replies: true, ask: true, offline: true, hot: true }

// replies and questions already pop up as the reply toast, so only these get their own pop-up
const POP_UP = ['offline', 'hot', 'pc']

function loadKinds() {
  try {
    return { ...DEFAULT_KINDS, ...JSON.parse(localStorage.getItem(STORAGE)) }
  } catch {
    return DEFAULT_KINDS
  }
}

export function useNotifications() {
  const [list, setList] = useState([]) // newest first, the last 30
  const [unread, setUnread] = useState(0)
  const [popup, setPopup] = useState(null) // the one showing as a pop-up right now
  const [kinds, setKinds] = useState(loadKinds)
  const kindsRef = useRef(kinds) // notify() reads the switches from here, so notify itself never changes

  useEffect(() => {
    kindsRef.current = kinds
    localStorage.setItem(STORAGE, JSON.stringify(kinds))
  }, [kinds])

  const notify = useCallback((kind, title, text = '') => {
    if (kindsRef.current[kind] === false) return // switched off in Settings
    const n = { id: `${Date.now()}-${Math.random()}`, kind, title, text, time: Date.now() }
    setList((prev) => [n, ...prev].slice(0, 30))
    setUnread((u) => u + 1)
    if (POP_UP.includes(kind)) setPopup(n)
  }, [])

  function toggleKind(id) {
    setKinds((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  // useCallback keeps these the same function every time. The pop-up's 5-second timer restarts
  // whenever closePopup changes, so a new function on every screen update would keep it open forever.
  const closePopup = useCallback(() => setPopup(null), [])
  const markRead = useCallback(() => setUnread(0), [])
  const clear = useCallback(() => {
    setList([])
    setUnread(0)
  }, [])

  return { list, unread, popup, kinds, notify, toggleKind, markRead, clear, closePopup }
}