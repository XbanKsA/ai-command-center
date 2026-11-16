import { SkipBack, Play, SkipForward, Volume1, VolumeX, Volume2 } from 'lucide-react'
import Card from './Card'

// "say" is what the button tells Kageon, exactly as if you had typed it
const BUTTONS = [
  { say: 'previous', label: 'Previous track', icon: SkipBack },
  { say: 'pause', label: 'Play or pause', icon: Play, main: true },
  { say: 'next', label: 'Next track', icon: SkipForward },
  { say: 'volume down', label: 'Volume down', icon: Volume1 },
  { say: 'mute', label: 'Mute', icon: VolumeX },
  { say: 'volume up', label: 'Volume up', icon: Volume2 },
]

function MediaCard({ onSay }) {
  return (
    <Card title="Media" note="PC audio" delay={6}>
      <div className="grid grid-cols-3 gap-2">
        {BUTTONS.map((b) => {
          const Icon = b.icon
          return (
            <button
              key={b.say}
              onClick={() => onSay(b.say)}
              aria-label={b.label}
              className={`press flex h-11.5 items-center justify-center rounded-xl ${b.main ? 'on-accent bg-accent text-accent-ink' : 'bg-well text-mid'}`}
            >
              <Icon className="h-5 w-5" strokeWidth={1.75} />
            </button>
          )
        })}
      </div>
    </Card>
  )
}

export default MediaCard