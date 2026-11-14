import { useEffect, useState } from 'react'

export function useIdle(ms) {
  const [idle, setIdle] = useState(false)

  useEffect(() => {
    let timer

    function activity() {
      setIdle(false)
      clearTimeout(timer)
      timer = setTimeout(() => setIdle(true), ms)
    }

    const events = ['pointerdown', 'keydown', 'wheel']
    events.forEach((e) => window.addEventListener(e, activity))
    activity() // start the first countdown

    return () => {
      clearTimeout(timer)
      events.forEach((e) => window.removeEventListener(e, activity))
    }
  }, [ms])

  return idle
}