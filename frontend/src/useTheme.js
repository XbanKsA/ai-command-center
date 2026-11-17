import { useState } from 'react'
import { applyTheme, loadTheme, saveTheme, DEFAULT_THEME } from './theme'

export function useTheme() {
  const [theme, setTheme] = useState(loadTheme)

  // change one or more of pos / shade / calm, show it, and remember it
  function changeTheme(patch, fade = false) {
    const next = { ...theme, ...patch }
    applyTheme(next, fade)
    saveTheme(next)
    setTheme(next)
  }

  function resetTheme() {
    changeTheme(DEFAULT_THEME, true)
  }

  return { theme, changeTheme, resetTheme }
}