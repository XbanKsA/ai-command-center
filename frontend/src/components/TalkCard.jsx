import { Mic, Square } from 'lucide-react'
import Card from './Card'
import { useMic } from '../useMic'

function TalkCard({ last, onVoice }) {
  const mic = useMic(onVoice)
  const Icon = mic.recording ? Square : Mic

  return (
    <Card title="Kageon" delay={7} className="flex min-h-0 flex-1 flex-col">
      <p className="line-clamp-3 text-sm text-mid">{last ?? 'Tap to talk, or press a key.'}</p>
      <button
        onClick={mic.toggle}
        disabled={mic.sending}
        className={`press on-accent mt-auto flex h-13 w-full items-center justify-center gap-2 rounded-xl font-semibold disabled:opacity-50 ${mic.recording ? 'animate-pulse bg-red-500 text-white' : 'bg-accent text-accent-ink'}`}
      >
        <Icon className="h-5 w-5" strokeWidth={1.75} />
        {mic.label}
      </button>
    </Card>
  )
}

export default TalkCard