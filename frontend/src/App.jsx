import { useState } from 'react'
import { useKeys } from './useKeys'
import KeyEditor from './components/KeyEditor'
import ReplyToast from './components/ReplyToast'
import { useJarvis } from './useJarvis'
import PinScreen from './components/PinScreen'
import Stats from './components/Stats'
import Clock from './components/Clock'
import Key from './components/Key'
import ModeToggle from './components/ModeToggle'
import { useIdle } from './useIdle'
import AlwaysOn from './components/AlwaysOn'
import ChatScreen from './components/ChatScreen'

const AOD_AFTER_MS = 60 * 1000 // 60 seconds

function App() {
        const { status, telemetry, error, sendPin, launch, ask, confirm, reply, clearReply, apps, searchApps, mode, changeMode, messages, sendVoice } = useJarvis()
    function runKey(k) {
      if (k.action.type === 'launch') launch(k.action.target)
      else ask(k.action.text)
    }
    function pressSlot(i) {
      const k = slots[i]
      if (!k || editMode) setEditing(i) // empty slot or edit mode -> open the editor
      else runKey(k)                   // normal key -> run it
    }
    const { slots, saveKey, deleteKey } = useKeys()
    const [editMode, setEditMode] = useState(false)
    const [editing, setEditing] = useState(null)
    const [chatOpen, setChatOpen] = useState(false)
    const idle = useIdle(AOD_AFTER_MS)

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


  return (
    <div className="h-screen bg-black text-white p-6 flex flex-col gap-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-[0.3em] text-cyan-400">JARVIS</h1>
           <Stats t={telemetry} />
                      <div className="flex items-center gap-4">
                        <ModeToggle mode={mode} onChange={changeMode} />
                                     <button onClick={() => setChatOpen(true)} className="h-10 rounded-xl bg-cyan-400 px-4 font-bold text-black">
               Ask JARVIS
             </button>
             <button
               onClick={() => setEditMode(!editMode)}
               className={`h-10 rounded-xl border px-4 ${editMode ? 'border-amber-400 bg-amber-400 font-bold text-black' : 'border-slate-700 text-slate-300'}`}
             >
               {editMode ? 'Done' : 'Edit'}
             </button>
             <Clock />
           </div>
      </header>

      <main className="grid grid-cols-5 grid-rows-3 gap-4 flex-1">
        {slots.map((k, i) =>
          k ? (
            <Key key={i} title={k.title} subtitle={k.subtitle} onPress={() => pressSlot(i)} />
          ) : (
            <button
              key={i}
              onClick={() => pressSlot(i)}
              className="rounded-2xl border-2 border-dashed border-slate-800 text-slate-500 hover:border-slate-600"
            >
              + Add key
            </button>
          )
        )}
      </main>
      <ReplyToast reply={reply} onClose={clearReply} onConfirm={confirm} />
            {chatOpen && (
        <ChatScreen
          messages={messages}
          onSend={ask}
          onVoice={sendVoice}
          onConfirm={confirm}
          onClose={() => setChatOpen(false)}
        />
      )}
      {idle && <AlwaysOn telemetry={telemetry} mode={mode} />}
            {editing !== null && (
        <KeyEditor
          initial={slots[editing]}
          apps={apps}
          onSearchApps={searchApps}
          onSave={(k) => { saveKey(editing, k); setEditing(null) }}
          onDelete={() => { deleteKey(editing); setEditing(null) }}
          onCancel={() => setEditing(null)}
        />
      )}
    </div>
  )
}

export default App