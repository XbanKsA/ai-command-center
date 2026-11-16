import { useState } from 'react'
import { useRecorder } from './useRecorder'

// One tap starts recording, the next tap sends it to Kageon
export function useMic(onVoice) {
  const { recording, start, stop } = useRecorder()
  const [sending, setSending] = useState(false)

  async function toggle() {
    if (sending) return
    if (!recording) {
      try {
        await start()
      } catch {
        alert('Microphone not available. Allow it and try again.')
      }
      return
    }
    const blob = await stop()
    setSending(true)
    await onVoice(blob)
    setSending(false)
  }

  const label = sending ? 'Thinking…' : recording ? 'Tap to send' : 'Tap to talk'
  return { recording, sending, label, toggle }
}