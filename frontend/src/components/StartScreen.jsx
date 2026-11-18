import Backdrop from './Backdrop'
import Logo from './Logo'

// The frame around the screens you see before the app: Connect, PIN and offline
function StartScreen({ children }) {
  return (
    <div className="relative isolate flex h-screen items-center justify-center overflow-hidden bg-page p-8 font-sans text-hi">
      <Backdrop />
      <div className="reveal flex w-full max-w-[34rem] flex-col gap-6">
        <div className="flex items-center gap-3">
          <Logo className="h-11 w-11" />
          <span className="font-display text-2xl font-medium">Kageon</span>
        </div>
        {children}
      </div>
    </div>
  )
}

export default StartScreen