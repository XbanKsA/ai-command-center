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
    <div className={`reveal fixed bottom-7 left-1/2 max-w-xl -translate-x-1/2 rounded-2xl border bg-card-solid px-5 py-3 shadow-2xl ${failed ? 'border-red-500' : 'border-accent-line'}`}>
      <p>{reply.text}</p>
      {reply.pendingId && (
        <div className="mt-3 flex min-w-60 gap-2">
          <button onClick={() => onConfirm(reply.pendingId, true)} className="press on-accent h-11 flex-1 rounded-xl bg-amber-400 font-semibold text-black">Yes</button>
          <button onClick={() => onConfirm(reply.pendingId, false)} className="press h-11 flex-1 rounded-xl border border-line font-semibold">No</button>
        </div>
      )}
    </div>
  )
}

export default ReplyToast