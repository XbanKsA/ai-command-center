import { useEffect, useState } from 'react'
import { discoverJarvis } from '../discovery'
import StartScreen from './StartScreen'
import StatusCard from './StatusCard'

function ConnectScreen({ onFound }) {
  const [state, setState] = useState('searching') // searching | not_found
  const [attempt, setAttempt] = useState(0)
  const [manual, setManual] = useState('')

  useEffect(() => {
    let cancelled = false
    setState('searching')
    discoverJarvis()
      .then((host) => {
        if (cancelled) return
        if (host) onFound(host)
        else setState('not_found')
      })
      .catch(() => { if (!cancelled) setState('not_found') })
    return () => { cancelled = true }
  }, [attempt, onFound])

  function connectManually(e) {
    e.preventDefault()
    if (manual) onFound(manual.includes(':') ? manual : `${manual}:8765`)
  }

  const searching = state === 'searching'

  return (
    <StartScreen>
      <div>
        <h1 className="font-display text-5xl font-medium leading-tight">Connect to your PC</h1>
        <p className="mt-3 text-mid">The tablet looks for Kageon on your Wi-Fi. The first time, you'll type the PIN shown on the PC.</p>
      </div>

      <StatusCard
        busy={searching}
        title={searching ? 'Looking for your PC…' : 'No PC found'}
        text={searching ? 'This takes a few seconds.' : 'Make sure Kageon is running on the PC and both are on the same Wi-Fi.'}
      >
        {!searching && (
          <button onClick={() => setAttempt(attempt + 1)} className="press h-11 shrink-0 rounded-xl border border-line bg-card px-4 text-sm font-semibold">
            Search again
          </button>
        )}
      </StatusCard>

      <form onSubmit={connectManually} className="flex flex-col gap-2">
        <label htmlFor="address" className="text-xs font-semibold text-low">Or type the PC address</label>
        <div className="flex gap-2.5">
          <input
            id="address"
            value={manual}
            onChange={(e) => setManual(e.target.value.trim())}
            placeholder="192.168.1.20"
            className="h-12 min-w-0 flex-1 rounded-xl border border-line bg-well px-4 outline-none placeholder:text-low focus:border-accent-line"
          />
          <button type="submit" disabled={!manual} className="press h-12 rounded-xl border border-line bg-card px-5 font-semibold disabled:opacity-40">
            Connect
          </button>
        </div>
      </form>
    </StartScreen>
  )
}

export default ConnectScreen