import { LayoutGrid, MessageSquare, Activity, Contrast } from 'lucide-react'

// The screens of the app, in the order they appear in the rail
export const SCREENS = [
  { id: 'deck', label: 'Deck', icon: LayoutGrid },
  { id: 'assistant', label: 'Assistant', icon: MessageSquare },
  { id: 'system', label: 'System', icon: Activity },
  { id: 'theme', label: 'Theme', icon: Contrast },
]