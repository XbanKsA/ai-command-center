import { useCallback, useEffect, useRef, useState } from 'react'

const SERVER = 'ws://localhost:8765/ws' // later: found automatically on Wi-Fi

export function useJarvis() {
  const [status, setStatus] = useState('connecting') // connecting , need_pin , connected , offline
  const [telemetry, setTelemetry] = useState(null)
  const [error, setError] = useState('')
  const [reply, setReply] = useState(null)
  const socketRef = useRef(null)

  useEffect(() => {
    let closedByUs = false
    let retryTimer

    function connect() {
      const ws = new WebSocket(SERVER)
      socketRef.current = ws

      ws.onmessage = (event) => {
        const msg = JSON.parse(event.data)

        if (msg.type === 'hello') {
          const token = localStorage.getItem('jarvis_token')
          if (token) ws.send(JSON.stringify({ type: 'auth', token }))
          else setStatus('need_pin')
        } else if (msg.type === 'auth_ok') {
          if (msg.token) localStorage.setItem('jarvis_token', msg.token)
          setError('')
          setStatus('connected')
        } else if (msg.type === 'auth_error') {
          if (msg.reason === 'invalid_token') localStorage.removeItem('jarvis_token')
          if (msg.reason === 'invalid_pin') setError('Wrong PIN, try again.')
          if (msg.reason === 'locked_out') setError(`Too many wrong PINs. Wait ${msg.retry_after} seconds.`)
          setStatus('need_pin') 
        } else if (msg.type === 'jarvis_reply' || msg.type === 'jarvis_event') {
        setReply({ text: msg.reply, status: msg.status, pendingId: msg.pending_id })
        } else if (msg.type === 'launch_result') {
        setReply({ text: msg.message, status: msg.ok ? 'done' : 'failed' })
        } else if (msg.type === 'telemetry') {
          setTelemetry(msg)
        }
      }

      ws.onclose = () => {
        if (closedByUs) return
        setStatus('offline')
        retryTimer = setTimeout(connect, 3000) // try again every 3 seconds
      }
    }

    connect()

    return () => {
      closedByUs = true
      clearTimeout(retryTimer)
      socketRef.current?.close()
    }
  }, [])

  function send(data) {
    const ws = socketRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data))
  }

  function sendPin(pin) { send({ type: 'auth', pin, device_name: 'Tablet app' }) }
  function launch(target) { send({ type: 'launch', target }) }
  function ask(text) { send({ type: 'chat', text }) }
  function confirm(pendingId, approve) { send({ type: 'confirm', pending_id: pendingId, approve }) }

  const clearReply = useCallback(() => setReply(null), [])

  return { status, telemetry, error, sendPin, launch, ask, confirm, reply, clearReply }
}