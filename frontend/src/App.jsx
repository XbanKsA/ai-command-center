import ReplyToast from './components/ReplyToast'
import { useJarvis } from './useJarvis'
import PinScreen from './components/PinScreen'
import Stats from './components/Stats'
import Clock from './components/Clock'
import Key from './components/Key'

const keys = [
  { id: 1, title: 'Steam', subtitle: 'App', action: { type: 'launch', target: 'steam' } },
  { id: 2, title: 'Discord', subtitle: 'App', action: { type: 'launch', target: 'discord' } },
  { id: 3, title: 'YouTube', subtitle: 'Website', action: { type: 'launch', target: 'https://www.youtube.com' } },
  { id: 4, title: 'Spotify', subtitle: 'App', action: { type: 'launch', target: 'spotify' } },
  { id: 5, title: 'Deadlock', subtitle: 'Game', action: { type: 'launch', target: 'deadlock' } },
  { id: 6, title: 'Gaming time', subtitle: 'Routine', action: { type: 'ask', text: 'gaming time' } },
  { id: 7, title: 'VS Code', subtitle: 'App', action: { type: 'launch', target: 'visual studio code' } },
  { id: 8, title: 'Which model?', subtitle: 'Ask JARVIS', action: { type: 'ask', text: 'which model are you using' } },
]


const TOTAL_SLOTS = 15

function App() {
    const { status, telemetry, error, sendPin, launch, ask, confirm, reply, clearReply } = useJarvis()
    function runKey(k) {
      if (k.action.type === 'launch') launch(k.action.target)
      else ask(k.action.text)
    }

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
            onPress={() => runKey(k)}
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
      <ReplyToast reply={reply} onClose={clearReply} onConfirm={confirm} />
    </div>
  )
}

export default App