/* =============================================
   JARVIS — Backend API Client
   Communicates with the FastAPI backend.
   All requests go through the Vite dev proxy (/api → localhost:8000).
   ============================================= */

const API_BASE = '/api';

/* ── Types ── */
export interface ChatPayload {
  message: string;
  previous_interaction_id?: string | null;
}

export interface ChatResult {
  reply: string;
  interaction_id: string;
  model: string;
}

export interface HealthResult {
  status: string;
  gemini_configured: boolean;
  model: string;
}

/** Callbacks supplied to {@link streamChatMessage}. */
export interface StreamCallbacks {
  /** Called for each incremental text chunk as it arrives. */
  onChunk: (text: string) => void;
  /** Called once when the stream finishes successfully. */
  onDone: (interactionId: string) => void;
  /** Called if the stream ends with an error. */
  onError: (message: string) => void;
}

/* ── Health check ── */
export async function checkHealth(): Promise<HealthResult> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) {
    throw new Error(`Health check failed: ${res.status}`);
  }
  return res.json();
}

/* ── Non-streaming chat (fallback) ── */
export async function sendChatMessage(payload: ChatPayload): Promise<ChatResult> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }

  return res.json();
}

/* ── Streaming chat via SSE ── */
/**
 * Opens a Server-Sent Events stream to `POST /api/chat/stream`.
 *
 * The backend emits three event types:
 *   `{"type":"chunk","text":"..."}` — incremental text delta
 *   `{"type":"done","interaction_id":"..."}` — stream complete
 *   `{"type":"error","message":"..."}` — error
 *
 * @param payload  Chat payload (message + optional previous_interaction_id).
 * @param callbacks Handlers for chunk / done / error events.
 * @param signal   Optional AbortSignal to cancel the stream early.
 */
export async function streamChatMessage(
  payload: ChatPayload,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    signal,
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Request failed: ${res.status}`);
  }

  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE lines are separated by '\n\n'; split on '\n' and accumulate remainder.
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const json = line.slice(6).trim();
      if (!json) continue;
      try {
        const evt = JSON.parse(json) as { type: string; text?: string; interaction_id?: string; message?: string };
        if (evt.type === 'chunk' && evt.text != null) {
          callbacks.onChunk(evt.text);
        } else if (evt.type === 'done') {
          callbacks.onDone(evt.interaction_id ?? '');
        } else if (evt.type === 'error') {
          callbacks.onError(evt.message ?? 'Unknown error from JARVIS backend.');
        }
      } catch {
        // Ignore malformed SSE lines
      }
    }
  }
}
