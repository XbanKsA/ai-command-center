import Card from './Card'

function Meter({ label, value }) {
  const shown = value == null ? '—' : `${Math.round(value)}%`
  return (
    <div>
      <div className="flex justify-between text-xs text-low">
        <span>{label}</span>
        <span className="font-semibold tabular-nums text-hi">{shown}</span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-well">
        <div
          className="h-full rounded-full bg-accent-text transition-[width] duration-700"
          style={{ width: `${value ?? 0}%` }}
        />
      </div>
    </div>
  )
}

// 11540 seconds -> "3h 12m"
function upText(seconds) {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return h ? `${h}h ${m}m` : `${m}m`
}

function PcCard({ t }) {
  if (!t) return null

  const temp = t.gpu?.temperature_c
  const note = `${temp != null ? `${temp}°C · ` : ''}up ${upText(t.system_uptime_seconds)}`

  return (
    <Card title="PC" note={note} delay={5}>
      <div className="flex flex-col gap-3">
        <Meter label="CPU" value={t.cpu_percent} />
        <Meter label="GPU" value={t.gpu_percent} />
        <Meter label="RAM" value={t.ram_percent} />
        <Meter label="VRAM" value={t.vram_percent} />
      </div>
    </Card>
  )
}

export default PcCard