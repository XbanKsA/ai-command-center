// An on/off switch. role="switch" tells screen readers what it is.
function Toggle({ on, onChange, label }) {
  return (
    <button
      role="switch"
      aria-checked={on}
      aria-label={label}
      onClick={() => onChange(!on)}
      className="flex h-11 w-15 shrink-0 items-center justify-end"
    >
      <span className={`relative h-7.5 w-13 rounded-full border transition-colors duration-200 ${on ? 'border-transparent bg-accent' : 'border-line bg-well'}`}>
        <span
          className={`absolute left-0.75 top-0.75 h-5.5 w-5.5 rounded-full transition-transform duration-200 ${on ? 'translate-x-5.5 bg-accent-ink' : 'bg-low'}`}
        />
      </span>
    </button>
  )
}

export default Toggle