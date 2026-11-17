import { useEffect, useState } from 'react'
import { AppWindow, Globe, Sparkles } from 'lucide-react'

const KINDS = [
  { id: 'app', label: 'PC app', icon: AppWindow },
  { id: 'website', label: 'Website', icon: Globe },
  { id: 'command', label: 'Kageon command', icon: Sparkles },
]

const APP_SOURCE = { startapp: 'Start Menu', shortcut: 'Shortcut', builtin: 'Windows' }

function kindOf(key) {
  if (!key) return 'app'
  if (key.action.type === 'ask') return 'command'
  return key.action.target.startsWith('http') ? 'website' : 'app'
}

function valueOf(key) {
  if (!key) return ''
  return key.action.type === 'ask' ? key.action.text : key.action.target
}

const field = 'h-12 w-full rounded-xl border border-line bg-well px-4 outline-none placeholder:text-low focus:border-accent-line'

function KeyEditor({ initial, apps, onSearchApps, onSave, onDelete, onCancel }) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [kind, setKind] = useState(kindOf(initial))
  const [value, setValue] = useState(valueOf(initial))
  const [confirmDelete, setConfirmDelete] = useState(false)

  // search the PC's apps 250 ms after you stop typing
  useEffect(() => {
    if (kind !== 'app' || !value) return
    const timer = setTimeout(() => onSearchApps(value), 250)
    return () => clearTimeout(timer)
  }, [kind, value, onSearchApps])

  function save() {
    const subtitle = { app: 'App', website: 'Website', command: 'Kageon' }[kind]
    let action
    if (kind === 'command') action = { type: 'ask', text: value }
    else if (kind === 'website') action = { type: 'launch', target: value.startsWith('http') ? value : `https://${value}` }
    else action = { type: 'launch', target: value }
    onSave({ title: title || value, subtitle, action })
  }

  const label = { app: 'App on your PC', website: 'Website address', command: 'What to say to Kageon' }[kind]
  const placeholder = { app: 'Start typing, e.g. steam', website: 'youtube.com', command: 'e.g. gaming time' }[kind]

  return (
    <div onClick={onCancel} className="fade-in fixed inset-0 z-20 flex items-center justify-center bg-black/50 backdrop-blur-sm">
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={initial ? 'Edit key' : 'New key'}
        className="rise flex w-[37.5rem] flex-col gap-4 rounded-3xl border border-line bg-card-solid p-6.5 shadow-2xl"
      >
        <h2 className="font-display text-2xl font-medium">{initial ? 'Edit key' : 'New key'}</h2>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-low">Title</span>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Steam" className={field} />
        </label>

        <div className="flex gap-1 rounded-2xl bg-well p-1">
          {KINDS.map((k) => {
            const Icon = k.icon
            return (
              <button
                key={k.id}
                onClick={() => setKind(k.id)}
                className={`press flex h-11 flex-1 items-center justify-center gap-2 rounded-xl text-sm font-semibold transition-colors duration-300 ${kind === k.id ? 'on-accent bg-accent text-accent-ink' : 'text-low'}`}
              >
                <Icon className="h-4 w-4" strokeWidth={1.75} />
                {k.label}
              </button>
            )
          })}
        </div>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold text-low">{label}</span>
          <input value={value} onChange={(e) => setValue(e.target.value)} placeholder={placeholder} className={field} />
        </label>

        {kind === 'app' && value && apps.length > 0 && (
          <div className="flex max-h-48 flex-col overflow-y-auto rounded-xl border border-line">
            {apps.map((a) => (
              <button
                key={a.name + a.target}
                onClick={() => { setValue(a.name); if (!title) setTitle(a.name) }}
                className="press flex h-11 shrink-0 items-center justify-between border-b border-line px-4 text-left text-sm last:border-b-0"
              >
                <span>{a.name}</span>
                <span className="text-xs text-low">{APP_SOURCE[a.kind] ?? a.kind}</span>
              </button>
            ))}
          </div>
        )}

        <div className="mt-1 flex items-center justify-between gap-3">
          {initial && !confirmDelete && (
            <button onClick={() => setConfirmDelete(true)} className="press h-11 rounded-xl border border-red-500/50 px-4 text-sm font-semibold text-red-400">
              Delete
            </button>
          )}
          {initial && confirmDelete && (
            <div className="reveal flex items-center gap-2">
              <span className="text-sm text-mid">Delete this key?</span>
              <button onClick={onDelete} className="press on-accent h-11 rounded-xl bg-red-600 px-4 text-sm font-semibold text-white">
                Delete
              </button>
              <button onClick={() => setConfirmDelete(false)} className="press h-11 rounded-xl border border-line px-4 text-sm font-semibold">
                Keep
              </button>
            </div>
          )}
          {!initial && <span />}

          {!confirmDelete && (
            <div className="flex gap-2.5">
              <button onClick={onCancel} className="press h-11 rounded-xl border border-line px-5 text-sm font-semibold">
                Cancel
              </button>
              <button
                onClick={save}
                disabled={!value}
                className="press on-accent h-11 min-w-28 rounded-xl bg-accent px-5 text-sm font-semibold text-accent-ink disabled:opacity-40"
              >
                Save
              </button>
            </div>
          )}  
        </div>
      </div>
    </div>
  )
}

export default KeyEditor