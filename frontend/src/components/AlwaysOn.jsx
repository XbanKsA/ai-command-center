import { useNow } from '../useNow'

function AlwaysOn({ telemetry, mode }) {
  const now = useNow()
  const t = telemetry ?? {}
  const stats = [
    ['CPU', t.cpu_percent],
    ['GPU', t.gpu_percent],
    ['RAM', t.ram_percent],
    ['VRAM', t.vram_percent],
  ]

  return (
    <div className="fixed inset-0 z-20 flex select-none flex-col items-center justify-center gap-6 bg-black">
      <div className="text-[200px] font-extralight leading-none text-slate-200">
        {now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
      </div>
      <div className="text-2xl text-slate-500">
        {now.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
      </div>

      <div className="mt-8 flex gap-14">
        {stats.map(([label, value]) => (
          <div key={label} className="flex flex-col items-center gap-1">
            <span className="font-mono text-3xl text-cyan-300 drop-shadow-[0_0_8px_rgba(34,211,238,0.7)]">
              {value == null ? '—' : `${Math.round(value)}%`}
            </span>
            <span className="text-xs tracking-[0.3em] text-slate-500">{label}</span>
          </div>
        ))}
      </div>

      {mode && <div className="mt-6 text-sm text-slate-500">{mode.label}</div>}
      <div className="absolute bottom-8 text-xs text-slate-600">Touch anywhere to wake</div>
    </div>
  )
}

export default AlwaysOn