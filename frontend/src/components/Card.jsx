// A glass box with an optional title row. Everything between <Card> and </Card> arrives as "children".
function Card({ title, note, delay = 0, className = '', children }) {
  return (
    <section style={{ '--i': delay }} className={`reveal rounded-2xl border border-line bg-card p-4 ${className}`}>
      {title && (
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">{title}</h2>
          {note && <span className="text-xs text-low">{note}</span>}
        </div>
      )}
      {children}
    </section>
  )
}

export default Card