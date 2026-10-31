import { useState, useCallback } from 'react';
import type { KeyboardEvent } from 'react';
import type { AssistantState } from '../types/jarvis';
import './CommandInput.css';

interface Props {
  state: AssistantState;
  onSend: (message: string) => void;
}

/**
 * Text command input for sending messages to the JARVIS backend.
 * Voice recognition is not yet implemented — this provides a typed interface
 * to the Gemini AI while voice interaction is developed in a future phase.
 */
export function CommandInput({ state, onSend }: Props) {
  const [value, setValue] = useState('');

  const busy = state === 'THINKING' || state === 'CONNECTING';

  const handleSubmit = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || busy) return;
    onSend(trimmed);
    setValue('');
  }, [value, busy, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  return (
    <div className="command-input" id="command-input">
      <div className="command-input__wrapper">
        <span className="command-input__prompt">&gt;</span>
        <input
          className="command-input__field"
          id="command-input-field"
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={busy ? 'JARVIS is thinking…' : 'Type a command for JARVIS…'}
          disabled={busy}
          autoComplete="off"
          spellCheck={false}
          aria-label="Command input"
        />
        <button
          className="command-input__send"
          id="btn-send"
          onClick={handleSubmit}
          disabled={busy || !value.trim()}
          aria-label="Send command"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
      {/* Voice recognition placeholder — real implementation in a future phase */}
      <p className="command-input__hint">
        Voice input: not yet implemented · type your query above
      </p>
    </div>
  );
}
