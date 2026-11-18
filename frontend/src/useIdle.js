import { useCallback, useEffect, useRef, useState } from 'react'

// idle turns true after `ms` without a touch. sleep() turns it on straight away.
export function useIdle(ms) {
  const [idle, setIdle] = useState(false)
  const timer = useRef(null)

  useEffect(() => {
    function activity() {
      setIdle(false)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setIdle(true), ms)
    }

    const events = ['pointerdown', 'keydown', 'wheel']
    events.forEach((e) => window.addEventListener(e, activity))
    activity() // start the first countdown

    return () => {
      clearTimeout(timer.current)
      events.forEach((e) => window.removeEventListener(e, activity))
    }
  }, [ms])

  const sleep = useCallback(() => {
    clearTimeout(timer.current)
    setIdle(true)
  }, [])

  return { idle, sleep }
}