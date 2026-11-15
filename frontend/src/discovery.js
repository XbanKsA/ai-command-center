import { Capacitor } from "@capacitor/core"
import { UdpSocket } from "capacitor-udp-socket"

const PORT = 37020

export async function discoverJarvis(timeoutMs = 6000) {
  // In the PC's browser there is no UDP -> just use this same PC
  if (!Capacitor.isNativePlatform()) return 'localhost:8765'

  const { socketId } = await UdpSocket.create()
  let listener

  try {
    const found = new Promise((resolve) => {
      UdpSocket.addListener('receive', (event) => {
        try {
          const msg = JSON.parse(atob(event.buffer))
          if (msg.service === 'Kageon' && msg.host && msg.port) resolve(`${msg.host}:${msg.port}`)
        } catch {
          // not a KAGEON message - ignore it
        }
      }).then((l) => { listener = l })
    })

    await UdpSocket.bind({ socketId, port: PORT })
    await UdpSocket.setBroadcast({ socketId, enabled: true })
    const probe = btoa(JSON.stringify({ service: 'Kageon', type: 'probe' }))
    await UdpSocket.send({ socketId, address: '255.255.255.255', port: PORT, buffer: probe })

    const timeout = new Promise((resolve) => setTimeout(() => resolve(null), timeoutMs))
    return await Promise.race([found, timeout])
  } finally {
    listener?.remove()
    UdpSocket.close({ socketId }).catch(() => {})
  }
}