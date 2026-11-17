import { Settings2 } from 'lucide-react'
import { SCREENS } from '../screens'

function Rail({ screen, onChange, onSettings }) {
  return (
    <nav className="flex w-15 flex-col items-center gap-1.5 rounded-3xl border border-line bg-card py-2.5 backdrop-blur-xl">
      <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-accent text-accent-ink">
        <svg viewBox="0 0 24 24" className="h-5.5 w-5.5" fill="currentColor">
          <path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z" />
        </svg>
      </div>

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
    </nav>
  )
}

export default Rail