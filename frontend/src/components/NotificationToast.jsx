import { useEffect } from 'react'
import NotificationIcon from './NotificationIcon'

// a small pop-up under the bell for a few seconds. Tapping it opens the full list.
function NotificationToast({ n, onClose, onOpen }) {
  useEffect(() => {
    if (!n) return
    const timer = setTimeout(onClose, 5000)
    return () => clearTimeout(timer)
  }, [n, onClose])

  if (!n) return null

  return (
    <button
      key={n.id}
      onClick={onOpen}
      className="reveal fixed right-4 top-21 z-14 flex w-[23.75rem] items-start gap-3 rounded-2xl border border-accent-line bg-card-solid p-3 text-left shadow-2xl"
    >
      <NotificationIcon kind={n.kind} />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{n.title}</span>
        {n.text && <span className="line-clamp-2 block text-sm text-mid">{n.text}</span>}
      </span>
    </button>
  )
}

export default NotificationToast