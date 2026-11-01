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
  /** Called after the background interaction ID is accepted by the backend. */
  onStarted?: (interactionId: string, status: string) => void;
  /** Called for each incremental text chunk as it arrives. */
  onChunk: (text: string) => void;
  /** Called if the stream reconnects through polling and replaces partial text. */
  onReplace?: (text: string) => void;
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
 * Creates a background interaction, then streams it by its returned ID.
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
  let interactionId: string | undefined;
  let finished = false;
  try {
    const startResponse = await fetch(`${API_BASE}/interactions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });

    if (!startResponse.ok) {
      const body = await startResponse.json().catch(() => ({ detail: startResponse.statusText }));
      throw new Error(body.detail || `Request failed: ${startResponse.status}`);
    }

    const started = (await startResponse.json()) as { interaction_id?: string; status?: string };
    interactionId = started.interaction_id;
    if (!interactionId) throw new Error('Backend did not return an interaction ID.');
    callbacks.onStarted?.(interactionId, started.status ?? 'in_progress');

    const streamUrl = `${API_BASE}/interactions/${encodeURIComponent(interactionId)}/stream`;
    const res = await fetch(streamUrl, { signal });
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail || `Request failed: ${res.status}`);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error('Backend did not open the interaction stream.');
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
          } else if (evt.type === 'replace' && evt.text != null) {
            callbacks.onReplace?.(evt.text);
          } else if (evt.type === 'done') {
            callbacks.onDone(evt.interaction_id ?? '');
            finished = true;
          } else if (evt.type === 'error') {
            callbacks.onError(evt.message ?? 'Unknown error from JARVIS backend.');
            finished = true;
          }
        } catch {
          // Ignore malformed SSE lines
        }
      }
    }
    if (!finished) throw new Error('Gemini stream ended before the interaction completed.');
  } finally {
    if (interactionId && signal?.aborted && !finished) {
      void fetch(`${API_BASE}/interactions/${encodeURIComponent(interactionId)}/cancel`, {
        method: 'POST',
      }).catch(() => undefined);
    }
  }
}
