import { Search } from 'lucide-react'
import Clock from './Clock'

function TopBar({ title, mode, onMode, onAsk }) {
  const gaming = mode?.mode === 'gaming'
  const how = mode?.switching ? 'switching…' : `${gaming ? 'Gaming' : 'Normal'} · ${mode?.auto ? 'Auto' : 'Manual'}`

  return (
    <header className="flex h-14 items-center gap-2.5 rounded-2xl border border-line bg-card pl-4.5 pr-4 backdrop-blur-xl">
      <div className="flex items-center gap-2 text-sm text-low">
        <span>Kageon</span>
        <span>/</span>
        <span className="font-semibold text-hi">{title}</span>
      </div>

      <button onClick={onAsk} className="ml-2.5 flex h-11 w-70 items-center gap-2 rounded-xl bg-well px-3 text-sm text-low">
        <Search className="h-4 w-4" />
        Ask Kageon…
      </button>

      <div className="flex-1" />

      <span className="flex h-8 items-center gap-2 rounded-full border border-line px-3 text-xs text-mid">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        Live
      </span>

      {mode && (
        <>
          <span className="flex h-8 items-center gap-2 rounded-full border border-line px-3 text-xs text-mid">
            <span className={`h-1.5 w-1.5 rounded-full ${gaming ? 'bg-amber-400' : 'bg-accent-text'}`} />
            <span className="font-semibold text-hi">{mode.model}</span>
            <span>{how}</span>
          </span>
          <button
            onClick={() => onMode(gaming ? 'auto' : 'gaming')}
            className={`h-11 rounded-xl border px-4 text-sm font-semibold ${gaming ? 'border-transparent bg-amber-400 text-black' : 'border-line bg-card'}`}
          >
            Gaming
          </button>
        </>
      )}

      <Clock />
    </header>
  )
}

export default TopBar