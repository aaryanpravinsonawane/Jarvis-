import { useCallback, useReducer, useRef } from 'react';
import type { AssistantState, TranscriptMessage } from '../types/jarvis';
import { streamChatMessage } from '../api/jarvis';

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
  | { type: 'UPDATE_MESSAGE'; payload: { id: string; content: string } }
  | { type: 'SET_PANEL'; payload: string | null }
  | { type: 'CLEAR_TRANSCRIPT' };

/* ── Reducer ── */
function reducer(state: JarvisState, action: Action): JarvisState {
  switch (action.type) {
    case 'SET_STATUS':
      return { ...state, status: action.payload };
    case 'ADD_MESSAGE':
      return { ...state, transcript: [...state.transcript, action.payload] };
    case 'UPDATE_MESSAGE':
      return {
        ...state,
        transcript: state.transcript.map(m =>
          m.id === action.payload.id ? { ...m, content: action.payload.content } : m,
        ),
      };
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

  /* Multi-turn: track the last interaction ID for conversation continuity */
  const lastInteractionId = useRef<string | null>(null);

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
    lastInteractionId.current = null;
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

  /**
   * Send a text message to the Gemini backend and stream the response
   * incrementally into the transcript.
   *
   * State machine:
   *   IDLE → THINKING (immediately, on submit)
   *   THINKING → SPEAKING (on first SSE chunk — time-to-first-token)
   *   SPEAKING → IDLE (2.5s after stream completes)
   *   * → ERROR (on failure)
   */
  const sendMessage = useCallback(async (text: string) => {
    // 1. Add user message and enter THINKING immediately.
    addMessage('user', text);
    setStatus('THINKING');

    // 2. Insert a placeholder JARVIS message that will be updated in-place.
    const jarvisId = crypto.randomUUID();
    dispatch({
      type: 'ADD_MESSAGE',
      payload: { id: jarvisId, role: 'jarvis', content: '', timestamp: Date.now() },
    });

    let accumulated = '';
    let firstChunk = true;

    try {
      await streamChatMessage(
        { message: text, previous_interaction_id: lastInteractionId.current },
        {
          onChunk: (chunk) => {
            accumulated += chunk;
            dispatch({ type: 'UPDATE_MESSAGE', payload: { id: jarvisId, content: accumulated } });
            // Transition to SPEAKING on the very first chunk (time-to-first-token).
            if (firstChunk) {
              firstChunk = false;
              setStatus('SPEAKING');
            }
          },
          onDone: (interactionId) => {
            // Persist interaction ID for multi-turn continuity.
            lastInteractionId.current = interactionId || null;
            setStatus('SPEAKING');
            setTimeout(() => setStatus('IDLE'), 2500);
          },
          onError: (message) => {
            dispatch({
              type: 'UPDATE_MESSAGE',
              payload: {
                id: jarvisId,
                content: `I'm sorry, Sir. I encountered an error: ${message}`,
              },
            });
            setStatus('ERROR');
          },
        },
      );
    } catch (err) {
      const detail = err instanceof Error ? err.message : 'Unknown error';
      dispatch({
        type: 'UPDATE_MESSAGE',
        payload: {
          id: jarvisId,
          content: `I'm sorry, Sir. I encountered an error: ${detail}`,
        },
      });
      setStatus('ERROR');
    }
  }, [addMessage, setStatus]);

  return {
    ...state,
    setStatus,
    addMessage,
    setPanel,
    clearTranscript,
    simulateSession,
    sendMessage,
  };
}
