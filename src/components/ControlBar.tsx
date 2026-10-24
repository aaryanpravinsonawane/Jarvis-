import type { AssistantState } from '../types/jarvis';
import './ControlBar.css';

interface Props {
  state: AssistantState;
  onStart: () => void;
  onStop: () => void;
  onReconnect: () => void;
}

export function ControlBar({ state, onStart, onStop, onReconnect }: Props) {
  const active = state !== 'IDLE' && state !== 'ERROR';

  let micLabel: string;
  let micAction: () => void;
  if (state === 'SPEAKING') { micLabel = 'INTERRUPT'; micAction = onStart; }
  else if (state === 'LISTENING') { micLabel = 'MUTE'; micAction = onStart; }
  else if (state === 'MUTED') { micLabel = 'UNMUTE'; micAction = onStart; }
  else { micLabel = 'START'; micAction = onStart; }

  return (
    <div className="control-bar" id="control-bar">
      {/* Stop */}
      <button
        className="ctrl-btn"
        id="btn-stop"
        onClick={onStop}
        disabled={!active}
        aria-label="Stop session"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18.36 6.64A9 9 0 1 1 5.64 6.64" />
          <line x1="12" y1="2" x2="12" y2="12" />
        </svg>
        <span>STOP</span>
      </button>

      {/* Mic (primary) */}
      <button
        className={`ctrl-btn ctrl-btn--mic ${active ? 'ctrl-btn--active' : ''}`}
        id="btn-mic"
        onClick={micAction}
        aria-label={micLabel}
      >
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
          <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="23" />
          <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
      </button>
      <span className="ctrl-mic-label">{micLabel}</span>

      {/* Reconnect */}
      <button
        className="ctrl-btn"
        id="btn-reconnect"
        onClick={onReconnect}
        aria-label="Reconnect"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="23 4 23 10 17 10" />
          <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
        </svg>
        <span>RECONNECT</span>
      </button>
    </div>
  );
}
