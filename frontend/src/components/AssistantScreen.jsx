import { useEffect, useRef, useState } from 'react'
import { ArrowUp, Mic, Square } from 'lucide-react'
import Card from './Card'
import { useMic } from '../useMic'

const QUICK = ["What's on my screen?", 'Which model are you using?', 'What do you remember?', 'How hot is my GPU?']

function Bubble({ m, onConfirm }) {
  const mine = m.from !== 'kageon' // typed on the tablet, or said on the PC
  return (
    <div
      className={`reveal max-w-[68%] rounded-2xl border px-4 py-2.5 leading-relaxed ${mine ? 'self-end rounded-br-md border-accent-line bg-accent-soft' : 'self-start rounded-bl-md border-line bg-card'}`}
    >
      {m.from === 'pc' && <p className="mb-0.5 text-xs text-low">Said on the PC</p>}
      <p>{m.text}</p>
      {m.pendingId && (
        <div className="mt-2.5 flex min-w-60 gap-2">
          <button onClick={() => onConfirm(m.pendingId, true)} className="press on-accent h-11 flex-1 rounded-xl bg-amber-400 font-semibold text-black">Yes</button>
          <button onClick={() => onConfirm(m.pendingId, false)} className="press h-11 flex-1 rounded-xl border border-line font-semibold">No</button>
        </div>
      )}
    </div>
  )
}

function Thinking() {
  return (
    <div className="flex gap-1.5 self-start px-4 py-3.5" aria-label="Kageon is thinking">
      {[0, 1, 2].map((i) => (
        <span key={i} className="h-2 w-2 animate-pulse rounded-full bg-low" style={{ animationDelay: `${i * 0.15}s` }} />
      ))}
    </div>
  )
}

function AssistantScreen({ messages, onSend, onVoice, onConfirm }) {
  const [text, setText] = useState('')
  const mic = useMic(onVoice)
  const listRef = useRef(null)

  // waiting for an answer: a voice clip is on its way, or our last message has no reply yet
  const thinking = mic.sending || messages.at(-1)?.from === 'me'

  // keep the newest message in view: scroll the chat box (and only the chat box) to its bottom
  useEffect(() => {
    const list = listRef.current
    list?.scrollTo({ top: list.scrollHeight, behavior: 'smooth' })
  }, [messages, thinking])

  function submit(e) {
    e.preventDefault() // stop the browser from reloading the page
    if (!text.trim()) return
    onSend(text.trim())
    setText('')
  }

  const MicIcon = mic.recording ? Square : Mic

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="reveal">
        <h1 className="font-display text-4xl font-medium">Assistant</h1>
        <p className="mt-1 text-sm text-low">Type, tap a quick command, or talk. Closing apps and power actions always ask first.</p>
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        <section style={{ '--i': 2 }} className="reveal flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-line bg-card">
          <div ref={listRef} className="min-h-0 flex-1 overflow-y-auto p-4.5">
            <div className="flex min-h-full flex-col justify-end gap-2.5">
              {messages.length === 0 && <p className="m-auto text-low">Ask me anything, or tap the mic.</p>}
              {messages.map((m) => (
                <Bubble key={m.id} m={m} onConfirm={onConfirm} />
              ))}
              {thinking && <Thinking />}
            </div>
          </div>

          <form onSubmit={submit} className="flex gap-2.5 border-t border-line p-3">
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Type to Kageon…"
              aria-label="Message"
              className="h-12 min-w-0 flex-1 rounded-xl border border-line bg-well px-4 outline-none placeholder:text-low focus:border-accent-line"
            />
            <button type="submit" aria-label="Send" className="press flex h-12 w-12 items-center justify-center rounded-xl border border-line bg-card">
              <ArrowUp className="h-5 w-5" strokeWidth={1.75} />
            </button>
            <button
              type="button"
              onClick={mic.toggle}
              disabled={mic.sending}
              className={`press on-accent flex h-12 w-44 items-center justify-center gap-2 rounded-xl font-semibold disabled:opacity-50 ${mic.recording ? 'animate-pulse bg-red-500 text-white' : 'bg-accent text-accent-ink'}`}
            >
              <MicIcon className="h-5 w-5" strokeWidth={1.75} />
              {mic.label}
            </button>
          </form>
        </section>

        <aside className="w-68">
          <Card title="Quick commands" delay={3}>
            <div className="flex flex-col gap-2">
              {QUICK.map((q) => (
                <button key={q} onClick={() => onSend(q)} className="press flex h-12 items-center rounded-xl bg-well px-3.5 text-left text-sm">
                  {q}
                </button>
              ))}
            </div>
          </Card>
        </aside>
      </div>
    </div>
  )
}

export default AssistantScreen