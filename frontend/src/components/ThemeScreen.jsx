import { useState } from 'react'
import Card from './Card'
import HueWheel from './HueWheel'
import Key from './Key'

function shadeName(s) {
  if (s === 0) return 'White'
  if (s < 18) return 'Mist'
  if (s < 38) return 'Silver'
  if (s < 62) return 'Gray'
  if (s < 78) return 'Graphite'
  if (s < 100) return 'Night'
  return 'Black'
}

function ThemeScreen({ theme, onChange, onReset }) {
  const [replay, setReplay] = useState(0) // bump it to play the preview's reveal again

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <div className="flex items-end justify-between">
        <div className="reveal">
          <h1 className="font-display text-4xl font-medium">Theme</h1>
          <p className="mt-1 text-sm text-low">Accent from the wheel. Background from the bar. Saved on this tablet.</p>
        </div>
        <button onClick={onReset} className="press reveal h-11 rounded-xl border border-line bg-card px-4 text-sm font-semibold">
          Reset
        </button>
      </div>

      <div className="flex min-h-0 flex-1 gap-4">
        <Card title="Accent" note="Tap or drag around the wheel" delay={2} className="flex w-[31rem] flex-col">
          <div className="flex min-h-0 flex-1 items-center justify-center">
            <HueWheel pos={theme.pos} onChange={(pos, fade) => onChange({ pos }, fade)} />
          </div>

          <div className="mt-3 flex items-baseline justify-between">
            <label htmlFor="shade" className="text-sm font-semibold">Background</label>
            <span className="text-xs text-low">{shadeName(theme.shade)}</span>
          </div>
          <input
            id="shade"
            type="range"
            min="0"
            max="100"
            value={theme.shade}
            onChange={(e) => {
              const shade = Number(e.target.value)
              const jumped = Math.abs(shade - theme.shade) > 4 // a tap jumps far; a drag moves a little at a time
              onChange({ shade }, jumped)
            }}
            className="shade-slider mt-2.5 w-full"
          />
          <div className="mt-2 flex justify-between text-xs text-low">
            <span>White</span>
            <span>Black</span>
          </div>
        </Card>

        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <Card key={replay} title="Preview" delay={3} className="flex flex-1 flex-col gap-4">
            <div className="flex gap-3">
              <div className="grid h-36 w-40 shrink-0">
                <Key title="Steam" subtitle="App" action={{ type: 'launch', target: 'steam' }} index={4} onPress={() => {}} />
              </div>
              <div className="flex min-w-0 flex-1 flex-col justify-between gap-3">
                <div className="flex gap-2">
                  <button className="press on-accent h-11 flex-1 rounded-xl bg-accent text-sm font-semibold text-accent-ink">Save</button>
                  <button className="press h-11 flex-1 rounded-xl border border-line text-sm font-semibold">Cancel</button>
                </div>
                <div>
                  <div className="flex justify-between text-xs text-low">
                    <span>GPU</span>
                    <span className="font-semibold text-hi">41%</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-well">
                    <div className="h-full w-[41%] rounded-full bg-accent-text" />
                  </div>
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-2">
              <p className="max-w-[68%] self-end rounded-2xl rounded-br-md border border-accent-line bg-accent-soft px-4 py-2.5">open spotify</p>
              <p className="max-w-[68%] self-start rounded-2xl rounded-bl-md border border-line bg-card px-4 py-2.5">Opening Spotify.</p>
            </div>
          </Card>

          <Card title="Motion" note="Tap to try" delay={4} className="flex flex-col gap-3">
            <div className="flex gap-2">
              <button className="press h-11 flex-1 rounded-xl border border-line bg-card text-sm font-semibold">Press · 0.16 s</button>
              <button onClick={() => setReplay(replay + 1)} className="press h-11 flex-1 rounded-xl border border-line bg-card text-sm font-semibold">
                Reveal · 0.5 s
              </button>
            </div>
            <div className="flex gap-1 rounded-2xl bg-well p-1">
              {[false, true].map((calm) => (
                <button
                  key={String(calm)}
                  onClick={() => onChange({ calm })}
                  className={`press h-11 flex-1 rounded-xl text-sm font-semibold transition-colors duration-300 ${theme.calm === calm ? 'on-accent bg-accent text-accent-ink' : 'text-low'}`}
                >
                  {calm ? 'Reduced motion' : 'Full motion'}
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}

export default ThemeScreen