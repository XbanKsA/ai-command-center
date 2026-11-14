import { useNow } from '../useNow'

function Clock() {
  const now = useNow()
  return (
    <span className="font-mono text-3xl">
      {now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })}
    </span>
  )
}

export default Clock