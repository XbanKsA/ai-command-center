// A small line chart of percentages (0-100), drawn as one SVG line that stretches to fit its box
function Sparkline({ values }) {
  if (values.length < 2) return <div className="flex-1" />

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * 100
      const y = 29 - ((v ?? 0) / 100) * 28 // SVG y grows downwards, so 100% sits near the top
      return `${x},${y}`
    })
    .join(' ')

  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="min-h-0 w-full flex-1 text-accent-text" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

export default Sparkline