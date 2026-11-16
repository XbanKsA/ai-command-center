import { AppWindow, Globe, Sparkles } from 'lucide-react'

// pick the icon from what the key does
function iconFor(action) {
  if (action.type === 'ask') return Sparkles // a Kageon command
  return action.target.startsWith('http') ? Globe : AppWindow // a website or an app
}

function Key({ title, subtitle, action, index, editing, onPress }) {
  const Icon = iconFor(action)

  return (
    <button
      onClick={onPress}
      style={{ '--i': index }}
      className={`press reveal flex min-w-0 flex-col items-start justify-between rounded-2xl border bg-card p-4 text-left ${editing ? 'border-dashed border-accent-line' : 'border-line'}`}
    >
      <span className="flex h-10.5 w-10.5 items-center justify-center rounded-xl bg-accent-soft text-accent-text">
        <Icon className="h-5 w-5" strokeWidth={1.75} />
      </span>
      <span className="max-w-full">
        <span className="line-clamp-2 font-semibold leading-tight">{title}</span>
        <span className="mt-0.5 block text-xs text-low">{subtitle}</span>
      </span>
    </button>
  )
}

export default Key