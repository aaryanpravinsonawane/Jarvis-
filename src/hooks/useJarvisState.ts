import { useCallback, useReducer } from 'react';
import type { AssistantState, TranscriptMessage } from '../types/jarvis';

/* ── State shape ── */
interface JarvisState {
  status: AssistantState;
  greeting: string;
  transcript: TranscriptMessage[];
  isSimMode: boolean;
  activePanel: string | null;
}

/* ── Actions ── */
type Action =
  | { type: 'SET_STATUS'; payload: AssistantState }
  | { type: 'ADD_MESSAGE'; payload: TranscriptMessage }
  | { type: 'SET_PANEL'; payload: string | null }
  | { type: 'CLEAR_TRANSCRIPT' };

/* ── Reducer ── */
function reducer(state: JarvisState, action: Action): JarvisState {
  switch (action.type) {
    case 'SET_STATUS':
      return { ...state, status: action.payload };
    case 'ADD_MESSAGE':
      return { ...state, transcript: [...state.transcript, action.payload] };
    case 'SET_PANEL':
      return {
        ...state,
        activePanel: state.activePanel === action.payload ? null : action.payload,
      };
    case 'CLEAR_TRANSCRIPT':
      return { ...state, transcript: [] };
    default:
      return state;
  }
}

/* ── Helpers ── */
function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning, Sir';
  if (h < 17) return 'Good afternoon, Sir';
  return 'Good evening, Sir';
}

function makeMsg(role: 'user' | 'jarvis', content: string): TranscriptMessage {
  return { id: crypto.randomUUID(), role, content, timestamp: Date.now() };
}

/* ── Hook ── */
export function useJarvisState() {
  const [state, dispatch] = useReducer(reducer, {
    status: 'IDLE' as AssistantState,
    greeting: getGreeting(),
    transcript: [],
    isSimMode: true,
    activePanel: null,
  });

  const setStatus = useCallback((s: AssistantState) => {
    dispatch({ type: 'SET_STATUS', payload: s });
  }, []);

  const addMessage = useCallback((role: 'user' | 'jarvis', content: string) => {
    dispatch({ type: 'ADD_MESSAGE', payload: makeMsg(role, content) });
  }, []);

  const setPanel = useCallback((p: string | null) => {
    dispatch({ type: 'SET_PANEL', payload: p });
  }, []);

  const clearTranscript = useCallback(() => {
    dispatch({ type: 'CLEAR_TRANSCRIPT' });
  }, []);

  /** Demo loop — cycles through assistant states with sample dialogue. */
  const simulateSession = useCallback(() => {
    setStatus('CONNECTING');

    setTimeout(() => {
      setStatus('LISTENING');
      addMessage('user', "Good evening, JARVIS. What's on my schedule today?");
    }, 2000);

    setTimeout(() => setStatus('THINKING'), 4000);

    setTimeout(() => {
      setStatus('SPEAKING');
      addMessage(
        'jarvis',
        "Good evening, Sir. This is a UI preview, so I'm not connected to a backend yet and can't read your schedule. Once the voice engine is wired in, I'll answer for real.",
      );
    }, 5500);

    setTimeout(() => setStatus('LISTENING'), 11000);
  }, [setStatus, addMessage]);

  return {
    ...state,
    setStatus,
    addMessage,
    setPanel,
    clearTranscript,
    simulateSession,
  };
}
