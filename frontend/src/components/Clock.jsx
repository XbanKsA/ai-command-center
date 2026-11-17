import { useNow } from '../useNow'

function Clock() {
  const now = useNow()
  return (
    <span className="ml-1.5 font-display text-xl tabular-nums">
      {now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
    </span>
  )
}

export default Clock