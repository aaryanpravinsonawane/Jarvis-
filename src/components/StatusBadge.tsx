import type { AssistantState } from '../types/jarvis';
import { STATE_CONFIGS } from '../types/jarvis';
import './StatusBadge.css';

interface Props {
  state: AssistantState;
}

export function StatusBadge({ state }: Props) {
  const cfg = STATE_CONFIGS[state];
  const isLive =
    state === 'LISTENING' || state === 'SPEAKING' ||
    state === 'THINKING'  || state === 'MUTED';

  let label: string;
  if (isLive) label = 'SIM \u00b7 LIVE';
  else if (state === 'IDLE') label = 'PREVIEW \u00b7 OFFLINE';
  else label = cfg.label;

  return (
    <div
      className={`status-badge status-badge--${state.toLowerCase()}`}
      style={{ '--badge-color': cfg.color } as React.CSSProperties}
    >
      <span className="status-badge__dot" />
      <span className="status-badge__label">{label}</span>
    </div>
  );
}
