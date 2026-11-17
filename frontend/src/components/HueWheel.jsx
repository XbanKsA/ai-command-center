import { useEffect, useState } from 'react'
import { hueName, wheelGradient } from '../theme'

const GRADIENT = wheelGradient() // works it out once, not on every render

function HueWheel({ pos, onChange }) {
  const [dragging, setDragging] = useState(false)
  const [angle, setAngle] = useState(pos) // the knob's turn; can go past 360 so it never spins the long way

  // when pos changes, turn the knob the short way: 350 -> 10 is +20 degrees, not -340
  useEffect(() => {
    setAngle((a) => a + ((((pos - a) % 360) + 540) % 360) - 180)
  }, [pos])

  // where on the ring did the finger land? 0 = top, 90 = right, 180 = bottom ...
  function posFrom(e) {
    const box = e.currentTarget.getBoundingClientRect()
    const dx = e.clientX - (box.left + box.width / 2)
    const dy = e.clientY - (box.top + box.height / 2)
    if (Math.hypot(dx, dy) < box.width * 0.3) return null // the middle of the wheel isn't the ring
    return Math.round((Math.atan2(dx, -dy) * 180) / Math.PI + 360) % 360
  }

  function down(e) {
    const p = posFrom(e)
    if (p === null) return
    e.currentTarget.setPointerCapture(e.pointerId) // keep getting moves even if the finger leaves the ring
    setDragging(true)
    onChange(p, true) // a tap: cross-fade
  }

  function move(e) {
    if (!dragging) return
    const p = posFrom(e)
    if (p !== null) onChange(p, false) // dragging: follow
  }

  return (
    <div className="relative aspect-square w-full max-w-[22.5rem]">
      <button
        aria-label="Accent colour"
        className="hue-ring absolute inset-0"
        style={{ background: GRADIENT }}
        onPointerDown={down}
        onPointerMove={move}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
      />
      <div
        className={`own-motion pointer-events-none absolute inset-0 ${dragging ? '' : 'transition-transform duration-500'}`}
        style={{ transform: `rotate(${angle}deg)` }}
      >
        <span className="absolute left-1/2 top-[9.7%] h-6.5 w-6.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] border-black/55 bg-white shadow-lg" />
      </div>
      <div className="pointer-events-none absolute inset-[20%] flex flex-col items-center justify-center gap-1">
        <span className="h-3.5 w-3.5 rounded-full bg-accent" />
        <span className="font-display text-3xl font-medium">{hueName(pos)}</span>
        <span className="text-xs text-low">Accent</span>
      </div>
    </div>
  )
}

export default HueWheel