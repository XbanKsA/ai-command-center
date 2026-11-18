import StartScreen from './StartScreen'
import StatusCard from './StatusCard'

// starting: the app just opened and is connecting. Otherwise the PC stopped answering and we keep retrying.
function OfflineScreen({ starting, host, onSearch }) {
  return (
    <StartScreen>
      <div>
        <h1 className="font-display text-5xl font-medium leading-tight">{starting ? 'Connecting…' : "Can't reach your PC"}</h1>
        <p className="mt-3 text-mid">
          {starting ? 'Saying hello to Kageon on your PC.' : 'Kageon may be closed, or the PC is asleep. The tablet keeps trying every few seconds.'}
        </p>
      </div>

      <StatusCard busy title={starting ? 'Connecting' : 'Trying again'} text={`PC address ${host}`}>
        {!starting && (
          <button onClick={onSearch} className="press h-11 shrink-0 rounded-xl border border-line bg-card px-4 text-sm font-semibold">
            Search again
          </button>
        )}
      </StatusCard>
    </StartScreen>
  )
}

export default OfflineScreen