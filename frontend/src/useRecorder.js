import { useRef, useState } from 'react'

export function useRecorder() {
  const [recording, setRecording] = useState(false)
  const recorderRef = useRef(null)
  const chunksRef = useRef([])

  async function start() {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const rec = new MediaRecorder(stream)
    chunksRef.current = []
    rec.ondataavailable = (e) => chunksRef.current.push(e.data)
    rec.start()
    recorderRef.current = rec
    setRecording(true)
  }

  function stop() {
    return new Promise((resolve) => {
      const rec = recorderRef.current
      if (!rec) return resolve(null)
      rec.onstop = () => {
        rec.stream.getTracks().forEach((t) => t.stop()) // switch the mic off
        recorderRef.current = null
        setRecording(false)
        resolve(new Blob(chunksRef.current, { type: rec.mimeType }))
      }
      rec.stop()
    })
  }

  return { recording, start, stop }
}