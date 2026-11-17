import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { setupTablet } from './nativeSetup'
setupTablet()
import { applyTheme, loadTheme } from './theme'
applyTheme(loadTheme())
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
