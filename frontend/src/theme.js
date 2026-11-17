// Turns two numbers (where the wheel knob is, and how dark the background is) into every colour in the app.

// 12 hand-tuned accent colours around the wheel: [hue, lightness, colourfulness].
// Between two of them we blend, so every spot on the wheel stays clean and readable.
const ANCHORS = [
  [25, 0.66, 0.21], [55, 0.74, 0.17], [95, 0.84, 0.16], [128, 0.84, 0.19],
  [150, 0.78, 0.19], [180, 0.78, 0.14], [215, 0.78, 0.13], [242, 0.7, 0.15],
  [264, 0.62, 0.2], [293, 0.64, 0.21], [325, 0.68, 0.23], [358, 0.68, 0.21],
]
export const HUE_NAMES = ['Red', 'Orange', 'Yellow', 'Lime', 'Green', 'Teal', 'Cyan', 'Sky', 'Blue', 'Violet', 'Magenta', 'Rose']

// pos: where the knob sits on the wheel, 0-360. shade: the background, 0 = white, 100 = black.
export const DEFAULT_THEME = { pos: 240, shade: 83, calm: false }
const STORAGE = 'kageon_theme'

const mix = (a, b, t) => a + (b - a) * t
const n = (x) => x.toFixed(3) // short numbers for CSS

export function accentAt(pos) {
  const i = Math.floor(pos / 30) % 12
  const t = (pos % 30) / 30
  const [h1, l1, c1] = ANCHORS[i]
  let [h2, l2, c2] = ANCHORS[(i + 1) % 12]
  if (h2 < h1) h2 += 360 // Rose (358) -> Red (25) goes past 360
  return { h: mix(h1, h2, t) % 360, l: mix(l1, l2, t), c: mix(c1, c2, t) }
}

export function hueName(pos) {
  return HUE_NAMES[Math.round(pos / 30) % 12]
}

// the wheel's ring: the accent colour at every 10 degrees
export function wheelGradient() {
  const stops = []
  for (let p = 0; p <= 360; p += 10) {
    const a = accentAt(p % 360)
    stops.push(`oklch(${n(a.l)} ${n(a.c)} ${n(a.h)}) ${p}deg`)
  }
  return `conic-gradient(${stops.join(', ')})`
}

export function palette({ pos, shade }) {
  const a = accentAt(pos)
  const h = n(a.h)
  const L = 0.985 * (1 - shade / 100) // the page's lightness: 0.985 is white, 0 is black
  let p

  if (L < 0.56) {
    // dark page -> light text. t goes 0 -> 1 from the default navy to mid gray
    const t = Math.max(0, (L - 0.17) / 0.39)
    const c = L < 0.17 ? 0.045 * (L / 0.17) : mix(0.045, 0.02, t)
    const solid = L < 0.35
    p = {
      page: `oklch(${n(L)} ${n(c)} ${h})`,
      card: solid ? 'oklch(1 0 0 / 0.055)' : 'oklch(0 0 0 / 0.16)',
      well: solid ? 'oklch(1 0 0 / 0.08)' : 'oklch(0 0 0 / 0.18)',
      line: `oklch(1 0 0 / ${n(mix(0.1, 0.2, t))})`,
      cardSolid: `oklch(${n(L + 0.06)} ${n(c)} ${h})`,
      hi: `oklch(${n(mix(0.97, 1, t))} 0.01 ${h})`,
      mid: `oklch(${n(mix(0.83, 0.96, t))} 0.02 ${h})`,
      low: `oklch(${n(mix(0.71, 0.92, t))} 0.025 ${h})`,
      accentL: mix(0.78, 0.95, t),
      glow: [0.5, L < 0.05 ? 0.3 : 0.42],
    }
  } else {
    // light page -> dark text. t goes 0 -> 1 from white to mid gray
    const t = (0.985 - L) / 0.425
    p = {
      page: `oklch(${n(L)} ${n(mix(0.006, 0.015, t))} ${h})`,
      card: `oklch(1 0 0 / ${n(mix(0.72, 0.25, t))})`,
      well: `oklch(0.25 0.04 ${h} / ${n(mix(0.09, 0.15, t))})`,
      line: `oklch(0.25 0.04 ${h} / ${n(mix(0.16, 0.26, t))})`,
      cardSolid: `oklch(${n(mix(0.995, 0.68, t))} ${n(mix(0.003, 0.015, t))} ${h})`,
      hi: `oklch(${n(mix(0.2, 0, t))} 0.03 ${h})`,
      mid: `oklch(${n(mix(0.36, 0.1, t))} 0.03 ${h})`,
      low: `oklch(${n(mix(0.45, 0.14, t))} 0.03 ${h})`,
      accentL: mix(0.45, 0.16, t),
      glow: [mix(0.8, 0.62, t), mix(0.3, 0.4, t)],
    }
  }

  const ac = n(a.c)
  const tc = n(Math.min(a.c, 0.15))
  const al = n(p.accentL)
  return {
    '--page': p.page,
    '--card': p.card,
    '--card-solid': p.cardSolid,
    '--line': p.line,
    '--well': p.well,
    '--hi': p.hi,
    '--mid': p.mid,
    '--low': p.low,
    '--accent': `oklch(${n(a.l)} ${ac} ${h})`,
    '--accent-ink': `oklch(0.16 0.04 ${h})`,
    '--accent-text': `oklch(${al} ${tc} ${h})`,
    '--accent-soft': `oklch(${al} ${ac} ${h} / 0.14)`,
    '--accent-line': `oklch(${al} ${ac} ${h} / 0.5)`,
    '--glow-a': `oklch(${n(p.glow[0])} 0.19 ${h} / ${n(p.glow[1])})`,
    '--glow-b': `oklch(${n(p.glow[0])} 0.14 ${n((a.h + 75) % 360)} / ${n(p.glow[1] / 2)})`,
  }
}


let lastDark = null // was the page dark last time? null = not drawn yet
let flipUntil = 0 // after the text flips light <-> dark, keep fading slowly until this time
let offTimer

// put the colours on the page. fade = true for a tap: everything cross-fades over 1.2 s.
// fade = false while dragging: colours follow the finger, smoothed over 0.15 s.
export function applyTheme(theme, fade = false) {
  const root = document.documentElement
  for (const [name, value] of Object.entries(palette(theme))) root.style.setProperty(name, value)
  root.classList.toggle('calm', theme.calm)

  const dark = 0.985 * (1 - theme.shade / 100) < 0.56 // the same test palette() uses for light or dark text
  const first = lastDark === null
  const flipped = !first && dark !== lastDark // text just switched light <-> dark
  lastDark = dark
  if (first) return // the app is starting: show the colours straight away

  // a tap, or the text flipping, is a slow cross-fade, even in the middle of a drag
  if (flipped) flipUntil = Date.now() + 1200
  const slow = fade || Date.now() < flipUntil
  root.style.setProperty('--theme-speed', slow ? '1.2s' : '0.15s')
  root.classList.add('theme-fade')
  clearTimeout(offTimer)
  offTimer = setTimeout(() => root.classList.remove('theme-fade'), 1200)
}

export function loadTheme() {
  try {
    return { ...DEFAULT_THEME, ...JSON.parse(localStorage.getItem(STORAGE)) }
  } catch {
    return DEFAULT_THEME
  }
}

export function saveTheme(theme) {
  localStorage.setItem(STORAGE, JSON.stringify(theme))
}