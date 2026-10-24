import { useMemo } from 'react';
import type { AssistantState } from '../types/jarvis';
import './WaveformVisualizer.css';

interface Props {
  state: AssistantState;
}

export function WaveformVisualizer({ state }: Props) {
  const active = state === 'SPEAKING' || state === 'LISTENING';

  const bars = useMemo(
    () =>
      Array.from({ length: 40 }, (_, i) => ({
        delay: `${((i * 0.05) % 1.5).toFixed(2)}s`,
        height: `${20 + Math.random() * 80}%`,
      })),
    [],
  );

  return (
    <div className={`waveform ${active ? 'waveform--active' : ''}`} id="waveform">
      {bars.map((b, i) => (
        <div
          key={i}
          className="waveform__bar"
          style={
            { animationDelay: b.delay, '--bar-h': b.height } as React.CSSProperties
          }
        />
      ))}
    </div>
  );
}
