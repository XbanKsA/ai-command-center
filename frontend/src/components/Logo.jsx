// The Kageon moon in an accent-coloured square. Size it with className.
function Logo({ className = 'h-10 w-10' }) {
  return (
    <span className={`flex shrink-0 items-center justify-center rounded-xl bg-accent text-accent-ink ${className}`}>
      <svg viewBox="0 0 24 24" className="h-[55%] w-[55%]" fill="currentColor" aria-hidden="true">
        <path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z" />
      </svg>
    </span>
  )
}

export default Logo