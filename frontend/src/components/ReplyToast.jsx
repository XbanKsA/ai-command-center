import { useEffect } from 'react'

function ReplyToast({ reply, onClose, onConfirm }) {
  useEffect(() => {
    if (!reply || reply.pendingId) return // questions stay until you answer
    const timer = setTimeout(onClose, 4000)
    return () => clearTimeout(timer)
  }, [reply, onClose])

  if (!reply) return null

  const failed = reply.status === 'failed' || reply.status === 'error'

  return (
    <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 max-w-xl rounded-2xl border bg-slate-950 px-6 py-4 shadow-2xl ${failed ? 'border-red-500' : 'border-cyan-400'}`}>
      <p className="text-lg">{reply.text}</p>
      {reply.pendingId && (
        <div className="mt-4 flex gap-3">
          <button onClick={() => onConfirm(reply.pendingId, true)} className="h-12 flex-1 rounded-xl bg-amber-500 font-bold text-black">Yes</button>
          <button onClick={() => onConfirm(reply.pendingId, false)} className="h-12 flex-1 rounded-xl border border-slate-600">No</button>
        </div>
      )}
    </div>
  )
}

export default ReplyToast