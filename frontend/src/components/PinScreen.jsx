import { useState } from 'react'

function PinScreen({ onSubmit, error }) {
  const [pin, setPin] = useState('')

  return (
    <div className="h-screen bg-black text-white flex flex-col items-center justify-center gap-6">
      <h1 className="text-3xl font-semibold">Enter the PIN shown on your PC</h1>
      <input
        value={pin}
        onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 4))}
        inputMode="numeric"
        placeholder="••••"
        className="w-64 h-20 text-center text-5xl font-mono tracking-[0.5em] rounded-2xl bg-slate-950 border border-slate-700 focus:border-cyan-400 outline-none"
      />
      {error && <p className="text-red-400">{error}</p>}
      <button
        onClick={() => onSubmit(pin)}
        disabled={pin.length !== 4}
        className="h-14 px-10 rounded-2xl bg-cyan-400 text-black font-bold disabled:opacity-30"
      >
        Connect
      </button>
    </div>
  )
}

export default PinScreen