import { useCallback, useEffect, useRef, useState } from 'react'

export function useJarvis(host) { 
  const [status, setStatus] = useState('connecting') // connecting , need_pin , connected , offline
  const [telemetry, setTelemetry] = useState(null)
  const [error, setError] = useState('')
  const [reply, setReply] = useState(null)
  const [apps, setApps] = useState([])
  const [mode, setModeInfo] = useState(null)
  const socketRef = useRef(null)
  const [messages, setMessages] = useState([])

  const addMessage = useCallback((m) => {
    const id = `${Date.now()}-${Math.random()}`
    setMessages((prev) => [...prev, { id, ...m }].slice(-50))
  }, [])

  useEffect(() => {
    if (!host) return
    let closedByUs = false
    let retryTimer

    function connect() {
      const ws = new WebSocket(`ws://${host}/ws`)
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
        } else if (msg.type === 'jarvis_reply') {
          setReply({ text: msg.reply, status: msg.status, pendingId: msg.pending_id })
          addMessage({ from: 'jarvis', text: msg.reply, pendingId: msg.pending_id })
        } else if (msg.type === 'jarvis_event') {
          setReply({ text: msg.reply, status: msg.status, pendingId: msg.pending_id })
          addMessage({ from: 'pc', text: msg.user_text })
          addMessage({ from: 'jarvis', text: msg.reply, pendingId: msg.pending_id })
        setReply({ text: msg.reply, status: msg.status, pendingId: msg.pending_id })
        } else if (msg.type === 'launch_result') {
        } else if (msg.type === 'apps') {
          setApps(msg.apps)
        } else if (msg.type === 'mode') {
          setModeInfo(msg)
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
  }, [host, addMessage])

  function send(data) {
    const ws = socketRef.current
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(data))
  }

  function sendPin(pin) { send({ type: 'auth', pin, device_name: 'Tablet app' }) }
  function launch(target) { send({ type: 'launch', target }) }
  function ask(text) {
    addMessage({ from: 'me', text })
    send({ type: 'chat', text })
  }
  function changeMode(m) { send({ type: 'set_mode', mode: m }) }
  function confirm(pendingId, approve) {
    setMessages((prev) => prev.map((m) => (m.pendingId === pendingId ? { ...m, pendingId: null } : m)))
    send({ type: 'confirm', pending_id: pendingId, approve })
  }
    async function sendVoice(blob) {
    try {
      const res = await fetch(`http://${host}/api/voice`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${localStorage.getItem('jarvis_token')}`,
          'Content-Type': blob.type,
        },
        body: blob,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (!data.transcript) {
        addMessage({ from: 'jarvis', text: "I didn't catch anything. Try again?" })
        return
      }
      addMessage({ from: 'me', text: data.transcript })
      addMessage({ from: 'jarvis', text: data.reply.reply, pendingId: data.reply.pending_id })
    } catch (err) {
      addMessage({ from: 'jarvis', text: `Voice failed: ${err.message}` })
    }
  }

  const clearReply = useCallback(() => setReply(null), [])
  const searchApps = useCallback((query) => {
  const ws = socketRef.current
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'list_apps', query }))
}, [])

      return { status, telemetry, error, sendPin, launch, ask, confirm, reply, clearReply, apps, searchApps, mode, changeMode, messages, sendVoice }
}