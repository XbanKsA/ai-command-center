import Clock from './components/Clock'
import Key from './components/Key'

const keys = [
  { id: 1, title: 'Steam', subtitle: 'App' },
  { id: 2, title: 'Discord', subtitle: 'App' },
  { id: 3, title: 'YouTube', subtitle: 'Website' },
  { id: 4, title: 'Spotify', subtitle: 'App' },
  { id: 5, title: 'Deadlock', subtitle: 'Game' },
  { id: 6, title: 'Gaming time', subtitle: 'Routine' },
  { id: 7, title: 'VS Code', subtitle: 'App' },
  { id: 8, title: 'Lock PC', subtitle: 'System' },
]

const TOTAL_SLOTS = 15

function App() {
  const emptySlots = TOTAL_SLOTS - keys.length

  return (
    <div className="h-screen bg-black text-white p-6 flex flex-col gap-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-[0.3em] text-cyan-400">JARVIS</h1>
           <Clock />
      </header>

      <main className="grid grid-cols-5 grid-rows-3 gap-4 flex-1">
        {keys.map((k) => (
          <Key
            key={k.id}
            title={k.title}
            subtitle={k.subtitle}
            onPress={() => alert(`You pressed ${k.title}`)}
          />
        ))}

        {Array.from({ length: emptySlots }).map((_, i) => (
          <button
            key={`empty-${i}`}
            className="rounded-2xl border-2 border-dashed border-slate-800 text-slate-500 hover:border-slate-600"
          >
            + Add key
          </button>
        ))}
      </main>
    </div>
  )
}

export default App