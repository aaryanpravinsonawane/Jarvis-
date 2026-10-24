import { useEffect, useRef } from 'react';
import type { TranscriptMessage } from '../types/jarvis';
import './TranscriptPanel.css';

interface Props {
  messages: TranscriptMessage[];
}

export function TranscriptPanel({ messages }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  /* auto-scroll on new messages */
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  return (
    <aside className="transcript-panel" id="transcript-panel">
      <div className="transcript-panel__header">
        <span className="transcript-panel__title">TRANSCRIPT</span>
        <span className="transcript-panel__dot" />
      </div>

      <div className="transcript-panel__body" ref={scrollRef}>
        {messages.length === 0 ? (
          <p className="transcript-panel__empty">
            Start a session to talk with JARVIS. Your conversation will appear here.
          </p>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`t-msg t-msg--${m.role}`}>
              <span className="t-msg__role">
                {m.role === 'user' ? 'YOU' : 'JARVIS'}
              </span>
              <p className="t-msg__text">
                {m.content}
                <span className="t-msg__cursor">{'\u258e'}</span>
              </p>
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
