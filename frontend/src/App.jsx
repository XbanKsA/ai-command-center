import { useCallback, useState } from 'react'
import { useKeys } from './useKeys'
import KeyEditor from './components/KeyEditor'
import ReplyToast from './components/ReplyToast'
import { useKageon } from './useKageon'
import PinScreen from './components/PinScreen'
import Key from './components/Key'
import { useIdle } from './useIdle'
import AlwaysOn from './components/AlwaysOn'
import ChatScreen from './components/ChatScreen'
import ConnectScreen from './components/ConnectScreen'
import Backdrop from './components/Backdrop'
import Rail from './components/Rail'
import TopBar from './components/TopBar'
import { SCREENS } from './screens'
import PcCard from './components/PcCard'
import MediaCard from './components/MediaCard'
import TalkCard from './components/TalkCard'
import { Plus, Pencil } from 'lucide-react'
import DeckTabs from './components/DeckTabs'

const AOD_AFTER_MS = 60 * 1000 // 60 seconds

function App() {
  const [host, setHost] = useState(() => localStorage.getItem('kageon_host'))

  const saveHost = useCallback((h) => {
    localStorage.setItem('kageon_host', h)
    setHost(h)
  }, [])

  function forgetHost() {
    localStorage.removeItem('kageon_host')
    setHost(null)
  }
        const { status, telemetry, error, sendPin, launch, ask, confirm, reply, clearReply, apps, searchApps, mode, changeMode, messages, sendVoice } = useKageon(host)
    function runKey(k) {
      if (k.action.type === 'launch') launch(k.action.target)
      else ask(k.action.text)
    }
    function pressSlot(i) {
      const k = slots[i]
      if (!k || editMode) setEditing(i) // empty slot or edit mode -> open the editor
      else runKey(k)                   // normal key -> run it
    }
    const { decks, saveKey, deleteKey } = useKeys()
    const [page, setPage] = useState(0)
    const slots = decks[page].slots
    const used = slots.filter(Boolean).length
    const firstEmpty = slots.findIndex((k) => !k)
    const [editMode, setEditMode] = useState(false)
    const [editing, setEditing] = useState(null)
    const [chatOpen, setChatOpen] = useState(false)
    const [screen, setScreen] = useState('deck')
    const title = SCREENS.find((s) => s.id === screen).label
    const lastReply = messages.findLast((m) => m.from === 'kageon')?.text
    function openScreen(id) {
      if (id === 'assistant') setChatOpen(true) // the old chat, until we build the new Assistant screen
      else setScreen(id)
    }
    const idle = useIdle(AOD_AFTER_MS)
    if (!host) return <ConnectScreen onFound={saveHost} />

  if (status === 'need_pin') return <PinScreen onSubmit={sendPin} error={error} />

  if (status === 'offline' || status === 'connecting') {
    return (
      <div className="h-screen bg-black flex flex-col gap-6 items-center justify-center">
        <div dir="rtl" className="rounded-3xl border border-red-900 bg-red-950/40 p-10 text-center">
          <h1 className="text-3xl font-bold text-red-300">تعذر الاتصال بالسيرفر! ⚠️</h1>
          <p className="mt-3 text-lg text-red-100/80">تأكد أن كلا الجهازين متصلان بنفس شبكة الـ Wi-Fi.</p>
        </div>
        <button
          onClick={forgetHost}
          className="rounded-xl border border-cyan-800 px-6 py-3 text-cyan-300"
        >
          Search again 🔍
        </button>
      </div>
    )
  }


  return (
    <div className="relative isolate flex h-screen gap-4 overflow-hidden bg-page p-4 font-sans text-hi">
      <Backdrop />
      <Rail screen={screen} onChange={openScreen} />

      <div className="flex min-w-0 flex-1 flex-col gap-4">
        <TopBar title={title} mode={mode} onMode={changeMode} onAsk={() => setChatOpen(true)} />

                {screen === 'deck' && (
          <div className="flex min-h-0 flex-1 flex-col gap-3">
            <div className="flex items-end justify-between">
              <div className="reveal">
                <h1 className="font-display text-4xl font-medium">Deck</h1>
                <p className="mt-1 text-sm text-low">
                  {editMode ? 'Editing: tap a key to change it' : `${used} keys on this page · tap one to run it`}
                </p>
              </div>
              <div className="reveal flex gap-2.5">
                <button
                  onClick={() => setEditMode(!editMode)}
                  className={`press flex h-11 items-center gap-2 rounded-xl border px-4 text-sm font-semibold ${editMode ? 'border-accent-line bg-accent-soft text-accent-text' : 'border-line bg-card'}`}
                >
                  <Pencil className="h-4 w-4" strokeWidth={1.75} />
                  {editMode ? 'Done' : 'Edit'}
                </button>
                <button
                  onClick={() => setEditing(firstEmpty)}
                  disabled={firstEmpty === -1}
                  className="press on-accent flex h-11 items-center gap-2 rounded-xl bg-accent px-4 text-sm font-semibold text-accent-ink disabled:opacity-40"
                >
                  <Plus className="h-4 w-4" strokeWidth={1.75} />
                  New key
                </button>
              </div>
            </div>

            <DeckTabs decks={decks} page={page} onChange={setPage} />

            <div className="flex min-h-0 flex-1 gap-4">
               <main key={page} className="grid min-w-0 flex-1 grid-cols-5 grid-rows-3 gap-3">
                {slots.map((k, i) =>
                  k ? (
                    <Key
                      key={i}
                      index={i}
                      title={k.title}
                      subtitle={k.subtitle}
                      action={k.action}
                      editing={editMode}
                      onPress={() => pressSlot(i)}
                    />
                  ) : (
                    <button
                      key={i}
                      onClick={() => pressSlot(i)}
                      style={{ '--i': i }}
                      className="press reveal flex items-center justify-center gap-2 rounded-2xl border border-dashed border-line text-sm text-low"
                    >
                      <Plus className="h-5 w-5" strokeWidth={1.75} />
                      Add key
                    </button>
                  )
                )}
              </main>

              <aside className="flex w-68 flex-col gap-3">
                <PcCard t={telemetry} />
                <MediaCard onSay={ask} />
                <TalkCard last={lastReply} onVoice={sendVoice} />
              </aside>
            </div>
          </div>
        )}

        {screen !== 'deck' && (
          <div className="flex flex-1 items-center justify-center text-low">
            The {title} screen comes in a later lesson
          </div>
        )}
      </div>   <ReplyToast reply={reply} onClose={clearReply} onConfirm={confirm} />
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
          onSave={(k) => { saveKey(page, editing, k); setEditing(null) }}
          onDelete={() => { deleteKey(page, editing); setEditing(null) }}
          onCancel={() => setEditing(null)}
        />
      )}
    </div>
  )
}

export default App