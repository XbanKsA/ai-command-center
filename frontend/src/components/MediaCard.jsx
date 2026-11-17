import { SkipBack, Play, Pause, SkipForward, Volume1, VolumeX, Volume2 } from 'lucide-react'
import Card from './Card'

// "key" is the media key the PC presses: no chat message, no waiting for Kageon
const BUTTONS = [
  { key: 'previous', label: 'Previous track', icon: SkipBack },
  { key: 'play_pause', label: 'Play or pause', main: true },
  { key: 'next', label: 'Next track', icon: SkipForward },
  { key: 'volume_down', label: 'Volume down', icon: Volume1 },
  { key: 'mute', label: 'Mute', icon: VolumeX },
  { key: 'volume_up', label: 'Volume up', icon: Volume2 },
]

function MediaCard({ media, onKey }) {
  const active = media?.active
  const playing = media?.playing
  // "Blinding Lights · The Weeknd" while something is open, otherwise just "Media"
  const song = active ? [media.title, media.artist].filter(Boolean).join(' · ') : ''

  return (
    <Card title={song || 'Media'} note={active ? media.app : 'PC audio'} delay={6}>
      <div className="grid grid-cols-3 gap-2">
        {BUTTONS.map((b) => {
          const Icon = b.main ? (playing ? Pause : Play) : b.icon
          return (
            <button
              key={b.key}
              onClick={() => onKey(b.key)}
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