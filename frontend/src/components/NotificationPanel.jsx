import NotificationIcon from './NotificationIcon'
import { useNow } from '../useNow'

function ago(time, now) {
  const s = Math.round((now - time) / 1000)
  if (s < 60) return 'now'
  if (s < 3600) return `${Math.round(s / 60)} min`
  return `${Math.round(s / 3600)} h`
}

function NotificationPanel({ list, onClear, onClose }) {
  const now = useNow()

  return (
    <>
      {/* an invisible layer behind the panel: tapping anywhere else closes it */}
      <button aria-label="Close notifications" onClick={onClose} className="fixed inset-0 z-15 cursor-default" />
      <div
        role="dialog"
        aria-label="Notifications"
        className="rise fixed right-4 top-21 z-16 flex max-h-[70vh] w-[23.75rem] flex-col rounded-2xl border border-line bg-card-solid p-2.5 shadow-2xl"
      >
        <div className="flex items-center justify-between py-1 pl-2.5">
          <h2 className="text-sm font-semibold">Notifications</h2>
          <button onClick={onClear} disabled={list.length === 0} className="press h-10 rounded-xl px-3 text-sm text-low disabled:opacity-40">
            Clear all
          </button>
        </div>
        <div className="min-h-0 overflow-y-auto">
          {list.length === 0 && <p className="py-6 text-center text-sm text-low">Nothing new</p>}
          {list.map((n) => (
            <div key={n.id} className="flex items-start gap-3 rounded-xl p-2.5">
              <NotificationIcon kind={n.kind} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{n.title}</p>
                {n.text && <p className="line-clamp-2 text-sm text-mid">{n.text}</p>}
              </div>
              <span className="shrink-0 text-xs text-low">{ago(n.time, now)}</span>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

export default NotificationPanel