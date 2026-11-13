function Stat({ label, value }) {
  const shown = value == null ? '—' : `${Math.round(value)}%`
  return (
    <div className="w-28">
      <div className="flex justify-between text-xs text-slate-400">
        <span>{label}</span>
        <span className="font-mono text-white">{shown}</span>
      </div>
      <div className="h-1.5 mt-1 rounded bg-slate-800">
        <div className="h-1.5 rounded bg-cyan-400 transition-all" style={{ width: `${value ?? 0}%` }} />
      </div>
    </div>
  )
}

function Stats({ t }) {
  if (!t) return null
  return (
    <div className="flex gap-5">
      <Stat label="CPU" value={t.cpu_percent} />
      <Stat label="GPU" value={t.gpu_percent} />
      <Stat label="RAM" value={t.ram_percent} />
      <Stat label="VRAM" value={t.vram_percent} />
    </div>
  )
}

export default Stats