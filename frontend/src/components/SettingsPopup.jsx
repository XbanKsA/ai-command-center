import { useCallback, useEffect, useState } from 'react'
import { Bell, Wifi, X } from 'lucide-react'
import ConnectionDiagram from './ConnectionDiagram'
import Toggle from './Toggle'
import { KAGEON_KINDS } from '../useNotifications'

const TABS = [
  { id: 'connection', label: 'Connection', icon: Wifi },
  { id: 'notifications', label: 'Notifications', icon: Bell },
]

const wait = (ms) => new Promise((r) => setTimeout(r, ms))

const PC_PROBLEM = {
  starting: 'Checking with the PC…',
  denied: 'Windows said no. On the PC, allow apps to access your notifications, then turn this off and on.',
  unavailable: "This PC can't share its notifications. Run setup.bat again on the PC.",
}

function PcApps({ pc, pcStatus, onPcChange, onPcApp }) {
  if (pcStatus.status !== 'ok') {
    return <p className="border-t border-line py-3 text-sm text-amber-300">{PC_PROBLEM[pcStatus.status] ?? PC_PROBLEM.starting}</p>
  }
  // apps the PC has seen, plus any you picked that haven't shown up since Kageon started
  const apps = [...new Set([...pcStatus.apps, ...pc.apps])]

  return (
    <div className="reveal border-t border-line py-3">
      <p className="mb-2.5 text-sm text-low">
        {apps.length ? 'Pick the apps to show:' : 'No apps yet. Apps appear here once they show a notification on the PC.'}
      </p>
      <div className="flex flex-wrap gap-2">
        {apps.map((app) => {
          const on = pc.apps.includes(app)
          return (
            <button
              key={app}
              aria-pressed={on}
              onClick={() => onPcApp(app)}
              className={`press h-11 rounded-full border px-4 text-sm font-medium transition-colors duration-300 ${on ? 'border-accent-line bg-accent-soft text-accent-text' : 'border-line text-low'}`}
            >
              {app}
            </button>
          )
        })}
      </div>
      <div className="mt-3 flex min-h-13 items-center justify-between gap-4 border-t border-line py-1">
        <div>
          <p className="font-medium">Hide message text on the always-on display</p>
          <p className="text-sm text-low">Shows only the app name and how many.</p>
        </div>
        <Toggle on={pc.hideOnAod} onChange={(on) => onPcChange({ hideOnAod: on })} label="Hide message text on the always-on display" />
      </div>
    </div>
  )
}

function SettingsPopup({ host, coreVersion, onTest, onForget, onClose, kinds, onToggleKind, pc, pcStatus, onPcChange, onPcApp }) {
  const [tab, setTab] = useState('connection')
  const [link, setLink] = useState('trying')
  const [ms, setMs] = useState(null)
  const [confirming, setConfirming] = useState(false)

  // ping the PC, and keep "trying" on screen for at least 0.8 s so you can see it happen
  const test = useCallback(async () => {
    const [rtt] = await Promise.all([onTest(), wait(800)])
    setMs(rtt)
    setLink(rtt === null ? 'failed' : 'on')
  }, [onTest])

  // test once when the popup opens (it starts in 'trying')
  useEffect(() => {
    test()
  }, [test])

  function testAgain() {
    setLink('trying')
    test()
  }

  const status = {
    trying: 'Checking the connection…',
    on: `Connected over Wi-Fi · ${ms} ms`,
    failed: 'No answer from the PC. Tap the Wi-Fi point to try again.',
  }[link]

  return (
    <div onClick={onClose} className="fade-in fixed inset-0 z-20 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="Settings"
        className="rise relative flex h-[35rem] w-[53.75rem] overflow-hidden rounded-3xl border border-line bg-card-solid shadow-2xl"
      >
        <nav className="flex w-54 shrink-0 flex-col gap-1.5 border-r border-line bg-well px-3.5 pb-4.5 pt-6">
          <h2 className="mb-3.5 ml-2 font-display text-2xl font-medium">Settings</h2>
          {TABS.map((t) => {
            const Icon = t.icon
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`press flex h-12 items-center gap-2.5 rounded-xl px-3 text-left font-medium ${tab === t.id ? 'bg-accent-soft text-accent-text' : 'text-mid'}`}
              >
                <Icon className="h-5 w-5" strokeWidth={1.75} />
                {t.label}
              </button>
            )
          })}
          <div className="flex-1" />
          <p className="px-2 text-xs leading-relaxed text-low">
            Tablet app {__APP_VERSION__}
            <br />
            Kageon Core {coreVersion || '—'}
          </p>
        </nav>

        <button onClick={onClose} aria-label="Close settings" className="press absolute right-3.5 top-3.5 z-5 flex h-11 w-11 items-center justify-center rounded-xl bg-card-solid text-low">
          <X className="h-5 w-5" strokeWidth={1.75} />
        </button>

        <div className="relative min-w-0 flex-1 overflow-y-auto px-6.5 py-6">
          {tab === 'connection' && (
            <div className="reveal flex flex-col">
              <h3 className="text-lg font-semibold">Connection</h3>
              <p role="status" className={`mt-1 min-h-5 text-sm ${link === 'failed' ? 'text-red-400' : 'text-low'}`}>
                {status}
              </p>

              <div className="my-4">
                <ConnectionDiagram state={link} onTest={testAgain} />
              </div>

              <div className="flex min-h-14 items-center justify-between gap-4 border-t border-line py-2">
                <div>
                  <p className="font-medium">This PC</p>
                  <p className="text-sm text-low">{host} · paired with a PIN</p>
                </div>
                <button
                  onClick={() => setConfirming(true)}
                  className="press on-accent h-11 shrink-0 rounded-xl bg-red-600 px-4 text-sm font-semibold text-white"
                >
                  Forget this PC
                </button>
              </div>
            </div>
          )}

          {tab === 'notifications' && (
            <div className="reveal flex flex-col">
              <h3 className="text-lg font-semibold">Notifications</h3>
              <p className="mb-2 mt-1 text-sm text-low">They show under the bell at the top, and the important ones pop up for a few seconds.</p>
              <p className="mb-1 mt-3 text-xs font-semibold text-low">On this tablet, from Kageon</p>
              {KAGEON_KINDS.map((k) => (
                <div key={k.id} className="flex min-h-13 items-center justify-between gap-4 border-t border-line py-1">
                  <span className="font-medium">{k.label}</span>
                  <Toggle on={kinds[k.id]} onChange={() => onToggleKind(k.id)} label={k.label} />
                </div>
              ))}

              <p className="mb-1 mt-5 text-xs font-semibold text-low">From your PC</p>
              <div className="flex min-h-13 items-center justify-between gap-4 border-t border-line py-1">
                <div>
                  <p className="font-medium">Show PC notifications</p>
                  <p className="text-sm text-low">Off until you turn it on. Only the apps you pick leave the PC.</p>
                </div>
                <Toggle on={pc.enabled} onChange={(on) => onPcChange({ enabled: on })} label="Show PC notifications" />
              </div>
              {pc.enabled && <PcApps pc={pc} pcStatus={pcStatus} onPcChange={onPcChange} onPcApp={onPcApp} />}
            </div>
          )}
        </div>

        {confirming && (
          <div className="fade-in absolute inset-0 z-10 flex items-center justify-center bg-black/55">
            <div role="alertdialog" aria-label="Forget this PC?" className="rise w-[25rem] rounded-2xl border border-line bg-card-solid p-6 shadow-2xl">
              <h3 className="font-display text-xl font-medium">Forget this PC?</h3>
              <p className="mb-5 mt-2 text-sm text-mid">
                The tablet will disconnect, and you'll need the PIN from the PC to pair again. Your keys and theme stay on this tablet.
              </p>
              <div className="flex gap-2.5">
                <button onClick={() => setConfirming(false)} className="press h-11 flex-1 rounded-xl border border-line text-sm font-semibold">
                  Cancel
                </button>
                <button onClick={onForget} className="press on-accent h-11 flex-1 rounded-xl bg-red-600 text-sm font-semibold text-white">
                  Forget this PC
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default SettingsPopup