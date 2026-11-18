import { useNow } from '../useNow'

// Always black: on the tablet's OLED screen black pixels are off, so this uses almost no power.
// The colours here are fixed on purpose (light text on black), whatever the theme.
function AlwaysOn({ telemetry, mode, notes, hidePcText }) {
  const now = useNow()
  const t = telemetry ?? {}
  const stats = [
    ['CPU', t.cpu_percent],
    ['GPU', t.gpu_percent],
    ['RAM', t.ram_percent],
    ['VRAM', t.vram_percent],
  ]

  // the unread notifications, counted by where they came from: "Discord 2 · Kageon 1"
  const unread = notes.list.slice(0, notes.unread)
  const counts = {}
  for (const n of unread) {
    const from = n.kind === 'pc' ? n.title : 'Kageon'
    counts[from] = (counts[from] ?? 0) + 1
  }
  const latest = unread[0]
  const showText = latest && !(latest.kind === 'pc' && hidePcText) // private PC messages stay hidden

  const how = mode && (mode.switching ? 'switching…' : `${mode.mode === 'gaming' ? 'Gaming' : 'Normal'} · ${mode.auto ? 'Auto' : 'Manual'}`)

  return (
    <div className="scene fixed inset-0 z-30 flex select-none flex-col items-center justify-center gap-4 bg-black text-[#d7dce6]">
      <div className="font-display text-[13rem] font-extralight leading-none tabular-nums">
        {now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
      </div>
      <div className="text-2xl text-[#8f97a6]">
        {now.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}
      </div>

      <div className="mt-7 flex gap-14">
        {stats.map(([label, value]) => (
          <div key={label} className="flex flex-col items-center gap-1">
            <span className="font-display text-3xl tabular-nums text-accent">{value == null ? '—' : `${Math.round(value)}%`}</span>
            <span className="text-sm text-[#8f97a6]">{label}</span>
          </div>
        ))}
      </div>

      {mode && <div className="mt-3 text-sm text-[#8f97a6]">{mode.model} · {how}</div>}

      {unread.length > 0 && (
        <div className="mt-2 flex max-w-[40rem] flex-col items-center gap-1 text-center">
          <p className="text-base text-[#b9c0cc]">
            {Object.entries(counts).map(([from, count]) => `${from} ${count}`).join(' · ')}
          </p>
          {showText && <p className="truncate text-sm text-[#8f97a6]">{latest.title}: {latest.text}</p>}
        </div>
      )}

      <div className="absolute bottom-8 text-sm text-[#7d8594]">Touch anywhere to wake</div>
    </div>
  )
}

export default AlwaysOn