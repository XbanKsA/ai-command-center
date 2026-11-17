import { Monitor, Tablet, Usb, Wifi } from 'lucide-react'

function Device({ icon: Icon, label }) {
  return (
    <div className="flex w-20 shrink-0 flex-col items-center gap-1.5 text-xs text-low">
      <Icon className="h-14 w-14 text-mid" strokeWidth={1.25} />
      {label}
    </div>
  )
}

// state: 'trying' | 'on' | 'failed'. Tapping the Wi-Fi point tests the connection again.
function ConnectionDiagram({ state, onTest }) {
  return (
    <div className="flex items-center gap-3.5 rounded-2xl border border-line bg-card px-5 pb-4 pt-5.5">
      <Device icon={Tablet} label="Tablet" />

      <div className="flex min-w-0 flex-1 flex-col gap-3.5">
        <div className={`link ${state}`}>
          <span className="link-wire" />
          <span className="link-dot to-pc" />
          <span className="link-dot to-tablet" />
          <span className="link-spin" />
          <button onClick={onTest} disabled={state === 'trying'} aria-label="Test the Wi-Fi connection" className="link-point press">
            <Wifi className="h-5 w-5" strokeWidth={1.75} />
          </button>
          <span className="link-label">Wi-Fi</span>
        </div>

        <div className="link off">
          <span className="link-wire" />
          <button disabled aria-label="USB cable (coming later)" className="link-point">
            <Usb className="h-5 w-5" strokeWidth={1.75} />
          </button>
          <span className="link-label">USB cable · later</span>
        </div>
      </div>

      <Device icon={Monitor} label="PC" />
    </div>
  )
}

export default ConnectionDiagram