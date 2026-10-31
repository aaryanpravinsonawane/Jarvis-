import { HolographicOrb } from './components/HolographicOrb';
import { StatusBadge } from './components/StatusBadge';
import { TranscriptPanel } from './components/TranscriptPanel';
import { ControlBar } from './components/ControlBar';
import { NavSidebar } from './components/NavSidebar';
import { WaveformVisualizer } from './components/WaveformVisualizer';
import { CommandInput } from './components/CommandInput';
import { STATE_CONFIGS } from './types/jarvis';
import { useJarvisState } from './hooks/useJarvisState';
import './App.css';

function App() {
  const {
    status,
    greeting,
    transcript,
    activePanel,
    setStatus,
    setPanel,
    simulateSession,
    sendMessage,
  } = useJarvisState();

  const cfg = STATE_CONFIGS[status];

  const handleMic = () => {
    if (status === 'IDLE' || status === 'ERROR') simulateSession();
    else if (status === 'SPEAKING') setStatus('LISTENING');
    else if (status === 'LISTENING') setStatus('MUTED');
    else if (status === 'MUTED') setStatus('LISTENING');
  };

  const handleStop = () => setStatus('IDLE');
  const handleReconnect = () => simulateSession();

  return (
    <div className="jarvis-app" id="jarvis-app">
      {/* Left nav */}
      <NavSidebar activePanel={activePanel} onPanelChange={setPanel} />

      {/* Centre column */}
      <main className="jarvis-main" id="jarvis-main">
        {/* Header */}
        <header className="jarvis-header">
          <div className="jarvis-header__brand">
            <h1 className="jarvis-title">J A R V I S</h1>
            <p className="jarvis-greeting">{greeting}</p>
          </div>
          <StatusBadge state={status} />
        </header>

        {/* Orb */}
        <section className="jarvis-orb-section" id="orb-section">
          <HolographicOrb state={status} />
        </section>

        {/* Status label + description */}
        <div className="jarvis-status-info">
          <div
            className="jarvis-status-pill"
            style={{ '--pill-color': cfg.color } as React.CSSProperties}
          >
            <span className="jarvis-status-dot" />
            <span>{cfg.label}</span>
          </div>
          <p className="jarvis-status-desc">{cfg.description}</p>
        </div>

        {/* Waveform */}
        <WaveformVisualizer state={status} />

        {/* Text command input — connected to Gemini backend */}
        <CommandInput state={status} onSend={sendMessage} />

        {/* Controls */}
        <ControlBar
          state={status}
          onStart={handleMic}
          onStop={handleStop}
          onReconnect={handleReconnect}
        />
      </main>

      {/* Right transcript */}
      <TranscriptPanel messages={transcript} />
    </div>
  );
}

export default App;
