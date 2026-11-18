import { useCallback, useEffect, useRef, useState } from 'react'

const HOT_C = 80 // GPU temperature that counts as running hot

function howLong(ms) {
  const s = Math.round(ms / 1000)
  return s < 60 ? `${s} s` : `${Math.round(s / 60)} min`
}

export function useKageon(host, notify) {
  const [status, setStatus] = useState('connecting')// connecting , need_pin , connected , offline
  const [telemetry, setTelemetry] = useState(null)
  const [history, setHistory] = useState([])
  const [coreVersion, setCoreVersion] = useState('')
  const pongWaiter = useRef(null)
  const [error, setError] = useState('')
  const [reply, setReply] = useState(null)
  const [apps, setApps] = useState([])
  const [mode, setModeInfo] = useState(null)
  const [media, setMedia] = useState(null)
  const [pcNotify, setPcNotify] = useState({ status: 'starting', apps: [] }) // can the PC read its notifications, and from which apps
  const socketRef = useRef(null)
  const hotRef = useRef(false) // already warned about the GPU? (so it warns once, not every second)
  const connectedRef = useRef(false)
  const offlineSince = useRef(null) // when the connection dropped
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
          setCoreVersion(msg.version)
          const token = localStorage.getItem('kageon_token')
          if (token) ws.send(JSON.stringify({ type: 'auth', token }))
          else setStatus('need_pin')
        } else if (msg.type === 'auth_ok') {
          if (msg.token) localStorage.setItem('kageon_token', msg.token)
          setError('')
          setStatus('connected')
          connectedRef.current = true
          if (offlineSince.current) {
            notify('offline', 'The PC was offline', `for ${howLong(Date.now() - offlineSince.current)}. Connected again.`)
            offlineSince.current = null
          }
        } else if (msg.type === 'auth_error') {
          if (msg.reason === 'invalid_token') localStorage.removeItem('kageon_token')
          if (msg.reason === 'invalid_pin') setError('Wrong PIN, try again.')
          if (msg.reason === 'locked_out') setError(`Too many wrong PINs. Wait ${msg.retry_after} seconds.`)
          setStatus('need_pin') 
        } else if (msg.type === 'assistant_reply') {
          setReply({ text: msg.reply, status: msg.status, pendingId: msg.pending_id })
          if (msg.pending_id) notify('ask', 'Kageon is asking', msg.reply)
          addMessage({ from: 'kageon', text: msg.reply, pendingId: msg.pending_id })
        } else if (msg.type === 'assistant_event') {
          setReply({ text: msg.reply, status: msg.status, pendingId: msg.pending_id })
          if (msg.pending_id) notify('ask', 'Kageon is asking', msg.reply)
          else notify('replies', `You said: "${msg.user_text}"`, msg.reply)
          addMessage({ from: 'pc', text: msg.user_text })
          addMessage({ from: 'kageon', text: msg.reply, pendingId: msg.pending_id })
        setReply({ text: msg.reply, status: msg.status, pendingId: msg.pending_id })
        } else if (msg.type === 'launch_result') {
        } else if (msg.type === 'apps') {
          setApps(msg.apps)
        } else if (msg.type === 'mode') {
          setModeInfo(msg)
        } else if (msg.type === 'notify_status') {
          setPcNotify({ status: msg.status, apps: msg.apps })
        } else if (msg.type === 'pc_notification') {
          notify('pc', msg.app, [msg.title, msg.text].filter(Boolean).join(' · '))
        } else if (msg.type === 'pong') {
          pongWaiter.current?.()
        } else if (msg.type === 'media') {
          setMedia(msg)
        } else if (msg.type === 'media_result') {
          if (!msg.ok) setReply({ text: msg.message, status: 'failed' })
        } else if (msg.type === 'telemetry') {
          setTelemetry(msg)
          setHistory((prev) => [...prev, msg].slice(-40)) 
          const temp = msg.gpu?.temperature_c
          if (temp >= HOT_C && !hotRef.current) {
            hotRef.current = true
            notify('hot', 'GPU running hot', `${temp}°C`)
          } else if (temp < HOT_C - 5) {
            hotRef.current = false // cooled down: warn again next time
          }
        }
      }

      ws.onclose = () => {
        if (closedByUs) return
        if (connectedRef.current) {
          connectedRef.current = false
          offlineSince.current = Date.now() // we were connected, now we're not
        }
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
  }, [host, addMessage, notify])

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
  function mediaKey(key) { send({ type: 'media_key', key }) }
  function confirm(pendingId, approve) {
    setMessages((prev) => prev.map((m) => (m.pendingId === pendingId ? { ...m, pendingId: null } : m)))
    send({ type: 'confirm', pending_id: pendingId, approve })
  }
    async function sendVoice(blob) {
    try {
      const res = await fetch(`http://${host}/api/voice`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${localStorage.getItem('kageon_token')}`,
          'Content-Type': blob.type,
        },
        body: blob,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (!data.transcript) {
        addMessage({ from: 'kageon', text: "I didn't catch anything. Try again?" })
        return
      }
      addMessage({ from: 'me', text: data.transcript })
      addMessage({ from: 'kageon', text: data.reply.reply, pendingId: data.reply.pending_id })
    } catch (err) {
      addMessage({ from: 'kageon', text: `Voice failed: ${err.message}` })
    }
  }
    // send a ping and time the answer: resolves to milliseconds, or null if the PC didn't answer in 3 s
  const testConnection = useCallback(() => {
    return new Promise((resolve) => {
      const started = performance.now()
      const timer = setTimeout(() => {
        pongWaiter.current = null
        resolve(null)
      }, 3000)
      pongWaiter.current = () => {
        clearTimeout(timer)
        pongWaiter.current = null
        resolve(Math.round(performance.now() - started))
      }
      const ws = socketRef.current
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
    })
  }, [])

  const sendNotifySettings = useCallback((pc) => {
    const ws = socketRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'notify_settings', enabled: pc.enabled, apps: pc.apps }))
    }
  }, [])


  const clearReply = useCallback(() => setReply(null), [])
  const searchApps = useCallback((query) => {
  const ws = socketRef.current
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'list_apps', query }))
}, [])

      return { status, telemetry, error, sendPin, launch, ask, confirm, reply, clearReply, apps, searchApps, mode, changeMode, messages, sendVoice, media, mediaKey, history, coreVersion, testConnection, pcNotify, sendNotifySettings }
}