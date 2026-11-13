import { useJarvis } from './useJarvis'
import PinScreen from './components/PinScreen'
import Stats from './components/Stats'
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
    const { status, telemetry, error, sendPin } = useJarvis()

  if (status === 'need_pin') return <PinScreen onSubmit={sendPin} error={error} />

  if (status === 'offline' || status === 'connecting') {
    return (
      <div className="h-screen bg-black flex items-center justify-center">
        <div dir="rtl" className="rounded-3xl border border-red-900 bg-red-950/40 p-10 text-center">
          <h1 className="text-3xl font-bold text-red-300">تعذر الاتصال بالسيرفر! ⚠️</h1>
          <p className="mt-3 text-lg text-red-100/80">تأكد أن كلا الجهازين متصلان بنفس شبكة الـ Wi-Fi.</p>
        </div>
      </div>
    )
  }
  const emptySlots = TOTAL_SLOTS - keys.length

  return (
    <div className="h-screen bg-black text-white p-6 flex flex-col gap-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-[0.3em] text-cyan-400">JARVIS</h1>
           <Stats t={telemetry} />
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