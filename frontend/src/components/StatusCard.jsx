// One line of status with a dot: pulsing while something is happening, amber when it needs you
function StatusCard({ busy, title, text, children }) {
  return (
    <div className="flex items-center gap-4 rounded-2xl border border-line bg-card p-4.5">
      <span className="relative flex h-11 w-11 shrink-0 items-center justify-center">
        {busy && <span className="absolute inset-1 animate-ping rounded-full bg-accent-text/40" />}
        <span className={`h-3.5 w-3.5 rounded-full ${busy ? 'bg-accent-text' : 'bg-amber-400'}`} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{title}</p>
        <p className="text-sm text-low">{text}</p>
      </div>
      {children}
    </div>
  )
}

export default StatusCard