import { Monitor, Sparkles, Thermometer, WifiOff } from 'lucide-react'

const ICONS = { replies: Sparkles, ask: Sparkles, offline: WifiOff, hot: Thermometer, pc: Monitor }

function NotificationIcon({ kind }) {
  const Icon = ICONS[kind] ?? Sparkles
  const hot = kind === 'hot' || kind === 'offline'
  return (
    <span className={`flex h-9.5 w-9.5 shrink-0 items-center justify-center rounded-xl ${hot ? 'bg-amber-400/15 text-amber-300' : 'bg-accent-soft text-accent-text'}`}>
      <Icon className="h-4.5 w-4.5" strokeWidth={1.75} />
    </span>
  )
}

export default NotificationIcon