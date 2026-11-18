import { useEffect, useState } from 'react'
import { Check, Delete } from 'lucide-react'
import StartScreen from './StartScreen'

const DIGITS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']
const key = 'press flex h-16 items-center justify-center rounded-2xl bg-well font-display text-3xl'

function PinScreen({ onSubmit, error }) {
  const [pin, setPin] = useState('')

  function add(d) {
    setPin((p) => (p.length < 4 ? p + d : p))
  }

  function send() {
    if (pin.length !== 4) return
    onSubmit(pin)
    setPin('') // a wrong PIN starts again from empty
  }

  // the PC's keyboard works too: digits, Backspace and Enter
  useEffect(() => {
    function onKey(e) {
      if (/^\d$/.test(e.key)) setPin((p) => (p.length < 4 ? p + e.key : p))
      else if (e.key === 'Backspace') setPin((p) => p.slice(0, -1))
      else if (e.key === 'Enter' && pin.length === 4) {
        onSubmit(pin)
        setPin('')
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pin, onSubmit])

  return (
    <StartScreen>
      <div>
        <h1 className="font-display text-5xl font-medium leading-tight">Enter the PIN</h1>
        <p className="mt-3 text-mid">Four digits, shown in the Kageon window on your PC.</p>
      </div>

      {/* key={error} replays the shake each time a new error arrives */}
      <div key={error} className={`flex justify-center gap-3 ${error ? 'animate-[link-shake_0.4s_ease]' : ''}`}>
        {[0, 1, 2, 3].map((i) => (
          <span
            key={i}
            className={`flex h-19 w-16 items-center justify-center rounded-2xl border transition-colors duration-300 ${i < pin.length ? 'border-accent-line bg-accent-soft' : 'border-line bg-well'}`}
          >
            <span className={`h-3.5 w-3.5 rounded-full bg-hi transition-transform duration-300 ${i < pin.length ? 'scale-100' : 'scale-0'}`} />
          </span>
        ))}
      </div>
      <p role="alert" className="-my-2 min-h-5 text-center text-sm text-red-400">{error}</p>

      <div className="grid grid-cols-3 gap-2.5">
        {DIGITS.map((d) => (
          <button key={d} onClick={() => add(d)} className={key}>{d}</button>
        ))}
        <button onClick={() => setPin(pin.slice(0, -1))} aria-label="Delete last digit" className={key}>
          <Delete className="h-6 w-6" strokeWidth={1.75} />
        </button>
        <button onClick={() => add('0')} className={key}>0</button>
        <button onClick={send} disabled={pin.length !== 4} aria-label="Connect" className={`${key} on-accent bg-accent text-accent-ink disabled:opacity-40`}>
          <Check className="h-6 w-6" strokeWidth={2} />
        </button>
      </div>
    </StartScreen>
  )
}

export default PinScreen