import { useEffect, useState } from 'react'
import { discoverJarvis } from '../discovery'

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

  if (state === 'searching') {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-4 bg-black text-white">
        <div className="h-16 w-16 animate-spin rounded-full border-4 border-slate-800 border-t-cyan-400" />
        <p className="text-xl">Searching for your PC on Wi-Fi…</p>
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-8 bg-black text-white">
      <div dir="rtl" className="rounded-3xl border border-red-900 bg-red-950/40 p-10 text-center">
        <h1 className="text-3xl font-bold text-red-300">تعذر الاتصال بالسيرفر! ⚠️</h1>
        <p className="mt-3 text-lg text-red-100/80">تأكد أن كلا الجهازين متصلان بنفس شبكة الـ Wi-Fi.</p>
      </div>
      <button onClick={() => setAttempt(attempt + 1)} className="h-14 rounded-2xl bg-cyan-400 px-8 font-bold text-black">
        Search again
      </button>
      <div className="flex gap-3">
        <input
          value={manual}
          onChange={(e) => setManual(e.target.value.trim())}
          placeholder="Or type the PC address, e.g. 192.168.1.20"
          className="h-12 w-96 rounded-xl border border-slate-700 bg-slate-950 px-4 outline-none focus:border-cyan-400"
        />
        <button
          onClick={() => onFound(manual.includes(':') ? manual : `${manual}:8765`)}
          disabled={!manual}
          className="h-12 rounded-xl border border-slate-600 px-5 disabled:opacity-30"
        >
          Connect
        </button>
      </div>
    </div>
  )
}

export default ConnectScreen