function Key({ title, subtitle, onPress }) {
  return (
    <button
      onClick={onPress}
      className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-slate-800 bg-slate-950 transition hover:border-cyan-400 active:scale-95"
    >
      <span className="text-base font-semibold">{title}</span>
      <span className="text-xs text-slate-400">{subtitle}</span>
    </button>
  )
}

export default Key