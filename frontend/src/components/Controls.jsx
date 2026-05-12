export default function Controls({ connected, connecting, onConnect, onDisconnect, muted, onToggleMute }) {
  if (!connected) {
    return (
      <div className="controls-row">
        <button className="btn btn-primary" onClick={onConnect} disabled={connecting}>
          {connecting ? 'Connecting...' : 'Connect'}
        </button>
      </div>
    );
  }

  return (
    <div className="controls-row">
      <button
        className={`btn btn-icon${muted ? ' active' : ''}`}
        onClick={onToggleMute}
        title={muted ? 'Unmute microphone' : 'Mute microphone'}
      >
        {muted ? '🔇' : '🎤'}
      </button>
      <button className="btn btn-danger" onClick={onDisconnect}>
        Leave Room
      </button>
    </div>
  );
}
