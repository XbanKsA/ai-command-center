function DeckTabs({ decks, page, onChange }) {
  return (
    <div className="reveal flex gap-1">
      {decks.map((deck, i) => (
        <button
          key={deck.name}
          onClick={() => onChange(i)}
          className={`press flex h-11 items-center gap-2 rounded-xl px-3.5 text-sm font-medium transition-colors duration-300 ${i === page ? 'bg-well text-hi' : 'text-low'}`}
        >
          {deck.name}
          <span className="text-xs text-low">{deck.slots.filter(Boolean).length}</span>
        </button>
      ))}
    </div>
  )
}

export default DeckTabs