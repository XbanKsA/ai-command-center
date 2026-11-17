import Card from './Card'
import Sparkline from './Sparkline'

function StatCard({ label, value, detail, values, delay }) {
  return (
    <Card title={label} note={detail} delay={delay} className="flex min-h-0 flex-col gap-3">
      <div className="flex items-baseline gap-1">
        <span className="font-display text-6xl font-light tabular-nums">{value == null ? '—' : Math.round(value)}</span>
        <span className="text-xl text-low">%</span>
      </div>
      <Sparkline values={values} />
      <div className="h-1.5 overflow-hidden rounded-full bg-well">
        <div className="h-full rounded-full bg-accent-text transition-[width] duration-700" style={{ width: `${value ?? 0}%` }} />
      </div>
    </Card>
  )
}

const MODE_BUTTONS = [
  { id: 'auto', label: 'Auto' },
  { id: 'normal', label: 'Normal' },
  { id: 'gaming', label: 'Gaming' },
]

function ModelRow({ name, model, about, active, dot }) {
  return (
    <div className={`flex h-12 items-center gap-3 rounded-xl border px-3.5 text-sm transition-colors duration-500 ${active ? 'border-accent-line bg-accent-soft' : 'border-transparent'}`}>
      <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} />
      <span className="w-18 font-semibold">{name}</span>
      <span className="font-semibold">{model}</span>
      <span className="truncate text-low">{about}</span>
    </div>
  )
}

function ModeCard({ mode, onMode }) {
  const gaming = mode.mode === 'gaming'
  const how = mode.switching ? 'switching…' : `${gaming ? 'Gaming' : 'Normal'} · ${mode.auto ? 'Auto' : 'Manual'}`

  return (
    <Card title="Model and mode" note={how} delay={6} className="flex flex-[1.35] flex-col gap-3">
      <div className="flex gap-1 rounded-2xl bg-well p-1">
        {MODE_BUTTONS.map((b) => (
          <button
            key={b.id}
            onClick={() => onMode(b.id)}
            className={`press h-11 flex-1 rounded-xl text-sm font-semibold transition-colors duration-300 ${mode.requested === b.id ? 'on-accent bg-accent text-accent-ink' : 'text-low'}`}
          >
            {b.label}
          </button>
        ))}
      </div>
      <ModelRow name="Normal" model={mode.models?.normal} about="chat and screen vision" active={!gaming} dot="bg-accent-text" />
      <ModelRow name="Gaming" model={mode.models?.gaming} about="leaves VRAM free for the game" active={gaming} dot="bg-amber-400" />
      {mode.game && <p className="text-sm text-mid">Game running: {mode.game}</p>}
      {mode.missing_models?.length > 0 && (
        <p className="text-sm text-amber-300">Missing on the PC. Run: {mode.pull_commands.join(', ')}</p>
      )}
    </Card>
  )
}

function Row({ label, value }) {
  return (
    <div className="flex min-h-9 items-center justify-between gap-3 text-sm">
      <span className="text-low">{label}</span>
      <span className="truncate">{value}</span>
    </div>
  )
}

function SystemScreen({ t, history, mode, onMode, host }) {
  if (!t) return null

  const gb = (used, total) => (used == null ? '' : `${used.toFixed(1)} / ${Math.round(total)} GB`)
  const temp = t.gpu?.temperature_c

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="reveal">
        <h1 className="font-display text-4xl font-medium">System</h1>
        <p className="mt-1 text-sm text-low">Your PC · up {t.system_uptime}</p>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-4 gap-3">
        <StatCard label="CPU" value={t.cpu_percent} detail="load" values={history.map((h) => h.cpu_percent)} delay={2} />
        <StatCard label="GPU" value={t.gpu_percent} detail={temp != null ? `${temp}°C` : ''} values={history.map((h) => h.gpu_percent)} delay={3} />
        <StatCard label="RAM" value={t.ram_percent} detail={gb(t.ram_used_gb, t.ram_total_gb)} values={history.map((h) => h.ram_percent)} delay={4} />
        <StatCard label="VRAM" value={t.vram_percent} detail={gb(t.gpu?.vram_used_gb, t.gpu?.vram_total_gb)} values={history.map((h) => h.vram_percent)} delay={5} />
      </div>

      <div className="flex gap-3">
        {mode && <ModeCard mode={mode} onMode={onMode} />}
        <Card title="Connection" delay={7} className="flex-1">
          <Row label="PC address" value={host} />
          <Row label="Graphics card" value={t.gpu?.name ?? 'Not found'} />
          <Row label="Kageon running for" value={t.server_uptime} />
          <Row label="Always-on display" value="after 60 s idle" />
        </Card>
      </div>
    </div>
  )
}

export default SystemScreen