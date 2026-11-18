import { Clock, Settings2 } from 'lucide-react'
import { SCREENS } from '../screens'
import Logo from './Logo'

function Rail({ screen, onChange, onSettings, onSleep }) {
  return (
    <nav className="flex w-15 flex-col items-center gap-1.5 rounded-3xl border border-line bg-card py-2.5 backdrop-blur-xl">
      <Logo className="mb-2 h-10 w-10" />

      {SCREENS.map((s) => {
        const Icon = s.icon
        const active = s.id === screen
        return (
          <button
            key={s.id}
            onClick={() => onChange(s.id)}
            aria-label={s.label}
            className={`press flex h-11 w-11 items-center justify-center rounded-xl transition-colors duration-300 ${active ? 'bg-accent-soft text-accent-text' : 'text-low'}`}
          >
            <Icon className="h-5 w-5" strokeWidth={1.75} />
          </button>
        )
      })}

      <div className="flex-1" />
      <button onClick={onSettings} aria-label="Settings" className="press flex h-11 w-11 items-center justify-center rounded-xl text-low">
        <Settings2 className="h-5 w-5" strokeWidth={1.75} />
      </button>
      <button onClick={onSleep} aria-label="Always-on display" className="press flex h-11 w-11 items-center justify-center rounded-xl text-low">
        <Clock className="h-5 w-5" strokeWidth={1.75} />
      </button>
    </nav>
  )
}

export default Rail