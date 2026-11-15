import { useEffect, useRef, useState } from 'react'
import { useRecorder } from '../useRecorder'

const QUICK = ["What's on my screen?", 'Which model are you using?', 'What do you remember?', 'How hot is my GPU?']

function ChatScreen({ messages, onSend, onVoice, onConfirm, onClose }) {
  const [text, setText] = useState('')
  const [sending, setSending] = useState(false)
  const { recording, start, stop } = useRecorder()
  const bottomRef = useRef(null)

  // scroll to the newest message whenever the list changes
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function submit(e) {
    e.preventDefault() // stop the browser from reloading the page
    if (!text.trim()) return
    onSend(text.trim())
    setText('')
  }

  async function toggleMic() {
    if (!recording) {
      try {
        await start()
      } catch {
        alert('Microphone not available. Allow it in the browser and try again.')
      }
      return
    }
    const blob = await stop()
    setSending(true)
    await onVoice(blob)
    setSending(false)
  }

  return (
    <div className="fixed inset-0 z-10 flex flex-col gap-4 bg-black p-6 text-white">
      <header className="flex items-center gap-4">
        <button onClick={onClose} aria-label="Back" className="h-12 w-12 rounded-xl border border-slate-800 text-xl">←</button>
        <h2 className="text-2xl font-bold tracking-[0.3em] text-cyan-400">KAGEON</h2>
      </header>

      <div className="flex min-h-0 flex-1 gap-6">
        <div className="flex flex-1 flex-col gap-3 overflow-y-auto pr-2">
          {messages.length === 0 && <p className="m-auto text-slate-500">Ask me anything, or tap the mic.</p>}

          {messages.map((m) => (
            <div
              key={m.id}
              className={`max-w-[70%] rounded-2xl px-5 py-3 ${
                m.from === 'kageon' ? 'self-start border border-slate-800 bg-slate-950' : 'self-end bg-cyan-950'
              }`}
            >
              {m.from === 'pc' && <p className="mb-1 text-xs text-slate-400">Said on the PC</p>}
              <p className="text-lg">{m.text}</p>
              {m.pendingId && (
                <div className="mt-3 flex gap-2">
                  <button onClick={() => onConfirm(m.pendingId, true)} className="h-11 flex-1 rounded-xl bg-amber-500 font-bold text-black">Yes</button>
                  <button onClick={() => onConfirm(m.pendingId, false)} className="h-11 flex-1 rounded-xl border border-slate-600">No</button>
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        <aside className="flex w-64 flex-col gap-2">
          <span className="text-xs tracking-widest text-slate-500">QUICK COMMANDS</span>
          {QUICK.map((q) => (
            <button key={q} onClick={() => onSend(q)} className="h-12 rounded-xl border border-slate-800 bg-slate-950 px-4 text-left">
              {q}
            </button>
          ))}
        </aside>
      </div>

      <form onSubmit={submit} className="flex gap-3">
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Type to KAGEON…"
          className="h-14 flex-1 rounded-2xl border border-slate-800 bg-slate-950 px-5 text-lg outline-none focus:border-cyan-400"
        />
        <button type="submit" className="h-14 rounded-2xl border border-slate-700 px-6">Send</button>
        <button
          type="button"
          onClick={toggleMic}
          disabled={sending}
          className={`h-14 min-w-44 rounded-2xl px-6 font-bold disabled:opacity-40 ${recording ? 'animate-pulse bg-red-500' : 'bg-cyan-400 text-black'}`}
        >
          {sending ? 'Thinking…' : recording ? '■ Tap to send' : '🎤 Tap to talk'}
        </button>
      </form>
    </div>
  )
}

export default ChatScreen