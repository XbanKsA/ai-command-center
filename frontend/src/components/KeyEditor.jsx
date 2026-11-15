import { useEffect, useState } from 'react'

const KINDS = [
  { id: 'app', label: 'PC app' },
  { id: 'website', label: 'Website' },
  { id: 'command', label: 'KAGEON command' },
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

function KeyEditor({ initial, apps, onSearchApps, onSave, onDelete, onCancel }) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [kind, setKind] = useState(kindOf(initial))
  const [value, setValue] = useState(valueOf(initial))

  // search the PC's apps 250 ms after you stop typing
  useEffect(() => {
    if (kind !== 'app' || !value) return
    const timer = setTimeout(() => onSearchApps(value), 250)
    return () => clearTimeout(timer)
  }, [kind, value, onSearchApps])

  function save() {
    const subtitle = { app: 'App', website: 'Website', command: 'KAGEON' }[kind]
    let action
    if (kind === 'command') action = { type: 'ask', text: value }
    else if (kind === 'website') action = { type: 'launch', target: value.startsWith('http') ? value : `https://${value}` }
    else action = { type: 'launch', target: value }
    onSave({ title: title || value, subtitle, action })
  }

  const label = { app: 'APP ON YOUR PC', website: 'WEBSITE ADDRESS', command: 'WHAT TO SAY TO KAGEON' }[kind]
  const placeholder = { app: 'Start typing, e.g. steam', website: 'youtube.com', command: 'e.g. gaming time' }[kind]

  return (
    <div className="fixed inset-0 z-10 flex items-center justify-center bg-black/80">
      <div className="w-[640px] flex flex-col gap-5 rounded-3xl border border-slate-800 bg-slate-950 p-8">
        <h2 className="text-2xl font-semibold">{initial ? 'Edit key' : 'New key'}</h2>

        <label className="flex flex-col gap-2">
          <span className="text-xs tracking-widest text-slate-400">TITLE</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Steam"
            className="h-12 rounded-xl border border-slate-700 bg-black px-4 outline-none focus:border-cyan-400"
          />
        </label>

        <div className="flex gap-2">
          {KINDS.map((k) => (
            <button
              key={k.id}
              onClick={() => setKind(k.id)}
              className={`h-11 flex-1 rounded-xl border ${kind === k.id ? 'border-cyan-400 bg-cyan-400/10' : 'border-slate-700 text-slate-400'}`}
            >
              {k.label}
            </button>
          ))}
        </div>

        <label className="flex flex-col gap-2">
          <span className="text-xs tracking-widest text-slate-400">{label}</span>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={placeholder}
            className="h-12 rounded-xl border border-slate-700 bg-black px-4 outline-none focus:border-cyan-400"
          />
        </label>

        {kind === 'app' && value && apps.length > 0 && (
          <div className="flex max-h-48 flex-col overflow-y-auto rounded-xl border border-slate-800">
            {apps.map((a) => (
              <button
                key={a.name + a.target}
                onClick={() => { setValue(a.name); if (!title) setTitle(a.name) }}
                className="flex h-11 shrink-0 items-center justify-between px-4 text-left hover:bg-slate-900"
              >
                <span>{a.name}</span>
                <span className="text-xs text-slate-500">{APP_SOURCE[a.kind] ?? a.kind}</span>
              </button>
            ))}
          </div>
        )}

        <div className="mt-2 flex justify-between">
          {initial ? (
            <button onClick={onDelete} className="h-12 rounded-xl border border-red-900 px-5 text-red-300">Delete</button>
          ) : (
            <span />
          )}
          <div className="flex gap-3">
            <button onClick={onCancel} className="h-12 rounded-xl border border-slate-700 px-6">Cancel</button>
            <button onClick={save} disabled={!value} className="h-12 rounded-xl bg-cyan-400 px-6 font-bold text-black disabled:opacity-30">Save</button>
          </div>
        </div>
      </div>
    </div>
  )
}

export default KeyEditor