function ModeToggle({ mode, onChange }) {
  if (!mode) return null

  const gaming = mode.mode === 'gaming'
  const how = mode.switching ? 'switching…' : mode.auto ? 'Auto' : 'Manual'

  return (
    <div className="flex items-center gap-3">
      <span className="flex h-10 items-center gap-2 rounded-full border border-slate-800 px-4 text-sm">
        <span className={`h-2 w-2 rounded-full ${gaming ? 'bg-amber-400' : 'bg-cyan-400'}`} />
        <span className="font-mono">{mode.model}</span>
        <span className="text-slate-400">· {gaming ? 'Gaming' : 'Normal'} · {how}</span>
      </span>
      <button
        onClick={() => onChange(gaming ? 'auto' : 'gaming')}
        className={`h-10 rounded-xl border px-4 font-semibold ${gaming ? 'border-amber-400 bg-amber-400 text-black' : 'border-slate-700 text-slate-300'}`}
      >
        Gaming Mode
      </button>
    </div>
  )
}

export default ModeToggle